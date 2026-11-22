"""Pluggable vision provider.

The shipped default is intentionally unavailable: PaperLens only supports a
text model today. A provider must accept real image bytes; passing a caption or
file path to a text model is not vision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Protocol

from ..config import settings


@dataclass
class VisionResult:
    analysis: str
    provider: str
    model: str
    elapsed_ms: int
    raw: dict = field(default_factory=dict)


class VisionProvider(Protocol):
    name: str
    available: bool

    def analyze(
        self, image_bytes: bytes, media_type: str, *, question: str,
        caption: str | None = None, paper_title: str | None = None,
    ) -> VisionResult: ...


class UnavailableVisionProvider:
    name = "none"
    available = False

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def analyze(self, image_bytes: bytes, media_type: str, **kwargs) -> VisionResult:
        raise RuntimeError(self.reason)


class MockVisionProvider:
    """Test-only provider. It never calls an external service."""

    name = "mock"
    available = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def analyze(
        self, image_bytes: bytes, media_type: str, *, question: str,
        caption: str | None = None, paper_title: str | None = None,
    ) -> VisionResult:
        self.calls.append({
            "bytes": len(image_bytes), "media_type": media_type, "question": question,
            "caption": caption, "paper_title": paper_title,
        })
        return VisionResult(
            analysis=f"Mock vision analysis for: {question[:120]}",
            provider="mock", model="mock-vision", elapsed_ms=1,
            raw={"caption": caption, "paper_title": paper_title},
        )


def get_vision_provider(config=None) -> VisionProvider:
    """Return a real provider only when explicitly configured.

    No paid provider is enabled by default. The mock provider is test-only and
    is never selected automatically in production.
    """
    provider = (getattr(settings, "vision_provider", "none") or "none").lower()
    if provider in {"none", "disabled", ""}:
        return UnavailableVisionProvider(
            "当前未配置视觉模型；只能读取真实图片文件和图注，不能进行像素级理解。"
        )
    # Deliberately no implicit network provider. A future adapter can be added
    # here after credentials and cost authorization are supplied.
    return UnavailableVisionProvider(f"未实现的 Vision Provider：{provider}")
