import asyncio
import contextlib
import json
from importlib.metadata import version

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import __version__, repo
from unifestbestellbot.bot import admin as admin_flow
from unifestbestellbot.events import EventBus
from unifestbestellbot.models import Registration, TicketStatus

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


def _ticket(s, **overrides):
    defaults = dict(
        category="Geld",
        text="x",
        group_requesting="Innenhof Cocktail",
        group_tasked="Finanz",
        actor_chat_id=5,
    )
    defaults.update(overrides)
    return repo.create_ticket(s, **defaults)


# The developer chat id is 100 (set in conftest.py).


def test_package_version_comes_from_installed_metadata():
    assert __version__ == version("unifestbestellbot")


async def test_version_reports_installed_package_version():
    msg = fake_message(user_id=100, text="/version")
    await admin_flow.cmd_version(msg)
    msg.answer.assert_awaited_once_with(f"Version: {__version__}")


async def test_closeall_closes_all_open_and_wip_tickets(s, config):
    open_t = _ticket(s, text="still open")
    wip_t = _ticket(s, text="in progress")
    repo.set_wip(s, wip_t.id, who="alice", actor_chat_id=5)
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config, events=EventBus())
    assert repo.get_ticket(s, open_t.id).status == TicketStatus.CLOSED
    assert repo.get_ticket(s, wip_t.id).status == TicketStatus.CLOSED


async def test_closeall_reports_count_to_caller(s, config):
    _ticket(s)
    _ticket(s)
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "2" in body


async def test_closeall_empty_state_reports_zero(s, config):
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config, events=EventBus())
    body = msg.answer.call_args.args[0]
    assert "0" in body


async def test_closeall_fans_out_to_requesting_and_tasked_groups(s, config):
    # A stall member that should get the CLOSED notification for their ticket.
    repo.upsert_registration(
        s, Registration(chat_id=5, group_name="Innenhof Cocktail")
    )
    # An orga peer that should get the peer notification.
    repo.upsert_registration(s, Registration(chat_id=7, group_name="Finanz"))
    t = _ticket(s)

    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config, events=EventBus())

    # Both the requesting stand member and the tasked orga peer got a DM.
    recipients = [
        call.kwargs["chat_id"]
        for call in msg.bot.send_message.await_args_list
        if "chat_id" in call.kwargs
    ]
    assert 5 in recipients
    assert 7 in recipients
    # The channel also got a CLOSED line referencing the ticket id.
    texts = [call.kwargs.get("text", "") for call in msg.bot.send_message.await_args_list]
    assert any(f"#{t.id}" in t_ and "CLOSED" in t_ for t_ in texts)


async def test_closeall_publishes_each_close_to_dashboard(s, config):
    """The dashboard must see every /closeall close, not just go stale."""
    t1 = _ticket(s, text="one")
    t2 = _ticket(s, text="two")
    bus = EventBus()
    received: list[dict] = []
    sub = bus.subscribe()

    async def consume():
        async for item in sub:
            received.append(json.loads(item))

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)

    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config, events=bus)
    await asyncio.sleep(0.01)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    closed_ids = {p["id"] for p in received if p["status"] == "closed"}
    assert {t1.id, t2.id} <= closed_ids


async def test_closeall_attributes_closes_to_developer_group(s, config):
    repo.upsert_registration(s, Registration(chat_id=7, group_name="Finanz"))
    _ticket(s)
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config, events=EventBus())
    # The channel log line carries the developer group attribution.
    texts = [call.kwargs.get("text", "") for call in msg.bot.send_message.await_args_list]
    assert any("Entwickler" in t for t in texts)


# --- /system --------------------------------------------------------------


def _system_output(msg) -> str:
    """Everything /system sent back to the caller, across chunked messages."""
    return "\n".join(call.args[0] for call in msg.answer.call_args_list)


async def test_system_lists_registrations_with_ids_names_and_display(s, config):
    repo.upsert_registration(
        s,
        Registration(
            chat_id=5,
            group_name="Innenhof Cocktail",
            first_name="Max",
            username="maxm",
            display_override="Maxi",
        ),
    )
    msg = fake_message(user_id=100, text="/system")
    await admin_flow.cmd_system(msg, db_session=s, config=config)
    out = _system_output(msg)
    assert "5" in out  # telegram id
    assert "Max" in out  # telegram name
    assert "@maxm" in out  # username
    assert "Maxi" in out  # display override
    assert "Innenhof Cocktail" in out  # group


async def test_system_tags_orga_versus_stand_groups(s, config):
    repo.upsert_registration(s, Registration(chat_id=7, group_name="Finanz"))
    repo.upsert_registration(s, Registration(chat_id=5, group_name="Innenhof Cocktail"))
    msg = fake_message(user_id=100, text="/system")
    await admin_flow.cmd_system(msg, db_session=s, config=config)
    out = _system_output(msg)
    assert "[Orga] Finanz" in out
    assert "[Stand] Innenhof Cocktail" in out


async def test_system_shows_open_tickets(s, config):
    t = _ticket(s, text="needs beer")
    msg = fake_message(user_id=100, text="/system")
    await admin_flow.cmd_system(msg, db_session=s, config=config)
    out = _system_output(msg)
    assert f"#{t.id}" in out
    assert "needs beer" in out


async def test_system_shows_orga_wip_and_closed_work(s, config):
    repo.upsert_registration(s, Registration(chat_id=7, group_name="Finanz"))
    wip_t = _ticket(s, text="claimed one")
    repo.set_wip(s, wip_t.id, who="Jonas", actor_chat_id=7)
    done_t = _ticket(s, text="finished one")
    repo.set_wip(s, done_t.id, who="Jonas", actor_chat_id=7)
    repo.close_ticket(s, done_t.id, actor_chat_id=7)

    msg = fake_message(user_id=100, text="/system")
    await admin_flow.cmd_system(msg, db_session=s, config=config)
    out = _system_output(msg)

    assert "ORGA ACTIVITY" in out
    assert "WIP now:" in out
    assert f"#{wip_t.id}" in out  # current WIP ticket for the orga member
    assert f"#{done_t.id}" in out  # their recently closed ticket


async def test_system_gated_to_developer(s, config):
    # IsDeveloper is a route filter, so it never dispatches to a non-dev. Verify
    # the filter itself rejects a non-developer id.
    from unifestbestellbot.bot.filters import IsDeveloper

    non_dev = fake_message(user_id=999, text="/system")
    assert await IsDeveloper()(non_dev) is False
    dev = fake_message(user_id=100, text="/system")
    assert await IsDeveloper()(dev) is True
