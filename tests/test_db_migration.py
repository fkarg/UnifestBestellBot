"""Schema-evolution safety: a DB carried across a mid-event deploy is missing
columns added after its creation. create_all() never alters existing tables, so
init_db() must additively ADD COLUMN. These tests pin that behaviour."""

from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine
from unifestbestellbot.db import _ensure_columns


def _legacy_engine(create_sql: str):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(create_sql)
    return engine


def _columns(engine, table: str):
    with engine.begin() as conn:
        return {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}


_LEGACY_TICKET = (
    "CREATE TABLE ticket (id INTEGER PRIMARY KEY, status TEXT, category TEXT, "
    "text TEXT, group_requesting TEXT, group_tasked TEXT, who_wip TEXT, "
    "created_at TIMESTAMP, closed_at TIMESTAMP)"
)
_LEGACY_REGISTRATION = (
    "CREATE TABLE registration (chat_id INTEGER PRIMARY KEY, group_name TEXT, "
    "username TEXT, first_name TEXT, last_name TEXT, registered_at TIMESTAMP, "
    "mute_peer_until TIMESTAMP)"
)


def test_ensure_columns_adds_missing_ticket_column():
    engine = _legacy_engine(_LEGACY_TICKET)
    assert "who_wip_chat_id" not in _columns(engine, "ticket")
    _ensure_columns(engine)
    assert "who_wip_chat_id" in _columns(engine, "ticket")


def test_ensure_columns_adds_missing_registration_column():
    engine = _legacy_engine(_LEGACY_REGISTRATION)
    assert "display_override" not in _columns(engine, "registration")
    _ensure_columns(engine)
    assert "display_override" in _columns(engine, "registration")


def test_ensure_columns_is_idempotent():
    engine = _legacy_engine(_LEGACY_TICKET)
    _ensure_columns(engine)
    # Running again on an already-migrated DB must not raise (duplicate column).
    _ensure_columns(engine)
    assert "who_wip_chat_id" in _columns(engine, "ticket")


def test_ensure_columns_skips_absent_table():
    # Only `ticket` exists; the registration entry in _ADDED_COLUMNS must be
    # skipped rather than raising "no such table".
    engine = _legacy_engine(_LEGACY_TICKET)
    _ensure_columns(engine)  # must not raise
    assert "who_wip_chat_id" in _columns(engine, "ticket")
