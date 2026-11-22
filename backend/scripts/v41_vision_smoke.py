
"""V4.1 real vision smoke test; skipped unless a real provider is authorized."""
from __future__ import annotations
import json, os, sys
import httpx

BASE = os.environ.get("PAPERLENS_API_BASE", "http://127.0.0.1:8000/api")

def main() -> int:
    if os.environ.get("PAPERLENS_REAL_VISION_AUTHORIZED") != "1":
        print("SKIPPED: real vision calls are not authorized. Set PAPERLENS_REAL_VISION_AUTHORIZED=1.")
        return 2
    email, password = os.environ.get("QA_EMAIL"), os.environ.get("QA_PASSWORD")
    if not email or not password:
        print("SKIPPED: QA_EMAIL / QA_PASSWORD required.")
        return 2
    with httpx.Client(timeout=180) as client:
        login = client.post(BASE + "/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            print("FAIL login", login.status_code); return 1
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        figures = client.get(BASE + "/figures", headers=headers).json().get("items", [])
        if not figures:
            print("FAIL: no figures to test."); return 1
        events = []
        with client.stream("POST", BASE + "/chat/stream", headers=headers, json={
            "message": "分析图像库中的 Figure 1，并结合论文说明实验结果。",
            "mode": "quick", "scope_type": "all", "image_ids": [figures[0]["id"]],
        }) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    try: events.append(json.loads(line[6:]))
                    except json.JSONDecodeError: pass
        steps = [event["step"] for event in events if event.get("type") == "step"]
        analyze = [step for step in steps if step.get("tool") == "analyze_image" and step.get("status") == "done"]
        if not analyze:
            print("FAIL: analyze_image did not run."); return 1
        summary = analyze[0].get("summary", "")
        if "无法完成真正的视觉分析" in summary or "Mock vision" in summary:
            print("FAIL: no real vision provider result; this is not a real vision test."); return 1
        print("PASS real-vision provider call")
        print(summary[:300])
        return 0

if __name__ == "__main__":
    raise SystemExit(main())
