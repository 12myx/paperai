"""Evidence System API: persisted, verifiable evidence records."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Annotation, Evidence, KnowledgeItem, Paper, User
from ..schemas import EvidenceCreate, EvidenceUpdate
from ..serializers import evidence_out
from ..services.evidence import (
    EVIDENCE_TYPES,
    EvidenceError,
    backfill_evidence,
    create_evidence,
    evidence_stats,
    list_evidence,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("")
def list_evidence_endpoint(
    paper_id: str | None = None,
    chunk_id: str | None = None,
    evidence_type: str | None = Query(None, alias="type"),
    source_type: str | None = None,
    source_id: str | None = None,
    analysis_id: str | None = None,
    verified: bool | None = None,
    query: str = "",
    limit: int = Query(100, ge=1, le=300),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if evidence_type and evidence_type not in EVIDENCE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知证据类型")
    rows = list_evidence(
        db,
        user,
        paper_id=paper_id,
        chunk_id=chunk_id,
        evidence_type=evidence_type,
        source_type=source_type,
        source_id=source_id,
        analysis_id=analysis_id,
        verified=verified,
        query=query,
        limit=limit,
        offset=offset,
    )
    return {"items": [evidence_out(item, title) for item, title in rows], "total": len(rows)}


@router.get("/stats")
def stats_endpoint(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {**evidence_stats(db, user), "types": EVIDENCE_TYPES}


@router.post("/backfill")
def backfill_endpoint(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return backfill_evidence(db, user)


@router.post("/from-annotation/{annotation_id}", status_code=status.HTTP_201_CREATED)
def evidence_from_annotation(
    annotation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    annotation = db.get(Annotation, annotation_id)
    if annotation is None or annotation.user_id != user.id or annotation.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批注不存在或无权访问")
    if not annotation.quote.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "批注没有可引用的原文")
    try:
        record, created = create_evidence(
            db,
            user,
            paper_id=annotation.paper_id,
            page=annotation.page_number,
            quote=annotation.quote,
            claim=annotation.note,
            evidence_type="direct",
            source_type="annotation",
            source_id=annotation.id,
            meta={"color": annotation.color, "tags": annotation.tags or []},
        )
    except EvidenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    paper = db.get(Paper, record.paper_id) if record.paper_id else None
    return {"evidence": evidence_out(record, paper.title if paper else None), "created": created}


@router.post("/from-knowledge/{knowledge_id}", status_code=status.HTTP_201_CREATED)
def evidence_from_knowledge(
    knowledge_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(KnowledgeItem, knowledge_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "知识条目不存在或无权访问")
    if not item.source_quote or not item.source_paper_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "该知识没有可回溯的原文引用")
    try:
        record, created = create_evidence(
            db,
            user,
            paper_id=item.source_paper_id,
            chunk_id=item.source_chunk_id,
            page=item.source_page,
            quote=item.source_quote,
            claim=item.title,
            evidence_type="direct",
            source_type="knowledge",
            source_id=item.id,
        )
    except EvidenceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    db.commit()
    paper = db.get(Paper, record.paper_id) if record.paper_id else None
    return {"evidence": evidence_out(record, paper.title if paper else None), "created": created}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_evidence_endpoint(
    payload: EvidenceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if payload.evidence_type not in EVIDENCE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知证据类型")
    if not payload.quote.strip() and payload.evidence_type != "insufficient":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "证据必须包含原文引用")
    try:
        record, created = create_evidence(
            db,
            user,
            paper_id=payload.paper_id,
            chunk_id=payload.chunk_id,
            page=payload.page,
            section=payload.section,
            quote=payload.quote,
            claim=payload.claim,
            evidence_type=payload.evidence_type,
            confidence=payload.confidence,
            source_type=payload.source_type,
            source_id=payload.source_id,
            analysis_id=payload.analysis_id,
            meta=payload.meta,
        )
    except EvidenceError as exc:
        code = status.HTTP_404_NOT_FOUND if "无权" in str(exc) or "不存在" in str(exc) else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(code, str(exc)) from exc
    db.commit()
    paper = db.get(Paper, record.paper_id) if record.paper_id else None
    return {"evidence": evidence_out(record, paper.title if paper else None), "created": created}


@router.get("/{evidence_id}")
def get_evidence(
    evidence_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    record = db.get(Evidence, evidence_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "证据不存在或无权访问")
    paper = db.get(Paper, record.paper_id) if record.paper_id else None
    return {"evidence": evidence_out(record, paper.title if paper else None)}


@router.patch("/{evidence_id}")
def update_evidence(
    evidence_id: str,
    payload: EvidenceUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    record = db.get(Evidence, evidence_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "证据不存在或无权访问")
    if payload.evidence_type is not None:
        if payload.evidence_type not in EVIDENCE_TYPES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知证据类型")
        record.evidence_type = payload.evidence_type
    if payload.claim is not None:
        record.claim = payload.claim[:3000] or None
    if payload.confidence is not None:
        record.confidence = max(0.0, min(1.0, payload.confidence))
    db.commit()
    paper = db.get(Paper, record.paper_id) if record.paper_id else None
    return {"evidence": evidence_out(record, paper.title if paper else None)}


@router.delete("/{evidence_id}")
def delete_evidence(
    evidence_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    record = db.get(Evidence, evidence_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "证据不存在或无权访问")
    db.delete(record)
    db.commit()
    return {"ok": True, "deleted_id": evidence_id}
