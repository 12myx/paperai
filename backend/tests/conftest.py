"""Test configuration: isolated database, storage and a realistic PDF fixture."""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

TMP_ROOT = Path(tempfile.mkdtemp(prefix="paperlens-tests-"))
os.environ["PAPERLENS_DATABASE_URL"] = f"sqlite:///{(TMP_ROOT / 'test.db').as_posix()}"
os.environ["PAPERLENS_STORAGE_DIR"] = str(TMP_ROOT / "storage")
os.environ["PAPERLENS_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["PAPERLENS_ENVIRONMENT"] = "test"
os.environ.pop("DEEPSEEK_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.main import app  # noqa: E402
from app.rate_limit import limiter  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limit():
    limiter.reset(limit=10000)
    yield
    limiter.reset(limit=10000)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def auth(client):
    email = "researcher@example.com"
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Research123!", "display_name": "Lin Researcher"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    return {"headers": {"Authorization": f"Bearer {payload['access_token']}"}, "user": payload["user"]}


def make_figure_image() -> bytes:
    image = Image.new("RGB", (640, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([40, 40, 600, 320], outline="#2F6F62", width=3)
    for index, height in enumerate([60, 120, 90, 200, 150, 240]):
        x = 70 + index * 85
        draw.rectangle([x, 320 - height, x + 55, 320], fill="#6F9E8F")
    draw.text((60, 20), "Figure 1: Retrieval accuracy across datasets", fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build_sample_pdf(title: str = "Grounded Retrieval Augmentation for Scientific Reading") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    title_style = ParagraphStyle("T", fontName="Helvetica-Bold", fontSize=20, leading=25, spaceAfter=12)
    author_style = ParagraphStyle("A", fontName="Helvetica", fontSize=11, leading=14, spaceAfter=14)
    heading = ParagraphStyle("H", fontName="Helvetica-Bold", fontSize=14, leading=18, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("B", fontName="Helvetica", fontSize=10, leading=15, spaceAfter=6)

    story = [
        Paragraph(title, title_style),
        Paragraph("Maya Chen, Daniel Okafor, and Lin Wei — Institute for Scientific Computing, 2024", author_style),
        Paragraph("Abstract", heading),
        Paragraph(
            "Scientific reading is bottlenecked by the gap between long papers and short attention spans. "
            "We present PaperLens, a grounded retrieval augmentation pipeline that indexes section-aware chunks, "
            "attaches page-level provenance to every generated claim, and evaluates faithfulness with a citation "
            "coverage metric. On a benchmark of 120 machine learning papers, PaperLens improves answer faithfulness "
            "from 61.2% to 87.4% while reducing unsupported statements by 43%. We further show that section-aware "
            "chunking outperforms fixed-window chunking by 9.1 points on cross-section questions.",
            body,
        ),
        Paragraph("Keywords: retrieval augmentation, scientific reading, citation grounding, evaluation", body),
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
            "The generator receives numbered evidence blocks [C1], [C2] and must cite them. A post-processing "
            "checker drops sentences without a valid citation or marks them as unsupported.",
            body,
        ),
        Spacer(1, 6),
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
        Paragraph("Figure 1 caption: retrieval accuracy across four datasets.", body),
        RLImage(io.BytesIO(make_figure_image()), width=150 * mm, height=84 * mm),
        Spacer(1, 8),
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
    return buffer.getvalue()


@pytest.fixture(scope="session")
def sample_pdf_bytes() -> bytes:
    return build_sample_pdf()


@pytest.fixture(scope="session")
def sample_pdf_bytes_b() -> bytes:
    return build_sample_pdf("Contrastive Pretraining for Low-Resource Scientific Retrieval")


@pytest.fixture(scope="session")
def paper(client, auth, sample_pdf_bytes):
    response = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("sample-paper.pdf", sample_pdf_bytes, "application/pdf")},
        data={"tags": "retrieval,evaluation"},
    )
    assert response.status_code == 201, response.text
    paper_id = response.json()["paper"]["id"]
    import time

    for _ in range(40):
        detail = client.get(f"/api/papers/{paper_id}", headers=auth["headers"])
        if detail.status_code == 200 and detail.json()["status"] in {"ready", "failed"}:
            break
        time.sleep(0.25)
    assert detail.json()["status"] == "ready", detail.text
    return detail.json()


@pytest.fixture(scope="session")
def paper_b(client, auth, sample_pdf_bytes_b):
    response = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("sample-paper-b.pdf", sample_pdf_bytes_b, "application/pdf")},
        data={"tags": "contrastive"},
    )
    assert response.status_code == 201, response.text
    paper_id = response.json()["paper"]["id"]
    import time

    for _ in range(40):
        detail = client.get(f"/api/papers/{paper_id}", headers=auth["headers"])
        if detail.status_code == 200 and detail.json()["status"] in {"ready", "failed"}:
            break
        time.sleep(0.25)
    assert detail.json()["status"] == "ready", detail.text
    return detail.json()


def sse_events(response) -> list[dict]:
    import json

    events = []
    for line in response.iter_lines():
        if not line:
            continue
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        if text.startswith("data: "):
            events.append(json.loads(text[6:]))
    return events