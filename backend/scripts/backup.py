"""Backup / restore CLI.

Examples:
  python scripts/backup.py create
  python scripts/backup.py inspect backups/xxx.zip
  python scripts/backup.py restore backups/xxx.zip --yes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.services.backup import create_backup, inspect_backup, restore_backup


def db_path() -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit("backup CLI currently supports SQLite only; use pg_dump for PostgreSQL")
    return Path(url.replace("sqlite:///", "", 1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "inspect", "restore"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("--output")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()
    if args.action == "create":
        result = create_backup(db_path(), settings.storage_dir, args.output)
    elif args.action == "inspect":
        if not args.path:
            raise SystemExit("inspect needs a backup path")
        result = inspect_backup(args.path)
    else:
        if not args.path:
            raise SystemExit("restore needs a backup path")
        result = restore_backup(args.path, db_path(), settings.storage_dir, confirm=args.yes)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
