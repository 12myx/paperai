"""Durable in-process processing queue.

SQLite is a single-writer database; one worker is intentional. Jobs are
persisted in processing_jobs, so a restart can re-enqueue work that was running.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from ..db import SessionLocal
from ..models import Paper, ProcessingJob, User, utcnow
from .processing import process_paper

logger = logging.getLogger("paperlens.queue")


class ProcessingQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] | None = None
        self._workers: list[asyncio.Task] = []
        self._started = False
        self._lock = asyncio.Lock()
        self._active = 0
        self._progress: dict[str, tuple[str, int]] = {}

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            self._queue = asyncio.Queue()
            self._started = True
            self._recover()
            self._workers = [asyncio.create_task(self._worker(index), name=f"paperlens-worker-{index}") for index in range(1)]
            logger.info("Processing queue started (%s worker)", len(self._workers))

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        self._workers = []
        self._started = False
        self._queue = None

    def _recover(self) -> None:
        with SessionLocal() as db:
            jobs = list(
                db.execute(
                    select(ProcessingJob).where(ProcessingJob.status.in_(["queued", "running", "retrying"]))
                ).scalars().all()
            )
            for job in jobs:
                paper = db.get(Paper, job.paper_id)
                if paper is not None and paper.status == "ready":
                    job.status = "completed"
                    job.progress = 100
                    job.stage = "已完成"
                    job.finished_at = utcnow()
                    continue
                job.status = "queued"
                job.stage = "恢复排队"
                job.progress = 0
                self._queue.put_nowait(job.id)  # type: ignore[union-attr]
            db.commit()

    async def enqueue(self, user: User, paper: Paper) -> ProcessingJob:
        await self.start()
        with SessionLocal() as db:
            job = ProcessingJob(
                user_id=user.id,
                paper_id=paper.id,
                status="queued",
                stage="等待处理",
                progress=0,
            )
            db.add(job)
            db.commit()
            db.refresh(job)
        assert self._queue is not None
        self._queue.put_nowait(job.id)
        return job

    async def retry(self, job: ProcessingJob) -> ProcessingJob:
        await self.start()
        with SessionLocal() as db:
            row = db.get(ProcessingJob, job.id)
            if row is not None and row.status in {"failed", "cancelled"}:
                row.status = "queued"
                row.stage = "重新排队"
                row.progress = 0
                row.error = None
                row.finished_at = None
                db.commit()
                self._queue.put_nowait(row.id)  # type: ignore[union-attr]
                return row
        return job

    def _set(self, job_id: str, **values) -> None:
        try:
            with SessionLocal() as db:
                job = db.get(ProcessingJob, job_id)
                if job is None:
                    return
                for key, value in values.items():
                    setattr(job, key, value)
                job.updated_at = utcnow()
                db.commit()
        except OperationalError:
            # SQLite may be writing the paper chunks; progress is best-effort.
            logger.debug("Progress update skipped: database busy")

    async def _flush_progress(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(0.4)
            stage, pct = self._progress.get(job_id, ("处理中", 0))
            self._set(job_id, stage=stage, progress=pct)

    async def _worker(self, index: int) -> None:
        assert self._queue is not None
        while True:
            job_id = await self._queue.get()
            self._active += 1
            try:
                await self._run(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Queue worker failed on job %s", job_id)
                self._set(job_id, status="failed", error="队列执行异常", finished_at=utcnow())
            finally:
                self._active -= 1
                self._queue.task_done()

    async def _run(self, job_id: str) -> None:
        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            if job is None or job.status in {"completed", "cancelled"}:
                return
            paper_id = job.paper_id
            max_attempts = job.max_attempts or 3
            start_attempt = job.attempts or 0

        for attempt in range(start_attempt + 1, max_attempts + 1):
            self._set(
                job_id,
                status="running",
                stage="开始处理",
                progress=0,
                attempts=attempt,
                started_at=job.started_at or utcnow(),
                error=None,
            )
            with SessionLocal() as db:
                paper = db.get(Paper, paper_id)
                if paper is not None:
                    paper.status = "processing"
                    paper.error = None
                    db.commit()

            def progress(stage: str, pct: int, _job_id: str = job_id) -> None:
                self._progress[_job_id] = (stage[:80], pct)

            flusher = asyncio.create_task(self._flush_progress(job_id))
            try:
                await asyncio.to_thread(process_paper, paper_id, progress, True)
                self._progress.pop(job_id, None)
                self._set(
                    job_id,
                    status="completed",
                    stage="已完成",
                    progress=100,
                    error=None,
                    finished_at=utcnow(),
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.exception("Processing attempt %s failed for %s", attempt, paper_id)
                if attempt < max_attempts:
                    self._set(
                        job_id,
                        status="retrying",
                        stage=f"失败重试 {attempt}/{max_attempts}",
                        error=str(exc)[:1200],
                    )
                    await asyncio.sleep(min(8, 2 ** attempt))
                else:
                    self._set(
                        job_id,
                        status="failed",
                        stage="失败",
                        error=str(exc)[:1200],
                        finished_at=utcnow(),
                    )
                    with SessionLocal() as db:
                        paper = db.get(Paper, paper_id)
                        if paper is not None:
                            paper.status = "failed"
                            paper.error = str(exc)[:1500]
                            db.commit()
            finally:
                flusher.cancel()
                self._progress.pop(job_id, None)

    def stats(self) -> dict:
        with SessionLocal() as db:
            rows = db.execute(select(ProcessingJob.status, func.count()).group_by(ProcessingJob.status)).all()
            counts = {status: count for status, count in rows}
        return {
            "queued": counts.get("queued", 0),
            "running": counts.get("running", 0),
            "retrying": counts.get("retrying", 0),
            "completed": counts.get("completed", 0),
            "failed": counts.get("failed", 0),
            "active_workers": self._active,
            "workers": len(self._workers),
        }

    def list(self, user: User, limit: int = 20) -> list[ProcessingJob]:
        with SessionLocal() as db:
            return list(
                db.execute(
                    select(ProcessingJob)
                    .where(ProcessingJob.user_id == user.id)
                    .order_by(ProcessingJob.created_at.desc())
                    .limit(limit)
                ).scalars().all()
            )


processing_queue = ProcessingQueue()