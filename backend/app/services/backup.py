"""SQLite + storage backup/restore for P9 drills.

This is intentionally a CLI/ops utility, not a public API: restoring replaces
the live database and storage, so it requires an explicit --yes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_backup(
    db_path: str | Path,
    storage_dir: str | Path,
    output: str | Path | None = None,
) -> dict:
    db_path = Path(db_path)
    storage_dir = Path(storage_dir)
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    output = Path(output) if output else Path("backups") / f"paperlens-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        temp_db = Path(tmp) / "paperlens.db"
        source = sqlite3.connect(str(db_path))
        target = sqlite3.connect(str(temp_db))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        manifest = {
            "format": "paperlens-backup/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_bytes": temp_db.stat().st_size,
            "database_sha256": _sha256(temp_db),
            "storage_files": sum(1 for path in storage_dir.rglob("*") if path.is_file()) if storage_dir.exists() else 0,
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(temp_db, "paperlens.db")
            if storage_dir.exists():
                for path in storage_dir.rglob("*"):
                    if path.is_file():
                        archive.write(path, "storage/" + str(path.relative_to(storage_dir)))
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    manifest["path"] = str(output)
    manifest["bytes"] = output.stat().st_size
    return manifest


def inspect_backup(path: str | Path) -> dict:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if "manifest.json" not in names:
            raise ValueError("backup has no manifest.json")
        manifest = json.loads(archive.read("manifest.json"))
        if "paperlens.db" not in names:
            raise ValueError("backup has no paperlens.db")
    return {**manifest, "path": str(path), "bytes": path.stat().st_size, "entries": len(names)}


def restore_backup(
    path: str | Path,
    db_path: str | Path,
    storage_dir: str | Path,
    *,
    confirm: bool = False,
) -> dict:
    if not confirm:
        raise ValueError("restore requires confirm=True")
    path = Path(path)
    manifest = inspect_backup(path)
    db_path = Path(db_path)
    storage_dir = Path(storage_dir)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    pre_db = db_path.with_suffix(db_path.suffix + f".pre-restore-{stamp}")
    pre_storage = storage_dir.parent / f"{storage_dir.name}.pre-restore-{stamp}"
    if db_path.exists():
        shutil.copy2(db_path, pre_db)
    if storage_dir.exists():
        shutil.copytree(storage_dir, pre_storage, dirs_exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        extract = Path(tmp)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(extract)
        restored_db = extract / "paperlens.db"
        if _sha256(restored_db) != manifest.get("database_sha256"):
            raise ValueError("database checksum mismatch")
        shutil.copy2(restored_db, db_path)
        restored_storage = extract / "storage"
        if storage_dir.exists():
            shutil.rmtree(storage_dir)
        if restored_storage.exists():
            shutil.copytree(restored_storage, storage_dir, dirs_exist_ok=True)
        else:
            storage_dir.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "restored": str(db_path),
        "pre_restore_db": str(pre_db),
        "pre_restore_storage": str(pre_storage),
        "manifest": manifest,
    }
