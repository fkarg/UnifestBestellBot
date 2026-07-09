import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import i18n, repo
from unifestbestellbot.bot import orga as orga_flow
from unifestbestellbot.models import Registration

from .fakes import fake_message


@pytest.fixture
def s():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def orga_user(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))


def _open_and_close(s, *, group_tasked: str = "Finanz", text: str = "x",
                    closer_chat_id: int = 1) -> int:
    t = repo.create_ticket(
        s,
        category="Geld",
        text=text,
        group_requesting="Cocktailbar 1",
        group_tasked=group_tasked,
        actor_chat_id=5,
    )
    repo.close_ticket(s, t.id, actor_chat_id=closer_chat_id)
    return t.id


# --- repo.recent_closes ---------------------------------------------------


def test_recent_closes_empty(s):
    assert repo.recent_closes(s) == []


def test_recent_closes_returns_most_recent_first(s):
    _open_and_close(s, text="first")
    _open_and_close(s, text="second")
    _open_and_close(s, text="third")
    summaries = repo.recent_closes(s)
    assert [c.ticket.text for c in summaries] == ["third", "second", "first"]


def test_recent_closes_filters_by_group_tasked(s):
    _open_and_close(s, group_tasked="Finanz", text="finanz one")
    _open_and_close(s, group_tasked="BiMi", text="bimi one")
    finanz_only = repo.recent_closes(s, group_tasked="Finanz")
    assert [c.ticket.text for c in finanz_only] == ["finanz one"]


def test_recent_closes_honours_limit(s):
    for i in range(5):
        _open_and_close(s, text=f"t{i}")
    summaries = repo.recent_closes(s, limit=2)
    assert len(summaries) == 2


def test_recent_closes_resolves_registered_closer_to_display_name(s):
    repo.upsert_registration(
        s,
        Registration(
            chat_id=42,
            group_name="Finanz",
            username="alice",
            first_name="Alice",
        ),
    )
    _open_and_close(s, closer_chat_id=42)
    [summary] = repo.recent_closes(s)
    assert "Alice" in summary.closer_display
    assert "alice" in summary.closer_display


def test_recent_closes_falls_back_to_chat_id_for_unregistered_closer(s):
    _open_and_close(s, closer_chat_id=9999)
    [summary] = repo.recent_closes(s)
    assert "9999" in summary.closer_display


# --- /history command ----------------------------------------------------


async def test_history_default_shows_recent_closes(s, config):
    _open_and_close(s, text="bezahlt", closer_chat_id=1)
    msg = fake_message(user_id=1, text="/history")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "bezahlt" in body
    assert "Finanz" in body  # the header names the orga group


async def test_history_with_explicit_n(s, config):
    for i in range(5):
        _open_and_close(s, text=f"t{i}")
    msg = fake_message(user_id=1, text="/history 2")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    # Only the two newest tickets should appear.
    assert "t4" in body and "t3" in body
    assert "t0" not in body and "t1" not in body and "t2" not in body


async def test_history_empty_state(s, config):
    msg = fake_message(user_id=1, text="/history")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Keine geschlossenen" in body


async def test_history_rejects_zero(s, config):
    _open_and_close(s)
    msg = fake_message(user_id=1, text="/history 0")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Benutzung" in body


async def test_history_rejects_above_maximum(s, config):
    msg = fake_message(user_id=1, text="/history 9999")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Benutzung" in body


async def test_history_rejects_non_numeric(s, config):
    msg = fake_message(user_id=1, text="/history abc")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Benutzung" in body


async def test_history_includes_closer_attribution(s, config):
    repo.upsert_registration(
        s, Registration(chat_id=42, group_name="Finanz", first_name="Alice")
    )
    _open_and_close(s, closer_chat_id=42, text="for-display")
    msg = fake_message(user_id=1, text="/history")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Alice" in body
    assert "for-display" in body


async def test_history_scopes_to_callers_orga_group(s, config):
    _open_and_close(s, group_tasked="Finanz", text="finanz one")
    _open_and_close(s, group_tasked="BiMi", text="bimi one")
    msg = fake_message(user_id=1, text="/history")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "finanz one" in body
    assert "bimi one" not in body


# --- /history <group> (inspect a stand's request history) ----------------


def _requested(s, *, group: str, text: str, close: bool = False) -> int:
    t = repo.create_ticket(
        s,
        category="Geld",
        text=text,
        group_requesting=group,
        group_tasked="Finanz",
        actor_chat_id=5,
    )
    if close:
        repo.close_ticket(s, t.id, actor_chat_id=1)
    return t.id


async def test_history_group_shows_all_statuses_for_that_group(s, config):
    _requested(s, group="Cocktailbar 1", text="still open")
    _requested(s, group="Cocktailbar 1", text="already done", close=True)
    # A different group's ticket must not leak in.
    _requested(s, group="Biertheke 1", text="other group")

    msg = fake_message(user_id=1, text="/history Cocktailbar 1")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Letzte Tickets von [Cocktailbar 1]" in body
    assert "still open" in body  # open ticket included
    assert "already done" in body  # closed ticket included
    assert "other group" not in body


async def test_history_group_honours_trailing_limit(s, config):
    _requested(s, group="Cocktailbar 1", text="oldest")
    _requested(s, group="Cocktailbar 1", text="newest")
    msg = fake_message(user_id=1, text="/history Cocktailbar 1 1")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "newest" in body  # newest first, limited to 1
    assert "oldest" not in body


async def test_history_group_empty_state(s, config):
    msg = fake_message(user_id=1, text="/history Cocktailbar 1")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Keine Tickets von [Cocktailbar 1]" in body


async def test_history_unknown_group_shows_usage(s, config):
    msg = fake_message(user_id=1, text="/history Nonexistent Stand")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert body == i18n.HISTORY_USAGE


async def test_history_group_rejects_out_of_range_limit(s, config):
    _requested(s, group="Cocktailbar 1", text="x")
    msg = fake_message(user_id=1, text="/history Cocktailbar 1 9999")
    await orga_flow.cmd_history(msg, db_session=s, config=config)
    assert msg.answer.call_args.args[0] == i18n.HISTORY_USAGE
