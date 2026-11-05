"""P9 operational metrics (no secrets)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User
from ..rate_limit import limiter
from ..services import rag
from ..services.queue import processing_queue

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/metrics")
def metrics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    dialect = db.get_bind().dialect.name
    return {
        "queue": processing_queue.stats(),
        "rag": rag.cache_stats(),
        "rate_limit": limiter.stats(),
        "database": {"dialect": dialect, "url_scheme": settings.database_url.split("://")[0]},
        "llm": {"timeout_seconds": settings.llm_timeout_seconds, "configured": bool(settings.deepseek_api_key)},
        "environment": settings.environment,
    }
