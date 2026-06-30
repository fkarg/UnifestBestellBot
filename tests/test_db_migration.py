"""Schema-evolution safety: a DB carried across a mid-event deploy is missing
columns added after its creation. create_all() never alters existing tables, so
init_db() must additively ADD COLUMN. These tests pin that behaviour."""

from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine
from unifestbestellbot.db import _ensure_ticket_columns


def _legacy_engine():
    """An engine whose `ticket` table predates the who_wip_chat_id column."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ticket (id INTEGER PRIMARY KEY, status TEXT, "
            "category TEXT, text TEXT, group_requesting TEXT, group_tasked TEXT, "
            "who_wip TEXT, created_at TIMESTAMP, closed_at TIMESTAMP)"
        )
    return engine


def _columns(engine):
    with engine.begin() as conn:
        return {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(ticket)")}


def test_ensure_columns_adds_missing_who_wip_chat_id():
    engine = _legacy_engine()
    assert "who_wip_chat_id" not in _columns(engine)
    _ensure_ticket_columns(engine)
    assert "who_wip_chat_id" in _columns(engine)


def test_ensure_columns_is_idempotent():
    engine = _legacy_engine()
    _ensure_ticket_columns(engine)
    # Running again on an already-migrated DB must not raise (duplicate column).
    _ensure_ticket_columns(engine)
    assert "who_wip_chat_id" in _columns(engine)
