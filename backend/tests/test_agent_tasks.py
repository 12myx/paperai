"""P6 tests: plan-first, task state machine, execution, self-check, rerun."""
from __future__ import annotations

import json
import uuid

from app.db import SessionLocal
from app.models import AgentTask, User
from app.services.agent_tasks import recover_interrupted_tasks
from app.services.tools import ToolError, ToolRunner


def _events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        line = next((item for item in block.splitlines() if item.startswith("data: ")), None)
        if line:
            events.append(json.loads(line[6:]))
    return events


def _other_user(client) -> dict:
    email = f"p6-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "Research123!", "display_name": "P6"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_plan_preview_and_update(client, auth, paper, paper_b):
    response = client.post(
        "/api/agent/tasks/plan",
        headers=auth["headers"],
        json={"message": "对比这两篇论文的方法与实验条件", "mode": "quick", "scope_type": "all"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task"]["status"] == "queued"
    assert body["task"]["plan_confirmed"] is False
    assert len(body["plan"]) >= 4
    assert body["conversation_id"]
    task_id = body["task"]["id"]

    edited = client.patch(
        "/api/agent/tasks/" + task_id + "/plan",
        headers=auth["headers"],
        json={"plan": [{**step, "title": ("调整：" + step["title"]) if index == 0 else step["title"]} for index, step in enumerate(body["plan"])]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["plan"][0]["title"].startswith("调整：")


def test_execute_task_and_self_check(client, auth, paper, paper_b):
    created = client.post(
        "/api/agent/tasks/plan",
        headers=auth["headers"],
        json={"message": "对比这两篇论文的方法与结论", "mode": "quick", "scope_type": "all"},
    ).json()
    task_id = created["task"]["id"]
    response = client.post("/api/agent/tasks/" + task_id + "/execute", headers=auth["headers"])
    assert response.status_code == 200, response.text
    events = _events(response.text)
    types = [event["type"] for event in events]
    assert "start" in types
    assert "plan" in types
    assert "done" in types
    assert "self_check" in types
    done = next(event for event in events if event["type"] == "done")
    assert done["content"]
    assert done["task_id"] == task_id

    detail = client.get("/api/agent/tasks/" + task_id, headers=auth["headers"]).json()
    assert detail["task"]["status"] == "completed"
    assert detail["task"]["self_check"]["goal_completed"] is True
    assert detail["result_message"]["content"]
    assert detail["task"]["progress"] == 100


def test_pause_resume_cancel_without_stream(client, auth, paper):
    created = client.post(
        "/api/agent/tasks/plan",
        headers=auth["headers"],
        json={"message": "帮我制定一个研究计划", "mode": "deep_read", "scope_type": "all"},
    ).json()
    task_id = created["task"]["id"]
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        task.status = "running"
        db.commit()

    paused = client.post("/api/agent/tasks/" + task_id + "/pause", headers=auth["headers"])
    assert paused.status_code == 200
    assert paused.json()["task"]["status"] == "paused"
    resumed = client.post("/api/agent/tasks/" + task_id + "/resume", headers=auth["headers"])
    assert resumed.status_code == 200
    assert resumed.json()["task"]["status"] == "running"
    cancelled = client.post("/api/agent/tasks/" + task_id + "/cancel", headers=auth["headers"])
    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["status"] == "cancelled"
    detail = client.get("/api/agent/tasks/" + task_id, headers=auth["headers"]).json()
    assert detail["result_message"] is None


def test_task_isolation_and_rerun(client, auth, paper, paper_b):
    created = client.post(
        "/api/agent/tasks/plan",
        headers=auth["headers"],
        json={"message": "对比两篇论文", "mode": "quick", "scope_type": "all"},
    ).json()
    task_id = created["task"]["id"]
    other = _other_user(client)
    assert client.get("/api/agent/tasks/" + task_id, headers=other).status_code == 404

    rerun = client.post("/api/agent/tasks/" + task_id + "/rerun", headers=auth["headers"])
    assert rerun.status_code == 200, rerun.text
    new_task = rerun.json()["task"]
    assert new_task["id"] != task_id
    assert new_task["rerun_of"] == task_id
    assert new_task["status"] == "queued"


def test_task_listing(client, auth, paper, paper_b):
    client.post(
        "/api/agent/tasks/plan",
        headers=auth["headers"],
        json={"message": "对比两篇论文", "mode": "quick", "scope_type": "all"},
    )
    listing = client.get("/api/agent/tasks", headers=auth["headers"])
    assert listing.status_code == 200
    assert listing.json()["items"]
    assert all("plan" in item for item in listing.json()["items"])


def test_interrupted_task_is_marked_failed_on_recovery(client, auth):
    with SessionLocal() as db:
        task = AgentTask(
            user_id=auth["user"]["id"],
            goal="重启恢复测试",
            status="running",
            plan=[],
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id
    recovered = recover_interrupted_tasks()
    assert recovered >= 1
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        assert task is not None
        assert task.status == "failed"
        assert "重启" in (task.error or "")
        db.delete(task)
        db.commit()


def test_tool_runner_rejects_paper_outside_scope(client, auth, paper, paper_b):
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == auth["user"]["email"]).one()
        runner = ToolRunner(db, user, None, scope_ids=[paper["id"]])
        assert runner._paper(paper["id"]).id == paper["id"]
        try:
            runner._paper(paper_b["id"])
        except ToolError as exc:
            assert "范围" in str(exc)
        else:
            raise AssertionError("out-of-scope paper should be rejected")
