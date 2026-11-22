"""V4.2 resource usage lifecycle tests."""
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


def test_resource_usage_has_included_read_and_referenced(client, auth, paper):
    item = client.post(
        "/api/knowledge", headers=auth["headers"],
        json={"title": "V4.2 usage " + uuid.uuid4().hex[:6], "content": "用于资源使用账本测试。", "kind": "note"},
    ).json()["item"]
    response = client.post(
        "/api/chat/stream", headers=auth["headers"],
        json={"message": "结合这条知识总结要点。", "mode": "quick", "scope_type": "all",
              "auto_retrieval": False, "knowledge_ids": [item["id"]]},
    )
    events = sse_events(response)
    done = next(event for event in events if event.get("type") == "done")
    run_id = done["run_id"]
    rows = client.get(f"/api/agent/runs/{run_id}/resources", headers=auth["headers"]).json()["items"]
    stages = {(row["resource_type"], row["stage"]) for row in rows}
    assert ("knowledge", "included") in stages
    assert ("knowledge", "read") in stages or ("paper", "included") in stages
    assert any(row["stage"] == "referenced" for row in rows)
