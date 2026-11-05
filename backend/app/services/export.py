"""Real document export: Markdown, PDF, DOCX, TXT, CSV and JSON."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone

from docx import Document
from docx.shared import Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

CJK_FONT = "STSong-Light"
_FONT_READY = False


def _ensure_font() -> None:
    global _FONT_READY
    if _FONT_READY:
        return
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(CJK_FONT))
        _FONT_READY = True
    except Exception:  # noqa: BLE001
        _FONT_READY = False


def _escape(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", text)
    return text


def _parse_markdown(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            index += 1
            code = []
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            blocks.append({"type": "code", "text": "\n".join(code)})
            index += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            blocks.append({"type": "heading", "level": len(heading.group(1)), "text": heading.group(2).strip()})
            index += 1
            continue
        if re.match(r"^\s*([-*+]\s+|\d+[.)]\s+)", line):
            items = []
            while index < len(lines) and re.match(r"^\s*([-*+]\s+|\d+[.)]\s+)", lines[index]):
                items.append(re.sub(r"^\s*([-*+]\s+|\d+[.)]\s+)", "", lines[index]).strip())
                index += 1
            blocks.append({"type": "list", "items": items})
            continue
        if line.startswith(">"):
            quote = []
            while index < len(lines) and lines[index].startswith(">"):
                quote.append(lines[index].lstrip("> ").strip())
                index += 1
            blocks.append({"type": "quote", "text": " ".join(quote)})
            continue
        if line.strip().startswith("|") and index + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|", lines[index + 1]):
            table_rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not re.match(r"^[\s:|-]+$", "".join(row)):
                    table_rows.append(row)
                index += 1
            blocks.append({"type": "table", "rows": table_rows})
            continue
        if line.strip() in {"---", "***", "___"}:
            blocks.append({"type": "hr"})
            index += 1
            continue
        paragraph = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r"^(#{1,6}\s|\s*[-*+]\s|\s*\d+[.)]\s|\||>|```)", lines[index]):
            paragraph.append(lines[index].strip())
            index += 1
        blocks.append({"type": "paragraph", "text": " ".join(paragraph)})
    return blocks


def to_markdown(title: str, content: str, meta: dict | None = None) -> str:
    meta = meta or {}
    header = [f"# {title}", ""]
    for key in ("author", "project", "papers", "generated"):
        if meta.get(key):
            header.append(f"- **{key}**: {meta[key]}")
    if len(header) > 3:
        header.append("")
    return "\n".join(header) + "\n" + content.strip() + "\n"


def to_txt(title: str, content: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", content, flags=re.M)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return f"{title}\n{'=' * min(len(title), 80)}\n\n{text.strip()}\n"


def to_json(title: str, content: str, meta: dict | None = None) -> str:
    payload = {
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "meta": meta or {},
        "markdown": content,
        "sections": [b for b in _parse_markdown(content) if b["type"] != "hr"],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_csv(title: str, content: str) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "index", "content"])
    section = title
    counter = 0
    for block in _parse_markdown(content):
        if block["type"] == "heading":
            section = block["text"]
            counter = 0
        elif block["type"] == "table":
            for row in block["rows"]:
                writer.writerow([section, "table", " | ".join(row)])
        elif block["type"] == "list":
            for item in block["items"]:
                counter += 1
                writer.writerow([section, counter, item])
        elif block.get("text"):
            counter += 1
            writer.writerow([section, counter, block["text"]])
    return buffer.getvalue()


def to_pdf(title: str, content: str) -> bytes:
    _ensure_font()
    font = CJK_FONT if _FONT_READY else "Helvetica"
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, title=title,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
    )
    sample = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("PLTitle", parent=sample["Title"], fontName=font, fontSize=20, leading=26, spaceAfter=10, textColor=colors.HexColor("#1B1F1D")),
        "h1": ParagraphStyle("PLH1", fontName=font, fontSize=15, leading=20, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#1B1F1D")),
        "h2": ParagraphStyle("PLH2", fontName=font, fontSize=13, leading=18, spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#2F6F62")),
        "h3": ParagraphStyle("PLH3", fontName=font, fontSize=11.5, leading=16, spaceBefore=8, spaceAfter=4, textColor=colors.HexColor("#3A4340")),
        "body": ParagraphStyle("PLBody", fontName=font, fontSize=10, leading=16, spaceAfter=5, textColor=colors.HexColor("#242A27")),
        "quote": ParagraphStyle("PLQuote", fontName=font, fontSize=9.5, leading=15, leftIndent=10, textColor=colors.HexColor("#4A5652"), backColor=colors.HexColor("#F3F5F2"), borderPadding=6),
        "code": ParagraphStyle("PLCode", fontName="Courier", fontSize=8.5, leading=12, leftIndent=8, backColor=colors.HexColor("#F4F4F2"), borderPadding=5),
        "meta": ParagraphStyle("PLMeta", fontName=font, fontSize=9, leading=13, textColor=colors.HexColor("#6B7570")),
    }
    story = [Paragraph(_escape(title), styles["title"]), Spacer(1, 4)]
    story.append(Paragraph(datetime.now().strftime("Generated by PaperLens AI · %Y-%m-%d %H:%M"), styles["meta"]))
    story.append(Spacer(1, 8))
    for block in _parse_markdown(content):
        if block["type"] == "heading":
            style = styles["h1"] if block["level"] <= 1 else styles["h2"] if block["level"] == 2 else styles["h3"]
            story.append(Paragraph(_escape(block["text"]), style))
        elif block["type"] == "paragraph":
            story.append(Paragraph(_escape(block["text"]), styles["body"]))
        elif block["type"] == "quote":
            story.append(Paragraph(_escape(block["text"]), styles["quote"]))
        elif block["type"] == "code":
            story.append(Paragraph(_escape(block["text"]).replace("\n", "<br/>"), styles["code"]))
        elif block["type"] == "list":
            for item in block["items"]:
                story.append(Paragraph("• " + _escape(item), styles["body"]))
        elif block["type"] == "table":
            rows = [[Paragraph(_escape(cell), styles["meta"]) for cell in row] for row in block["rows"][:40]]
            if rows:
                table = Table(rows, repeatRows=1, hAlign="LEFT")
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9DED9")),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF3EF")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 6))
        elif block["type"] == "hr":
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#D9DED9")))
    document.build(story)
    return buffer.getvalue()


def to_docx(title: str, content: str) -> bytes:
    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    document.add_heading(title, level=0)
    document.add_paragraph(f"Generated by PaperLens AI · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    for block in _parse_markdown(content):
        if block["type"] == "heading":
            document.add_heading(block["text"], level=min(block["level"], 4))
        elif block["type"] == "paragraph":
            document.add_paragraph(block["text"])
        elif block["type"] == "quote":
            paragraph = document.add_paragraph(block["text"])
            paragraph.style = document.styles["Intense Quote"]
        elif block["type"] == "code":
            paragraph = document.add_paragraph(block["text"])
            paragraph.style = document.styles["Macro Text"]
        elif block["type"] == "list":
            for item in block["items"]:
                document.add_paragraph(item, style="List Bullet")
        elif block["type"] == "table":
            rows = block["rows"]
            if rows:
                table = document.add_table(rows=len(rows), cols=max(len(r) for r in rows))
                table.style = "Light Grid Accent 1"
                for r_index, row in enumerate(rows):
                    for c_index, cell in enumerate(row):
                        table.cell(r_index, c_index).text = cell
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def build_export(fmt: str, title: str, content: str, meta: dict | None = None) -> tuple[bytes, str]:
    fmt = fmt.lower().strip()
    if fmt == "md":
        return to_markdown(title, content).encode("utf-8"), "md"
    if fmt in {"txt", "text"}:
        return to_txt(title, content).encode("utf-8"), "txt"
    if fmt == "pdf":
        return to_pdf(title, content), "pdf"
    if fmt in {"docx", "doc"}:
        return to_docx(title, content), "docx"
    if fmt == "csv":
        return to_csv(title, content).encode("utf-8-sig"), "csv"
    if fmt == "json":
        return to_json(title, content, meta).encode("utf-8"), "json"
    raise ValueError(f"Unsupported export format: {fmt}")
