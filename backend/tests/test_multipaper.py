"""P4 tests: facets, matrix, conflicts, evolution and gap validation."""
from __future__ import annotations

import uuid

from app.db import SessionLocal
from app.models import PaperFacet


def _other_user(client) -> dict:
    email = f"p4-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "P4"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_matrix_builds_facets_and_evidence(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/matrix",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["rows"]) == 2
    assert len(body["dimensions"]) == 6
    assert body["local"] is True
    assert body["insight_id"]
    for row in body["rows"]:
        assert row["fields"]["research_question"]["text"]
        assert row["fields"]["method"]["text"]
    assert body["citations"]
    assert any(citation["verified"] for citation in body["citations"])

    with SessionLocal() as db:
        count = db.query(PaperFacet).filter(PaperFacet.user_id == auth["user"]["id"]).count()
    assert count >= 2


def test_conflicts_local_does_not_invent_conflicts(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/conflicts",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["local"] is True
    assert body["conflicts"] == []
    assert len(body["comparability"]) == 1
    assert "不判定" in body["note"]
    assert body["comparability"][0]["reason"]


def test_evolution_local_only_uses_real_years(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/evolution",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["local"] is True
    assert body["relations"] == []
    assert len(body["timeline"]) == 2
    assert all(item["year"] for item in body["timeline"])
    assert "不推断" in body["note"]


def test_gap_validation_returns_evidence_coverage(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/gap/validate",
        headers=auth["headers"],
        json={"claim": "section-aware chunking improves faithfulness", "paper_ids": [paper["id"], paper_b["id"]]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["support_count"] >= 1
    assert body["paper_count"] == 2
    assert body["supports"]
    assert "覆盖" in body["note"]
    assert body["citations"]


def test_insights_are_queryable(client, auth, paper, paper_b):
    created = client.post(
        "/api/research/matrix",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    ).json()
    listing = client.get("/api/research/insights?kind=matrix", headers=auth["headers"])
    assert listing.status_code == 200
    assert any(item["id"] == created["insight_id"] for item in listing.json()["items"])
    detail = client.get("/api/research/insights/" + created["insight_id"], headers=auth["headers"])
    assert detail.status_code == 200
    assert detail.json()["insight"]["kind"] == "matrix"


def test_matrix_isolation(client, auth, paper, paper_b):
    other = _other_user(client)
    blocked = client.post(
        "/api/research/matrix",
        headers=other,
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    )
    assert blocked.status_code == 404
    created = client.post(
        "/api/research/matrix",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    ).json()
    assert client.get("/api/research/insights/" + created["insight_id"], headers=other).status_code == 404


def test_matrix_requires_at_least_one_paper(client, auth):
    response = client.post("/api/research/matrix", headers=auth["headers"], json={"paper_ids": []})
    assert response.status_code == 422
