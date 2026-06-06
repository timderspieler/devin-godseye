"""Database engine and session management."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger("godseye.database")


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # Required so the engine can be shared across the poller thread/loop.
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _migrate_add_columns() -> None:
    """Add columns introduced after initial schema (no Alembic needed)."""
    insp = inspect(engine)
    if "sessions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("sessions")}
        if "pr_state" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN pr_state VARCHAR(32)")
                )
            logger.info("Migrated: added pr_state column to sessions table")


def init_db() -> None:
    """Create all tables. Import models so they register with the metadata."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for use outside of request handlers (e.g. the poller)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
