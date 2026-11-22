"""Evidence System: verified, traceable evidence records.

Every AI claim should be backed by an Evidence row that points to a real
chunk/page. Evidence is deliberately *not* the same thing as a citation:
a citation is a transient [C#] marker in an answer, while evidence is a
persisted, verifiable record that can be reused by Research Intelligence,
knowledge items and academic artefacts.

Verification is local and deterministic: the quote is checked against the
stored chunk text. We never mark a quote as verified just because a model
produced it.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Annotation,
    Chunk,
    Conversation,
    Evidence,
    KnowledgeItem,
    Message,
    Paper,
    ResearchAnalysis,
    User,
)

EVIDENCE_TYPES = {
    "direct": "原文直接证据",
    "shared": "多篇论文共同支持",
    "inferred": "AI 基于证据的推导",
    "hypothesis": "AI 研究假设",
    "insufficient": "证据不足",
    "external": "需要外部验证",
}
BASE_CONFIDENCE = {
    "direct": 0.92,
    "shared": 0.85,
    "inferred": 0.62,
    "hypothesis": 0.45,
    "insufficient": 0.15,
    "external": 0.5,
}


class EvidenceError(ValueError):
    pass


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text or "")
    value = value.replace("\u00ad", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip().casefold()


def verify_quote(chunk_text: str, quote: str) -> tuple[bool, str]:
    """Check a quote against the stored chunk text (deterministic, no model)."""
    if not quote or not quote.strip():
        return False, "空引用"
    q = normalize_text(quote).strip(" \"'“”‘’")
    text = normalize_text(chunk_text)
    if not q:
        return False, "空引用"
    if q in text:
        return True, "原文精确匹配"

    segments = [normalize_text(part).strip() for part in re.split(r"…|\.\.\.", q)]
    segments = [part for part in segments if part]
    if segments and all(part in text for part in segments):
        return True, "原文片段匹配"

    sentences = [s for s in re.split(r"(?<=[。！？.!?])\s*", q) if len(normalize_text(s)) >= 30]
    if sentences and all(normalize_text(sentence) in text for sentence in sentences):
        return True, f"句子完整匹配 {len(sentences)}/{len(sentences)}"
    return False, "引用未在原文中找到（可能已被截断或错误生成）"


def _paper_for_user(db: Session, user_id: str, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None or paper.user_id != user_id:
        raise EvidenceError("论文不存在或无权访问")
    return paper


def resolve_chunk(
    db: Session,
    user_id: str,
    paper_id: str | None,
    chunk_id: str | None,
    page: int | None,
    quote: str,
) -> tuple[Chunk | None, Paper | None]:
    """Resolve a chunk by id, or by page + quote overlap, scoped to the user."""
    if chunk_id:
        row = db.execute(
            select(Chunk, Paper)
            .join(Paper, Paper.id == Chunk.paper_id)
            .where(Chunk.id == chunk_id, Paper.user_id == user_id)
        ).first()
        if row is None:
            raise EvidenceError("切片不存在或无权访问")
        return row[0], row[1]

    if not paper_id:
        return None, None
    paper = _paper_for_user(db, user_id, paper_id)
    statement = select(Chunk).where(Chunk.paper_id == paper.id)
    if page:
        statement = statement.where(Chunk.page_start <= page, Chunk.page_end >= page)
    chunks = list(db.execute(statement.order_by(Chunk.order_index)).scalars().all())
    if not chunks:
        return None, paper
    if not quote:
        return chunks[0], paper

    normalized_quote = normalize_text(quote)
    best: tuple[int, Chunk] | None = None
    for chunk in chunks:
        text = normalize_text(chunk.text)
        if normalized_quote and normalized_quote in text:
            return chunk, paper
        score = 0
        for sentence in re.split(r"(?<=[。！？.!?])\s*", quote):
            normalized_sentence = normalize_text(sentence)
            if len(normalized_sentence) >= 24 and normalized_sentence in text:
                score += 2
        if len(normalized_quote) >= 40 and normalized_quote[:60] in text:
            score += 3
        if score and (best is None or score > best[0]):
            best = (score, chunk)
    return (best[1] if best else None), paper


def _fingerprint(
    user_id: str,
    paper_id: str | None,
    chunk_id: str | None,
    quote: str,
    claim: str | None,
    evidence_type: str,
    source_type: str,
    source_id: str | None,
    analysis_id: str | None,
) -> str:
    payload = "|".join(
        [
            user_id,
            paper_id or "",
            chunk_id or "",
            normalize_text(quote)[:500],
            normalize_text(claim or "")[:220],
            evidence_type,
            source_type,
            source_id or "",
            analysis_id or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_evidence(
    db: Session,
    user: User,
    *,
    paper_id: str | None = None,
    chunk_id: str | None = None,
    page: int | None = None,
    section: str | None = None,
    quote: str = "",
    claim: str | None = None,
    evidence_type: str = "direct",
    confidence: float | None = None,
    source_type: str = "manual",
    source_id: str | None = None,
    analysis_id: str | None = None,
    meta: dict | None = None,
) -> tuple[Evidence, bool]:
    """Create (or return an existing) evidence record. Returns (evidence, created)."""
    if evidence_type not in EVIDENCE_TYPES:
        raise EvidenceError(f"未知证据类型：{evidence_type}")

    quote = (quote or "").strip()[:4000]
    claim = clean_claim(claim, 3000)
    chunk, paper = resolve_chunk(db, user.id, paper_id, chunk_id, page, quote)
    if paper is None and paper_id:
        paper = _paper_for_user(db, user.id, paper_id)

    if chunk is not None:
        paper = paper or db.get(Paper, chunk.paper_id)
        paper_id = chunk.paper_id
        chunk_id = chunk.id
        page = page or chunk.page_start
        section = section or chunk.section_title

    verified = False
    note = "没有可定位的原文切片"
    if chunk is not None and quote:
        verified, note = verify_quote(chunk.text, quote)
    elif chunk is not None and evidence_type == "insufficient":
        note = "未检索到足够证据"

    base = BASE_CONFIDENCE.get(evidence_type, 0.5)
    value = base if confidence is None else max(0.0, min(1.0, float(confidence)))
    if not verified and evidence_type not in {"insufficient", "external"}:
        value = min(value, 0.3)

    fingerprint = _fingerprint(
        user.id, paper_id, chunk_id, quote, claim, evidence_type, source_type, source_id, analysis_id
    )
    existing = db.execute(
        select(Evidence).where(Evidence.user_id == user.id, Evidence.fingerprint == fingerprint)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    evidence = Evidence(
        user_id=user.id,
        paper_id=paper_id,
        chunk_id=chunk_id,
        analysis_id=analysis_id,
        page=page,
        section=(section or "")[:400] or None,
        quote=quote,
        claim=claim,
        evidence_type=evidence_type,
        confidence=round(value, 3),
        verified=verified,
        verification_note=note[:300],
        source_type=source_type,
        source_id=source_id,
        fingerprint=fingerprint,
        meta=meta or {},
    )
    db.add(evidence)
    db.flush()
    return evidence, True


def create_insufficient(
    db: Session,
    user: User,
    *,
    claim: str,
    source_type: str,
    source_id: str | None = None,
    analysis_id: str | None = None,
    paper_id: str | None = None,
) -> tuple[Evidence, bool]:
    return create_evidence(
        db,
        user,
        paper_id=paper_id,
        quote="",
        claim=claim,
        evidence_type="insufficient",
        source_type=source_type,
        source_id=source_id,
        analysis_id=analysis_id,
        meta={"reason": "no_sufficient_evidence"},
    )


def clean_claim(text: str | None, limit: int = 280) -> str | None:
    """Turn an AI answer into a short, readable claim (no Markdown noise)."""
    if not text:
        return None
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith((">", "#", "|", "```")):
            continue
        lines.append(stripped.lstrip("-* "))
    value = " ".join(lines)
    value = re.sub(r"[*_`]", "", value)
    value = re.sub(r"\[C\d+\]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit] or None


def default_type_for(kind: str, citation_count: int) -> str:
    if kind in {"gap", "comparison", "fragment_comparison", "critical", "analysis", "explore"}:
        return "inferred"
    if kind in {"opportunity", "report"}:
        return "hypothesis"
    if kind == "external":
        return "external"
    if kind == "multi_paper" and citation_count > 1:
        return "shared"
    return "direct"


def harvest_citations(
    db: Session,
    user: User,
    citations: list[dict],
    *,
    source_type: str,
    source_id: str | None,
    analysis_id: str | None = None,
    analysis_kind: str = "",
    claim: str | None = None,
    evidence_type: str | None = None,
    insufficient_if_empty: bool = False,
) -> tuple[list[Evidence], int]:
    """Persist evidence for citations produced by an answer or analysis."""
    created: list[Evidence] = []
    skipped = 0
    paper_ids = {c.get("paper_id") for c in citations if c.get("paper_id")}
    default_type = evidence_type or default_type_for(analysis_kind, len(paper_ids))

    for citation in citations:
        quote = str(citation.get("quote") or "")
        if not quote:
            continue
        resource_type = citation.get("resource_type")
        if resource_type in {"knowledge", "image", "artifact", "project"} and citation.get("resource_id"):
            try:
                record, is_new = create_evidence(
                    db,
                    user,
                    paper_id=None,
                    chunk_id=None,
                    page=citation.get("page"),
                    section=citation.get("section"),
                    quote=quote,
                    claim=claim,
                    evidence_type=default_type,
                    source_type=resource_type,
                    source_id=str(citation.get("resource_id")),
                    analysis_id=analysis_id,
                    meta={
                        "citation_key": citation.get("key"),
                        "resource_title": citation.get("resource_title"),
                        "resource_type": resource_type,
                        "source_paper_id": citation.get("paper_id"),
                        "answer_source_type": source_type,
                        "answer_source_id": source_id,
                        "analysis_kind": analysis_kind,
                    },
                )
            except EvidenceError:
                skipped += 1
                continue
            if is_new:
                created.append(record)
            else:
                skipped += 1
            continue
        try:
            record, is_new = create_evidence(
                db,
                user,
                paper_id=citation.get("paper_id"),
                chunk_id=citation.get("chunk_id"),
                page=citation.get("page"),
                section=citation.get("section"),
                quote=quote,
                claim=claim,
                evidence_type=default_type,
                source_type=source_type,
                source_id=source_id,
                analysis_id=analysis_id,
                meta={
                    "citation_key": citation.get("key"),
                    "paper_title": citation.get("paper_title"),
                    "analysis_kind": analysis_kind,
                },
            )
        except EvidenceError:
            skipped += 1
            continue
        if is_new:
            created.append(record)
        else:
            skipped += 1

    if not citations and insufficient_if_empty:
        record, is_new = create_insufficient(
            db,
            user,
            claim=(claim or "该结果没有检索到可回溯的原文证据")[:2000],
            source_type=source_type,
            source_id=source_id,
            analysis_id=analysis_id,
        )
        if is_new:
            created.append(record)
        else:
            skipped += 1
    return created, skipped


def save_analysis(
    db: Session,
    user: User,
    *,
    kind: str,
    title: str,
    content: str,
    citations: list[dict],
    scope_type: str = "papers",
    scope_ids: list[str] | None = None,
    paper_ids: list[str] | None = None,
    local: bool = False,
    model: str | None = None,
    evidence_type: str | None = None,
) -> tuple[ResearchAnalysis, list[Evidence]]:
    """Persist an AI analysis and harvest its evidence in one transaction."""
    analysis = ResearchAnalysis(
        user_id=user.id,
        kind=kind,
        title=title[:390],
        scope_type=scope_type,
        scope_ids=scope_ids or [],
        paper_ids=paper_ids or [],
        content=content,
        citations=citations,
        local=local,
        model=model,
    )
    db.add(analysis)
    db.flush()
    created, _skipped = harvest_citations(
        db,
        user,
        citations,
        source_type="analysis",
        source_id=analysis.id,
        analysis_id=analysis.id,
        analysis_kind=kind,
        claim=title,
        evidence_type=evidence_type,
        insufficient_if_empty=True,
    )
    db.commit()
    db.refresh(analysis)
    return analysis, created


def list_evidence(
    db: Session,
    user: User,
    *,
    paper_id: str | None = None,
    chunk_id: str | None = None,
    evidence_type: str | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    analysis_id: str | None = None,
    verified: bool | None = None,
    query: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[Evidence, str | None]]:
    statement = (
        select(Evidence, Paper.title)
        .outerjoin(Paper, Paper.id == Evidence.paper_id)
        .where(Evidence.user_id == user.id)
    )
    if paper_id:
        statement = statement.where(Evidence.paper_id == paper_id)
    if chunk_id:
        statement = statement.where(Evidence.chunk_id == chunk_id)
    if evidence_type:
        statement = statement.where(Evidence.evidence_type == evidence_type)
    if source_type:
        statement = statement.where(Evidence.source_type == source_type)
    if source_id:
        statement = statement.where(Evidence.source_id == source_id)
    if analysis_id:
        statement = statement.where(Evidence.analysis_id == analysis_id)
    if verified is not None:
        statement = statement.where(Evidence.verified == verified)
    if query.strip():
        needle = f"%{query.strip()}%"
        statement = statement.where(
            Evidence.quote.ilike(needle) | Evidence.claim.ilike(needle) | Evidence.section.ilike(needle)
        )
    statement = statement.order_by(Evidence.created_at.desc()).limit(max(1, min(limit, 300))).offset(max(0, offset))
    return [(row[0], row[1]) for row in db.execute(statement).all()]


def evidence_stats(db: Session, user: User) -> dict:
    rows = db.execute(
        select(Evidence.evidence_type, func.count(Evidence.id))
        .where(Evidence.user_id == user.id)
        .group_by(Evidence.evidence_type)
    ).all()
    total = db.execute(select(func.count(Evidence.id)).where(Evidence.user_id == user.id)).scalar() or 0
    verified = db.execute(
        select(func.count(Evidence.id)).where(Evidence.user_id == user.id, Evidence.verified.is_(True))
    ).scalar() or 0
    papers = db.execute(
        select(func.count(func.distinct(Evidence.paper_id))).where(
            Evidence.user_id == user.id, Evidence.paper_id.is_not(None)
        )
    ).scalar() or 0
    by_type = {key: 0 for key in EVIDENCE_TYPES}
    for evidence_type, count in rows:
        by_type[evidence_type] = count
    return {"total": total, "verified": verified, "papers": papers, "by_type": by_type}


def _looks_insufficient(answer: str) -> bool:
    needles = ("未检索到", "没有足够证据", "证据不足", "no sufficient evidence", "没有找到")
    return any(needle in answer for needle in needles)


def backfill_evidence(db: Session, user: User) -> dict:
    """Backfill evidence from existing messages, annotations and knowledge."""
    created = 0
    skipped = 0

    messages = db.execute(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Conversation.user_id == user.id, Message.role == "assistant")
    ).scalars().all()
    for message in messages:
        citations = message.citations or []
        if not citations:
            continue
        records, skipped_count = harvest_citations(
            db,
            user,
            citations,
            source_type="message",
            source_id=message.id,
            analysis_kind=message.mode or "quick",
            claim=message.content[:600],
            insufficient_if_empty=False,
        )
        created += len(records)
        skipped += skipped_count

    annotations = db.execute(
        select(Annotation).where(Annotation.user_id == user.id, Annotation.deleted_at.is_(None))
    ).scalars().all()
    for annotation in annotations:
        if not annotation.quote:
            continue
        record, is_new = create_evidence(
            db,
            user,
            paper_id=annotation.paper_id,
            page=annotation.page_number,
            quote=annotation.quote,
            claim=annotation.note,
            evidence_type="direct",
            source_type="annotation",
            source_id=annotation.id,
            meta={"color": annotation.color},
        )
        created += 1 if is_new else 0
        skipped += 0 if is_new else 1

    knowledge_items = db.execute(
        select(KnowledgeItem).where(KnowledgeItem.user_id == user.id)
    ).scalars().all()
    for item in knowledge_items:
        if not item.source_quote or not item.source_paper_id:
            continue
        record, is_new = create_evidence(
            db,
            user,
            paper_id=item.source_paper_id,
            page=item.source_page,
            quote=item.source_quote,
            claim=item.title,
            evidence_type="direct",
            source_type="knowledge",
            source_id=item.id,
        )
        created += 1 if is_new else 0
        skipped += 0 if is_new else 1

    db.commit()
    return {"created": created, "skipped": skipped}


def insufficient_for_answer(
    db: Session,
    user: User,
    *,
    answer: str,
    source_type: str,
    source_id: str | None,
    analysis_id: str | None = None,
) -> Evidence | None:
    if not _looks_insufficient(answer):
        return None
    record, is_new = create_insufficient(
        db,
        user,
        claim=answer[:800],
        source_type=source_type,
        source_id=source_id,
        analysis_id=analysis_id,
    )
    return record if is_new else None