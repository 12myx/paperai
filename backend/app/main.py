"""PaperLens AI FastAPI application."""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .compression import StaticGZipMiddleware
from .config import settings
from .db import SessionLocal, init_db
from .rate_limit import key_for, limiter
from .services.actions import expire_actions, reconcile_stale_actions
from .services.agent_tasks import recover_interrupted_tasks
from .services.queue import processing_queue
from .routers import annotations, artifacts, auth, chat, evidence, exports, figures, intelligence, jobs, library, ops, papers, research, research_intel, settings as settings_router

# Windows registries often map .mjs/.js to text/plain, which breaks ES modules.
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("image/svg+xml", ".svg")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("paperlens")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        expire_actions(db)
        reconcile_stale_actions(db)
    recover_interrupted_tasks()
    await processing_queue.start()
    limiter.limit = max(1, settings.rate_limit_per_minute)
    logger.info("PaperLens API ready (env=%s, db=%s)", settings.environment, settings.database_url.split("://")[0])
    yield
    await processing_queue.stop()


app = FastAPI(
    title="PaperLens AI",
    description="AI research companion: grounded reading, multi-paper synthesis and a persistent knowledge base.",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(StaticGZipMiddleware, minimum_size=1024)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_timeout(request: Request, call_next):
    try:
        return await asyncio.wait_for(call_next(request), timeout=max(30, settings.request_timeout_seconds))
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"detail": "请求超时，请缩小范围或稍后重试"})


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    path = request.url.path
    if settings.rate_limit_enabled and path.startswith("/api") and path not in {"/api/health", "/api/openapi.json", "/api/docs"}:
        key = key_for(request.headers.get("authorization"), request.client.host if request.client else None)
        allowed, retry_after, remaining = limiter.hit(key)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after), "X-RateLimit-Remaining": "0"},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    started = time.time()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if settings.is_production:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        response.headers["X-Response-Time"] = f"{(time.time() - started) * 1000:.0f}ms"
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
        "model_provider": settings.deepseek_model if settings.deepseek_api_key else "local",
        "storage": str(settings.storage_dir),
    }


for module in (auth, papers, annotations, figures, chat, research, research_intel, intelligence, artifacts, jobs, ops, library, evidence, exports, settings_router):
    app.include_router(module.router, prefix="/api")

if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        candidate = (FRONTEND_DIST / full_path).resolve()
        if FRONTEND_DIST in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")