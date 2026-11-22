"""V4.2: conflicts/evolution must work on the async model path."""
from __future__ import annotations

from app.routers import research_intel
from app.services import multipaper
from app.services.llm import ModelConfig


class FakeClient:
    def __init__(self, config):
        self.config = config

    async def complete(self, *args, **kwargs):
        return {"content": '{"conflicts": [], "relations": []}'}


def test_conflicts_and_evolution_with_async_model(monkeypatch, client, auth, paper, paper_b):
    config = ModelConfig(provider="deepseek", base_url="https://example.invalid", api_key="test", model="test-model")
    monkeypatch.setattr(research_intel, "resolve_model_config", lambda db, user: config)
    monkeypatch.setattr(multipaper, "LLMClient", FakeClient)
    ids = [paper["id"], paper_b["id"]]
    conflicts = client.post("/api/research/conflicts", headers=auth["headers"], json={"paper_ids": ids, "force": True})
    evolution = client.post("/api/research/evolution", headers=auth["headers"], json={"paper_ids": ids, "force": True})
    assert conflicts.status_code == 200, conflicts.text
    assert evolution.status_code == 200, evolution.text
    assert conflicts.json()["local"] is False
    assert evolution.json()["local"] is False
