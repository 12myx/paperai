"""V4.2 auto-retrieval and resource-exclusion tests."""
from __future__ import annotations

import json
import uuid


def sse_events(response) -> list[dict]:
    out = []
    for line in response.iter_lines():
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        if text.startswith("data: "):
            out.append(json.loads(text[6:]))
    return out


def chat(client, auth, **extra) -> list[dict]:
    response = client.post(
        "/api/chat/stream", headers=auth["headers"],
        json={"message": "总结我的研究资料。", "mode": "quick", "scope_type": "all", **extra},
    )
    assert response.status_code == 200, response.text
    return sse_events(response)


def make_knowledge(client, auth, title: str) -> dict:
    response = client.post(
        "/api/knowledge", headers=auth["headers"],
        json={"title": title, "content": "自动检索与排除测试知识。", "kind": "note"},
    )
    assert response.status_code == 201, response.text
    return response.json()["item"]


def test_auto_retrieval_off_uses_only_explicit_resource(client, auth):
    item = make_knowledge(client, auth, "V4.2 显式知识 " + uuid.uuid4().hex[:6])
    events = chat(client, auth, auto_retrieval=False, knowledge_ids=[item["id"]])
    steps = [event["step"] for event in events if event.get("type") == "step"]
    assert any(step.get("tool") == "read_knowledge" for step in steps)
    assert not any(step.get("tool") in {"search_knowledge", "retrieve_chunks"} for step in steps)
    done = next(event for event in events if event.get("type") == "done")
    assert any(citation.get("resource_id") == item["id"] for citation in done["citations"])


def test_auto_retrieval_off_without_resource_does_not_search(client, auth):
    events = chat(client, auth, auto_retrieval=False)
    steps = [event["step"] for event in events if event.get("type") == "step"]
    assert not any(step.get("tool") in {"search_knowledge", "retrieve_chunks", "search_images", "list_artifacts"} for step in steps)
    done = next(event for event in events if event.get("type") == "done")
    assert done["citations"] == []
    assert any(event.get("type") == "notice" for event in events)


def test_explicit_excluded_resource_is_not_used(client, auth):
    item = make_knowledge(client, auth, "V4.2 被排除知识 " + uuid.uuid4().hex[:6])
    events = chat(client, auth, auto_retrieval=False, knowledge_ids=[item["id"]], exclude_ids=[item["id"]])
    steps = [event["step"] for event in events if event.get("type") == "step"]
    assert not any(step.get("tool") == "read_knowledge" for step in steps)
    done = next(event for event in events if event.get("type") == "done")
    assert all(citation.get("resource_id") != item["id"] for citation in done.get("citations", []))