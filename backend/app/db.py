"""Database engine, session factory and declarative base."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register metadata)

    Base.metadata.create_all(bind=engine)
    migrate_v42_figure_columns()
    migrate_v42_artifact_columns()


def migrate_v42_figure_columns() -> None:
    """Add P0 figure classification columns for existing databases.

    This is intentionally an idempotent additive migration; no existing
    figure rows or columns are removed.
    """

    inspector = inspect(engine)
    if "figures" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("figures")}
    sqlite = settings.database_url.startswith("sqlite")
    bool_default = "0" if sqlite else "FALSE"
    additions = {
        "detected_kind": "VARCHAR(24) NOT NULL DEFAULT 'unclassified'",
        "quality_score": "INTEGER NOT NULL DEFAULT 0",
        "caption_confidence": "FLOAT NOT NULL DEFAULT 0",
        "is_page_snapshot": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "ignored": f"BOOLEAN NOT NULL DEFAULT {bool_default}",
        "review_status": "VARCHAR(16) NOT NULL DEFAULT 'auto'",
        "visual_status": "VARCHAR(16) NOT NULL DEFAULT 'unavailable'",
    }
    with engine.begin() as connection:
        for name, ddl in additions.items():
            if name in existing:
                continue
            connection.execute(text(f"ALTER TABLE figures ADD COLUMN {name} {ddl}"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_figures_detected_kind ON figures (detected_kind)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_figures_is_page_snapshot ON figures (is_page_snapshot)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_figures_ignored ON figures (ignored)"))

def migrate_v42_artifact_columns() -> None:
    """Add knowledge-pack persistence columns without rebuilding the table."""

    inspector = inspect(engine)
    if "academic_artifacts" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("academic_artifacts")}
    additions = {
        "knowledge_item_ids": "JSON NOT NULL DEFAULT '[]'",
        "knowledge_saved_at": "TIMESTAMP NULL",
    }
    with engine.begin() as connection:
        for name, ddl in additions.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE academic_artifacts ADD COLUMN {name} {ddl}"))
