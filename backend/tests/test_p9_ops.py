"""P9 tests: queue, rate limit, incremental cache, backup and ops metrics."""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
import tempfile
import time
from pathlib import Path

from app.rate_limit import SlidingWindowLimiter, limiter
from app.services import rag
from app.services.backup import create_backup, inspect_backup, restore_backup


def test_queue_processes_reprocess_and_reports(client, auth, paper):
    response = client.post("/api/papers/" + paper["id"] + "/reprocess", headers=auth["headers"])
    assert response.status_code == 200, response.text
    deadline = time.time() + 25
    job = None
    while time.time() < deadline:
        payload = client.get("/api/jobs?limit=20", headers=auth["headers"]).json()
        job = next((item for item in payload["items"] if item["paper_id"] == paper["id"]), None)
        if job and job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.3)
    assert job is not None, "queue job exists"
    assert job["status"] == "completed", job
    assert job["progress"] == 100
    assert payload["stats"]["workers"] >= 1
    detail = client.get("/api/jobs/" + job["id"], headers=auth["headers"])
    assert detail.status_code == 200


def test_retry_exhausted_job_reprocesses(client, auth, paper):
    from app.db import SessionLocal
    from app.models import ProcessingJob
    from app.models import User

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == auth["user"]["email"]).one()
        job = ProcessingJob(
            user_id=user.id,
            paper_id=paper["id"],
            status="failed",
            stage="失败",
            progress=0,
            attempts=3,
            max_attempts=3,
            error="forced failure",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    retried = client.post("/api/jobs/" + job_id + "/retry", headers=auth["headers"])
    assert retried.status_code == 200, retried.text
    deadline = time.time() + 25
    job = None
    while time.time() < deadline:
        job = client.get("/api/jobs/" + job_id, headers=auth["headers"]).json()["job"]
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.3)
    assert job is not None
    assert job["status"] == "completed", job
    assert job["attempts"] >= 1


def test_rate_limit_returns_429(client, auth):
    limiter.reset(limit=2)
    try:
        first = client.get("/api/settings", headers=auth["headers"])
        second = client.get("/api/settings", headers=auth["headers"])
        third = client.get("/api/settings", headers=auth["headers"])
        assert first.status_code == 200 and second.status_code == 200
        assert third.status_code == 429, third.text
        assert third.headers.get("Retry-After")
        assert "请求过于频繁" in third.text
    finally:
        limiter.reset(limit=600)


def test_incremental_cache_stats(client, auth, paper, paper_b):
    rag.invalidate(auth["user"]["id"])
    from app.db import SessionLocal
    with SessionLocal() as db:
        rag.search(db, auth["user"]["id"], "retrieval", None, top_k=5)
        first = rag.cache_stats()
        rag.invalidate_paper(auth["user"]["id"], paper["id"])
        rag.search(db, auth["user"]["id"], "retrieval", None, top_k=5)
        second = rag.cache_stats()
    assert second["index_builds"] > first["index_builds"]
    assert second["document_hits"] > first["document_hits"]
    assert second["document_entries"] >= 2


def test_ops_metrics(client, auth):
    response = client.get("/api/ops/metrics", headers=auth["headers"])
    assert response.status_code == 200
    body = response.json()
    assert "queue" in body and "rag" in body and "rate_limit" in body
    assert body["database"]["dialect"] == "sqlite"


def test_backup_create_inspect_restore(tmp_path):
    db = tmp_path / "source.db"
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "paper.txt").write_text("evidence", encoding="utf-8")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO items VALUES ('a', 'before')")
    conn.commit()
    conn.close()

    archive = tmp_path / "backup.zip"
    manifest = create_backup(db, storage, archive)
    assert archive.exists()
    assert manifest["database_sha256"]
    inspected = inspect_backup(archive)
    assert inspected["format"] == "paperlens-backup/v1"
    assert inspected["storage_files"] == 1

    restored_db = tmp_path / "restored" / "paperlens.db"
    restored_storage = tmp_path / "restored" / "storage"
    result = restore_backup(archive, restored_db, restored_storage, confirm=True)
    assert result["ok"] is True
    restored = sqlite3.connect(restored_db)
    assert restored.execute("SELECT value FROM items WHERE id='a'").fetchone()[0] == "before"
    restored.close()
    assert (restored_storage / "paper.txt").read_text(encoding="utf-8") == "evidence"

def test_rate_limiter_concurrency():
    guard = SlidingWindowLimiter(limit=10, window_seconds=60)
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: guard.hit("same-key")[0], range(50)))
    assert sum(1 for allowed in results if allowed) == 10