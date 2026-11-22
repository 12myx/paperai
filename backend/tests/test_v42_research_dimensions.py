"""V4.2: compare dimensions must drive the local comparison columns."""
from __future__ import annotations


def test_compare_dimensions_change_matrix_columns(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/compare", headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]], "focus": "局限性、研究结论"},
    )
    assert response.status_code == 200, response.text
    content = response.json()["content"]
    header = next((line for line in content.splitlines() if line.startswith("| 论文 |")), "")
    assert "局限性" in header
    assert "研究结论" in header
    assert "研究问题" not in header


def test_custom_compare_dimension_creates_custom_column(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/compare", headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]], "focus": "产业适配成本"},
    )
    assert response.status_code == 200, response.text
    content = response.json()["content"]
    assert "产业适配成本" in content