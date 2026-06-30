import asyncio
import contextlib
import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import orga as orga_flow
from unifestbestellbot.events import EventBus
from unifestbestellbot.models import Registration, TicketStatus

from .fakes import fake_callback, fake_message


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


@pytest.fixture
def events():
    return EventBus()


@pytest.fixture(autouse=True)
def orga_user(s):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))


def _ticket(s, **overrides):
    defaults = dict(
        category="Geld",
        text="Wechselgeld Münzen",
        group_requesting="Cocktailbar",
        group_tasked="Finanz",
        actor_chat_id=5,
    )
    defaults.update(overrides)
    return repo.create_ticket(s, **defaults)


# --- /tickets, /all -------------------------------------------------------


async def test_tickets_empty_for_orga_group(s, config):
    msg = fake_message(user_id=1)
    await orga_flow.cmd_tickets(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "keine offenen Tickets" in body


async def test_tickets_lists_own_group_only(s, config):
    _ticket(s, group_tasked="Finanz", text="finanz one")
    _ticket(s, group_tasked="BiMi", text="bimi one")
    msg = fake_message(user_id=1)
    await orga_flow.cmd_tickets(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "finanz one" in body
    assert "bimi one" not in body


async def test_all_groups_orga_groups_in_output(s, config):
    _ticket(s, group_tasked="Finanz", text="finanz one")
    _ticket(s, group_tasked="BiMi", text="bimi one")
    msg = fake_message(user_id=1)
    await orga_flow.cmd_all(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "[Finanz]" in body
    assert "[BiMi]" in body
    assert "finanz one" in body
    assert "bimi one" in body


async def test_all_when_empty(s, config):
    msg = fake_message(user_id=1)
    await orga_flow.cmd_all(msg, db_session=s, config=config)
    assert "keine offenen Tickets" in msg.answer.call_args.args[0]


# --- /wip ----------------------------------------------------------------


async def test_wip_with_id_marks_ticket_wip(s, config):
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/wip {t.id}")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).status == TicketStatus.WIP


async def test_wip_without_id_shows_picker_with_open_tickets(s, config):
    t = _ticket(s)
    msg = fake_message(user_id=1, text="/wip")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=EventBus())
    kb = msg.answer.call_args.kwargs["reply_markup"]
    labels = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"wip:{t.id}" in labels
    assert "wip:_cancel" in labels


async def test_wip_picker_empty_when_no_open(s, config):
    t = _ticket(s)
    repo.set_wip(s, t.id, who="x", actor_chat_id=1)
    msg = fake_message(user_id=1, text="/wip")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "Keine offenen Tickets" in body


async def test_wip_callback_transitions(s, config):
    t = _ticket(s)
    cb = fake_callback(user_id=1, data=f"wip:{t.id}")
    await orga_flow.on_wip_choice(cb, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).status == TicketStatus.WIP
    cb.message.edit_text.assert_awaited()
    cb.answer.assert_awaited_once()


async def test_wip_callback_cancel_does_nothing(s, config):
    t = _ticket(s)
    cb = fake_callback(user_id=1, data="wip:_cancel")
    await orga_flow.on_wip_choice(cb, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).status == TicketStatus.OPEN
    cb.answer.assert_awaited_once()


async def test_wip_rejects_already_wip(s, config):
    t = _ticket(s)
    repo.set_wip(s, t.id, who="someone", actor_chat_id=99)
    msg = fake_message(user_id=1, text=f"/wip {t.id}")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "arbeitet bereits" in body


async def test_wip_missing_ticket(s, config):
    msg = fake_message(user_id=1, text="/wip 999")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "geschlossen oder existiert noch nicht" in body


# --- /close --------------------------------------------------------------


async def test_close_with_id_closes(s, config):
    t = _ticket(s)
    repo.set_wip(s, t.id, who="x", actor_chat_id=1)
    msg = fake_message(user_id=1, text=f"/close {t.id}")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).status == TicketStatus.CLOSED


async def test_close_can_skip_wip(s, config):
    """Closing an OPEN ticket directly is allowed (legacy behaviour)."""
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/close {t.id}")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).status == TicketStatus.CLOSED


async def test_close_picker_only_lists_wip(s, config):
    open_t = _ticket(s, text="still open")
    wip_t = _ticket(s, text="being worked on")
    repo.set_wip(s, wip_t.id, who="x", actor_chat_id=1)
    msg = fake_message(user_id=1, text="/close")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=EventBus())
    kb = msg.answer.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"close:{wip_t.id}" in callbacks
    assert f"close:{open_t.id}" not in callbacks


async def test_close_callback_closes(s, config):
    t = _ticket(s)
    repo.set_wip(s, t.id, who="x", actor_chat_id=1)
    cb = fake_callback(user_id=1, data=f"close:{t.id}")
    await orga_flow.on_close_choice(cb, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).status == TicketStatus.CLOSED


async def test_close_picker_defaults_to_own_wip_with_show_all(s, config):
    mine = _ticket(s, text="mine")
    theirs = _ticket(s, text="theirs")
    repo.set_wip(s, mine.id, who="me", actor_chat_id=1)
    repo.set_wip(s, theirs.id, who="bob", actor_chat_id=2)
    msg = fake_message(user_id=1, text="/close")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=EventBus())
    kb = msg.answer.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"close:{mine.id}" in callbacks
    assert f"close:{theirs.id}" not in callbacks  # owned by another orga
    assert "close:_all" in callbacks  # toggle to the full group list


async def test_close_all_callback_shows_full_group_wip(s, config):
    mine = _ticket(s, text="mine")
    theirs = _ticket(s, text="theirs")
    repo.set_wip(s, mine.id, who="me", actor_chat_id=1)
    repo.set_wip(s, theirs.id, who="bob", actor_chat_id=2)
    cb = fake_callback(user_id=1, data="close:_all")
    await orga_flow.on_close_choice(cb, db_session=s, config=config, events=EventBus())
    kb = cb.message.edit_text.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"close:{mine.id}" in callbacks
    assert f"close:{theirs.id}" in callbacks  # now the whole group is shown
    assert "close:_all" not in callbacks  # no further toggle on the full view


async def test_close_picker_falls_back_to_group_when_no_own(s, config):
    theirs = _ticket(s, text="theirs")
    repo.set_wip(s, theirs.id, who="bob", actor_chat_id=2)
    msg = fake_message(user_id=1, text="/close")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "Keine eigenen" in body
    kb = msg.answer.call_args.kwargs["reply_markup"]
    callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert f"close:{theirs.id}" in callbacks
    assert "close:_all" not in callbacks  # already the full list


async def test_close_picker_empty_when_no_wip_at_all(s, config):
    _ticket(s, text="still open")  # OPEN, not WIP
    msg = fake_message(user_id=1, text="/close")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=EventBus())
    assert "Keine WIP Tickets" in msg.answer.call_args.args[0]


async def test_set_wip_records_chat_id(s, config):
    t = _ticket(s)
    repo.set_wip(s, t.id, who="me", actor_chat_id=42)
    assert repo.get_ticket(s, t.id).who_wip_chat_id == 42


# --- /move ---------------------------------------------------------------


async def test_move_changes_group_tasked(s, config):
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/move {t.id} BiMi")
    await orga_flow.cmd_move(msg, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).group_tasked == "BiMi"


async def test_move_rejects_wip_tickets(s, config):
    t = _ticket(s)
    repo.set_wip(s, t.id, who="x", actor_chat_id=1)
    msg = fake_message(user_id=1, text=f"/move {t.id} BiMi")
    await orga_flow.cmd_move(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "bereits bearbeitet" in body
    assert repo.get_ticket(s, t.id).group_tasked == "Finanz"


async def test_move_rejects_unknown_group(s, config):
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/move {t.id} NoSuchGroup")
    await orga_flow.cmd_move(msg, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, t.id).group_tasked == "Finanz"  # unchanged


async def test_move_missing_args(s, config):
    msg = fake_message(user_id=1, text="/move")
    await orga_flow.cmd_move(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "Benutzung" in body


# --- /message ------------------------------------------------------------


async def test_message_forwards_to_requesting_group(s, config):
    repo.upsert_registration(s, Registration(chat_id=2, group_name="Cocktailbar"))
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/message {t.id} Hallo welt")
    await orga_flow.cmd_message(msg, db_session=s, config=config)
    msg.bot.send_message.assert_any_await(
        chat_id=2,
        text="🟣 Nachricht von Finanz: Hallo welt",
        reply_markup=None,
    )


async def test_message_records_audit_event(s, config):
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/message {t.id} Heads up")
    await orga_flow.cmd_message(msg, db_session=s, config=config)
    # The audit event is checked end-to-end in test_repo.py; here just confirm reply.
    assert "Nachricht verschickt" in msg.answer.call_args.args[0]


async def test_message_missing_args(s, config):
    msg = fake_message(user_id=1, text="/message")
    await orga_flow.cmd_message(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Benutzung" in body


# --- /bug, /feature, /help2 ----------------------------------------------


async def test_bug_forwards_to_developer(s, config):
    msg = fake_message(user_id=1, text="/bug things are broken")
    await orga_flow.cmd_bug(msg, db_session=s, config=config)
    # bot.send_message is called for the developer
    msg.bot.send_message.assert_awaited()
    assert "weitergeleitet" in msg.answer.call_args.args[0]


async def test_bug_without_args_shows_usage(s, config):
    msg = fake_message(user_id=1, text="/bug")
    await orga_flow.cmd_bug(msg, db_session=s, config=config)
    assert "Benutzung" in msg.answer.call_args.args[0]


async def test_feature_forwards_to_developer(s, config):
    msg = fake_message(user_id=1, text="/feature a better dashboard")
    await orga_flow.cmd_feature(msg, db_session=s, config=config)
    msg.bot.send_message.assert_awaited()


async def test_help2_returns_orga_help(s, config):
    msg = fake_message(user_id=1)
    await orga_flow.cmd_help2(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "/move" in body and "/wip" in body


# --- dashboard publishing (SSE liveness) ---------------------------------
#
# The orga lifecycle commands must publish the updated ticket to the
# EventBus so the live TV dashboard reflects wip/close/move without a
# manual reload. Previously they didn't, and the board went stale.


class _Collector:
    """Subscribes to an EventBus and records every payload it receives."""

    def __init__(self):
        self.received: list[dict] = []
        self._task: asyncio.Task | None = None

    @classmethod
    async def start(cls, bus: EventBus) -> _Collector:
        c = cls()
        sub = bus.subscribe()

        async def consume():
            async for item in sub:
                c.received.append(json.loads(item))

        c._task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)  # let the subscriber register
        return c

    async def stop(self):
        await asyncio.sleep(0.01)  # let queued items drain
        assert self._task is not None
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task


async def test_wip_publishes_updated_ticket(s, config):
    bus = EventBus()
    collector = await _Collector.start(bus)
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/wip {t.id}")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=bus)
    await collector.stop()
    assert any(p["id"] == t.id and p["status"] == "wip" for p in collector.received)


async def test_close_publishes_updated_ticket(s, config):
    bus = EventBus()
    collector = await _Collector.start(bus)
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/close {t.id}")
    await orga_flow.cmd_close(msg, db_session=s, config=config, events=bus)
    await collector.stop()
    assert any(p["id"] == t.id and p["status"] == "closed" for p in collector.received)


async def test_move_publishes_updated_ticket(s, config):
    bus = EventBus()
    collector = await _Collector.start(bus)
    t = _ticket(s)
    msg = fake_message(user_id=1, text=f"/move {t.id} BiMi")
    await orga_flow.cmd_move(msg, db_session=s, config=config, events=bus)
    await collector.stop()
    assert any(
        p["id"] == t.id and p["group_tasked"] == "BiMi" for p in collector.received
    )


async def test_wip_lost_race_tells_user_already_taken(s, config, monkeypatch):
    """If the ticket is claimed by another orga between the handler's read
    and the atomic set_wip (which then raises ValueError), the user is told
    it's already taken rather than the error surfacing unhandled."""
    t = _ticket(s)

    def _raise(*a, **k):
        raise ValueError("lost the race")

    monkeypatch.setattr(orga_flow.repo, "set_wip", _raise)
    msg = fake_message(user_id=1, text=f"/wip {t.id}")
    await orga_flow.cmd_wip(msg, db_session=s, config=config, events=EventBus())
    assert "arbeitet bereits" in msg.answer.call_args.args[0]


# --- /helpers ------------------------------------------------------------


async def test_helpers_calls_shift_lookup_with_user_group(s, config):
    calls = []

    async def lookup(group, cfg):
        calls.append(group)
        return "Schichtinfo"

    msg = fake_message(user_id=1, text="/helpers")
    await orga_flow.cmd_helpers(msg, db_session=s, config=config, shift_lookup=lookup)
    assert calls == ["Finanz"]
    assert "Schichtinfo" in msg.answer.call_args.args[0]


async def test_helpers_with_arg_overrides_group(s, config):
    calls = []

    async def lookup(group, cfg):
        calls.append(group)
        return ""

    msg = fake_message(user_id=1, text="/helpers Cocktailbar")
    await orga_flow.cmd_helpers(msg, db_session=s, config=config, shift_lookup=lookup)
    assert calls == ["Cocktailbar"]
