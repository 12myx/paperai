"""Preflight checks before generating academic artifacts.

A scanned PDF can be marked ready while containing no extractable text. The
artifact generator must not turn that into an empty "failed" draft.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Chunk, Figure, Paper, PaperPage, User


def paper_preflight(db: Session, user: User, paper: Paper) -> dict:
    chunks = db.execute(select(func.count(Chunk.id)).where(Chunk.paper_id == paper.id)).scalar() or 0
    chars = db.execute(select(func.coalesce(func.sum(func.length(Chunk.text)), 0)).where(Chunk.paper_id == paper.id)).scalar() or 0
    pages = db.execute(select(func.count(PaperPage.id)).where(PaperPage.paper_id == paper.id)).scalar() or 0
    figures = db.execute(select(func.count(Figure.id)).where(Figure.paper_id == paper.id, Figure.ignored.is_(False))).scalar() or 0
    ready = chunks > 0 and int(chars) >= 200
    if paper.status != "ready":
        reason, message = "not_parsed", "论文尚未解析完成"
    elif chunks == 0:
        reason, message = "scanned_pdf", "该论文是扫描件，未提取到可检索文本；请先 OCR 或上传可搜索 PDF"
    elif int(chars) < 200:
        reason, message = "too_little_text", "论文可检索文本过少，无法生成有证据的内容"
    else:
        reason, message = "ready", "可生成"
    return {
        "paper_id": paper.id,
        "title": paper.title,
        "year": paper.year,
        "status": paper.status,
        "pages": int(pages),
        "chunks": int(chunks),
        "chars": int(chars),
        "figures": int(figures),
        "ready": ready,
        "reason": reason,
        "message": message,
    }


def scope_preflight(db: Session, user: User, papers: list[Paper]) -> dict:
    items = [paper_preflight(db, user, paper) for paper in papers]
    ready = [item for item in items if item["ready"]]
    return {
        "items": items,
        "ready": len(ready) > 0,
        "ready_count": len(ready),
        "blocked_count": len(items) - len(ready),
        "all_ready": len(ready) == len(items) and bool(items),
    }
