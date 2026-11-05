"""Small in-process sliding-window rate limiter.

For multi-process deployments this should move to Redis; the interface is kept
small so that swap is straightforward.
"""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, limit: int = 120, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def reset(self, limit: int | None = None) -> None:
        self._hits.clear()
        if limit is not None:
            self.limit = max(1, limit)

    def hit(self, key: str) -> tuple[bool, int, int]:
        now = time.time()
        bucket = self._hits[key]
        while bucket and now - bucket[0] >= self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = max(1, int(self.window - (now - bucket[0])) + 1)
            return False, retry_after, 0
        bucket.append(now)
        return True, 0, max(0, self.limit - len(bucket))

    def stats(self) -> dict:
        now = time.time()
        active = {key: sum(1 for t in bucket if now - t < self.window) for key, bucket in self._hits.items()}
        return {"limit": self.limit, "window_seconds": self.window, "keys": len(active), "active_requests": sum(active.values())}


def key_for(authorization: str | None, client_host: str | None) -> str:
    raw = (authorization or "") + "|" + (client_host or "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


limiter = SlidingWindowLimiter()
