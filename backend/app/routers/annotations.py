"""Highlights and notes tied to a PDF location."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Annotation, Paper, User, utcnow
from ..schemas import AnnotationCreate, AnnotationUpdate
from ..serializers import annotation_out

router = APIRouter(prefix="/annotations", tags=["annotations"])

COLORS = {"yellow", "blue", "green", "red", "purple"}


def _owned(db: Session, user: User, annotation_id: str) -> Annotation:
    annotation = db.get(Annotation, annotation_id)
    if annotation is None or annotation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "批注不存在或无权访问")
    return annotation


@router.get("")
def list_annotations(
    paper_id: str | None = None,
    color: str | None = None,
    tag: str | None = None,
    favorite: bool | None = None,
    include_deleted: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Annotation).where(Annotation.user_id == user.id)
    if paper_id:
        statement = statement.where(Annotation.paper_id == paper_id)
    if color:
        statement = statement.where(Annotation.color == color)
    if favorite is not None:
        statement = statement.where(Annotation.favorite == favorite)
    if not include_deleted:
        statement = statement.where(Annotation.deleted_at.is_(None))
    annotations = list(db.execute(statement.order_by(Annotation.page_number, Annotation.created_at)).scalars().all())
    if tag:
        annotations = [a for a in annotations if tag in (a.tags or [])]
    return {"items": [annotation_out(a) for a in annotations]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_annotation(payload: AnnotationCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = db.get(Paper, payload.paper_id)
    if paper is None or paper.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "论文不存在或无权访问")
    if payload.color not in COLORS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "颜色不在允许的范围内")
    if not payload.quote.strip() and not payload.rects:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "批注需要选中文本或位置")
    annotation = Annotation(
        user_id=user.id,
        paper_id=paper.id,
        page_number=max(1, payload.page),
        color=payload.color,
        quote=payload.quote[:4000],
        rects=payload.rects[:40],
        note=(payload.note or None),
        tags=[t[:32] for t in payload.tags][:12],
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return {"annotation": annotation_out(annotation)}


@router.patch("/{annotation_id}")
def update_annotation(annotation_id: str, payload: AnnotationUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    annotation = _owned(db, user, annotation_id)
    if payload.color is not None:
        if payload.color not in COLORS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "颜色不在允许的范围内")
        annotation.color = payload.color
    if payload.note is not None:
        annotation.note = payload.note[:5000]
    if payload.tags is not None:
        annotation.tags = [t[:32] for t in payload.tags][:12]
    if payload.favorite is not None:
        annotation.favorite = payload.favorite
    annotation.updated_at = utcnow()
    db.commit()
    return {"annotation": annotation_out(annotation)}


@router.delete("/{annotation_id}")
def delete_annotation(annotation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    annotation = _owned(db, user, annotation_id)
    annotation.deleted_at = utcnow()
    db.commit()
    return {"ok": True, "deleted_id": annotation.id, "undo_available": True}


@router.post("/{annotation_id}/restore")
def restore_annotation(annotation_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    annotation = _owned(db, user, annotation_id)
    annotation.deleted_at = None
    annotation.updated_at = utcnow()
    db.commit()
    return {"annotation": annotation_out(annotation)}
