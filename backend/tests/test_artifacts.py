"""P8 tests: eight artifacts, evidence tables, quality checker, export."""
from __future__ import annotations

import uuid

from app.db import SessionLocal
from app.models import AcademicArtifact

KINDS = [
    "literature_review", "reading_report", "comparison_report", "direction_analysis",
    "proposal_draft", "research_plan", "experiment_design", "ppt_outline",
]


def _other_user(client) -> dict:
    email = f"p8-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "P8"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_generate_every_artifact_kind(client, auth, paper, paper_b):
    for kind in KINDS:
        response = client.post(
            "/api/artifacts/generate",
            headers=auth["headers"],
            json={"kind": kind, "scope_type": "all"},
        )
        assert response.status_code == 200, kind + ": " + response.text
        body = response.json()
        artifact = body["artifact"]
        quality = body["quality"]
        assert artifact["kind"] == kind
        assert len(artifact["content"]) > 500, kind
        assert artifact["citations"], kind
        assert artifact["evidence_table"], kind
        assert "仅基于资料库" in artifact["scope_statement"]
        assert quality["issues"] is not None
        errors = [issue for issue in quality["issues"] if issue["severity"] == "error"]
        assert not errors, kind + ": " + str(errors)


def test_quality_rerun_and_fake_citation(client, auth, paper, paper_b):
    created = client.post(
        "/api/artifacts/generate",
        headers=auth["headers"],
        json={"kind": "literature_review", "scope_type": "all"},
    ).json()
    artifact_id = created["artifact"]["id"]
    with SessionLocal() as db:
        artifact = db.get(AcademicArtifact, artifact_id)
        artifact.content += "\n\n## 伪造引用\n这一结论来自 [C99]。"
        db.commit()
    checked = client.post("/api/artifacts/" + artifact_id + "/check", headers=auth["headers"])
    assert checked.status_code == 200
    issues = checked.json()["quality"]["issues"]
    assert any(issue["code"] == "missing_citation" for issue in issues)
    assert checked.json()["quality"]["status"] == "fail"


def test_artifact_export_formats(client, auth, paper, paper_b):
    artifact = client.post(
        "/api/artifacts/generate",
        headers=auth["headers"],
        json={"kind": "reading_report", "scope_type": "all"},
    ).json()["artifact"]
    for fmt in ("md", "pdf", "docx"):
        exported = client.post(
            "/api/artifacts/" + artifact["id"] + "/export",
            headers=auth["headers"],
            json={"format": fmt},
        )
        assert exported.status_code == 201, fmt + ": " + exported.text
        record = exported.json()["export"]
        assert record["download_url"].endswith("/download")
        downloaded = client.get(record["download_url"], headers=auth["headers"])
        assert downloaded.status_code == 200
        assert len(downloaded.content) > 500


def test_artifact_isolation(client, auth, paper):
    artifact = client.post(
        "/api/artifacts/generate",
        headers=auth["headers"],
        json={"kind": "direction_analysis", "scope_type": "all"},
    ).json()["artifact"]
    other = _other_user(client)
    assert client.get("/api/artifacts/" + artifact["id"], headers=other).status_code == 404
    assert client.post("/api/artifacts/" + artifact["id"] + "/check", headers=other).status_code == 404
