"""End-to-end API tests covering the acceptance criteria."""
from __future__ import annotations

import io
import json
import uuid

from .conftest import build_sample_pdf, sse_events


def _register(client, prefix: str = "user") -> dict:
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "Test User"})
    assert response.status_code == 201, response.text
    data = response.json()
    return {"headers": {"Authorization": f"Bearer {data['access_token']}"}, "email": email, "user": data["user"]}


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_registration_login_and_profile(client):
    auth = _register(client, "auth")
    me = client.get("/api/auth/me", headers=auth["headers"])
    assert me.status_code == 200
    assert me.json()["user"]["email"] == auth["email"]
    login = client.post("/api/auth/login", json={"email": auth["email"], "password": "Research123!"})
    assert login.status_code == 200
    assert login.json()["access_token"]
    bad = client.post("/api/auth/login", json={"email": auth["email"], "password": "wrong-password"})
    assert bad.status_code == 401
    unauthorized = client.get("/api/papers")
    assert unauthorized.status_code == 401
    profile = client.patch("/api/auth/profile", headers=auth["headers"], json={"affiliation": "Tsinghua University"})
    assert profile.json()["user"]["affiliation"] == "Tsinghua University"


def test_paper_parsing_extracts_structure(paper):
    assert paper["page_count"] >= 2
    assert paper["sections"], "sections should be detected"
    titles = " ".join(section["title"] for section in paper["sections"]).lower()
    assert "introduction" in titles
    assert "method" in titles
    assert paper["chunks_count"] >= 4
    assert "retrieval" in (paper["abstract"] or "").lower()


def test_paper_metadata_update(client, auth, paper):
    response = client.patch(
        f"/api/papers/{paper['id']}",
        headers=auth["headers"],
        json={"favorite": True, "note": "metadata note", "tags": ["retrieval", "updated"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()["paper"]
    assert body["favorite"] is True
    assert body["note"] == "metadata note"
    assert "updated" in body["tags"]


def test_blank_pdf_is_not_ready(client, auth):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    doc = canvas.Canvas(buffer, pagesize=A4)
    doc.showPage()
    doc.save()
    upload = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("blank.pdf", buffer.getvalue(), "application/pdf")},
        data={"allow_duplicate": "true"},
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["paper"]["id"]
    import time
    detail = None
    for _ in range(40):
        detail = client.get(f"/api/papers/{paper_id}", headers=auth["headers"])
        if detail.json()["status"] in {"ready", "failed"}:
            break
        time.sleep(0.25)
    assert detail is not None
    body = detail.json()
    assert body["status"] == "failed", body
    assert "可检索文本" in (body.get("error") or "")


def test_duplicate_detection(client, auth, sample_pdf_bytes):
    first = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("dup.pdf", sample_pdf_bytes, "application/pdf")},
        data={"allow_duplicate": "true"},
    )
    assert first.status_code == 201
    duplicated = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("dup2.pdf", sample_pdf_bytes, "application/pdf")},
    )
    assert duplicated.status_code == 409
    body = duplicated.json()["detail"]
    assert body["code"] == "duplicate"


def test_pdf_upload_validation(client, auth):
    not_pdf = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
    )
    assert not_pdf.status_code == 422
    wrong_ext = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("paper.txt", b"%PDF-1.4", "text/plain")},
    )
    assert wrong_ext.status_code == 422


def test_pdf_download_and_outline(client, auth, paper):
    file_response = client.get(f"/api/papers/{paper['id']}/file", headers=auth["headers"])
    assert file_response.status_code == 200
    assert file_response.content.startswith(b"%PDF")
    outline = client.get(f"/api/papers/{paper['id']}/outline", headers=auth["headers"])
    assert outline.status_code == 200
    assert len(outline.json()["sections"]) >= 3
    assert len(outline.json()["chunks"]) > 3
    page = client.get(f"/api/papers/{paper['id']}/pages/1", headers=auth["headers"])
    assert page.status_code == 200
    assert "abstract" in page.json()["text"].lower()


def test_chat_stream_is_grounded(client, auth, paper):
    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=auth["headers"],
        json={"message": "这篇论文的检索方法如何提升忠实度？", "mode": "deep_read", "scope_type": "papers", "scope_ids": [paper["id"]]},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = sse_events(response)
    kinds = [event["type"] for event in events]
    assert "start" in kinds
    assert "delta" in kinds
    assert "done" in kinds
    done = [event for event in events if event["type"] == "done"][-1]
    assert done["citations"], "answers must carry citations"
    assert done["content"]
    assert "[C" in done["content"]
    assert done["provider"] == "local"
    conversation_id = done["conversation_id"]
    stored = client.get(f"/api/conversations/{conversation_id}", headers=auth["headers"])
    assert stored.status_code == 200
    messages = stored.json()["messages"]
    assert len(messages) == 2
    assert messages[1]["citations"]
    steps = client.get(f"/api/agent/runs/{done['run_id']}", headers=auth["headers"])
    assert steps.status_code == 200
    assert len(steps.json()["steps"]) >= 1


def test_annotations_persist_and_restore(client, auth, paper):
    created = client.post(
        "/api/annotations",
        headers=auth["headers"],
        json={
            "paper_id": paper["id"], "page": 2, "color": "blue",
            "quote": "section-aware chunker keeps page provenance",
            "rects": [{"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.03}],
            "note": "关键方法", "tags": ["method"],
        },
    )
    assert created.status_code == 201, created.text
    annotation = created.json()["annotation"]
    listing = client.get(f"/api/annotations?paper_id={paper['id']}", headers=auth["headers"])
    assert any(item["id"] == annotation["id"] for item in listing.json()["items"])
    filtered = client.get(f"/api/annotations?paper_id={paper['id']}&color=blue", headers=auth["headers"])
    assert len(filtered.json()["items"]) == 1
    updated = client.patch(f"/api/annotations/{annotation['id']}", headers=auth["headers"], json={"note": "更新后的笔记", "favorite": True})
    assert updated.json()["annotation"]["note"] == "更新后的笔记"
    deleted = client.delete(f"/api/annotations/{annotation['id']}", headers=auth["headers"])
    assert deleted.json()["undo_available"] is True
    after_delete = client.get(f"/api/annotations?paper_id={paper['id']}", headers=auth["headers"])
    assert after_delete.json()["items"] == []
    restored = client.post(f"/api/annotations/{annotation['id']}/restore", headers=auth["headers"])
    assert restored.json()["annotation"]["id"] == annotation["id"]
    visible = client.get(f"/api/annotations?paper_id={paper['id']}", headers=auth["headers"])
    assert len(visible.json()["items"]) == 1


def test_summary_local_mode(client, auth, paper):
    response = client.post(f"/api/papers/{paper['id']}/summary", headers=auth["headers"], json={"mode": "methods"})
    assert response.status_code == 422
    response = client.post(f"/api/papers/{paper['id']}/summary", headers=auth["headers"], json={"mode": "method"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["local"] is True
    assert body["citations"]
    assert "本地抽取模式" in body["content"]


def test_translation_requires_model(client, auth, paper):
    response = client.post(f"/api/papers/{paper['id']}/translate", headers=auth["headers"], json={"page": 1})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "model_required"


def test_compare_and_gap_local(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/compare",
        headers=auth["headers"],
        json={"paper_ids": [paper["id"], paper_b["id"]], "focus": "研究方法与实验设置"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["local"] is True
    assert "证据矩阵" in body["content"]
    assert len(body["citations"]) >= 4
    gap = client.post("/api/research/gap", headers=auth["headers"], json={"paper_ids": [paper["id"], paper_b["id"]]})
    assert gap.status_code == 200
    assert gap.json()["content"]


def test_fragment_comparison(client, auth, paper, paper_b):
    response = client.post(
        "/api/research/compare",
        headers=auth["headers"],
        json={
            "paper_ids": [paper["id"], paper_b["id"]],
            "focus": "方法差异",
            "fragments": [
                {"paper_id": paper["id"], "text": "Section-aware chunking keeps page provenance for every chunk.", "page": 2, "section": "3 Method"},
                {"paper_id": paper_b["id"], "text": "Contrastive pretraining aligns abstracts with section summaries.", "page": 2, "section": "3 Method"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert "片段" in response.json()["content"]


def test_knowledge_library_and_graph(client, auth, paper):
    created = client.post(
        "/api/knowledge",
        headers=auth["headers"],
        json={
            "title": "Section-aware chunking improves faithfulness",
            "content": "Ablation shows +9.1 points over fixed chunking.",
            "kind": "insight", "tags": ["method"], "source_paper_id": paper["id"], "source_page": 2,
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()["item"]
    listing = client.get("/api/knowledge?query=faithfulness", headers=auth["headers"])
    assert any(row["id"] == item["id"] for row in listing.json()["items"])
    graph = client.get("/api/knowledge/graph", headers=auth["headers"])
    assert graph.status_code == 200
    assert any(node["id"] == f"knowledge:{item['id']}" for node in graph.json()["nodes"])
    assert any(edge["source"] == f"knowledge:{item['id']}" for edge in graph.json()["edges"])


def test_collections_and_projects(client, auth, paper):
    collection = client.post("/api/collections", headers=auth["headers"], json={"name": "RAG reading list"})
    assert collection.status_code == 201
    collection_id = collection.json()["collection"]["id"]
    added = client.post(f"/api/collections/{collection_id}/papers", headers=auth["headers"], json=[paper["id"]])
    assert added.json()["added"] == 1
    collection_list = client.get("/api/collections", headers=auth["headers"])
    assert collection_list.json()["items"][0]["paper_count"] == 1
    project = client.post("/api/projects", headers=auth["headers"], json={"name": "Thesis chapter 2", "goal": "Survey grounded reading"})
    project_id = project.json()["project"]["id"]
    client.post(f"/api/projects/{project_id}/items", headers=auth["headers"], json={"kind": "paper", "ref_id": paper["id"], "title": paper["title"]})
    detail = client.get(f"/api/projects/{project_id}", headers=auth["headers"])
    assert len(detail.json()["items"]) == 1
    updated = client.patch(f"/api/projects/{project_id}", headers=auth["headers"], json={"progress": 40})
    assert updated.json()["project"]["progress"] == 40


def test_export_all_formats(client, auth, paper):
    body = {"title": "PaperLens 研究报告", "kind": "report", "paper_id": paper["id"]}
    for fmt in ("md", "txt", "json", "csv", "pdf", "docx"):
        response = client.post("/api/exports", headers=auth["headers"], json={**body, "format": fmt})
        assert response.status_code == 201, (fmt, response.text)
        record = response.json()["export"]
        download = client.get(record["download_url"], headers=auth["headers"])
        assert download.status_code == 200
        assert len(download.content) > 200, fmt
        if fmt == "pdf":
            assert download.content.startswith(b"%PDF")
        if fmt == "docx":
            assert download.content.startswith(b"PK")
    listing = client.get("/api/exports", headers=auth["headers"])
    assert len(listing.json()["items"]) >= 6


def test_user_isolation(client, auth, paper):
    other = _register(client, "intruder")
    assert client.get(f"/api/papers/{paper['id']}", headers=other["headers"]).status_code == 404
    assert client.get(f"/api/papers/{paper['id']}/file", headers=other["headers"]).status_code == 404
    assert client.post("/api/annotations", headers=other["headers"], json={"paper_id": paper["id"], "page": 1, "color": "yellow", "quote": "x"}).status_code == 404
    assert client.get(f"/api/papers/{paper['id']}/outline", headers=other["headers"]).status_code == 404
    other_list = client.get("/api/papers", headers=other["headers"])
    assert other_list.json()["items"] == []


def test_agent_write_action_requires_confirmation(client, auth, paper):
    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=auth["headers"],
        json={"message": "把这篇论文的核心结论保存到知识库", "mode": "quick", "scope_type": "papers", "scope_ids": [paper["id"]]},
    ) as response:
        events = sse_events(response)
    actions = [event["action"] for event in events if event["type"] == "action"]
    assert actions, "write tool should produce a pending action"
    action = actions[0]
    assert action["tool"] == "save_knowledge"
    confirmed = client.post("/api/agent/actions/confirm", headers=auth["headers"], json={"tool": action["tool"], "args": action["args"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result"]["data"]["knowledge_id"]
    items = client.get("/api/knowledge", headers=auth["headers"])
    assert any(item["title"].startswith("研究笔记") for item in items.json()["items"])


def test_settings_and_model_status(client, auth):
    payload = client.get("/api/settings", headers=auth["headers"]).json()
    assert payload["model"]["configured"] is False
    assert payload["model"]["mode"] == "extractive"
    updated = client.patch("/api/settings", headers=auth["headers"], json={"theme": "dark", "language": "en", "onboarding_completed": True})
    assert updated.json()["settings"]["theme"] == "dark"
    usage = client.get("/api/settings/usage", headers=auth["headers"])
    assert usage.status_code == 200
    data_export = client.post("/api/settings/data-export", headers=auth["headers"])
    assert data_export.status_code == 200
    record = data_export.json()["export"]
    download = client.get(record["download_url"], headers=auth["headers"])
    assert download.status_code == 200
    assert b"papers" in download.content


def test_figures_extracted(client, auth, paper):
    figures = client.get(f"/api/figures?paper_id={paper['id']}", headers=auth["headers"])
    assert figures.status_code == 200
    items = figures.json()["items"]
    assert items, "the embedded figure should be extracted"
    figure = items[0]
    image = client.get(figure["image_url"], headers=auth["headers"])
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")
    updated = client.patch(f"/api/figures/{figure['id']}", headers=auth["headers"], json={"note": "重要结果", "saved": True})
    assert updated.json()["figure"]["saved"] is True
    other = _register(client, "figintruder")
    assert client.get(figure["image_url"], headers=other["headers"]).status_code == 404


def test_conversation_history(client, auth):
    with client.stream(
        "POST",
        "/api/chat/stream",
        headers=auth["headers"],
        json={"message": "什么是检索增强生成？", "mode": "quick"},
    ) as response:
        events = sse_events(response)
    done = [event for event in events if event["type"] == "done"][-1]
    conversation = client.get(f"/api/conversations/{done['conversation_id']}", headers=auth["headers"])
    assert conversation.json()["conversation"]["title"]
    listing = client.get("/api/conversations", headers=auth["headers"])
    assert any(item["id"] == done["conversation_id"] for item in listing.json()["items"])
    deleted = client.delete(f"/api/conversations/{done['conversation_id']}", headers=auth["headers"])
    assert deleted.json()["ok"] is True

def test_tag_filter(client, auth, paper):
    response = client.get("/api/papers?tag=retrieval", headers=auth["headers"])
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(row["id"] == paper["id"] for row in items)
    tags = client.get("/api/papers/tags", headers=auth["headers"]).json()["tags"]
    assert any(tag["name"] == "retrieval" for tag in tags)


def test_critical_analysis_local_mode(client, auth, paper):
    response = client.post(f"/api/papers/{paper['id']}/analysis", headers=auth["headers"], json={"mode": "critical"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["local"] is True
    assert body["citations"], "critical review must reference evidence"
    assert "证据审查" in body["content"] or "批判" in body["content"]


def test_chunk_level_fragment_comparison(client, auth, paper, paper_b):
    outline_a = client.get(f"/api/papers/{paper['id']}/outline", headers=auth["headers"]).json()["chunks"]
    outline_b = client.get(f"/api/papers/{paper_b['id']}/outline", headers=auth["headers"]).json()["chunks"]
    response = client.post(
        "/api/research/compare",
        headers=auth["headers"],
        json={
            "paper_ids": [paper["id"], paper_b["id"]],
            "focus": "方法差异",
            "fragments": [
                {"paper_id": paper["id"], "chunk_id": outline_a[1]["id"]},
                {"paper_id": paper_b["id"], "chunk_id": outline_b[1]["id"]},
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["fragments"]) == 2
    assert body["citations"]


def test_export_knowledge_items(client, auth, paper):
    created = client.post(
        "/api/knowledge",
        headers=auth["headers"],
        json={"title": "可导出的知识", "content": "内容包含中文与 English。", "kind": "note", "source_paper_id": paper["id"]},
    )
    item_id = created.json()["item"]["id"]
    response = client.post(
        "/api/exports",
        headers=auth["headers"],
        json={"kind": "knowledge", "format": "md", "title": "知识导出", "knowledge_ids": [item_id]},
    )
    assert response.status_code == 201, response.text
    record = response.json()["export"]
    download = client.get(record["download_url"], headers=auth["headers"])
    assert download.status_code == 200
    assert "可导出的知识".encode("utf-8") in download.content


def test_export_delete_removes_file(client, auth):
    from pathlib import Path
    from app.db import SessionLocal
    from app.models import ExportRecord
    from app.services.storage import storage

    created = client.post(
        "/api/exports",
        headers=auth["headers"],
        json={"kind": "test", "format": "md", "title": "delete-file-check", "content": "# delete me"},
    )
    assert created.status_code == 201, created.text
    export_id = created.json()["export"]["id"]
    with SessionLocal() as db:
        record = db.get(ExportRecord, export_id)
        assert record is not None
        path = storage.abs_path(record.path)
    assert path.exists()
    deleted = client.delete(f"/api/exports/{export_id}", headers=auth["headers"])
    assert deleted.status_code == 200
    assert not path.exists()


def test_delete_requires_confirmation(client, auth, sample_pdf_bytes_b):
    upload = client.post(
        "/api/papers",
        headers=auth["headers"],
        files={"file": ("to-delete.pdf", sample_pdf_bytes_b, "application/pdf")},
        data={"allow_duplicate": "true"},
    )
    assert upload.status_code == 201
    paper_id = upload.json()["paper"]["id"]
    blocked = client.delete(f"/api/papers/{paper_id}", headers=auth["headers"])
    assert blocked.status_code == 400
    removed = client.delete(f"/api/papers/{paper_id}?confirm=true", headers=auth["headers"])
    assert removed.status_code == 200
    assert client.get(f"/api/papers/{paper_id}", headers=auth["headers"]).status_code == 404

def test_account_deletion_removes_data(client):
    from app.db import SessionLocal
    from app.models import AgentTask

    auth = _register(client, "delete-account")
    client.post("/api/knowledge", headers=auth["headers"], json={"title": "临时数据", "content": "将被删除"})
    task_response = client.post(
        "/api/agent/tasks/plan",
        headers=auth["headers"],
        json={"message": "删除账号前的测试任务", "scope_type": "all"},
    )
    assert task_response.status_code == 200, task_response.text
    task_id = task_response.json()["task"]["id"]
    wrong = client.request(
        "DELETE", "/api/settings/account", headers=auth["headers"],
        json={"password": "Research123!", "confirm": "NO"},
    )
    assert wrong.status_code == 400
    removed = client.request(
        "DELETE", "/api/settings/account", headers=auth["headers"],
        json={"password": "Research123!", "confirm": "DELETE"},
    )
    assert removed.status_code == 200, removed.text
    login = client.post("/api/auth/login", json={"email": auth["email"], "password": "Research123!"})
    assert login.status_code == 401
    assert client.get("/api/settings", headers=auth["headers"]).status_code == 401
    with SessionLocal() as db:
        assert db.get(AgentTask, task_id) is None