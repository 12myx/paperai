"""Durable lifecycle ledger for research resources used by an agent run."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ResourceUsage, User, utcnow

STAGES = ("retrieved", "included", "read", "referenced")


def record_usage(
    db: Session,
    user: User,
    *,
    run_id: str,
    conversation_id: str | None,
    message_id: str | None = None,
    resource_type: str,
    resource_id: str,
    resource_name: str = "",
    stage: str,
    selection_source: str = "auto",
    retrieval_reason: str | None = None,
    tool_name: str | None = None,
) -> ResourceUsage | None:
    if stage not in STAGES or not run_id or not user.id or not resource_id:
        return None
    existing = db.execute(
        select(ResourceUsage).where(
            ResourceUsage.run_id == run_id,
            ResourceUsage.resource_type == resource_type,
            ResourceUsage.resource_id == resource_id,
            ResourceUsage.stage == stage,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row = ResourceUsage(
        user_id=user.id,
        conversation_id=conversation_id,
        run_id=run_id,
        message_id=message_id,
        resource_type=resource_type,
        resource_id=resource_id[:128],
        resource_name=(resource_name or "")[:390],
        stage=stage,
        selection_source=selection_source[:24],
        retrieval_reason=(retrieval_reason or "")[:1200] or None,
        tool_name=tool_name,
        created_at=utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        return None
    return row


def list_run_usage(db: Session, user: User, run_id: str) -> list[dict]:
    rows = list(
        db.execute(
            select(ResourceUsage)
            .where(ResourceUsage.user_id == user.id, ResourceUsage.run_id == run_id)
            .order_by(ResourceUsage.created_at.asc(), ResourceUsage.stage.asc())
        ).scalars().all()
    )
    return [
        {
            "id": row.id,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "resource_name": row.resource_name,
            "stage": row.stage,
            "selection_source": row.selection_source,
            "retrieval_reason": row.retrieval_reason,
            "tool_name": row.tool_name,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def source_for(resource_id: str, explicit_ids: list[str], project_id: str | None) -> str:
    if resource_id in set(explicit_ids or []):
        return "explicit"
    if project_id:
        return "project"
    return "auto"


def record_context(
    db: Session,
    user: User,
    *,
    run_id: str,
    conversation_id: str | None,
    context,
    request,
    papers,
) -> None:
    explicit_knowledge = list(request.knowledge_ids or [])
    explicit_images = list(request.image_ids or [])
    explicit_artifacts = list(request.artifact_ids or [])
    project_id = context.project.id if context.project else None
    for paper in papers:
        record_usage(
            db, user, run_id=run_id, conversation_id=conversation_id,
            resource_type="paper", resource_id=paper.id, resource_name=paper.title,
            stage="included", selection_source=source_for(paper.id, list(request.scope_ids or []), None),
            retrieval_reason="当前研究范围",
        )
    for item in context.knowledge:
        record_usage(
            db, user, run_id=run_id, conversation_id=conversation_id,
            resource_type="knowledge", resource_id=item.id, resource_name=item.title,
            stage="included", selection_source=source_for(item.id, explicit_knowledge, project_id),
            retrieval_reason="显式选择" if item.id in explicit_knowledge else ("项目上下文" if project_id else "问题相关检索"),
        )
    for figure in context.images:
        record_usage(
            db, user, run_id=run_id, conversation_id=conversation_id,
            resource_type="image", resource_id=figure.id, resource_name=figure.caption or figure.kind,
            stage="included", selection_source=source_for(figure.id, explicit_images, project_id),
            retrieval_reason="显式选择" if figure.id in explicit_images else ("项目上下文" if project_id else "问题相关检索"),
        )
    for artifact in context.artifacts:
        record_usage(
            db, user, run_id=run_id, conversation_id=conversation_id,
            resource_type="artifact", resource_id=artifact.id, resource_name=artifact.title,
            stage="included", selection_source=source_for(artifact.id, explicit_artifacts, project_id),
            retrieval_reason="显式选择" if artifact.id in explicit_artifacts else ("项目上下文" if project_id else "问题相关检索"),
        )
    if context.project:
        record_usage(
            db, user, run_id=run_id, conversation_id=conversation_id,
            resource_type="project", resource_id=context.project.id,
            resource_name=context.project.name, stage="included",
            selection_source="explicit" if context.project.id in list(request.scope_ids or []) else "project",
            retrieval_reason="项目上下文",
        )
