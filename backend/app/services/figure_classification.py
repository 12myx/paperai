"""P0 figure/table classification and visual-record curation.

This is a read-only classification pass over existing extraction rows. It does
not re-parse PDFs and does not delete anything; page snapshots are hidden by
the default API view, not removed.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Figure, PaperPage, User

CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?|tab(?:le)?|chart|scheme|图|表)\s*[.:]?\s*\d+", re.I)


def _page_text(db: Session, paper_id: str, page_number: int) -> tuple[str, float, float]:
    page = db.execute(
        select(PaperPage).where(PaperPage.paper_id == paper_id, PaperPage.page_number == page_number)
    ).scalar_one_or_none()
    if page is None:
        return "", 0.0, 0.0
    return page.text or "", float(page.width or 0), float(page.height or 0)


def classify_figure(db: Session, figure: Figure, page_text: str | None = None, page_width: float = 0, page_height: float = 0) -> Figure:
    if page_text is None:
        page_text, page_width, page_height = _page_text(db, figure.paper_id, figure.page_number)
    caption = (figure.caption or "").strip()
    caption_confidence = 0.0
    if caption:
        caption_confidence = 0.92 if CAPTION_RE.match(caption) else 0.35
    bbox = figure.bbox or {}
    x0, y0 = float(bbox.get("x0", 0) or 0), float(bbox.get("y0", 0) or 0)
    x1, y1 = float(bbox.get("x1", 0) or 0), float(bbox.get("y1", 0) or 0)
    coverage = 0.0
    width_ratio = 0.0
    if page_width > 0 and page_height > 0:
        coverage = max(0.0, min(1.0, ((x1 - x0) * (y1 - y0)) / (page_width * page_height)))
        width_ratio = max(0.0, min(1.0, (x1 - x0) / page_width))
    text_len = len(page_text.strip())

    if figure.kind == "table" or figure.table_markdown:
        detected = "table"
        quality = 82 + (8 if caption_confidence >= 0.7 else 0) + min(10, len(figure.table_markdown or "") // 1000)
        snapshot = False
    elif coverage >= 0.55 and text_len >= 180:
        detected = "page_snapshot"
        quality = 8
        snapshot = True
    elif caption_confidence < 0.5 and width_ratio >= 0.78 and (text_len < 120 or coverage >= 0.35):
        # Scanned pages are often split into full-width horizontal bands and
        # have almost no extractable text. A real caption overrides this rule.
        detected = "page_snapshot"
        quality = 7
        snapshot = True
    elif coverage > 0.8 and text_len >= 80:
        detected = "page_snapshot"
        quality = 6
        snapshot = True
    elif caption_confidence >= 0.5:
        detected = "figure"
        quality = 74 + (8 if coverage and coverage < 0.5 else 0)
        snapshot = False
    elif coverage >= 0.02 and (figure.width >= 100 or figure.height >= 100):
        detected = "unclassified"
        quality = 32
        snapshot = False
    else:
        detected = "unclassified"
        quality = 18
        snapshot = False

    if detected == "figure" and coverage <= 0.0:
        quality -= 10
    figure.detected_kind = detected
    figure.is_page_snapshot = snapshot
    figure.caption_confidence = round(caption_confidence, 2)
    figure.quality_score = max(0, min(100, int(quality)))
    if figure.review_status not in {"confirmed", "rejected"}:
        figure.review_status = "auto"
    return figure


def classify_user_figures(db: Session, user: User) -> dict:
    figures = list(db.execute(select(Figure).where(Figure.user_id == user.id)).scalars().all())
    page_cache: dict[tuple[str, int], tuple[str, float, float]] = {}
    counts: dict[str, int] = {}
    for figure in figures:
        key = (figure.paper_id, figure.page_number)
        if key not in page_cache:
            page_cache[key] = _page_text(db, figure.paper_id, figure.page_number)
        classify_figure(db, figure, *page_cache[key])
        counts[figure.detected_kind] = counts.get(figure.detected_kind, 0) + 1
    db.commit()
    return {"total": len(figures), "by_kind": counts}