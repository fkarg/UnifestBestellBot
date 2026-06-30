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
    _ensure_columns(engine)


# Columns added after the initial schema, per table. create_all() only creates
# missing *tables*, never alters an existing one. The DB is normally wiped
# between events (so create_all builds the current schema fresh), but a
# mid-event deploy reuses the live file, where a new column would be missing
# and queries would fail. These additive ADD COLUMNs cover that case.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "ticket": {"who_wip_chat_id": "INTEGER"},
    "registration": {"display_override": "TEXT"},
}


def _ensure_columns(engine: Engine) -> None:
    """Idempotently add any post-initial-schema columns missing from an
    existing DB. SQLite only; a freshly create_all()'d DB already has them."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {
                row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if not existing:
                continue  # table doesn't exist (e.g. partial test DB); skip
            for column, ddl_type in columns.items():
                if column not in existing:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"
                    )


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s
