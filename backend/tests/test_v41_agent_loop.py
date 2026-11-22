"""V4.1 mock-provider tests for the real agent tool loop and guarded writes."""
from __future__ import annotations

import json
import uuid

import pytest

from app.config import settings
from app.services import actions, agent, agent_tasks
from app.services.llm import ModelConfig


def sse_events(response) -> list[dict]:
    out = []
    for line in response.iter_lines():
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        if text.startswith("data: "):
            out.append(json.loads(text[6:]))
    return out


def tool_call(name: str, args: dict, call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


class FakeLLM:
    responses: list[dict] = []
    instances: list["FakeLLM"] = []

    def __init__(self, config):
        self.config = config
        self.calls = 0
        self.stream_text = "最终答案：已使用检索到的资料 [C1]。"
        FakeLLM.instances.append(self)

    async def complete(self, messages, tools=None, **overrides):
        self.calls += 1
        index = min(self.calls - 1, len(FakeLLM.responses) - 1)
        response = dict(FakeLLM.responses[index])
        response.setdefault("content", "")
        response.setdefault("tool_calls", [])
        response.setdefault("usage", {"total_tokens": 100})
        return response

    async def stream(self, messages, **overrides):
        for piece in self.stream_text:
            yield piece


@pytest.fixture
def model_mode(monkeypatch):
    config = ModelConfig(provider="mock", base_url="http://mock", api_key="test", model="mock-tool-model")
    monkeypatch.setattr(agent, "resolve_model_config", lambda db, user: config)
    monkeypatch.setattr(agent, "LLMClient", FakeLLM)

    async def fake_plan(*args, **kwargs):
        return [{"id": "s1", "title": "检索并回答", "tool": "search_knowledge", "description": "mock"}], "model"

    monkeypatch.setattr(agent_tasks, "build_plan_with_model", fake_plan)
    FakeLLM.responses = []
    FakeLLM.instances = []
    return config


def chat(client, auth, message: str, **extra):
    response = client.post(
        "/api/chat/stream",
        headers=auth["headers"],
        json={"message": message, "mode": "quick", "scope_type": "all", **extra},
    )
    assert response.status_code == 200, response.text
    return sse_events(response)


def make_knowledge(client, auth, title: str) -> dict:
    response = client.post(
        "/api/knowledge",
        headers=auth["headers"],
        json={"title": title, "content": "这是 V4.1 测试知识：section-aware RAG 需要证据。", "kind": "note"},
    )
    assert response.status_code == 201, response.text
    return response.json()["item"]


def test_mock_model_drives_tool_loop_and_returns_citation(client, auth, model_mode):
    item = make_knowledge(client, auth, "V4.1 工具循环知识 " + uuid.uuid4().hex[:6])
    FakeLLM.responses = [
        {"tool_calls": [tool_call("search_knowledge", {"query": "V4.1 工具循环知识"})]},
        {"content": "根据知识条目，检索增强需要证据 [C1]。"},
    ]
    events = chat(client, auth, "结合我的知识库解释检索增强。")
    steps = [event["step"] for event in events if event.get("type") == "step"]
    assert any(step.get("tool") == "search_knowledge" and step.get("status") == "done" for step in steps)
    done = next(event for event in events if event.get("type") == "done")
    assert any(citation.get("resource_id") == item["id"] for citation in done["citations"])
    assert FakeLLM.instances[0].calls >= 2
    assert "根据知识条目" in "".join(event.get("text", "") for event in events if event.get("type") == "delta")


def test_mock_model_unknown_tool_is_reported_not_executed(client, auth, model_mode):
    FakeLLM.responses = [
        {"tool_calls": [tool_call("delete_everything", {"user_id": "other"})]},
        {"content": "未知工具已被拒绝。"},
    ]
    events = chat(client, auth, "尝试调用不存在的工具。")
    steps = [event["step"] for event in events if event.get("type") == "step"]
    assert any(step.get("tool") == "delete_everything" and step.get("status") == "error" for step in steps)
    assert any(event.get("type") == "done" for event in events)


def test_mock_model_write_is_pending_and_requires_bound_confirmation(client, auth, model_mode, monkeypatch):
    before = len(client.get("/api/knowledge", headers=auth["headers"]).json()["items"])
    FakeLLM.responses = [
        {"tool_calls": [tool_call("save_knowledge", {"title": "V4.1 待确认", "content": "写入内容"})]},
        {"content": "已生成待确认操作。"},
    ]
    events = chat(client, auth, "把结论保存到知识库。")
    action = next(event["action"] for event in events if event.get("type") == "action")
    assert action["tool"] == "save_knowledge"
    assert action.get("action_id")
    assert action.get("args_digest")
    after = len(client.get("/api/knowledge", headers=auth["headers"]).json()["items"])
    assert after == before

    tampered = dict(action["args"])
    tampered["content"] = "被篡改的内容"
    bad = client.post(
        "/api/agent/actions/confirm", headers=auth["headers"],
        json={"tool": action["tool"], "args": tampered, "action_id": action["action_id"]},
    )
    assert bad.status_code == 400

    good = client.post(
        "/api/agent/actions/confirm", headers=auth["headers"],
        json={"tool": action["tool"], "args": action["args"], "action_id": action["action_id"]},
    )
    assert good.status_code == 200, good.text
    replay = client.post(
        "/api/agent/actions/confirm", headers=auth["headers"],
        json={"tool": action["tool"], "args": action["args"], "action_id": action["action_id"]},
    )
    assert replay.status_code == 400
    assert len(client.get("/api/knowledge", headers=auth["headers"]).json()["items"]) == before + 1


def test_mock_model_tool_budget_and_duplicate_protection(client, auth, model_mode, monkeypatch):
    monkeypatch.setattr(settings, "agent_max_tool_calls", 1)
    FakeLLM.responses = [
        {"tool_calls": [tool_call("search_knowledge", {"query": "预算"})]},
        {"tool_calls": [tool_call("search_knowledge", {"query": "预算"})]},
    ]
    events = chat(client, auth, "测试工具预算。")
    steps = [event["step"] for event in events if event.get("type") == "step"]
    assert len([step for step in steps if step.get("status") == "done"]) <= 1
    assert any(event.get("type") == "notice" for event in events)
    assert any(event.get("type") == "done" for event in events)


def test_mock_model_write_tool_without_confirm_cannot_bypass_guard(client, auth, model_mode):
    FakeLLM.responses = [
        {"tool_calls": [tool_call("export_document", {"title": "x", "content": "x", "format": "md"})]},
        {"content": "导出需要确认。"},
    ]
    from app.services.tools import ToolRunner
    from app.services.llm import resolve_model_config

    # The mock loop must surface an action, not silently write an export record.
    before = client.get("/api/exports", headers=auth["headers"]).json().get("total", 0)
    events = chat(client, auth, "把结果导出。")
    assert any(event.get("type") == "action" and event["action"]["tool"] == "export_document" for event in events)
    after = client.get("/api/exports", headers=auth["headers"]).json().get("total", 0)
    assert after == before