"""V4.2 persistent action concurrency tests (SQLite thread-level)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json


def sse_events(response) -> list[dict]:
    out = []
    for line in response.iter_lines():
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        if text.startswith("data: "):
            out.append(json.loads(text[6:]))
    return out


def test_two_way_concurrent_confirm_claims_once(client, auth, paper):
    with client.stream(
        "POST", "/api/chat/stream", headers=auth["headers"],
        json={"message": "把这篇论文的核心结论保存到知识库", "mode": "quick",
              "scope_type": "papers", "scope_ids": [paper["id"]]},
    ) as response:
        events = sse_events(response)
    action = next(event["action"] for event in events if event.get("type") == "action")
    before = len(client.get("/api/knowledge", headers=auth["headers"]).json()["items"])
    payload = {"tool": action["tool"], "args": action["args"], "action_id": action["action_id"]}

    def confirm() -> int:
        return client.post("/api/agent/actions/confirm", headers=auth["headers"], json=payload).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(lambda _: confirm(), range(20)))
    assert codes.count(200) == 1, codes
    assert all(code in {200, 400} for code in codes), codes
    after = len(client.get("/api/knowledge", headers=auth["headers"]).json()["items"])
    assert after == before + 1
    status = client.get(f"/api/agent/actions/{action['action_id']}", headers=auth["headers"])
    assert status.status_code == 200
    assert status.json()["action"]["status"] == "succeeded"


def test_action_status_is_persisted_and_foreign_user_denied(client, auth, paper):
    with client.stream(
        "POST", "/api/chat/stream", headers=auth["headers"],
        json={"message": "把这篇论文的核心结论保存到知识库", "mode": "quick",
              "scope_type": "papers", "scope_ids": [paper["id"]]},
    ) as response:
        events = sse_events(response)
    action = next(event["action"] for event in events if event.get("type") == "action")
    # Status is readable before confirmation and comes from the database row.
    status = client.get(f"/api/agent/actions/{action['action_id']}", headers=auth["headers"])
    assert status.status_code == 200
    assert status.json()["action"]["status"] == "pending"

    other = client.post(
        "/api/auth/register",
        json={"email": "v42-other@example.com", "password": "Research123!", "display_name": "Other"},
    )
    assert other.status_code in {201, 400}
    if other.status_code == 201:
        headers = {"Authorization": "Bearer " + other.json()["access_token"]}
        denied = client.get(f"/api/agent/actions/{action['action_id']}", headers=headers)
        assert denied.status_code == 404
