"""V4.2 UX regression: search relevance, duplicate detail, concise local banner."""
from __future__ import annotations

import uuid

from app.services.analysis import LOCAL_BANNER


def test_paper_search_ranks_title_match_first(client, auth, paper, paper_b):
    grounded = client.get("/api/papers", headers=auth["headers"], params={"query": "Grounded", "limit": 20}).json()["items"]
    contrastive = client.get("/api/papers", headers=auth["headers"], params={"query": "Contrastive", "limit": 20}).json()["items"]
    assert grounded[0]["title"].startswith("Grounded"), [p["title"] for p in grounded]
    assert contrastive[0]["title"].startswith("Contrastive"), [p["title"] for p in contrastive]


def test_duplicate_knowledge_returns_actionable_409(client, auth):
    title = "UX duplicate " + uuid.uuid4().hex[:6]
    payload = {"title": title, "content": "同一段重复知识内容，用于验证 409 candidate。", "kind": "note"}
    first = client.post("/api/knowledge", headers=auth["headers"], json=payload)
    second = client.post("/api/knowledge", headers=auth["headers"], json=payload)
    assert first.status_code == 201
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_knowledge"
    assert detail["candidate"]["id"]
    assert detail["candidate"]["title"] == title


def test_local_banner_is_concise():
    assert len(LOCAL_BANNER) < 120
    assert "本地抽取" in LOCAL_BANNER
