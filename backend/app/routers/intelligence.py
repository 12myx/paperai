"""P5 Research Intelligence API: landscape, trends, connections, opportunities."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import IntelligenceReport, User
from ..schemas import IntelligenceRequest
from ..serializers import intelligence_report_out, paper_brief
from ..services import intelligence
from ..services.llm import resolve_model_config

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get("/scope")
def get_scope(
    scope_type: str = "all",
    scope_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        papers, scope = intelligence.resolve_scope(db, user, scope_type, scope_id)
    except intelligence.IntelligenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"scope": scope, "papers": [paper_brief(paper) for paper in papers]}


@router.post("/overview")
async def build_overview(
    payload: IntelligenceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if payload.scope_type not in intelligence.SCOPE_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知研究范围类型")
    config = resolve_model_config(db, user)
    try:
        return await intelligence.build_overview(
            db,
            user,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            paper_ids=payload.paper_ids,
            config=config,
            force=payload.force,
        )
    except intelligence.IntelligenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/reports")
def list_reports(
    kind: str | None = None,
    scope_type: str | None = None,
    scope_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(IntelligenceReport).where(IntelligenceReport.user_id == user.id)
    if kind:
        statement = statement.where(IntelligenceReport.kind == kind)
    if scope_type:
        statement = statement.where(IntelligenceReport.scope_type == scope_type)
    if scope_id:
        statement = statement.where(IntelligenceReport.scope_id == scope_id)
    rows = list(
        db.execute(statement.order_by(IntelligenceReport.created_at.desc()).limit(limit)).scalars().all()
    )
    return {"items": [intelligence_report_out(row) for row in rows]}


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    report = db.get(IntelligenceReport, report_id)
    if report is None or report.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "研究情报不存在或无权访问")
    return {"report": intelligence_report_out(report)}
