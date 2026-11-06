"""Evidence System tests: verification, harvesting, isolation and analyses."""
from __future__ import annotations

import uuid

from app.db import SessionLocal
from app.models import Chunk

from .conftest import sse_events


def _first_chunk(paper_id: str) -> Chunk:
    with SessionLocal() as db:
        chunk = (
            db.query(Chunk)
            .filter(Chunk.paper_id == paper_id, Chunk.page_start == 2)
            .order_by(Chunk.order_index)
            .first()
        )
        if chunk is None:
            chunk = db.query(Chunk).filter(Chunk.paper_id == paper_id).first()
        db.expunge(chunk)
        return chunk


def _other_user(client) -> dict:
    email = f"evidence-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "Other"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_create_evidence_and_verify(client, auth, paper):
    chunk = _first_chunk(paper["id"])
    quote = chunk.text[:220]
    response = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={
            "paper_id": paper["id"],
            "chunk_id": chunk.id,
            "page": chunk.page_start,
            "quote": quote,
            "claim": "这是测试断言",
            "evidence_type": "direct",
            "source_type": "manual",
    },
    )
    assert response.status_code == 201, response.text
    evidence = response.json()["evidence"]
    assert evidence["verified"] is True
    assert evidence["evidence_type"] == "direct"
    assert evidence["confidence"] >= 0.8
    assert evidence["page"] == chunk.page_start
    assert evidence["paper_title"]

    listed = client.get("/api/evidence?paper_id=" + paper["id"], headers=auth["headers"])
    assert listed.status_code == 200
    assert any(row["id"] == evidence["id"] for row in listed.json()["items"])


def test_unverifiable_quote_is_marked(client, auth, paper):
    chunk = _first_chunk(paper["id"])
    response = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={
            "paper_id": paper["id"],
            "chunk_id": chunk.id,
            "quote": "This sentence was invented by a model and does not exist in the paper.",
            "evidence_type": "direct",
        },
    )
    assert response.status_code == 201
    evidence = response.json()["evidence"]
    assert evidence["verified"] is False
    assert "未在原文中找到" in (evidence["verification_note"] or "")
    assert evidence["confidence"] <= 0.3


def test_prefix_with_fabricated_suffix_is_not_verified(client, auth, paper):
    chunk = _first_chunk(paper["id"])
    normalized = " ".join(chunk.text.split())
    quote = normalized[:90] + "这是伪造的后半段内容。"
    response = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={
            "paper_id": paper["id"],
            "chunk_id": chunk.id,
            "page": chunk.page_start,
            "quote": quote,
            "claim": "伪造后缀不应通过",
            "evidence_type": "direct",
        },
    )
    assert response.status_code == 201, response.text
    evidence = response.json()["evidence"]
    assert evidence["verified"] is False, evidence["verification_note"]
    ellipsis_quote = normalized[:90] + "…伪造后缀"
    ellipsis = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={
            "paper_id": paper["id"],
            "chunk_id": chunk.id,
            "page": chunk.page_start,
            "quote": ellipsis_quote,
            "claim": "省略号后的伪造内容不应通过",
            "evidence_type": "direct",
        },
    )
    assert ellipsis.status_code == 201
    assert ellipsis.json()["evidence"]["verified"] is False


def test_evidence_type_validation_and_insufficient(client, auth, paper):
    invalid = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={"paper_id": paper["id"], "quote": "x", "evidence_type": "made-up"},
    )
    assert invalid.status_code == 422
    insufficient = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={"quote": "", "claim": "没有找到足够证据", "evidence_type": "insufficient"},
    )
    assert insufficient.status_code == 201
    body = insufficient.json()["evidence"]
    assert body["verified"] is False
    assert body["confidence"] <= 0.2
    assert body["evidence_type"] == "insufficient"


def test_evidence_user_isolation(client, auth, paper):
    other = _other_user(client)
    blocked = client.post(
        "/api/evidence",
        headers=other,
        json={"paper_id": paper["id"], "quote": "attempt to cross the boundary", "evidence_type": "direct"},
    )
    assert blocked.status_code == 404

    mine = client.post(
        "/api/evidence",
        headers=auth["headers"],
        json={"paper_id": paper["id"], "quote": _first_chunk(paper["id"]).text[:150], "evidence_type": "direct"},
    )
    evidence_id = mine.json()["evidence"]["id"]
    assert client.get("/api/evidence/" + evidence_id, headers=other).status_code == 404
    assert client.delete("/api/evidence/" + evidence_id, headers=other).status_code == 404


def test_chat_harvests_evidence(client, auth, paper):
    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=auth["headers"],
        json={"message": "这篇论文的方法如何保证引用可追溯？", "mode": "deep_read", "scope_type": "papers", "scope_ids": [paper["id"]]},
    ) as response:
        events = sse_events(response)
    done = [event for event in events if event["type"] == "done"][-1]
    assert done["evidence_count"] >= 1
    message_id = done["message_id"]

    listing = client.get(
        "/api/evidence?source_type=message&source_id=" + message_id,
        headers=auth["headers"],
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items
    assert any(item["verified"] for item in items)
    assert all(item["source_type"] == "message" for item in items)


def test_summary_persists_analysis_and_evidence(client, auth, paper):
    response = client.post(
        "/api/papers/" + paper["id"] + "/summary",
        headers=auth["headers"],
        json={"mode": "method"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_id"]
    assert body["evidence_count"] >= 1

    listing = client.get(
        "/api/evidence?analysis_id=" + body["analysis_id"],
        headers=auth["headers"],
    )
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert items
    assert all(item["analysis_id"] == body["analysis_id"] for item in items)
    assert any(item["evidence_type"] in {"direct", "shared", "inferred"} for item in items)


def test_compare_persists_analysis(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/compare",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]], "focus": "研究方法"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_id"]
    assert body["evidence_count"] >= 1
    listing = client.get("/api/evidence?analysis_id=" + body["analysis_id"], headers=auth["headers"])
    assert listing.json()["items"]


def test_annotation_to_evidence(client, auth, paper):
    chunk = _first_chunk(paper["id"])
    quote = chunk.text[:180]
    annotation = client.post(
        "/api/annotations",
        headers=auth["headers"],
        json={"paper_id": paper["id"], "page": chunk.page_start, "color": "yellow", "quote": quote, "note": "证据测试"},
    ).json()["annotation"]
    response = client.post("/api/evidence/from-annotation/" + annotation["id"], headers=auth["headers"])
    assert response.status_code == 201, response.text
    body = response.json()["evidence"]
    assert body["source_type"] == "annotation"
    assert body["verified"] is True
    assert body["page"] == chunk.page_start


def test_backfill_and_stats(client, auth, paper):
    before = client.get("/api/evidence/stats", headers=auth["headers"]).json()
    response = client.post("/api/evidence/backfill", headers=auth["headers"])
    assert response.status_code == 200
    assert "created" in response.json()
    after = client.get("/api/evidence/stats", headers=auth["headers"]).json()
    assert after["total"] >= before["total"]
    assert after["verified"] >= 1
    assert sum(after["by_type"].values()) == after["total"]


def test_evidence_filters(client, auth, paper):
    chunk = _first_chunk(paper["id"])
    for evidence_type in ("direct", "hypothesis"):
        client.post(
            "/api/evidence",
            headers=auth["headers"],
            json={
                "paper_id": paper["id"],
                "chunk_id": chunk.id,
                "quote": chunk.text[:200],
                "evidence_type": evidence_type,
                "claim": "筛选测试",
            },
        )
    filtered = client.get("/api/evidence?type=hypothesis&verified=false", headers=auth["headers"])
    assert filtered.status_code == 200
    assert all(item["evidence_type"] == "hypothesis" for item in filtered.json()["items"])