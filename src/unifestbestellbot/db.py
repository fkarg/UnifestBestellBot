"""SQLite engine + session factory. No migrations: `init_db()` calls
`create_all` at startup. Between events the DB file is deleted."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from .settings import get_settings


@event.listens_for(Engine, "connect")
def _enable_sqlite_pragmas(dbapi_conn, _):
    try:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    except Exception:
        # Non-SQLite drivers will not understand these PRAGMAs; skip silently.
        pass


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs: dict = {"connect_args": connect_args, "echo": False}
    if url in ("sqlite://", "sqlite:///:memory:"):
        # Single shared in-memory DB so all sessions see the same data
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def init_db() -> None:
    """Create all tables. Idempotent. Called once at startup."""
    # Import models so SQLModel.metadata knows about them.
    from . import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _ensure_ticket_columns(engine)


def _ensure_ticket_columns(engine: Engine) -> None:
    """Add columns introduced after the initial schema to a pre-existing DB.

    create_all() only creates missing *tables*; it never alters an existing
    one. The DB is normally wiped between events (so create_all builds the
    current schema fresh), but a mid-event deploy reuses the live file, where
    the new column would be missing and every ticket query would fail. This
    additive, idempotent ADD COLUMN covers that case. SQLite only."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(ticket)")}
        if "who_wip_chat_id" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE ticket ADD COLUMN who_wip_chat_id INTEGER"
            )


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s
