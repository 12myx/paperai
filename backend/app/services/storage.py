"""Filesystem storage abstraction with path-traversal protection."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..config import settings

_SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff.\- ]+", re.UNICODE)


def safe_filename(name: str, fallback: str = "document") -> str:
    stem = Path(name or "").stem[:120]
    suffix = Path(name or "").suffix[:12]
    stem = _SAFE_NAME.sub("_", stem).strip(" ._") or fallback
    suffix = _SAFE_NAME.sub("", suffix)
    return f"{stem}{suffix}"


class Storage:
    """Local disk storage. The public API is path-relative so an S3 backend
    can be swapped in later without touching routers."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or settings.storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- paths
    def user_dir(self, user_id: str) -> Path:
        path = self.root / "users" / user_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def paper_dir(self, user_id: str, paper_id: str) -> Path:
        path = self.user_dir(user_id) / "papers" / paper_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def abs_path(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise ValueError("Path escapes the storage root")
        return candidate

    # ---------------------------------------------------------------- write
    def save_pdf(self, user_id: str, paper_id: str, filename: str, data: bytes) -> str:
        directory = self.paper_dir(user_id, paper_id)
        target = directory / "source.pdf"
        target.write_bytes(data)
        return str(target.relative_to(self.root)).replace("\\", "/")

    def save_figure(self, user_id: str, paper_id: str, index: int, data: bytes, ext: str = "png") -> str:
        directory = self.paper_dir(user_id, paper_id) / "figures"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"figure-{index:03d}.{ext}"
        target.write_bytes(data)
        return str(target.relative_to(self.root)).replace("\\", "/")

    def save_export(self, user_id: str, filename: str, data: bytes) -> str:
        directory = self.user_dir(user_id) / "exports"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / safe_filename(filename)
        index = 1
        while target.exists():
            target = directory / f"{safe_filename(filename)[:-len(target.suffix)]}-{index}{target.suffix}"
            index += 1
        target.write_bytes(data)
        return str(target.relative_to(self.root)).replace("\\", "/")

    # ---------------------------------------------------------------- delete
    def delete_relative(self, relative: str) -> None:
        try:
            path = self.abs_path(relative)
        except ValueError:
            return
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass

    def delete_paper(self, user_id: str, paper_id: str) -> None:
        shutil.rmtree(self.paper_dir(user_id, paper_id), ignore_errors=True)

    def delete_user(self, user_id: str) -> None:
        shutil.rmtree(self.user_dir(user_id), ignore_errors=True)


storage = Storage()