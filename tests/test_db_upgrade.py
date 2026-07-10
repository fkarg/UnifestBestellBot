"""Mid-event upgrade: a `bot.db` file created by an older release is carried
across a `git pull` + restart. `test_db_migration.py` pins that `_ensure_columns`
adds the missing columns; this file goes one step further and pins that the
current SQLModel ORM — which selects and inserts *every* current column — works
against that upgraded legacy file with real legacy rows in it. That end-to-end
"does the app actually function after the upgrade" is the real deploy risk; a
`PRAGMA table_info` check alone wouldn't catch an ORM/data mismatch.

The legacy schema here predates every entry in `db._ADDED_COLUMNS`: the ticket
has no `who_wip_chat_id`, the registration none of the mute/display columns."""

import sqlite3

from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.db import _ensure_columns, checkpoint_and_close
from unifestbestellbot.models import TicketStatus

_LEGACY_SCHEMA = """
CREATE TABLE registration (
    chat_id INTEGER NOT NULL PRIMARY KEY,
    group_name VARCHAR NOT NULL,
    username VARCHAR,
    first_name VARCHAR,
    last_name VARCHAR,
    registered_at DATETIME NOT NULL
);
CREATE TABLE ticket (
    id INTEGER NOT NULL PRIMARY KEY,
    status VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    text VARCHAR NOT NULL,
    group_requesting VARCHAR NOT NULL,
    group_tasked VARCHAR NOT NULL,
    who_wip VARCHAR,
    created_at DATETIME NOT NULL,
    closed_at DATETIME
);
CREATE TABLE auditevent (
    id INTEGER NOT NULL PRIMARY KEY,
    ts DATETIME NOT NULL,
    kind VARCHAR NOT NULL,
    ticket_id INTEGER,
    actor_chat_id INTEGER,
    payload_json VARCHAR
);
"""

_T = "2026-07-09 10:00:00.000000"  # a format SQLAlchemy's SQLite DateTime parses

_LEGACY_ROWS = [
    # A stand and the orga that will have closed a ticket.
    f"INSERT INTO registration VALUES (5, 'Cocktailbar 1', 'coco', 'Coco', NULL, '{_T}')",
    f"INSERT INTO registration VALUES (1, 'Finanz', 'fin', 'Fin', NULL, '{_T}')",
    # open, wip (with a who_wip string but — legacy — no who_wip_chat_id column),
    # and a closed ticket plus its close audit event.
    # Status is stored by enum *name* (OPEN/WIP/CLOSED), matching what the ORM
    # writes — a real legacy bot.db holds these, not the lowercase values.
    f"INSERT INTO ticket VALUES (1, 'OPEN', 'Geld', 'legacy open', 'Cocktailbar 1', 'Finanz', NULL, '{_T}', NULL)",
    f"INSERT INTO ticket VALUES (2, 'WIP', 'Geld', 'legacy wip', 'Cocktailbar 1', 'Finanz', 'Alice', '{_T}', NULL)",
    f"INSERT INTO ticket VALUES (3, 'CLOSED', 'Geld', 'legacy closed', 'Cocktailbar 1', 'Finanz', 'Bob', '{_T}', '{_T}')",
    f"INSERT INTO auditevent VALUES (1, '{_T}', 'close', 3, 1, NULL)",
]


def _legacy_db(path) -> str:
    url = f"sqlite:///{path}"
    engine = create_engine(url)
    with engine.begin() as conn:
        for stmt in _LEGACY_SCHEMA.strip().split(";"):
            if stmt.strip():
                conn.exec_driver_sql(stmt)
        for row in _LEGACY_ROWS:
            conn.exec_driver_sql(row)
    engine.dispose()
    return url


def _upgrade(url: str):
    """What init_db() does to an existing file: create_all is a no-op for tables
    that already exist, then _ensure_columns adds the post-initial columns."""
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)
    return engine


def test_added_columns_present_after_upgrade(tmp_path):
    engine = _upgrade(_legacy_db(tmp_path / "bot.db"))
    with engine.begin() as conn:
        tcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(ticket)")}
        rcols = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(registration)")}
    assert "who_wip_chat_id" in tcols
    assert {"mute_peer_until", "display_override", "mute_opened", "mute_wip", "mute_closed"} <= rcols


def test_orm_reads_legacy_rows_after_upgrade(tmp_path):
    engine = _upgrade(_legacy_db(tmp_path / "bot.db"))
    with Session(engine) as s:
        # Registration loads; the new columns take their defaults on legacy rows.
        reg = repo.registration_for(s, 1)
        assert reg is not None and reg.group_name == "Finanz"
        assert reg.display_override is None
        assert reg.mute_peer_until is None
        assert reg.is_peer_kind_muted("opened") is False

        # active_tickets = open + wip (not closed); who_wip_chat_id is NULL on the
        # legacy wip row and must read back as None, not raise.
        active = repo.active_tickets(s)
        assert {t.id for t in active} == {1, 2}
        wip = next(t for t in active if t.id == 2)
        assert wip.who_wip == "Alice"
        assert wip.who_wip_chat_id is None
        assert wip.status == TicketStatus.WIP

        # The closed ticket surfaces through the audit-joined close log with the
        # closer resolved from their (legacy) registration.
        [summary] = repo.recent_closes(s)
        assert summary.ticket.text == "legacy closed"
        assert "Fin" in summary.closer_display


def test_writes_work_against_upgraded_legacy_db(tmp_path):
    engine = _upgrade(_legacy_db(tmp_path / "bot.db"))
    with Session(engine) as s:
        # A brand-new ticket writes every current column, including who_wip_chat_id.
        fresh = repo.create_ticket(
            s,
            category="Bier",
            text="post-upgrade",
            group_requesting="Cocktailbar 1",
            group_tasked="Finanz",
            actor_chat_id=5,
        )
        assert fresh.id is not None
        assert fresh.who_wip_chat_id is None

        # Claiming the legacy OPEN ticket populates the new who_wip_chat_id column
        # on a row that predates it — the exact path a mid-event deploy exercises.
        claimed = repo.set_wip(s, 1, who="Fin", actor_chat_id=1)
        assert claimed.status == TicketStatus.WIP
        assert claimed.who_wip_chat_id == 1

        closed = repo.close_ticket(s, 1, actor_chat_id=1)
        assert closed.status == TicketStatus.CLOSED
        assert closed.closed_at is not None


def test_checkpoint_and_close_merges_wal_into_database_file(tmp_path):
    path = tmp_path / "bot.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("CREATE TABLE saved_value (value TEXT NOT NULL)")
        conn.exec_driver_sql("INSERT INTO saved_value VALUES ('persisted')")

    assert path.with_name("bot.db-wal").exists()

    checkpoint_and_close(engine)

    assert not path.with_name("bot.db-wal").exists()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM saved_value").fetchall() == [("persisted",)]


def test_sqlite_connections_use_a_single_file_journal(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bot.db'}")
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "delete"
    finally:
        engine.dispose()
