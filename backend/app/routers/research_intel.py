"""P4 Research Intelligence endpoints: facets, matrix, conflicts, evolution."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import CollectionPaper, Paper, ResearchInsight, User
from ..schemas import GapValidateRequest, PaperSetRequest
from ..serializers import insight_out
from ..services import multipaper
from ..services.llm import resolve_model_config

router = APIRouter(tags=["research-intelligence"])


def _resolve_papers(db: Session, user: User, paper_ids: list[str], minimum: int = 2) -> list[Paper]:
    ids = [paper_id for paper_id in dict.fromkeys(paper_ids) if paper_id]
    if len(ids) < minimum:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"至少需要 {minimum} 篇论文")
    papers = list(db.execute(select(Paper).where(Paper.user_id == user.id, Paper.id.in_(ids))).scalars().all())
    if len(papers) != len(ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "部分论文不存在或无权访问")
    return papers


@router.post("/research/matrix")
async def research_matrix(
    payload: PaperSetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    papers = _resolve_papers(db, user, payload.paper_ids, minimum=1)
    config = resolve_model_config(db, user)
    result = await multipaper.build_matrix(db, user, papers, config, force=payload.force)
    return result


@router.post("/research/conflicts")
async def research_conflicts(
    payload: PaperSetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    papers = _resolve_papers(db, user, payload.paper_ids, minimum=2)
    config = resolve_model_config(db, user)
    result = await multipaper.build_conflicts(db, user, papers, config, force=payload.force)
    return result


@router.post("/research/evolution")
async def research_evolution(
    payload: PaperSetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    papers = _resolve_papers(db, user, payload.paper_ids, minimum=2)
    config = resolve_model_config(db, user)
    result = await multipaper.build_evolution(db, user, papers, config, force=payload.force)
    return result


@router.post("/research/gap/validate")
def validate_gap(
    payload: GapValidateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    papers = _resolve_papers(db, user, payload.paper_ids, minimum=1)
    config = resolve_model_config(db, user)
    return multipaper.validate_gap(db, user, payload.claim.strip(), papers, config)


@router.get("/research/insights")
def list_insights(
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(ResearchInsight).where(ResearchInsight.user_id == user.id)
    if kind:
        statement = statement.where(ResearchInsight.kind == kind)
    rows = list(
        db.execute(statement.order_by(ResearchInsight.created_at.desc()).limit(limit)).scalars().all()
    )
    return {"items": [insight_out(row) for row in rows]}


@router.get("/research/insights/{insight_id}")
def get_insight(
    insight_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    insight = db.get(ResearchInsight, insight_id)
    if insight is None or insight.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "研究情报不存在或无权访问")
    return {"insight": insight_out(insight)}
