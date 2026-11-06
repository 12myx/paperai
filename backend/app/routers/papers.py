"""Paper upload, library queries, PDF streaming and deletion."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Annotation,
    Chunk,
    Collection,
    CollectionPaper,
    Figure,
    Paper,
    Section,
    UsageEvent,
    User,
    utcnow,
)
from ..schemas import PaperUpdate
from ..serializers import paper_brief
from ..serializers import paper_detail as serialize_paper_detail
from ..services.queue import processing_queue
from ..services.rag import invalidate_paper
from ..services.storage import safe_filename, storage

router = APIRouter(prefix="/papers", tags=["papers"])


def get_paper_or_404(db: Session, user: User, paper_id: str) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None or paper.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "论文不存在或无权访问")
    return paper


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_paper(
    file: UploadFile = File(...),
    tags: str = Form(""),
    collection_id: str | None = Form(None),
    allow_duplicate: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    filename = safe_filename(file.filename or "paper.pdf", "paper")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "仅支持 PDF 文件")

    limit = settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"文件超过 {settings.max_upload_mb}MB 限制")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data.startswith(b"%PDF"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "文件内容不是有效的 PDF")

    digest = hashlib.sha256(data).hexdigest()
    duplicate = db.execute(
        select(Paper).where(Paper.user_id == user.id, Paper.sha256 == digest, Paper.status != "failed")
    ).scalars().first()
    if duplicate and not allow_duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "duplicate", "message": "资料库中已存在同一篇论文", "paper_id": duplicate.id, "title": duplicate.title},
        )

    paper = Paper(
        user_id=user.id,
        title=Path(filename).stem[:590] or "Untitled paper",
        filename=filename,
        stored_path="",
        size_bytes=len(data),
        sha256=digest,
        status="processing",
        tags=[t.strip() for t in tags.split(",") if t.strip()][:20],
        meta={},
    )
    db.add(paper)
    db.flush()
    paper.stored_path = storage.save_pdf(user.id, paper.id, filename, data)
    if collection_id:
        collection = db.get(Collection, collection_id)
        if collection and collection.user_id == user.id:
            db.add(CollectionPaper(collection_id=collection.id, paper_id=paper.id))
    db.add(UsageEvent(user_id=user.id, kind="paper_upload", detail=f"{paper.id}:{len(data)}"))
    db.commit()
    db.refresh(paper)

    await processing_queue.enqueue(user, paper)
    return {"paper": paper_brief(paper), "duplicate": bool(duplicate)}


@router.get("")
def list_papers(
    query: str = "",
    status_filter: str = Query("", alias="status"),
    favorite: bool | None = None,
    tag: str = "",
    collection_id: str | None = None,
    sort: str = "recent",
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    statement = select(Paper).where(Paper.user_id == user.id)
    if query.strip():
        pattern = f"%{query.strip()}%"
        statement = statement.where(
            or_(Paper.title.ilike(pattern), Paper.authors.ilike(pattern), Paper.abstract.ilike(pattern))
        )
    if status_filter:
        statement = statement.where(Paper.status == status_filter)
    if favorite is not None:
        statement = statement.where(Paper.favorite == favorite)
    if tag:
        statement = statement.where(cast(Paper.tags, String).ilike(f'%"{tag}"%'))
    if collection_id:
        statement = statement.join(CollectionPaper, CollectionPaper.paper_id == Paper.id).where(
            CollectionPaper.collection_id == collection_id
        )
    order = {
        "recent": Paper.created_at.desc(),
        "oldest": Paper.created_at.asc(),
        "title": Paper.title.asc(),
        "pages": Paper.page_count.desc(),
    }.get(sort, Paper.created_at.desc())
    total = db.execute(select(func.count()).select_from(statement.subquery())).scalar() or 0
    papers = list(db.execute(statement.order_by(order).limit(limit).offset(offset)).scalars().all())
    ids = [p.id for p in papers]
    counts: dict[str, int] = {}
    if ids:
        rows = db.execute(
            select(Chunk.paper_id, func.count(Chunk.id)).where(Chunk.paper_id.in_(ids)).group_by(Chunk.paper_id)
        ).all()
        counts = {paper_id: count for paper_id, count in rows}
    return {"items": [paper_brief(p, counts.get(p.id)) for p in papers], "total": total}


@router.get("/tags")
def list_tags(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    papers = db.execute(select(Paper.tags).where(Paper.user_id == user.id)).scalars().all()
    counter: dict[str, int] = {}
    for tags in papers:
        for tag in tags or []:
            counter[tag] = counter.get(tag, 0) + 1
    return {"tags": [{"name": k, "count": v} for k, v in sorted(counter.items(), key=lambda item: -item[1])]}


@router.get("/{paper_id}")
def paper_detail(paper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = get_paper_or_404(db, user, paper_id)
    sections = list(db.execute(select(Section).where(Section.paper_id == paper.id).order_by(Section.order_index)).scalars().all())
    figures_count = db.execute(select(func.count(Figure.id)).where(Figure.paper_id == paper.id)).scalar() or 0
    annotations_count = db.execute(
        select(func.count(Annotation.id)).where(Annotation.paper_id == paper.id, Annotation.user_id == user.id, Annotation.deleted_at.is_(None))
    ).scalar() or 0
    chunks_count = db.execute(select(func.count(Chunk.id)).where(Chunk.paper_id == paper.id)).scalar() or 0
    return serialize_paper_detail(paper, sections, figures_count, annotations_count, chunks_count)


@router.patch("/{paper_id}")
def update_paper(paper_id: str, payload: PaperUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = get_paper_or_404(db, user, paper_id)
    if payload.title is not None:
        if not payload.title.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "标题不能为空")
        paper.title = payload.title.strip()[:590]
    if payload.authors is not None:
        paper.authors = payload.authors.strip()[:2000] or None
    if payload.year is not None:
        paper.year = payload.year
    if payload.venue is not None:
        paper.venue = payload.venue.strip()[:300] or None
    if payload.tags is not None:
        paper.tags = [t.strip()[:48] for t in payload.tags if t.strip()][:24]
    if payload.favorite is not None:
        paper.favorite = payload.favorite
    if payload.note is not None:
        paper.note = payload.note[:5000]
    paper.updated_at = utcnow()
    db.commit()
    invalidate_paper(user.id, paper.id)
    return {"paper": paper_brief(paper)}


@router.delete("/{paper_id}")
def delete_paper(paper_id: str, confirm: bool = Query(False), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if not confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "删除论文需要确认（confirm=true）")
    paper = get_paper_or_404(db, user, paper_id)
    db.delete(paper)
    db.commit()
    storage.delete_paper(user.id, paper.id)
    invalidate_paper(user.id, paper_id)
    return {"ok": True, "deleted_id": paper_id}


@router.post("/{paper_id}/reprocess")
async def reprocess(paper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = get_paper_or_404(db, user, paper_id)
    paper.status = "processing"
    paper.error = None
    db.commit()
    await processing_queue.enqueue(user, paper)
    return {"ok": True, "status": "processing"}


@router.get("/{paper_id}/file")
def paper_file(paper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    paper = get_paper_or_404(db, user, paper_id)
    try:
        path = storage.abs_path(paper.stored_path)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件路径无效") from exc
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "原始 PDF 文件不存在")
    return FileResponse(path, media_type="application/pdf", filename=paper.filename, content_disposition_type="inline")


@router.get("/{paper_id}/outline")
def paper_outline(paper_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    paper = get_paper_or_404(db, user, paper_id)
    sections = list(db.execute(select(Section).where(Section.paper_id == paper.id).order_by(Section.order_index)).scalars().all())
    chunks = list(db.execute(select(Chunk).where(Chunk.paper_id == paper.id).order_by(Chunk.order_index)).scalars().all())
    return {
        "sections": [
            {"id": s.id, "title": s.title, "level": s.level, "page_start": s.page_start, "page_end": s.page_end, "order_index": s.order_index}
            for s in sections
        ],
        "chunks": [
            {
                "id": c.id, "section_id": c.section_id, "section": c.section_title, "page_start": c.page_start,
                "page_end": c.page_end, "order_index": c.order_index, "tags": c.tags,
                "preview": c.text[:180],
            }
            for c in chunks
        ],
    }


@router.get("/{paper_id}/pages/{page_number}")
def page_text(paper_id: str, page_number: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    from ..models import PaperPage

    paper = get_paper_or_404(db, user, paper_id)
    page = db.execute(
        select(PaperPage).where(PaperPage.paper_id == paper.id, PaperPage.page_number == page_number)
    ).scalar_one_or_none()
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该页不存在")
    return {"page": page.page_number, "width": page.width, "height": page.height, "text": page.text}