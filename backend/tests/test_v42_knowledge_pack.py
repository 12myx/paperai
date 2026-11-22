"""V4.2: paper knowledge pack, preflight and knowledge-base persistence."""
from __future__ import annotations


def test_preflight_reports_ready_text_paper(client, auth, paper):
    response = client.get("/api/artifacts/preflight", headers=auth["headers"], params={"paper_id": paper["id"]})
    assert response.status_code == 200
    body = response.json()["preflight"]
    assert body["ready"] is True
    assert body["chunks"] > 0
    assert body["reason"] == "ready"


def test_knowledge_pack_generate_and_save_once(client, auth, paper):
    generated = client.post(
        "/api/artifacts/generate", headers=auth["headers"],
        json={"kind": "knowledge_pack", "scope_type": "papers", "paper_ids": [paper["id"]]},
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    artifact = body["artifact"]
    assert artifact["kind"] == "knowledge_pack"
    assert artifact["citations"]
    assert body["quality"]["status"] in {"pass", "warning"}, body["quality"]["issues"]
    assert artifact["knowledge_saved"] is False
    assert any(issue["code"] == "small_scope" for issue in body["quality"]["issues"]) is False

    saved = client.post(f"/api/artifacts/{artifact['id']}/save-to-knowledge", headers=auth["headers"])
    assert saved.status_code == 200, saved.text
    first = saved.json()
    assert first["count"] >= 3
    assert first["export"]["download_url"]
    assert first["artifact"]["knowledge_saved"] is True

    second = client.post(f"/api/artifacts/{artifact['id']}/save-to-knowledge", headers=auth["headers"])
    assert second.status_code == 200
    assert second.json()["count"] == first["count"]
    assert second.json()["export"] is None

    knowledge = client.get("/api/knowledge?limit=100", headers=auth["headers"])
    assert knowledge.status_code == 200
    ids = {item["id"] for item in knowledge.json()["items"]}
    assert {item["id"] for item in first["items"]} <= ids

def test_scanned_paper_is_blocked_before_empty_artifact(client, auth):
    import uuid
    from app.db import SessionLocal
    from app.models import Paper

    with SessionLocal() as db:
        paper = Paper(
            user_id=auth["user"]["id"], title="Scanned paper " + uuid.uuid4().hex[:6],
            filename="scanned.pdf", stored_path="scanned.pdf", sha256=uuid.uuid4().hex * 2,
            status="ready", page_count=2,
        )
        db.add(paper)
        db.commit()
        paper_id = paper.id

    preflight = client.get("/api/artifacts/preflight", headers=auth["headers"], params={"paper_id": paper_id})
    assert preflight.status_code == 200
    assert preflight.json()["preflight"]["ready"] is False
    assert preflight.json()["preflight"]["reason"] == "scanned_pdf"

    generated = client.post(
        "/api/artifacts/generate", headers=auth["headers"],
        json={"kind": "knowledge_pack", "scope_type": "papers", "paper_ids": [paper_id]},
    )
    assert generated.status_code == 422
    assert "扫描件" in generated.text

def test_knowledge_pack_requires_explicit_paper(client, auth):
    response = client.post(
        "/api/artifacts/generate", headers=auth["headers"],
        json={"kind": "knowledge_pack", "scope_type": "all"},
    )
    assert response.status_code == 422
    assert "不能绑定整个资料库" in response.text
