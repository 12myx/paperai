"""PDF parsing pipeline built on PyMuPDF.

The parser produces a structured representation that keeps page, section,
paragraph and bounding-box information so every AI answer can be traced back
to a location in the original document.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

import pymupdf

HEADING_KEYWORDS = (
    "abstract", "introduction", "related work", "background", "method", "methods",
    "methodology", "approach", "materials and methods", "experiment", "experiments",
    "experimental setup", "results", "results and discussion", "discussion",
    "conclusion", "conclusions", "future work", "limitations", "references",
    "acknowledgements", "acknowledgments", "appendix", "摘要", "引言", "绪论",
    "相关工作", "研究方法", "方法", "实验", "实验结果", "结果", "讨论", "结论",
    "参考文献", "致谢", "附录",
)
CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?|tab(?:le)?|chart|scheme|图|表)\s*[.:]?\s*\d+", re.I)
NUMBERED_HEADING = re.compile(r"^\s*(\d+(?:\.\d+){0,3})[.)]?\s+[A-Z\u4e00-\u9fff]")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
MATH_CHARS = set("=+−-×÷∑∫∏√≤≥≈≠∈∉⊂⊆∪∩→←↔∂∇αβγδεζηθικλμνξοπρστυφχψωΓΔΘΛΞΠΣΦΨΩ^_{}[]")


@dataclass
class Paragraph:
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    font_size: float
    bold: bool
    is_heading: bool = False
    level: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass
class ParsedPaper:
    title: str
    authors: str | None
    year: int | None
    abstract: str | None
    language: str
    page_count: int
    pages: list[dict]
    paragraphs: list[Paragraph]
    sections: list[dict]
    chunks: list[dict]
    figures: list[dict]
    full_text: str
    meta: dict


def _clean_line(line: str) -> str:
    return re.sub(r"[ \t]+", " ", line).strip()


def _join_lines(lines: list[str]) -> str:
    out = ""
    for raw in lines:
        line = _clean_line(raw)
        if not line:
            continue
        if not out:
            out = line
            continue
        prev = out[-1]
        if out.endswith("-") and line[:1].islower():
            out = out[:-1] + line
        elif _is_cjk(prev) or _is_cjk(line[:1]):
            out += line
        else:
            out += " " + line
    return out


def _is_cjk(char: str) -> bool:
    return bool(char) and "\u4e00" <= char <= "\u9fff"


def _block_text(block: dict) -> tuple[str, float, bool, int]:
    lines, sizes, bold_chars, total_chars = [], [], 0, 0
    for line in block.get("lines", []):
        parts = []
        for span in line.get("spans", []):
            text = span.get("text", "")
            parts.append(text)
            size = round(float(span.get("size", 0)), 1)
            weight = max(len(text.strip()), 1)
            sizes.extend([size] * weight)
            total_chars += weight
            flags = int(span.get("flags", 0))
            if flags & 16 or "bold" in str(span.get("font", "")).lower():
                bold_chars += weight
        lines.append("".join(parts))
    text = _join_lines(lines)
    size = statistics.median(sizes) if sizes else 0.0
    bold = total_chars > 0 and bold_chars / total_chars > 0.6
    return text, size, bold, total_chars


def _looks_like_heading(text: str, size: float, bold: bool, body_size: float) -> tuple[bool, int]:
    stripped = text.strip()
    if not stripped or len(stripped) > 180 or stripped.endswith((".", "。", ",", "，")):
        return False, 0
    words = stripped.split()
    if len(words) > 18:
        return False, 0
    lowered = stripped.lower().strip(":： ")
    level = 0
    if any(lowered.startswith(k) or lowered == k for k in HEADING_KEYWORDS):
        level = 1
    numbered = NUMBERED_HEADING.match(stripped)
    if numbered:
        level = max(1, numbered.group(1).count(".") + 1)
    big = size >= max(body_size * 1.14, body_size + 1.2)
    boldish = bold and size >= body_size * 0.98
    if level and (big or boldish or len(stripped) <= 60):
        return True, min(level, 3)
    if big and not lowered.startswith(("http", "www")):
        return True, 1
    if boldish and numbered and all(w[0].isupper() for w in words[:3] if w):
        return True, level or 2
    return False, 0


def _detect_language(text: str) -> str:
    sample = text[:4000]
    cjk = sum(1 for ch in sample if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for ch in sample if ch.isascii() and ch.isalpha())
    if cjk > latin * 0.25:
        return "zh"
    return "en"


def _formula_density(text: str) -> float:
    if not text:
        return 0.0
    symbols = sum(1 for ch in text if ch in MATH_CHARS)
    return symbols / max(len(text), 1)


def _caption_for(page_blocks: list[dict], bbox: tuple[float, float, float, float]) -> str | None:
    x0, y0, x1, y1 = bbox
    candidates: list[tuple[int, float, str]] = []
    for block in page_blocks:
        text = block["text"].strip()
        if not text or len(text) > 500:
            continue
        looks_like_caption = bool(CAPTION_RE.match(text)) or text.lower().startswith(("fig.", "figure", "table"))
        if not looks_like_caption:
            continue
        bx0, by0, bx1, by1 = block["bbox"]
        if by0 >= y1 - 10 and by0 - y1 < 180 and abs(bx0 - x0) < 140:
            candidates.append((0, by0 - y1, text))
        elif by1 <= y0 + 10 and y0 - by1 < 180 and abs(bx0 - x0) < 140:
            candidates.append((1, y0 - by1, text))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2][:600]

    # Fall back to the nearest non-heading text block below the image.
    fallback: list[tuple[float, str]] = []
    for block in page_blocks:
        text = block["text"].strip()
        bx0, by0, bx1, by1 = block["bbox"]
        if by0 >= y1 - 10 and by0 - y1 < 100 and len(text) > 12:
            if NUMBERED_HEADING.match(text) or (len(text) < 40 and text.isupper()):
                continue
            fallback.append((by0 - y1, text[:400]))
    if fallback:
        fallback.sort(key=lambda item: item[0])
        return fallback[0][1]
    return None


def extract_pdf(data: bytes, max_pages: int = 400) -> ParsedPaper:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"无法打开 PDF 文件：{exc}") from exc

    if doc.needs_pass:
        raise ValueError("该 PDF 受密码保护，无法解析")

    page_count = min(doc.page_count, max_pages)
    pages: list[dict] = []
    raw_blocks: list[dict] = []

    for page_index in range(page_count):
        page = doc[page_index]
        page_dict = page.get_text("dict")
        blocks = []
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            text, size, bold, chars = _block_text(block)
            if not text or len(text) < 2:
                continue
            bbox = tuple(float(v) for v in block.get("bbox", (0, 0, 0, 0)))
            blocks.append({"text": text, "size": size, "bold": bold, "chars": chars, "bbox": bbox})
        raw_blocks.append({"page": page_index + 1, "blocks": blocks, "width": page.rect.width, "height": page.rect.height})
        pages.append(
            {
                "page_number": page_index + 1,
                "width": round(page.rect.width, 2),
                "height": round(page.rect.height, 2),
                "text": "\n".join(b["text"] for b in blocks),
            }
        )

    # Body font size from the first few pages, weighted by character count.
    size_pool: list[float] = []
    for entry in raw_blocks[:4]:
        for block in entry["blocks"]:
            size_pool.extend([block["size"]] * min(block["chars"], 200))
    body_size = statistics.median(size_pool) if size_pool else 10.0

    # Title: largest text block on the first page that is not a running header.
    title = ""
    if raw_blocks and raw_blocks[0]["blocks"]:
        candidates = sorted(raw_blocks[0]["blocks"], key=lambda b: (-b["size"], -b["chars"]))[:6]
        for candidate in candidates:
            if 6 <= len(candidate["text"]) <= 300 and not candidate["text"].lower().startswith(("http", "doi")):
                title = candidate["text"].replace("\n", " ").strip()
                break
    meta_title = (doc.metadata or {}).get("title") or ""
    if len(meta_title.strip()) > 6 and (not title or len(title) < 12):
        title = meta_title.strip()

    first_page_text = raw_blocks[0]["blocks"] if raw_blocks else []
    authors = None
    for block in first_page_text[:6]:
        text = block["text"]
        if re.search(r"[A-Z][a-z]+\s+[A-Z][a-z]+", text) and 5 < len(text) < 300 and block["size"] < (body_size * 1.35):
            authors = re.sub(r"\s+", " ", text)[:300]
            break

    full_text_parts = [b["text"] for entry in raw_blocks for b in entry["blocks"]]
    language = _detect_language("\n".join(full_text_parts))
    meta_author = (doc.metadata or {}).get("author")
    if not authors and meta_author:
        authors = meta_author[:300]

    # --- paragraphs + headings -------------------------------------------------
    paragraphs: list[Paragraph] = []
    for entry in raw_blocks:
        for block in entry["blocks"]:
            text = block["text"].strip()
            if not text:
                continue
            is_heading, level = _looks_like_heading(text, block["size"], block["bold"], body_size)
            if text.lower().startswith(("references", "参考文献")) and len(text) < 30:
                is_heading, level = True, 1
            paragraphs.append(
                Paragraph(
                    text=text,
                    page=entry["page"],
                    bbox=block["bbox"],
                    font_size=block["size"],
                    bold=block["bold"],
                    is_heading=is_heading,
                    level=level,
                )
            )

    # --- sections --------------------------------------------------------------
    sections: list[dict] = []
    current = {"title": "Front Matter", "level": 1, "page_start": 1, "page_end": 1, "paragraphs": []}
    for para in paragraphs:
        if para.is_heading:
            if current["paragraphs"] or not sections:
                current["page_end"] = para.page
                sections.append(current)
            current = {"title": para.text.strip()[:300], "level": para.level or 1, "page_start": para.page, "page_end": para.page, "paragraphs": []}
        else:
            current["paragraphs"].append(para)
            current["page_end"] = para.page
    if current["paragraphs"]:
        sections.append(current)
    sections = [s for s in sections if s["title"] and (s["paragraphs"] or len(sections) == 1)]
    for index, section in enumerate(sections):
        section["order_index"] = index
        section["char_start"] = 0
        section["char_end"] = 0

    # --- abstract --------------------------------------------------------------
    abstract = None
    abstract_para = None
    for para in paragraphs:
        low = para.text.lower().strip()
        if low.startswith("abstract") or low.startswith("摘要"):
            body = re.sub(r"^(abstract|摘要)[\s:：.-]*", "", para.text, flags=re.I).strip()
            if len(body) > 60:
                abstract_para = body
                break
    if abstract_para:
        abstract = abstract_para[:2500]
    else:
        for index, section in enumerate(sections):
            if section["title"].lower().startswith(("abstract", "摘要")):
                joined = " ".join(p.text for p in section["paragraphs"])[:2500]
                abstract = joined or None
                break
    if abstract:
        abstract = re.sub(r"\s+", " ", abstract).strip()

    # --- figures & tables ------------------------------------------------------
    figures: list[dict] = []
    seen_xrefs: set[int] = set()
    figure_index = 0
    for page_index in range(page_count):
        page = doc[page_index]
        page_blocks = raw_blocks[page_index]["blocks"] if page_index < len(raw_blocks) else []
        for image in page.get_images(full=True):
            xref = image[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                info = doc.extract_image(xref)
            except Exception:  # noqa: BLE001
                continue
            width, height = info.get("width", 0), info.get("height", 0)
            if width < 140 or height < 90:
                continue
            try:
                rects = page.get_image_rects(xref)
            except Exception:  # noqa: BLE001
                rects = []
            bbox = tuple(float(v) for v in rects[0]) if rects else (0, 0, width, height)
            if bbox[2] - bbox[0] < 40 or bbox[3] - bbox[1] < 40:
                continue
            figure_index += 1
            figures.append(
                {
                    "page_number": page_index + 1,
                    "order_index": figure_index,
                    "data": info["image"],
                    "ext": info.get("ext", "png"),
                    "width": width,
                    "height": height,
                    "bbox": {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]},
                    "caption": _caption_for(page_blocks, bbox),
                    "kind": "figure",
                    "table_markdown": None,
                }
            )
            if figure_index >= 60:
                break
        if figure_index >= 60:
            break

        try:
            tab_finder = page.find_tables()
            tables = list(getattr(tab_finder, "tables", []) or [])
        except Exception:  # noqa: BLE001
            tables = []
        for table in tables:
            try:
                markdown = table.to_markdown() if hasattr(table, "to_markdown") else ""
            except Exception:  # noqa: BLE001
                markdown = ""
            if not markdown:
                try:
                    rows = table.extract()
                    markdown = "\n".join("| " + " | ".join(str(c or "") for c in row) + " |" for row in rows)
                except Exception:  # noqa: BLE001
                    markdown = ""
            if not markdown.strip():
                continue
            rect = getattr(table, "bbox", None) or (0, 0, 0, 0)
            table_png = None
            try:
                clip = pymupdf.Rect(rect)
                if clip.width > 1 and clip.height > 1:
                    table_png = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(1.7, 1.7)).tobytes("png")
            except Exception:  # noqa: BLE001 - table text still remains useful
                table_png = None
            figure_index += 1
            figures.append(
                {
                    "page_number": page_index + 1,
                    "order_index": figure_index,
                    "data": table_png,
                    "ext": "png",
                    "width": max(1, rect[2] - rect[0]),
                    "height": max(1, rect[3] - rect[1]),
                    "bbox": {"x0": rect[0], "y0": rect[1], "x1": rect[2], "y1": rect[3]},
                    "caption": _caption_for(page_blocks, rect) or f"Table {figure_index}",
                    "kind": "table",
                    "table_markdown": markdown[:20000],
                }
            )

    # --- metadata --------------------------------------------------------------
    page_one_text = "\n".join(b["text"] for b in (raw_blocks[0]["blocks"] if raw_blocks else []))
    doi_match = DOI_RE.search("\n".join(full_text_parts[:4]))
    years = re.findall(r"\b(19[89]\d|20[0-4]\d)\b", page_one_text)
    meta = {
        "doi": doi_match.group(0) if doi_match else None,
        "body_font_size": body_size,
        "keywords": _extract_keywords(page_one_text),
        "parser": "pymupdf",
        "parser_version": pymupdf.__version__,
        "total_pages": doc.page_count,
        "truncated": doc.page_count > max_pages,
    }
    if (doc.metadata or {}).get("subject"):
        meta["subject"] = doc.metadata.get("subject")[:300]

    full_text = "\n\n".join(full_text_parts)
    doc.close()

    return ParsedPaper(
        title=(title or "Untitled paper")[:590],
        authors=authors,
        year=int(years[0]) if years else None,
        abstract=abstract,
        language=language,
        page_count=page_count,
        pages=pages,
        paragraphs=paragraphs,
        sections=sections,
        chunks=[],
        figures=figures,
        full_text=full_text,
        meta=meta,
    )


def _extract_keywords(text: str) -> list[str]:
    match = re.search(r"(?:keywords?|key words|关键词)\s*[:：]\s*(.{0,300})", text, re.I)
    if not match:
        return []
    raw = match.group(1).split("\n")[0]
    parts = re.split(r"[,;，；、]", raw)
    return [p.strip(" .") for p in parts if 2 <= len(p.strip()) <= 60][:12]