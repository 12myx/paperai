"""P9 processing queue inspection and retry."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import ProcessingJob, User
from ..serializers import processing_job_out
from ..services.queue import processing_queue

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
) -> dict:
    rows = processing_queue.list(user, limit=limit)
    return {"items": [processing_job_out(job) for job in rows], "stats": processing_queue.stats()}


@router.get("/stats")
def job_stats(user: User = Depends(get_current_user)) -> dict:
    return processing_queue.stats()


@router.get("/{job_id}")
def get_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.get(ProcessingJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    return {"job": processing_job_out(job)}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.get(ProcessingJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在或无权访问")
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有失败/取消的任务可以重试")
    updated = await processing_queue.retry(job)
    return {"job": processing_job_out(updated)}