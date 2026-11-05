"""P7 tests: auto tags, hybrid search, duplicates, clusters, versions."""
from __future__ import annotations

import uuid


def _create(client, headers, title: str, content: str, *, force: bool = False, tags: list[str] | None = None):
    return client.post(
        "/api/knowledge",
        headers=headers,
        json={"title": title, "content": content, "kind": "insight", "tags": tags or [], "force": force},
    )


def _other_user(client) -> dict:
    email = f"p7-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "P7"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_auto_tags_and_version_one(client, auth):
    response = _create(
        client,
        auth["headers"],
        "低资源检索的对比学习结论",
        "contrastive pretraining improves low-resource scientific retrieval. limitation: only English papers.",
    )
    assert response.status_code == 201, response.text
    item = response.json()["item"]
    assert item["version"] == 1
    assert item["auto_tags"]
    assert item["cluster_label"]
    versions = client.get("/api/knowledge/" + item["id"] + "/versions", headers=auth["headers"]).json()
    assert len(versions["versions"]) == 1
    assert versions["versions"][0]["version"] == 1


def test_duplicate_blocks_then_force_creates(client, auth):
    first = _create(client, auth["headers"], "重复检测样本", "evidence grounded answer with citations").json()["item"]
    second = _create(client, auth["headers"], "重复检测样本", "evidence grounded answer with citations")
    assert second.status_code == 409, second.text
    detail = second.json()["detail"]
    assert detail["code"] == "duplicate_knowledge"
    assert detail["candidate"]["id"] == first["id"]
    listed = client.get("/api/knowledge?query=重复检测样本", headers=auth["headers"]).json()["items"]
    assert len([item for item in listed if item["title"] == "重复检测样本"]) == 1

    forced = _create(client, auth["headers"], "重复检测样本", "evidence grounded answer with citations", force=True)
    assert forced.status_code == 201, forced.text
    assert forced.json()["duplicate_of"] == first["id"]


def test_versions_and_rollback(client, auth):
    item = _create(client, auth["headers"], "版本测试", "original content about retrieval").json()["item"]
    updated = client.patch(
        "/api/knowledge/" + item["id"],
        headers=auth["headers"],
        json={"content": "updated content about evaluation", "tags": ["evaluation"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["item"]["version"] == 2
    versions = client.get("/api/knowledge/" + item["id"] + "/versions", headers=auth["headers"]).json()["versions"]
    assert [row["version"] for row in versions][:2] == [2, 1]
    rolled = client.post(
        "/api/knowledge/" + item["id"] + "/versions/1/rollback",
        headers=auth["headers"],
        json={"note": "回到初始版本"},
    )
    assert rolled.status_code == 200, rolled.text
    assert "original content" in rolled.json()["item"]["content"]
    assert rolled.json()["item"]["version"] == 3
    latest = client.get("/api/knowledge/" + item["id"] + "/versions", headers=auth["headers"]).json()["versions"]
    assert latest[0]["note"] == "回到初始版本"


def test_hybrid_search_and_clusters(client, auth):
    _create(client, auth["headers"], "Section-aware chunking", "section aware chunking improves citation faithfulness")
    _create(client, auth["headers"], "Contrastive retrieval", "contrastive pretraining for low resource scientific search")
    results = client.get("/api/knowledge?query=low resource scientific retrieval", headers=auth["headers"]).json()
    assert results["search"]["mode"] == "hybrid"
    assert results["items"]
    assert results["items"][0]["search_score"] > 0
    clusters = client.get("/api/knowledge/clusters", headers=auth["headers"]).json()
    assert clusters["total"] >= 2
    assert clusters["items"]
    assert clusters["items"][0]["count"] >= 1


def test_graph_has_tag_and_concept_nodes(client, auth, paper, paper_b):
    client.post(
        "/api/research/matrix",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]]},
    )
    _create(client, auth["headers"], "图谱知识", "method and dataset concepts from the paper")
    graph = client.get("/api/knowledge/graph", headers=auth["headers"]).json()
    types = {node["type"] for node in graph["nodes"]}
    assert "paper" in types and "knowledge" in types and "tag" in types
    assert "method" in types or "dataset" in types or "question" in types
    assert any(edge["relation"] == "tagged" for edge in graph["edges"])


def test_knowledge_isolation(client, auth):
    item = _create(client, auth["headers"], "隔离知识", "private knowledge content").json()["item"]
    other = _other_user(client)
    assert client.get("/api/knowledge/" + item["id"] + "/versions", headers=other).status_code == 404
    blocked = _create(client, other, "隔离知识", "private knowledge content")
    assert blocked.status_code == 201

def test_merge_similar_knowledge(client, auth):
    left = _create(client, auth["headers"], "合并目标", "target content about retrieval").json()["item"]
    right = _create(client, auth["headers"], "合并来源", "source content about evaluation", force=True).json()["item"]
    merged = client.post(
        "/api/knowledge/" + left["id"] + "/merge",
        headers=auth["headers"],
        json={"source_ids": [right["id"]], "note": "合并测试"},
    )
    assert merged.status_code == 200, merged.text
    item = merged.json()["item"]
    assert "source content" in item["content"]
    assert item["version"] >= 2
    assert client.get("/api/knowledge/" + right["id"] + "/versions", headers=auth["headers"]).status_code == 404
