"""Section-aware chunking.

Chunks keep the original paragraph boundaries instead of hard character cuts so
that quotes stay grammatically complete and can be located in the PDF.
"""
from __future__ import annotations

import re

from .pdf import ParsedPaper

MAX_CHARS = 1150
MIN_CHARS = 260
MAX_PARAGRAPH = 2200

SECTION_TAGS = {
    "abstract": "abstract", "摘要": "abstract",
    "introduction": "introduction", "引言": "introduction", "绪论": "introduction",
    "related": "related-work", "background": "related-work", "相关工作": "related-work",
    "method": "method", "approach": "method", "方法": "method", "研究方法": "method",
    "experiment": "experiment", "evaluation": "experiment", "实验": "experiment",
    "result": "result", "结果": "result",
    "discussion": "discussion", "讨论": "discussion",
    "conclusion": "conclusion", "结论": "conclusion",
    "limitation": "limitation", "局限": "limitation",
    "future": "future-work", "展望": "future-work",
    "reference": "references", "参考文献": "references",
    "appendix": "appendix", "附录": "appendix",
}


def _tag_for_section(title: str) -> str:
    lowered = title.lower()
    for key, tag in SECTION_TAGS.items():
        if key in lowered:
            return tag
    return "body"


def _split_long_paragraph(text: str) -> list[str]:
    if len(text) <= MAX_PARAGRAPH:
        return [text]
    sentences = re.split(r"(?<=[。！？.!?])\s+", text)
    pieces, buffer = [], ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(buffer) + len(sentence) + 1 > MAX_CHARS and buffer:
            pieces.append(buffer.strip())
            buffer = sentence
        else:
            buffer = f"{buffer} {sentence}".strip()
    if buffer:
        pieces.append(buffer.strip())
    return pieces


def build_chunks(parsed: ParsedPaper) -> list[dict]:
    chunks: list[dict] = []
    section_of_paragraph: dict[int, tuple[str, str, str]] = {}
    for section in parsed.sections:
        for paragraph in section["paragraphs"]:
            section_of_paragraph[id(paragraph)] = (section["title"], section["level"], section["order_index"])

    # Global character offsets: chunks are offsets into parsed.full_text.
    offsets: dict[int, int] = {}
    cursor = 0
    for paragraph in parsed.paragraphs:
        offsets[id(paragraph)] = cursor
        cursor += len(paragraph.text) + 2

    buffer_texts: list[str] = []
    buffer_paras = []
    order = 0

    def flush() -> None:
        nonlocal buffer_texts, buffer_paras, order
        if not buffer_paras:
            return
        text = "\n\n".join(buffer_texts).strip()
        if len(text) < 40:
            buffer_texts, buffer_paras = [], []
            return
        first, last = buffer_paras[0], buffer_paras[-1]
        title, level, section_order = section_of_paragraph.get(id(first), ("Front Matter", 1, 0))
        start = offsets.get(id(first), 0)
        end = offsets.get(id(last), start) + len(last.text)
        tags = [_tag_for_section(title)]
        formula_hits = sum(1 for p in buffer_paras if _formula_density(p.text) > 0.08)
        if formula_hits >= 2 or (len(buffer_paras) == 1 and _formula_density(text) > 0.12):
            tags.append("formula")
        if any(p.is_heading for p in buffer_paras):
            tags.append("heading")
        chunks.append(
            {
                "text": text,
                "section_title": title[:400],
                "section_order": section_order,
                "order_index": order,
                "page_start": first.page,
                "page_end": last.page,
                "char_start": start,
                "char_end": end,
                "bbox": {
                    "page": first.page,
                    "x0": first.bbox[0], "y0": first.bbox[1],
                    "x1": last.bbox[2], "y1": last.bbox[3],
                },
                "token_count": _estimate_tokens(text),
                "tags": tags,
                "kind": "formula" if "formula" in tags else "paragraph",
            }
        )
        order += 1
        buffer_texts, buffer_paras = [], []

    for paragraph in parsed.paragraphs:
        if paragraph.is_heading and len(paragraph.text) > 220:
            continue
        for piece in _split_long_paragraph(paragraph.text):
            prospective = sum(len(t) for t in buffer_texts) + len(piece)
            if buffer_texts and prospective > MAX_CHARS:
                flush()
            buffer_texts.append(piece)
            buffer_paras.append(paragraph)
            if sum(len(t) for t in buffer_texts) >= MAX_CHARS:
                flush()
        if len(buffer_texts) and sum(len(t) for t in buffer_texts) >= MAX_CHARS:
            flush()
    flush()

    # Drop chunks that are almost entirely references noise.
    return [c for c in chunks if len(c["text"]) >= 40]


def _formula_density(text: str) -> float:
    if not text:
        return 0.0
    marks = set("=+−-×÷∑∫∏√≤≥≈≠∈→←αβγδεζηθικλμνξοπρστυφχψω^_{}")
    return sum(1 for ch in text if ch in marks) / len(text)


def _estimate_tokens(text: str) -> int:
    latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(latin_words * 1.3 + cjk * 0.9) + 1
