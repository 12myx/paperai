"""Grounded research endpoints: summaries, reviews, translation, comparison."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, get_user_settings
from ..models import Chunk, CollectionPaper, Paper, PaperPage, User
from ..schemas import CompareRequest, ExtractRequest, GapRequest, SingleExtractRequest, SummaryRequest, TranslateRequest
from ..services import analysis
from ..services.evidence import save_analysis
from ..services.llm import LLMError, resolve_model_config
from ..services.rag import search as rag_search
from ..services.tools import ToolError, ToolRunner

router = APIRouter(tags=["research"])


def _paper(db: Session, user: User, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None or paper.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "论文不存在或无权访问")
    return paper


def _resolve_papers(db: Session, user: User, paper_ids: list[str], collection_id: str | None = None) -> list[Paper]:
    ids = list(paper_ids)
    if collection_id:
        ids.extend(
            db.execute(select(CollectionPaper.paper_id).where(CollectionPaper.collection_id == collection_id)).scalars().all()
        )
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请至少选择一篇论文")
    papers = list(db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))).scalars().all())
    if len(papers) != len(set(ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "部分论文不存在或无权访问")
    return papers


@router.post("/papers/{paper_id}/summary")
async def summarize(paper_id: str, payload: SummaryRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = _paper(db, user, paper_id)
    if paper.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "论文尚未解析完成")
    if payload.mode not in analysis.SUMMARY_MODES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知的总结模式")
    config = resolve_model_config(db, user)
    try:
        content, citations, local = await analysis.generative_summary(db, user, config, paper, payload.mode)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    label = analysis.SUMMARY_LABELS.get(payload.mode, "总结")
    record, evidence = save_analysis(
        db,
        user,
        kind="summary",
        title=f"{paper.title} · {label}",
        content=content,
        citations=citations,
        scope_type="paper",
        scope_ids=[paper.id],
        paper_ids=[paper.id],
        local=local,
        model=config.model if config else "local-extractive",
        evidence_type="direct",
    )
    return {
        "mode": payload.mode,
        "label": label,
        "content": content,
        "citations": citations,
        "local": local,
        "model": config.model if config else "local-extractive",
        "analysis_id": record.id,
        "evidence_count": len(evidence),
    }


@router.post("/papers/{paper_id}/analysis")
async def analyze(paper_id: str, payload: SummaryRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = _paper(db, user, paper_id)
    if paper.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "论文尚未解析完成")
    kind = payload.mode
    if kind not in {"critical", "innovation", "limitation", "future", "gap"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "不支持的分析类型")
    config = resolve_model_config(db, user)
    try:
        if kind == "critical":
            content, citations, local = await analysis.critical_review(db, config, paper)
        else:
            mode = "innovation" if kind == "innovation" else "limitation" if kind == "limitation" else "future"
            content, citations, local = await analysis.generative_summary(db, user, config, paper, mode)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    labels = {
        "critical": "批判性评估",
        "innovation": "创新性分析",
        "limitation": "局限性分析",
        "future": "未来研究方向",
        "gap": "研究缺口",
    }
    record, evidence = save_analysis(
        db,
        user,
        kind=kind,
        title=f"{paper.title} · {labels.get(kind, kind)}",
        content=content,
        citations=citations,
        scope_type="paper",
        scope_ids=[paper.id],
        paper_ids=[paper.id],
        local=local,
        model=config.model if config else "local-extractive",
        evidence_type="inferred",
    )
    return {
        "kind": kind,
        "content": content,
        "citations": citations,
        "local": local,
        "analysis_id": record.id,
        "evidence_count": len(evidence),
    }


@router.post("/papers/{paper_id}/translate")
async def translate(paper_id: str, payload: TranslateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = _paper(db, user, paper_id)
    settings_row = get_user_settings(db, user)
    config = resolve_model_config(db, user)
    text = (payload.text or "").strip()
    if not text and payload.page:
        page = db.execute(
            select(PaperPage).where(PaperPage.paper_id == paper.id, PaperPage.page_number == payload.page)
        ).scalar_one_or_none()
        text = page.text if page else ""
    if not text and payload.section_id:
        chunks = db.execute(
            select(Chunk).where(Chunk.paper_id == paper.id, Chunk.section_id == payload.section_id).order_by(Chunk.order_index)
        ).scalars().all()
        text = "\n\n".join(chunk.text for chunk in chunks)
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请提供要翻译的文本、页码或章节")
    if config is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "model_required", "message": "翻译需要生成式模型，请在「设置 → AI 模型」中配置 DeepSeek API Key。"},
        )
    try:
        translated = await analysis.translate_text(
            config,
            text[:10000],
            payload.target_language or settings_row.translation_language,
            payload.style or settings_row.translation_style,
        )
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {
        "content": translated,
        "source": text,
        "target_language": payload.target_language or settings_row.translation_language,
        "model": config.model,
        "local": False,
    }


@router.post("/papers/{paper_id}/extract")
async def extract(paper_id: str, payload: SingleExtractRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = _paper(db, user, paper_id)
    runner = ToolRunner(db, user, resolve_model_config(db, user), scope_ids=[paper.id], allow_writes=False)
    try:
        result = await runner.run("extract_knowledge", {"instruction": payload.instruction, "paper_ids": [paper.id]})
    except (ToolError, LLMError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    citations = result.get("citations", [])
    local = (result.get("data") or {}).get("local", False)
    record, evidence = save_analysis(
        db,
        user,
        kind="extract",
        title=f"{paper.title} · 自定义提取",
        content=result["summary"],
        citations=citations,
        scope_type="paper",
        scope_ids=[paper.id],
        paper_ids=[paper.id],
        local=local,
        model=None if local else "generative",
        evidence_type="direct",
    )
    return {
        "content": result["summary"],
        "citations": citations,
        "local": local,
        "analysis_id": record.id,
        "evidence_count": len(evidence),
    }


@router.post("/research/compare")
async def compare(payload: CompareRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    config = resolve_model_config(db, user)
    if payload.fragments:
        fragments = []
        for raw in payload.fragments[:8]:
            paper = _paper(db, user, raw.get("paper_id", ""))
            text = (raw.get("text") or "").strip()
            page = raw.get("page") or 1
            section = raw.get("section") or ""
            chunk_id = raw.get("chunk_id")
            if chunk_id:
                chunk = db.get(Chunk, chunk_id)
                if chunk and chunk.paper_id == paper.id:
                    text = chunk.text
                    page = chunk.page_start
                    section = chunk.section_title
            if not text:
                continue
            fragments.append(
                {"paper_id": paper.id, "paper_title": paper.title, "year": paper.year, "page": page, "section": section, "text": text, "chunk_id": chunk_id}
            )
        if len(fragments) < 2:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "至少需要两个有效片段")
        content, citations, local = await analysis.fragment_compare(config, fragments, payload.focus)
        paper_ids = list(dict.fromkeys(fragment["paper_id"] for fragment in fragments))
        record, evidence = save_analysis(
            db,
            user,
            kind="fragment_comparison",
            title=payload.focus.strip()[:200] or "自选片段对比",
            content=content,
            citations=citations,
            scope_type="fragments",
            scope_ids=paper_ids,
            paper_ids=paper_ids,
            local=local,
            model=config.model if config else "local-extractive",
            evidence_type="inferred",
        )
        return {
            "content": content,
            "citations": citations,
            "local": local,
            "fragments": fragments,
            "analysis_id": record.id,
            "evidence_count": len(evidence),
        }

    papers = _resolve_papers(db, user, payload.paper_ids)
    if len(papers) < 2:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "对比至少需要两篇论文")
    content, citations, local = await analysis.generative_compare(db, config, papers, payload.focus)
    paper_ids = [paper.id for paper in papers]
    record, evidence = save_analysis(
        db,
        user,
        kind="comparison",
        title=payload.focus.strip()[:200] or "多论文对比",
        content=content,
        citations=citations,
        scope_type="papers",
        scope_ids=paper_ids,
        paper_ids=paper_ids,
        local=local,
        model=config.model if config else "local-extractive",
        evidence_type="inferred",
    )
    return {
        "content": content,
        "citations": citations,
        "local": local,
        "papers": [{"id": p.id, "title": p.title} for p in papers],
        "analysis_id": record.id,
        "evidence_count": len(evidence),
    }


@router.post("/research/gap")
async def research_gap(payload: GapRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    papers = _resolve_papers(db, user, payload.paper_ids, payload.collection_id)
    config = resolve_model_config(db, user)
    content, citations, local = await analysis.generative_gap_analysis(db, config, papers[:8])
    paper_ids = [paper.id for paper in papers[:8]]
    record, evidence = save_analysis(
        db,
        user,
        kind="gap",
        title="研究缺口分析",
        content=content,
        citations=citations,
        scope_type="papers",
        scope_ids=paper_ids,
        paper_ids=paper_ids,
        local=local,
        model=config.model if config else "local-extractive",
        evidence_type="inferred",
    )
    return {
        "content": content,
        "citations": citations,
        "local": local,
        "paper_count": len(papers),
        "analysis_id": record.id,
        "evidence_count": len(evidence),
    }


@router.post("/research/extract")
async def research_extract(payload: ExtractRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    papers = _resolve_papers(db, user, payload.paper_ids, payload.collection_id)
    runner = ToolRunner(db, user, resolve_model_config(db, user), scope_ids=[p.id for p in papers], allow_writes=False)
    try:
        result = await runner.run("extract_knowledge", {"instruction": payload.instruction, "paper_ids": [p.id for p in papers]})
    except (ToolError, LLMError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    citations = result.get("citations", [])
    local = (result.get("data") or {}).get("local", False)
    paper_ids = [paper.id for paper in papers]
    record, evidence = save_analysis(
        db,
        user,
        kind="extract",
        title=payload.instruction[:120],
        content=result["summary"],
        citations=citations,
        scope_type="papers",
        scope_ids=paper_ids,
        paper_ids=paper_ids,
        local=local,
        model=None if local else "generative",
        evidence_type="direct",
    )
    return {
        "content": result["summary"],
        "citations": citations,
        "local": local,
        "analysis_id": record.id,
        "evidence_count": len(evidence),
    }