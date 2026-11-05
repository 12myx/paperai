"""QA seed: creates a realistic account with one parsed paper.

Run against a local API:  python scripts/qa_seed.py
Never run this against production.
"""
from __future__ import annotations

import io
import os
import sys
import time

import httpx

API = "http://127.0.0.1:8000/api"
EMAIL = os.environ.get("QA_EMAIL", "qa@paperlens.ai")
PASSWORD = os.environ.get("QA_PASSWORD", "")
if not PASSWORD:
    raise SystemExit("Set QA_PASSWORD before running qa_seed.py")


def build_pdf(title_text: str = "Grounded Retrieval Augmentation for Scientific Reading", abstract_prefix: str = "") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 600, 320], outline="#2F6F62", width=3)
    for index, height in enumerate([60, 120, 90, 200, 150, 240]):
        x = 70 + index * 85
        draw.rectangle([x, 320 - height, x + 55, 320], fill="#6F9E8F")
    draw.text((60, 20), "Figure 1: Faithfulness across chunking strategies", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    title = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=20, leading=25, spaceAfter=12)
    authors = ParagraphStyle("A", fontName="Helvetica", fontSize=11, leading=14, spaceAfter=14)
    heading = ParagraphStyle("H", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("B", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=6)

    story = [
        Paragraph(title_text, title),
        Paragraph("Maya Chen, Daniel Okafor, and Lin Wei - Institute for Scientific Computing, 2024", authors),
        Paragraph("Abstract", heading),
        Paragraph(
            abstract_prefix + "Scientific reading is bottlenecked by the gap between long papers and short attention spans. "
            "We present PaperLens, a grounded retrieval augmentation pipeline that indexes section-aware chunks, "
            "attaches page-level provenance to every generated claim, and evaluates faithfulness with a citation "
            "coverage metric. On a benchmark of 120 machine learning papers, PaperLens improves answer faithfulness "
            "from 61.2% to 87.4% while reducing unsupported statements by 43%. Section-aware chunking outperforms "
            "fixed-window chunking by 9.1 points on cross-section questions.",
            body,
        ),
        Paragraph("Keywords: retrieval augmentation, scientific reading, citation grounding", body),
        PageBreak(),
        Paragraph("1 Introduction", heading),
        Paragraph(
            "Researchers read dozens of papers per month, yet most reading assistants summarise without evidence. "
            "A summary that cannot be traced back to a page is difficult to trust and impossible to cite. "
            "This work asks whether retrieval augmentation can make every generated sentence auditable. "
            "We study three research questions: how to chunk scientific text, how to attach provenance, and how "
            "to measure faithfulness. Our contributions are a section-aware chunker, a provenance contract, and "
            "an evaluation protocol with citation coverage and unsupported-claim rate.",
            body,
        ),
        Paragraph("2 Related Work", heading),
        Paragraph(
            "Prior systems combine PDF parsing with large language models but treat the document as a flat string. "
            "Flat chunking breaks equations, tables and cross-references. Retrieval augmented generation improves "
            "factuality in open-domain question answering, but scientific documents add structural constraints: "
            "methods are described once and referenced later, and experimental numbers appear in tables far from "
            "the claim. Our approach keeps section, page and bounding box metadata for every chunk.",
            body,
        ),
        Paragraph("3 Method", heading),
        Paragraph(
            "We parse the PDF with a layout-aware extractor, detect headings using font size and numbering patterns, "
            "and build chunks that never cross section boundaries. Each chunk stores its page range, character "
            "offsets and bounding boxes. Retrieval combines BM25 term matching with character n-gram cosine "
            "similarity, and a reranker promotes chunks whose section title matches the question intent. "
            "The generator receives numbered evidence blocks and must cite them. A post-processing checker "
            "drops sentences without a valid citation or marks them as unsupported.",
            body,
        ),
        Paragraph("Table 1: Ablation of chunking strategies", body),
        Paragraph("Strategy | Faithfulness | Coverage | Unsupported rate", body),
        Paragraph("Fixed 512 tokens | 61.2 | 0.54 | 28.4", body),
        Paragraph("Paragraph chunks | 78.3 | 0.71 | 17.1", body),
        Paragraph("Section-aware (ours) | 87.4 | 0.83 | 9.8", body),
        PageBreak(),
        Paragraph("4 Experiments", heading),
        Paragraph(
            "We evaluate on 120 papers from arXiv cs.CL and cs.LG, with 480 questions written by graduate students. "
            "Baselines include a flat-chunk retrieval pipeline and a long-context model without retrieval. "
            "Our method reaches 87.4% faithfulness and 0.83 citation coverage. Ablations show that removing the "
            "section-aware chunker costs 9.1 points, and removing the reranker costs 4.6 points. "
            "Latency remains under 1.8 seconds per answer on a single GPU.",
            body,
        ),
        Paragraph("Figure 1 caption: faithfulness across chunking strategies.", body),
        RLImage(buffer, width=150 * mm, height=84 * mm),
        Paragraph("5 Discussion and Conclusion", heading),
        Paragraph(
            "Grounded retrieval substantially improves trust in AI reading assistants. However, our evaluation "
            "covers only English papers in two subfields, and citation coverage does not guarantee reasoning "
            "quality. A limitation is that tables with merged cells are still extracted imperfectly. "
            "Future work should test multilingual papers, integrate figure understanding, and study how "
            "researchers actually verify citations in practice.",
            body,
        ),
        Paragraph("References", heading),
        Paragraph("Lewis et al. 2020. Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. NeurIPS.", body),
        Paragraph("Smith and Lee. 2022. Evaluating Faithfulness in Scientific Summarisation. ACL.", body),
    ]
    doc.build(story)
    return pdf_buffer.getvalue()


def main() -> int:
    client = httpx.Client(base_url=API, timeout=60)
    register = client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD, "display_name": "林知研"})
    if register.status_code == 409:
        login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        token = login.json()["access_token"]
    elif register.status_code == 201:
        token = register.json()["access_token"]
    else:
        print("register failed", register.status_code, register.text)
        return 1
    headers = {"Authorization": "Bearer " + token}
    client.headers.update(headers)

    def ingest(title_text: str, filename: str, tags: str, abstract_prefix: str = "") -> dict:
        pdf = build_pdf(title_text, abstract_prefix)
        upload = client.post("/papers", files={"file": (filename, pdf, "application/pdf")}, data={"tags": tags})
        if upload.status_code == 409:
            paper_id_local = upload.json()["detail"]["paper_id"]
        else:
            paper_id_local = upload.json()["paper"]["id"]
        for _ in range(80):
            detail_local = client.get("/papers/" + paper_id_local).json()
            if detail_local["status"] in {"ready", "failed"}:
                break
            time.sleep(0.4)
        print("paper:", detail_local["status"], detail_local["page_count"], "pages,", detail_local["chunks_count"], "chunks,", len(detail_local["sections"]), "sections", "|", detail_local["title"][:40])
        return detail_local

    detail = ingest("Grounded Retrieval Augmentation for Scientific Reading", "grounded-retrieval.pdf", "retrieval,grounding")
    paper_id = detail["id"]
    second = ingest(
        "Contrastive Pretraining for Low-Resource Scientific Retrieval",
        "contrastive-pretraining.pdf",
        "retrieval,contrastive",
        "This study investigates contrastive pretraining for scientific retrieval in low-resource languages. ",
    )

    annotations = [
        (2, "blue", "Each chunk stores its page range, character offsets and bounding boxes.", {"x": 0.11, "y": 0.47, "w": 0.74, "h": 0.028}, "方法核心：来源契约"),
        (3, "green", "Our method reaches 87.4% faithfulness and 0.83 citation coverage.", {"x": 0.11, "y": 0.32, "w": 0.76, "h": 0.028}, "关键结果，可用于组会"),
        (3, "red", "A limitation is that tables with merged cells are still extracted imperfectly.", {"x": 0.11, "y": 0.62, "w": 0.74, "h": 0.028}, "表格解析的局限"),
    ]
    existing = client.get("/annotations", params={"paper_id": paper_id}).json()["items"]
    if not existing:
        for page, color, quote, rects, note in annotations:
            response = client.post("/annotations", json={"paper_id": paper_id, "page": page, "color": color, "quote": quote, "rects": [rects], "note": note, "tags": ["qa"]})
            print("annotation", response.status_code)

    second_annotations = client.get("/annotations", params={"paper_id": second["id"]}).json()["items"]
    if not second_annotations:
        client.post("/annotations", json={
            "paper_id": second["id"], "page": 2, "color": "purple",
            "quote": "Retrieval combines BM25 term matching with character n-gram cosine similarity.",
            "rects": [{"x": 0.11, "y": 0.52, "w": 0.72, "h": 0.028}],
            "note": "与第一篇的检索策略可对比", "tags": ["comparison"],
        })

    knowledge = client.get("/knowledge", params={"query": "来源契约"}).json()["items"]
    if not knowledge:
        client.post("/knowledge", json={
            "title": "章节感知切片能提升忠实度 9.1 个点",
            "content": "An ablation shows section-aware chunking outperforms fixed 512-token chunking by 9.1 points on faithfulness (87.4 vs 61.2).",
            "kind": "insight", "tags": ["method", "ablation"], "source_paper_id": paper_id, "source_page": 2,
        })

    projects = client.get("/projects").json()["items"]
    if not projects:
        project = client.post("/projects", json={"name": "论文阅读助手调研", "goal": "评估可追溯的 AI 阅读助手方案", "description": "为毕业设计做准备"}).json()["project"]
        client.post(f"/projects/{project['id']}/items", json={"kind": "paper", "ref_id": paper_id, "title": detail["title"]})
        client.post(f"/projects/{project['id']}/items", json={"kind": "note", "title": "下一步", "content": "对比 3 篇 RAG 论文的实验设置，整理成表格。"})

    collections = client.get("/collections").json()["items"]
    if not collections:
        collection = client.post("/collections", json={"name": "RAG 阅读清单", "description": "检索增强与引用可靠性"}).json()["collection"]
        client.post(f"/collections/{collection['id']}/papers", json=[paper_id])

    print("QA account ready:", EMAIL, "/", PASSWORD)
    print("paper_id:", paper_id, "| second:", second["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())