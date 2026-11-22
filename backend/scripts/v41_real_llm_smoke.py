
"""V4.1 real-model smoke test.

This script never runs unless the operator explicitly authorizes a paid call.
It does not print API keys. If no model is configured it fails loudly rather
than reporting a fake pass.

Usage:
  PAPERLENS_REAL_LLM_AUTHORIZED=1 QA_EMAIL=... QA_PASSWORD=... \
    python backend/scripts/v41_real_llm_smoke.py
"""
from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ.get("PAPERLENS_API_BASE", "http://127.0.0.1:8000/api")


def main() -> int:
    if os.environ.get("PAPERLENS_REAL_LLM_AUTHORIZED") != "1":
        print("SKIPPED: paid real-model calls are not authorized. Set PAPERLENS_REAL_LLM_AUTHORIZED=1.")
        return 2
    email = os.environ.get("QA_EMAIL")
    password = os.environ.get("QA_PASSWORD")
    if not email or not password:
        print("SKIPPED: QA_EMAIL / QA_PASSWORD are required.")
        return 2
    with httpx.Client(timeout=180) as client:
        login = client.post(BASE + "/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            print("FAIL login", login.status_code)
            return 1
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        events: list[dict] = []
        with client.stream(
            "POST", BASE + "/chat/stream", headers=headers,
            json={
                "message": "结合知识库和论文，说明检索增强生成的关键证据，并使用 [C#] 引用。",
                "mode": "quick", "scope_type": "all",
            },
        ) as response:
            if response.status_code != 200:
                print("FAIL stream", response.status_code)
                return 1
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                try:
                    events.append(json.loads(line[6:]))
                except json.JSONDecodeError:
                    continue
        start = next((event for event in events if event.get("type") == "start"), {})
        if start.get("provider") != "deepseek":
            print("FAIL: provider is not deepseek; configure a real model first.")
            return 1
        steps = [event["step"] for event in events if event.get("type") == "step"]
        done = next((event for event in events if event.get("type") == "done"), {})
        if not steps:
            print("FAIL: no real tool step was executed.")
            return 1
        if not done.get("citations"):
            print("FAIL: no citations returned.")
            return 1
        print("PASS real-model loop")
        print("provider:", start.get("provider"))
        print("tools:", [step.get("tool") for step in steps])
        print("citations:", len(done.get("citations") or []))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
