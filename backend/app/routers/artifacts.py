"""P8 academic artifacts and quality checking."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import AcademicArtifact, ArtifactQualityReport, User
from ..schemas import ArtifactExportRequest, ArtifactGenerateRequest
from ..serializers import artifact_out, export_out, quality_out
from ..services import artifacts
from ..services.llm import resolve_model_config

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/kinds")
def artifact_kinds() -> dict:
    return {"items": [{"id": key, **value} for key, value in artifacts.KINDS.items()]}


@router.post("/generate")
async def generate_artifact(
    payload: ArtifactGenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if payload.kind not in artifacts.KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知成果类型")
    config = resolve_model_config(db, user)
    try:
        artifact, report = await artifacts.generate_artifact(
            db,
            user,
            kind=payload.kind,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            paper_ids=payload.paper_ids,
            title=payload.title,
            config=config,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"artifact": artifact_out(artifact), "quality": quality_out(report)}


@router.get("")
def list_artifacts(
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(AcademicArtifact).where(AcademicArtifact.user_id == user.id)
    if kind:
        statement = statement.where(AcademicArtifact.kind == kind)
    rows = list(db.execute(statement.order_by(AcademicArtifact.created_at.desc()).limit(limit)).scalars().all())
    return {"items": [artifact_out(row) for row in rows]}


@router.get("/{artifact_id}")
def get_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    artifact = db.get(AcademicArtifact, artifact_id)
    if artifact is None or artifact.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成果不存在或无权访问")
    report = artifacts.latest_report(db, user, artifact.id)
    return {"artifact": artifact_out(artifact), "quality": quality_out(report)}


@router.post("/{artifact_id}/check")
def check_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    artifact = db.get(AcademicArtifact, artifact_id)
    if artifact is None or artifact.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成果不存在或无权访问")
    check = artifacts.check_artifact(db, artifact)
    report = ArtifactQualityReport(
        user_id=user.id,
        artifact_id=artifact.id,
        status=check["status"],
        score=check["score"],
        issues=check["issues"],
        summary=check["summary"],
    )
    db.add(report)
    artifact.quality_score = check["score"]
    artifact.quality_status = check["status"]
    db.commit()
    db.refresh(report)
    return {"quality": quality_out(report), "artifact": artifact_out(artifact)}


@router.post("/{artifact_id}/export", status_code=status.HTTP_201_CREATED)
def export_artifact(
    artifact_id: str,
    payload: ArtifactExportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    artifact = db.get(AcademicArtifact, artifact_id)
    if artifact is None or artifact.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成果不存在或无权访问")
    try:
        record = artifacts.export_artifact(db, user, artifact, payload.format)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"export": export_out(record)}


@router.delete("/{artifact_id}")
def delete_artifact(artifact_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    artifact = db.get(AcademicArtifact, artifact_id)
    if artifact is None or artifact.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "成果不存在或无权访问")
    db.delete(artifact)
    db.commit()
    return {"ok": True}
