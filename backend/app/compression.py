"""Compress static assets only; never buffer SSE streams."""
from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


class StaticGZipMiddleware(GZipMiddleware):
    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        super().__init__(app, minimum_size=minimum_size)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/assets/") or path in {"/favicon.svg"}:
                await super().__call__(scope, receive, send)
                return
        await self.app(scope, receive, send)
