"""P5 tests: scope, landscape, trends, connections, opportunities, caching."""
from __future__ import annotations

import uuid


def _other_user(client) -> dict:
    email = f"p5-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "P5"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_scope_all(client, auth, paper, paper_b):
    response = client.get("/api/intelligence/scope?scope_type=all", headers=auth["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"]["paper_count"] >= 2
    assert body["scope"]["years"]
    assert body["scope"]["external_data"] is False
    assert "资料库" in body["scope"]["boundary"]
    assert len(body["papers"]) >= 2


def test_overview_builds_four_reports(client, auth, paper, paper_b):
    response = client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "all", "force": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["reports"].keys()) == {"landscape", "trends", "connections", "opportunities"}
    assert body["scope"]["paper_count"] >= 2

    landscape = body["reports"]["landscape"]["data"]
    assert landscape["core_questions"]
    assert landscape["technical_routes"]
    assert landscape["representative_papers"]
    assert all(item.get("page") for item in landscape["core_questions"])
    assert "资料库" in landscape["overview"]

    trends = body["reports"]["trends"]["data"]
    assert sum(item["count"] for item in trends["year_counts"]) >= 1
    assert "资料库" in trends["note"]

    connections = body["reports"]["connections"]["data"]
    assert any(node["type"] == "paper" for node in connections["nodes"])
    assert any(node["type"] == "method" for node in connections["nodes"])
    assert connections["edges"]
    assert all("basis" in edge for edge in connections["edges"])

    opportunities = body["reports"]["opportunities"]["data"]
    assert opportunities["opportunities"]
    first = opportunities["opportunities"][0]
    assert first["evidence"]
    assert "启发式" in opportunities["note"]
    assert "不保证" in first["risks"]


def test_overview_cache_and_force(client, auth, paper, paper_b):
    first = client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "all", "force": True},
    ).json()
    ids = {kind: report["id"] for kind, report in first["reports"].items()}
    cached = client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "all", "force": False},
    ).json()
    assert {kind: report["id"] for kind, report in cached["reports"].items()} == ids
    forced = client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "all", "force": True},
    ).json()
    assert forced["reports"]["landscape"]["id"] != ids["landscape"]


def test_project_scope(client, auth, paper):
    project = client.post(
        "/api/projects",
        headers=auth["headers"],
        json={"name": "P5 情报项目", "goal": "测试研究情报范围"},
    ).json()["project"]
    client.post(
        "/api/projects/" + project["id"] + "/items",
        headers=auth["headers"],
        json={"kind": "paper", "ref_id": paper["id"], "title": paper["title"]},
    )
    scope = client.get(
        "/api/intelligence/scope?scope_type=project&scope_id=" + project["id"],
        headers=auth["headers"],
    )
    assert scope.status_code == 200, scope.text
    assert scope.json()["scope"]["paper_count"] == 1
    assert "P5 情报项目" in scope.json()["scope"]["label"]
    overview = client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "project", "scope_id": project["id"], "force": True},
    )
    assert overview.status_code == 200, overview.text
    assert overview.json()["reports"]["landscape"]["scope_label"].startswith("项目")


def test_intelligence_isolation(client, auth, paper, paper_b):
    other = _other_user(client)
    blocked = client.get("/api/intelligence/scope?scope_type=all", headers=other)
    assert blocked.status_code == 422  # the other user has an empty library
    created = client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "all", "force": True},
    ).json()
    report_id = created["reports"]["landscape"]["id"]
    assert client.get("/api/intelligence/reports/" + report_id, headers=other).status_code == 404
    listing = client.get("/api/intelligence/reports", headers=other)
    assert listing.json()["items"] == []


def test_reports_listing(client, auth, paper, paper_b):
    client.post(
        "/api/intelligence/overview",
        headers=auth["headers"],
        json={"scope_type": "all", "force": True},
    )
    listing = client.get("/api/intelligence/reports?kind=trends", headers=auth["headers"])
    assert listing.status_code == 200
    assert listing.json()["items"]
    assert all(item["kind"] == "trends" for item in listing.json()["items"])
