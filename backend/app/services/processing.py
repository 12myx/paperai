"""Background paper ingestion: store, parse, chunk, index."""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy import delete

from ..config import settings
from ..db import SessionLocal
from ..models import Chunk, Figure, Paper, PaperPage, Section, UsageEvent, utcnow
from .chunking import build_chunks
from .pdf import extract_pdf
from .rag import invalidate_paper
from .storage import storage

logger = logging.getLogger("paperlens.processing")


class PermanentProcessingError(Exception):
    """A document that cannot succeed by retrying the same bytes (e.g. scanned PDF)."""


def process_paper(
    paper_id: str,
    progress: Callable[[str, int], None] | None = None,
    raise_on_error: bool = False,
) -> None:
    db = SessionLocal()

    def report(stage: str, pct: int) -> None:
        if progress is not None:
            try:
                progress(stage, max(0, min(100, pct)))
            except Exception:  # noqa: BLE001 - progress must never break parsing
                logger.exception("Progress callback failed")

    try:
        paper = db.get(Paper, paper_id)
        if paper is None:
            return
        paper.status = "processing"
        paper.error = None
        db.commit()
        report("读取 PDF", 10)

        path = storage.abs_path(paper.stored_path)
        data = path.read_bytes()
        parsed = extract_pdf(data, max_pages=settings.max_pdf_pages)
        report("解析版面与章节", 35)

        db.execute(delete(Chunk).where(Chunk.paper_id == paper.id))
        db.execute(delete(Section).where(Section.paper_id == paper.id))
        db.execute(delete(PaperPage).where(PaperPage.paper_id == paper.id))
        db.execute(delete(Figure).where(Figure.paper_id == paper.id))
        db.commit()
        report("写入页面与章节", 50)

        offset = 0
        for page in parsed.pages:
            db.add(
                PaperPage(
                    paper_id=paper.id,
                    page_number=page["page_number"],
                    width=page["width"],
                    height=page["height"],
                    text=page["text"],
                    char_start=offset,
                    char_end=offset + len(page["text"]),
                )
            )
            offset += len(page["text"]) + 1

        section_records: dict[int, Section] = {}
        for section in parsed.sections:
            record = Section(
                paper_id=paper.id,
                title=section["title"][:390],
                level=section.get("level", 1),
                order_index=section.get("order_index", 0),
                page_start=section.get("page_start", 1),
                page_end=section.get("page_end", 1),
            )
            db.add(record)
            section_records[section.get("order_index", 0)] = record
        db.flush()

        chunks = build_chunks(parsed)
        if not chunks:
            raise PermanentProcessingError("PDF 中未提取到可检索文本，可能是扫描版或图片型 PDF；请先进行 OCR 或上传文本版。")
        report("构建章节感知切片", 65)
        for chunk in chunks:
            section = section_records.get(chunk["section_order"])
            db.add(
                Chunk(
                    paper_id=paper.id,
                    section_id=section.id if section else None,
                    section_title=chunk["section_title"],
                    order_index=chunk["order_index"],
                    page_start=chunk["page_start"],
                    page_end=chunk["page_end"],
                    text=chunk["text"],
                    char_start=chunk["char_start"],
                    char_end=chunk["char_end"],
                    bbox=chunk["bbox"],
                    token_count=chunk["token_count"],
                    tags=chunk["tags"],
                    kind=chunk["kind"],
                )
            )

        report("提取图表", 80)
        for figure in parsed.figures:
            image_path = None
            if figure.get("data"):
                ext = figure.get("ext") or "png"
                if ext not in {"png", "jpeg", "jpg"}:
                    ext = "png"
                image_path = storage.save_figure(paper.user_id, paper.id, figure["order_index"], figure["data"], ext)
            db.add(
                Figure(
                    user_id=paper.user_id,
                    paper_id=paper.id,
                    page_number=figure["page_number"],
                    order_index=figure["order_index"],
                    image_path=image_path,
                    caption=figure.get("caption"),
                    kind=figure.get("kind", "figure"),
                    width=figure.get("width", 0),
                    height=figure.get("height", 0),
                    bbox=figure.get("bbox") or {},
                    table_markdown=figure.get("table_markdown"),
                )
            )

        if parsed.title and len(parsed.title.strip()) > 6 and "untitled" not in parsed.title.lower():
            paper.title = parsed.title[:590]
        if parsed.authors:
            paper.authors = parsed.authors
        if parsed.year:
            paper.year = parsed.year
        if parsed.abstract:
            paper.abstract = parsed.abstract
        paper.language = parsed.language
        paper.page_count = parsed.page_count
        paper.meta = {**(paper.meta or {}), **parsed.meta, "section_count": len(parsed.sections), "chunk_count": len(chunks)}
        paper.status = "ready"
        paper.updated_at = utcnow()
        report("完成索引", 100)
        db.add(UsageEvent(user_id=paper.user_id, kind="paper_processed", detail=f"{paper.id}:{len(chunks)} chunks"))
        db.commit()
        invalidate_paper(paper.user_id, paper.id)
        logger.info("Processed paper %s (%s chunks)", paper.id, len(chunks))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Paper processing failed: %s", paper_id)
        paper = db.get(Paper, paper_id)
        if paper:
            paper.status = "failed"
            paper.error = str(exc)[:1500]
            db.commit()
        if raise_on_error:
            raise
    finally:
        db.close()