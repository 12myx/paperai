"""V4 unified research context, tools and ownership tests."""
from __future__ import annotations

import json
import uuid


def events(response) -> list[dict]:
    out = []
    for line in response.iter_lines():
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        if text.startswith("data: "):
            out.append(json.loads(text[6:]))
    return out


def chat(client, auth, message: str, **extra) -> list[dict]:
    payload = {"message": message, "mode": "quick", "scope_type": "all", **extra}
    response = client.post("/api/chat/stream", headers=auth["headers"], json=payload)
    assert response.status_code == 200, response.text
    return events(response)


def make_knowledge(client, auth, title: str, content: str, project_id: str | None = None) -> dict:
    body = {"title": title, "content": content, "kind": "note", "tags": ["v4"]}
    if project_id:
        body["project_id"] = project_id
    response = client.post("/api/knowledge", headers=auth["headers"], json=body)
    assert response.status_code == 201, response.text
    return response.json()["item"]


def test_knowledge_and_paper_joint_chat(client, auth, paper):
    item = make_knowledge(
        client, auth, "V4 RAG 笔记",
        "PaperLens 使用 section-aware chunking 和页面级来源；检索增强生成需要证据。",
    )
    events_ = chat(client, auth, "结合我知识库里的 V4 RAG 笔记与论文，解释检索增强生成的要点。")
    start = next(event for event in events_ if event.get("type") == "start")
    assert any(row["id"] == item["id"] for row in start["resources"]["knowledge"])
    assert any(step.get("step", {}).get("tool") == "search_knowledge" for step in events_ if step.get("type") == "step")
    done = next(event for event in events_ if event.get("type") == "done")
    assert any(citation.get("resource_type") == "knowledge" and citation.get("resource_id") == item["id"] for citation in done["citations"])
    assert "个人知识库" in "".join(event.get("text", "") for event in events_ if event.get("type") == "delta")
    evidence = client.get("/api/evidence", headers=auth["headers"], params={"source_type": "knowledge"}).json()
    assert any(row["source_id"] == item["id"] for row in evidence["items"])


def test_project_context_includes_goal_note_and_resources(client, auth, paper):
    project_response = client.post(
        "/api/projects", headers=auth["headers"],
        json={"name": "V4 项目 " + uuid.uuid4().hex[:6], "goal": "验证项目级研究上下文", "description": "项目描述"},
    )
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()["project"]
    item_response = client.post(
        f"/api/projects/{project['id']}/items", headers=auth["headers"],
        json={"kind": "note", "title": "项目笔记", "content": "下一步需要补充实验。"},
    )
    assert item_response.status_code == 201, item_response.text
    assert client.post(
        f"/api/projects/{project['id']}/items", headers=auth["headers"],
        json={"kind": "paper", "ref_id": paper["id"], "title": paper["title"]},
    ).status_code == 201
    knowledge = make_knowledge(client, auth, "项目知识", "项目相关的 RAG 知识。", project["id"])
    assert client.post(
        f"/api/projects/{project['id']}/items", headers=auth["headers"],
        json={"kind": "knowledge", "ref_id": knowledge["id"], "title": knowledge["title"]},
    ).status_code == 201

    events_ = chat(
        client, auth, "结合当前项目目标、论文和项目笔记总结现状。",
        scope_type="project", scope_ids=[project["id"]], project_id=project["id"],
    )
    start = next(event for event in events_ if event.get("type") == "start")
    assert start["resources"]["project"]["id"] == project["id"]
    assert any(step.get("step", {}).get("tool") == "get_project_context" for step in events_ if step.get("type") == "step")
    done = next(event for event in events_ if event.get("type") == "done")
    assert any(citation.get("resource_type") == "project" and citation.get("resource_id") == project["id"] for citation in done["citations"])
    assert "验证项目级研究上下文" in "".join(event.get("text", "") for event in events_ if event.get("type") == "delta")


def test_image_reads_real_file_and_limits_vision(client, auth, paper):
    figures = client.get("/api/figures", headers=auth["headers"], params={"paper_id": paper["id"]}).json()["items"]
    assert figures, "sample PDF should expose a figure"
    figure = figures[0]
    events_ = chat(client, auth, "解释图像库里的 Figure 1，并结合论文说明；没有视觉能力就明确说。", image_ids=[figure["id"]])
    steps = [event["step"] for event in events_ if event.get("type") == "step"]
    read_step = next(step for step in steps if step.get("tool") == "read_image" and step.get("status") == "done")
    assert "已读取真实图片文件" in read_step.get("summary", "")
    done = next(event for event in events_ if event.get("type") == "done")
    assert any(citation.get("resource_type") == "image" and citation.get("resource_id") == figure["id"] for citation in done["citations"])
    assert "无法完成真正的视觉分析" in "".join(event.get("text", "") for event in events_ if event.get("type") == "delta")


def test_artifact_tool_generation_confirmation_and_check(client, auth, paper):
    events_ = chat(client, auth, "根据论文生成一份文献综述。")
    action = next(event["action"] for event in events_ if event.get("type") == "action" and event["action"]["tool"] == "generate_artifact")
    confirmed = client.post(
        "/api/agent/actions/confirm", headers=auth["headers"],
        json={"tool": "generate_artifact", "args": action["args"], "action_id": action.get("action_id")},
    )
    assert confirmed.status_code == 200, confirmed.text
    artifact_id = confirmed.json()["result"]["data"]["artifact_id"]
    assert client.get(f"/api/artifacts/{artifact_id}", headers=auth["headers"]).status_code == 200

    checked = chat(client, auth, "检查这份成果的质量和引用问题。", artifact_ids=[artifact_id])
    steps = [event["step"] for event in checked if event.get("type") == "step"]
    assert any(step.get("tool") == "check_artifact" for step in steps)
    assert any(event.get("type") == "done" for event in checked)


def test_foreign_resources_are_not_resolved(client, auth, paper):
    item = make_knowledge(client, auth, "私有 V4 笔记", "只属于用户 A 的内容。")
    email = "v4-other-" + uuid.uuid4().hex[:8] + "@example.com"
    register = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "Other"})
    assert register.status_code == 201, register.text
    other_headers = {"Authorization": "Bearer " + register.json()["access_token"]}
    other_auth = {"headers": other_headers, "user": register.json()["user"]}
    events_ = chat(
        client, other_auth, "读取我无权访问的知识和项目。",
        knowledge_ids=[item["id"]], project_id="does-not-belong",
    )
    start = next(event for event in events_ if event.get("type") == "start")
    assert start["resources"]["knowledge"] == []
    assert start["resources"]["project"] is None
    done = next(event for event in events_ if event.get("type") == "done")
    assert all(citation.get("resource_id") != item["id"] for citation in done.get("citations", []))

def test_foreign_image_and_artifact_are_not_resolved(client, auth, paper):
    figures = client.get("/api/figures", headers=auth["headers"], params={"paper_id": paper["id"]}).json()["items"]
    assert figures
    generated = client.post(
        "/api/artifacts/generate", headers=auth["headers"],
        json={"kind": "literature_review", "scope_type": "papers", "paper_ids": [paper["id"]]},
    )
    assert generated.status_code == 200, generated.text
    artifact_id = generated.json()["artifact"]["id"]

    email = "v4-other2-" + uuid.uuid4().hex[:8] + "@example.com"
    register = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "Other 2"})
    assert register.status_code == 201, register.text
    other_auth = {"headers": {"Authorization": "Bearer " + register.json()["access_token"]}, "user": register.json()["user"]}
    events_ = chat(
        client, other_auth, "读取别人的图片和成果。",
        image_ids=[figures[0]["id"]], artifact_ids=[artifact_id],
    )
    start = next(event for event in events_ if event.get("type") == "start")
    assert start["resources"]["images"] == []
    assert start["resources"]["artifacts"] == []
    done = next(event for event in events_ if event.get("type") == "done")
    ids = {citation.get("resource_id") for citation in done.get("citations", [])}
    assert figures[0]["id"] not in ids
    assert artifact_id not in ids