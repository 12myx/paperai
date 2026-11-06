"""P4 multi-paper research: facets, evidence matrix, conflicts, evolution.

Everything is grounded in *facets*: short, evidence-backed statements about each
paper (question, method, dataset, metrics, findings, limitations).  Local mode
extracts these from real chunks; generative mode asks the model for structured
JSON but still verifies every quote against the chunk text.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chunk, Evidence, Paper, PaperFacet, ResearchInsight, User
from . import analysis
from .evidence import EvidenceError, create_evidence
from .llm import LLMClient, LLMError, ModelConfig
from .rag import search as rag_search

DIMENSIONS = [
    ("research_question", "研究问题"),
    ("method", "研究方法"),
    ("dataset", "数据集"),
    ("metrics", "评价指标"),
    ("findings", "主要发现"),
    ("limitations", "局限性"),
]

TAG_MAP = {
    "research_question": ("abstract", "introduction"),
    "method": ("method",),
    "dataset": ("experiment", "method", "result"),
    "metrics": ("experiment", "result"),
    "findings": ("result", "conclusion"),
    "limitations": ("limitation", "future-work", "discussion", "conclusion"),
}

PATTERNS = {
    "research_question": re.compile(r"(\?|we (?:study|ask|investigate|address)|this (?:paper|work)|研究问题|本文)", re.I),
    "dataset": re.compile(r"(dataset|data set|benchmark|corpus|arxiv|imagenet|glue|squad|ms marco|数据集|语料|基准)", re.I),
    "metrics": re.compile(r"(accuracy|precision|recall|f1|bleu|rouge|latency|throughput|auc|%|指标|准确率|召回)", re.I),
    "limitations": re.compile(
        r"(limitation|future work|however|remain(?:s)? (?:unclear|challenging|limited|limited)|"
        r"not (?:yet )?(?:addressed|evaluated)|only (?:english|covers|evaluated)|"
        r"不足|局限|未来|尚未|有待)",
        re.I,
    ),
}


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def _norm(value: str | None) -> str:
    text = re.sub(r"\s+", " ", (value or "")).strip()
    if not text or text == "未提及":
        return ""
    return text.casefold()


def _sentences(chunks: list[Chunk], tags: tuple[str, ...]) -> list[tuple[Chunk, str]]:
    pool = [chunk for chunk in chunks if any(tag in (chunk.tags or []) for tag in tags)]
    if not pool:
        pool = chunks
    out: list[tuple[Chunk, str]] = []
    for chunk in pool[:10]:
        for sentence in analysis.split_sentences(chunk.text):
            out.append((chunk, sentence))
    return out


def _local_field(db: Session, user: User, paper: Paper, field: str, chunks: list[Chunk]) -> dict:
    candidates = _sentences(chunks, TAG_MAP.get(field, ()))
    pattern = PATTERNS.get(field)
    scored: list[tuple[int, Chunk, str]] = []
    for index, (chunk, sentence) in enumerate(candidates):
        if len(sentence) < 20:
            continue
        score = 1
        if pattern and pattern.search(sentence):
            score += 4
        if field == "research_question" and "?" in sentence:
            score += 3
        if field == "findings" and re.search(r"(%|improve|reduce|outperform|achiev|结果|提升|降低)", sentence, re.I):
            score += 2
        scored.append((score - index * 0.001, chunk, sentence))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return {"text": "未提及", "quote": None, "page": None, "section": None, "chunk_id": None, "evidence_id": None, "verified": False}
    if field in {"dataset", "metrics", "limitations"} and scored[0][0] < 4.5:
        return {"text": "未提及", "quote": None, "page": None, "section": None, "chunk_id": None, "evidence_id": None, "verified": False}
    _score, chunk, sentence = scored[0]
    text = sentence[:260]
    evidence = None
    try:
        evidence, _ = create_evidence(
            db,
            user,
            paper_id=paper.id,
            chunk_id=chunk.id,
            page=chunk.page_start,
            section=chunk.section_title,
            quote=sentence,
            claim=f"{dict(DIMENSIONS)[field]}：{text[:120]}",
            evidence_type="direct",
            source_type="facet",
            source_id=paper.id,
            meta={"field": field},
        )
    except EvidenceError:
        evidence = None
    return {
        "text": text,
        "quote": sentence[:1200],
        "page": chunk.page_start,
        "section": chunk.section_title,
        "chunk_id": chunk.id,
        "evidence_id": evidence.id if evidence else None,
        "verified": bool(evidence.verified) if evidence else False,
    }


def _facet_for(db: Session, user: User, paper: Paper) -> PaperFacet | None:
    return db.execute(
        select(PaperFacet).where(PaperFacet.user_id == user.id, PaperFacet.paper_id == paper.id)
    ).scalar_one_or_none()


def _local_facets(db: Session, user: User, paper: Paper) -> tuple[dict, bool]:
    chunks = list(
        db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all()
    )
    fields = {field: _local_field(db, user, paper, field, chunks) for field, _label in DIMENSIONS}
    return fields, True


def _model_facets(db: Session, user: User, paper: Paper, config: ModelConfig, fallback: dict) -> tuple[dict, bool]:
    context, citations = analysis.paper_context(db, paper, max_chars=7000)
    if not citations:
        return fallback, True
    prompt = (
        "请从论文原文中提取结构化研究画像。只输出 JSON，不要 Markdown。\n"
        "JSON 必须包含六个键：research_question, method, dataset, metrics, findings, limitations。\n"
        "每个键的值是 {\"text\": \"不超过 80 字的中文概括\", \"quote\": \"支撑该概括的原文句子\", \"citation\": \"C1\"}。\n"
        "quote 必须逐字来自对应 citation 的原文；找不到就填空字符串和空 citation。\n"
        "不要编造数据集、指标或结论。\n\n"
        "论文：\n" + context
    )
    try:
        response = LLMClient(config).complete(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1200,
        )
    except LLMError:
        return fallback, True
    payload = _parse_json(response.get("content") or "")
    if not payload:
        return fallback, True

    by_key = {citation["key"]: citation for citation in citations}
    fields = dict(fallback)
    model_used = False
    for field, _label in DIMENSIONS:
        item = payload.get(field) or {}
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:260]
        quote = str(item.get("quote") or "").strip()
        key = str(item.get("citation") or "").strip()
        citation = by_key.get(key)
        if not text or not quote or not citation:
            continue
        try:
            evidence, _ = create_evidence(
                db,
                user,
                paper_id=paper.id,
                chunk_id=citation.get("chunk_id"),
                page=citation.get("page"),
                section=citation.get("section"),
                quote=quote,
                claim=f"{_label}：{text[:120]}",
                evidence_type="direct",
                source_type="facet",
                source_id=paper.id,
                meta={"field": field, "origin": "model"},
            )
        except EvidenceError:
            continue
        fields[field] = {
            "text": text,
            "quote": quote[:1200],
            "page": citation.get("page"),
            "section": citation.get("section"),
            "chunk_id": citation.get("chunk_id"),
            "evidence_id": evidence.id,
            "verified": evidence.verified,
        }
        model_used = True
    return fields, not model_used


def _prune_facet_evidence(db: Session, paper_id: str, fields: dict) -> None:
    keep = {
        (fields.get(field) or {}).get("evidence_id")
        for field, _label in DIMENSIONS
        if (fields.get(field) or {}).get("evidence_id")
    }
    rows = db.execute(
        select(Evidence).where(
            Evidence.source_type == "facet",
            Evidence.source_id == paper_id,
        )
    ).scalars().all()
    for row in rows:
        if row.id not in keep:
            db.delete(row)


async def ensure_facets(
    db: Session,
    user: User,
    papers: list[Paper],
    config: ModelConfig | None,
    force: bool = False,
) -> list[PaperFacet]:
    facets: list[PaperFacet] = []
    for paper in papers:
        existing = _facet_for(db, user, paper)
        if existing and not force:
            facets.append(existing)
            continue
        fallback, _ = _local_facets(db, user, paper)
        fields, local = fallback, True
        model_name = None
        if config is not None:
            fields, local = _model_facets(db, user, paper, config, fallback)
            model_name = config.model
        _prune_facet_evidence(db, paper.id, fields)
        if existing:
            existing.fields = fields
            existing.local = local
            existing.model = model_name
            existing.note = None if not local else "本地抽取"
            facet = existing
        else:
            facet = PaperFacet(
                user_id=user.id,
                paper_id=paper.id,
                fields=fields,
                local=local,
                model=model_name,
                note=None if not local else "本地抽取",
            )
            db.add(facet)
        facets.append(facet)
    db.commit()
    for facet in facets:
        db.refresh(facet)
    return facets


def _facet_citations(db: Session, papers: list[Paper], facets: list[PaperFacet]) -> tuple[list[dict], str]:
    """Build numbered citations + a compact profile context for the model."""
    evidence_ids = []
    for facet in facets:
        for field, _label in DIMENSIONS:
            cell = (facet.fields or {}).get(field) or {}
            if cell.get("evidence_id"):
                evidence_ids.append(cell["evidence_id"])
    evidence_map = {}
    if evidence_ids:
        rows = db.execute(select(Evidence).where(Evidence.user_id == facets[0].user_id, Evidence.id.in_(evidence_ids))).scalars().all()
        evidence_map = {item.id: item for item in rows}
    citations: list[dict] = []
    paper_map = {paper.id: paper for paper in papers}
    lines: list[str] = []
    for facet in facets:
        paper = paper_map.get(facet.paper_id)
        if paper is None:
            continue
        lines.append(f"### 《{paper.title}》（{paper.year or '年份未知'}）id={paper.id}")
        for field, label in DIMENSIONS:
            cell = (facet.fields or {}).get(field) or {}
            text = cell.get("text") or "未提及"
            evidence = evidence_map.get(cell.get("evidence_id"))
            key = None
            if evidence is not None:
                key = f"C{len(citations) + 1}"
                citations.append(
                    {
                        "key": key,
                        "chunk_id": evidence.chunk_id,
                        "paper_id": paper.id,
                        "paper_title": paper.title,
                        "paper_year": paper.year,
                        "section": evidence.section or cell.get("section") or "",
                        "page": evidence.page or cell.get("page") or 1,
                        "quote": evidence.quote,
                        "verified": evidence.verified,
                    }
                )
            lines.append(f"- {label}：{text}" + (f" [{key}]" if key else ""))
        lines.append("")
    return citations, "\n".join(lines)


def _save_insight(
    db: Session,
    user: User,
    *,
    kind: str,
    title: str,
    papers: list[Paper],
    data: dict,
    citations: list[dict],
    local: bool,
    model: str | None,
) -> ResearchInsight:
    insight = ResearchInsight(
        user_id=user.id,
        kind=kind,
        title=title[:390],
        scope_type="papers",
        paper_ids=[paper.id for paper in papers],
        data=data,
        citations=citations,
        local=local,
        model=model,
    )
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


async def build_matrix(
    db: Session,
    user: User,
    papers: list[Paper],
    config: ModelConfig | None,
    force: bool = False,
) -> dict:
    facets = await ensure_facets(db, user, papers, config, force)
    citations, context = _facet_citations(db, papers, facets)
    rows = []
    paper_map = {paper.id: paper for paper in papers}
    for facet in facets:
        paper = paper_map.get(facet.paper_id)
        if paper is None:
            continue
        rows.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "year": paper.year,
                "local": facet.local,
                "fields": facet.fields or {},
            }
        )
    rows.sort(key=lambda row: (row["year"] or 0, row["title"]))
    local = all(row["local"] for row in rows) if rows else True
    data = {
        "rows": rows,
        "dimensions": [{"id": field, "label": label} for field, label in DIMENSIONS],
        "local": local,
        "scope": f"资料库内 {len(rows)} 篇论文",
        "note": "单元格来自论文原文切片；点击页码可回到原文。"
        if local
        else "部分单元格由模型提取，并已尝试按原文核验。",
    }
    insight = _save_insight(
        db,
        user,
        kind="matrix",
        title=f"证据矩阵 · {len(rows)} 篇论文",
        papers=papers,
        data=data,
        citations=citations,
        local=local,
        model=config.model if config and not local else None,
    )
    return {"insight_id": insight.id, **data, "citations": citations}


def _comparability(db: Session, papers: list[Paper], facets: list[PaperFacet]) -> list[dict]:
    by_paper = {facet.paper_id: facet for facet in facets}
    paper_map = {paper.id: paper for paper in papers}
    pairs = []
    for i, a in enumerate(papers):
        for b in papers[i + 1 :]:
            fa = (by_paper.get(a.id).fields or {}) if by_paper.get(a.id) else {}
            fb = (by_paper.get(b.id).fields or {}) if by_paper.get(b.id) else {}
            da = _norm((fa.get("dataset") or {}).get("text"))
            db_ = _norm((fb.get("dataset") or {}).get("text"))
            ma = _norm((fa.get("metrics") or {}).get("text"))
            mb = _norm((fb.get("metrics") or {}).get("text"))
            same_dataset = bool(da and db_ and da == db_)
            same_metric = bool(ma and mb and ma == mb)
            comparable = same_dataset and same_metric
            if comparable:
                reason = "数据集与指标文本一致"
            elif same_dataset or same_metric:
                reason = "仅数据集或指标之一一致，结果不可直接比较"
            else:
                reason = "数据集与指标均未对齐，不能直接判定冲突"
            pairs.append(
                {
                    "paper_a": a.id,
                    "paper_b": b.id,
                    "title_a": a.title,
                    "title_b": b.title,
                    "dataset_a": (fa.get("dataset") or {}).get("text") or "未提及",
                    "dataset_b": (fb.get("dataset") or {}).get("text") or "未提及",
                    "metrics_a": (fa.get("metrics") or {}).get("text") or "未提及",
                    "metrics_b": (fb.get("metrics") or {}).get("text") or "未提及",
                    "same_dataset": same_dataset,
                    "same_metric": same_metric,
                    "comparable": comparable,
                    "reason": reason,
                }
            )
    return pairs


async def build_conflicts(
    db: Session,
    user: User,
    papers: list[Paper],
    config: ModelConfig | None,
    force: bool = False,
) -> dict:
    facets = await ensure_facets(db, user, papers, config, force)
    citations, context = _facet_citations(db, papers, facets)
    comparability = _comparability(db, papers, facets)
    local = True
    conflicts: list[dict] = []
    note = "本地抽取模式只并列各论文的研究问题、方法与发现，不判定学术观点冲突；请人工核对或配置生成式模型。"
    if config is not None:
        prompt = (
            "你是严谨的学术比较助手。基于下面论文的结构化画像与编号证据，判断是否存在学术观点冲突。\n"
            "只输出 JSON：{\"conflicts\":[{\"question\":\"\",\"stance_a\":\"\",\"stance_b\":\"\","
            "\"paper_a\":\"论文id\",\"paper_b\":\"论文id\",\"evidence_keys\":[\"C1\"],"
            "\"analysis\":\"\",\"severity\":\"low|medium|high\",\"comparable\":true}]}。\n"
            "规则：只有研究问题相同、且数据集/指标可比较时才可称冲突；条件不同只能写差异，不能写冲突。"
            "没有证据就不要生成冲突；无法判断就返回空数组。\n\n" + context
        )
        try:
            response = LLMClient(config).complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1600,
            )
            payload = _parse_json(response.get("content") or "")
            if payload is not None:
                by_key = {citation["key"]: citation for citation in citations}
                for item in payload.get("conflicts") or []:
                    if not isinstance(item, dict):
                        continue
                    keys = [key for key in (item.get("evidence_keys") or []) if key in by_key]
                    if not keys or not bool(item.get("comparable", False)):
                        continue
                    conflicts.append(
                        {
                            "question": str(item.get("question") or "")[:300],
                            "stance_a": str(item.get("stance_a") or "")[:600],
                            "stance_b": str(item.get("stance_b") or "")[:600],
                            "paper_a": str(item.get("paper_a") or ""),
                            "paper_b": str(item.get("paper_b") or ""),
                            "analysis": str(item.get("analysis") or "")[:1200],
                            "severity": str(item.get("severity") or "medium"),
                            "comparable": bool(item.get("comparable", False)),
                            "evidence": [by_key[key] for key in keys],
                        }
                    )
                local = False
                note = "生成式对比；仅列出带证据且条件可比的冲突，条件不同只标记为差异。"
        except LLMError:
            note = "模型调用失败，已回退为本地证据并列；不判定冲突。"

    profiles = []
    facet_map = {facet.paper_id: facet for facet in facets}
    for paper in papers:
        facet = facet_map.get(paper.id)
        fields = (facet.fields or {}) if facet else {}
        profiles.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "year": paper.year,
                "method": (fields.get("method") or {}).get("text") or "未提及",
                "findings": (fields.get("findings") or {}).get("text") or "未提及",
                "limits": (fields.get("limitations") or {}).get("text") or "未提及",
            }
        )

    data = {
        "conflicts": conflicts,
        "comparability": comparability,
        "profiles": profiles,
        "local": local,
        "note": note,
        "scope": f"资料库内 {len(papers)} 篇论文",
    }
    insight = _save_insight(
        db,
        user,
        kind="conflicts",
        title=f"观点冲突 · {len(papers)} 篇论文",
        papers=papers,
        data=data,
        citations=citations,
        local=local,
        model=config.model if config and not local else None,
    )
    return {"insight_id": insight.id, **data, "citations": citations}


async def build_evolution(
    db: Session,
    user: User,
    papers: list[Paper],
    config: ModelConfig | None,
    force: bool = False,
) -> dict:
    facets = await ensure_facets(db, user, papers, config, force)
    citations, context = _facet_citations(db, papers, facets)
    paper_map = {paper.id: paper for paper in papers}
    timeline = []
    for facet in facets:
        paper = paper_map.get(facet.paper_id)
        if paper is None:
            continue
        timeline.append(
            {
                "paper_id": paper.id,
                "title": paper.title,
                "year": paper.year,
                "method": ((facet.fields or {}).get("method") or {}).get("text") or "未提及",
                "findings": ((facet.fields or {}).get("findings") or {}).get("text") or "未提及",
                "evidence_id": ((facet.fields or {}).get("method") or {}).get("evidence_id"),
            }
        )
    timeline.sort(key=lambda row: (row["year"] or 0, row["title"]))
    relations: list[dict] = []
    local = True
    note = "本地抽取模式仅按真实发表年份排列方法，不推断技术继承关系。"
    if config is not None:
        prompt = (
            "基于论文结构化画像与编号证据，分析方法演化关系。只输出 JSON："
            "{\"relations\":[{\"from_paper\":\"id\",\"to_paper\":\"id\","
            "\"relation\":\"extends|improves|uses|compares|unknown\",\"reason\":\"\","
            "\"evidence_keys\":[\"C1\"],\"status\":\"explicit|possible|unknown\"}]}。\n"
            "只有原文明确写出继承/改进/使用关系时 status=explicit；仅凭年份先后或方法相似不得推断，最多 possible，并说明不确定性。"
            "没有证据就不要生成关系。\n\n" + context
        )
        try:
            response = LLMClient(config).complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1400,
            )
            payload = _parse_json(response.get("content") or "")
            if payload is not None:
                by_key = {citation["key"]: citation for citation in citations}
                valid_papers = {paper.id for paper in papers}
                for item in payload.get("relations") or []:
                    if not isinstance(item, dict):
                        continue
                    keys = [key for key in (item.get("evidence_keys") or []) if key in by_key]
                    if not keys:
                        continue
                    from_paper = str(item.get("from_paper") or "")
                    to_paper = str(item.get("to_paper") or "")
                    if not from_paper or not to_paper:
                        continue
                    if from_paper not in valid_papers or to_paper not in valid_papers:
                        continue
                    if to_paper and to_paper not in valid_papers:
                        continue
                    relations.append(
                        {
                            "from_paper": str(item.get("from_paper") or ""),
                            "to_paper": str(item.get("to_paper") or ""),
                            "relation": str(item.get("relation") or "unknown"),
                            "reason": str(item.get("reason") or "")[:800],
                            "status": str(item.get("status") or "possible"),
                            "evidence": [by_key[key] for key in keys],
                        }
                    )
                local = False
                note = "生成式方法演化；explicit 表示原文明确说明，possible 表示基于证据的推测。"
        except LLMError:
            note = "模型调用失败，已回退为本地时间线；不推断继承关系。"

    data = {
        "timeline": timeline,
        "relations": relations,
        "local": local,
        "note": note,
        "scope": f"资料库内 {len(papers)} 篇论文",
    }
    insight = _save_insight(
        db,
        user,
        kind="evolution",
        title=f"方法演化 · {len(papers)} 篇论文",
        papers=papers,
        data=data,
        citations=citations,
        local=local,
        model=config.model if config and not local else None,
    )
    return {"insight_id": insight.id, **data, "citations": citations}


def validate_gap(
    db: Session,
    user: User,
    claim: str,
    papers: list[Paper],
    config: ModelConfig | None,
) -> dict:
    paper_ids = [paper.id for paper in papers]
    citations = rag_search(db, user.id, claim, paper_ids, top_k=12)
    grouped: dict[str, list[dict]] = {}
    for citation in citations:
        grouped.setdefault(citation["paper_id"], []).append(citation)
    supports = []
    for paper in papers:
        items = grouped.get(paper.id, [])
        if not items:
            continue
        best = items[0]
        supports.append(
            {
                "paper_id": paper.id,
                "paper_title": paper.title,
                "page": best["page"],
                "section": best["section"],
                "quote": best["quote"],
                "evidence_key": best["key"],
            }
        )
    support_count = len(supports)
    paper_count = len(papers)
    strength = "multi" if support_count >= 2 else "single" if support_count == 1 else "none"
    data = {
        "claim": claim[:1000],
        "supports": supports,
        "support_count": support_count,
        "paper_count": paper_count,
        "strength": strength,
        "local": True,
        "note": "这是基于检索相关度的证据覆盖，不代表论文明确支持该研究缺口；需要人工阅读原文。",
        "scope": f"资料库内 {paper_count} 篇论文",
    }
    insight = _save_insight(
        db,
        user,
        kind="gap_validation",
        title="研究缺口跨论文验证",
        papers=papers,
        data=data,
        citations=citations,
        local=True,
        model=None,
    )
    return {"insight_id": insight.id, **data, "citations": citations}