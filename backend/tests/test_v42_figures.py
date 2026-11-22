"""V4.2 P0 figure classification, layered views and visual-record curation."""
from __future__ import annotations


def test_figure_layers_curation_and_visual_record(client, auth, paper):
    figures = client.get("/api/figures", headers=auth["headers"], params={"paper_id": paper["id"], "view": "featured"}).json()
    assert figures["items"], "sample figure should be featured"
    assert figures["summary"]["featured"] >= 1
    figure = figures["items"][0]
    assert figure["detected_kind"] in {"figure", "table"}
    assert figure["quality_score"] >= 55

    ignored = client.patch(
        f"/api/figures/{figure['id']}", headers=auth["headers"],
        json={"ignored": True, "review_status": "rejected"},
    )
    assert ignored.status_code == 200, ignored.text
    after = client.get("/api/figures", headers=auth["headers"], params={"paper_id": paper["id"], "view": "featured"}).json()
    assert all(item["id"] != figure["id"] for item in after["items"])

    restored = client.patch(
        f"/api/figures/{figure['id']}", headers=auth["headers"],
        json={"ignored": False, "review_status": "confirmed"},
    )
    assert restored.status_code == 200

    saved = client.patch(f"/api/figures/{figure['id']}", headers=auth["headers"], json={"saved": True})
    assert saved.status_code == 200
    records = client.get("/api/figures", headers=auth["headers"], params={"paper_id": paper["id"], "view": "saved"}).json()
    assert any(item["id"] == figure["id"] for item in records["items"])
    assert records["summary"]["saved"] >= 1


def test_reclassify_endpoint_is_idempotent(client, auth):
    first = client.post("/api/figures/reclassify", headers=auth["headers"])
    second = client.post("/api/figures/reclassify", headers=auth["headers"])
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["result"]["total"] >= first.json()["result"]["total"] - 0

def test_full_width_text_poor_scan_is_page_snapshot():
    from app.models import Figure
    from app.services.figure_classification import classify_figure

    figure = Figure(
        id="test-figure", user_id="test-user", paper_id="test-paper",
        page_number=1, order_index=1, caption=None, kind="figure",
        width=3072, height=341, bbox={"x0": 18, "y0": 18, "x1": 570, "y1": 79},
        table_markdown=None,
    )
    classify_figure(None, figure, page_text="", page_width=595, page_height=842)
    assert figure.detected_kind == "page_snapshot"
    assert figure.is_page_snapshot is True
    assert figure.quality_score < 55


def test_table_markdown_is_classified_as_table():
    from app.models import Figure
    from app.services.figure_classification import classify_figure

    figure = Figure(
        id="test-table", user_id="test-user", paper_id="test-paper",
        page_number=2, order_index=2, caption="Table 1: Results", kind="table",
        width=400, height=200, bbox={"x0": 40, "y0": 200, "x1": 500, "y1": 400},
        table_markdown="| a | b |\n| 1 | 2 |",
    )
    classify_figure(None, figure, page_text="x" * 300, page_width=595, page_height=842)
    assert figure.detected_kind == "table"
    assert figure.is_page_snapshot is False
    assert figure.quality_score >= 55
