import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import admin as admin_flow
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


async def test_closeall_closes_all_open_and_wip_tickets(s, config):
    open_t = _ticket(s, text="still open")
    wip_t = _ticket(s, text="in progress")
    repo.set_wip(s, wip_t.id, who="alice", actor_chat_id=5)
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config)
    assert repo.get_ticket(s, open_t.id).status == TicketStatus.CLOSED
    assert repo.get_ticket(s, wip_t.id).status == TicketStatus.CLOSED


async def test_closeall_reports_count_to_caller(s, config):
    _ticket(s)
    _ticket(s)
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "2" in body


async def test_closeall_empty_state_reports_zero(s, config):
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config)
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
    await admin_flow.cmd_closeall(msg, db_session=s, config=config)

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


async def test_closeall_attributes_closes_to_developer_group(s, config):
    repo.upsert_registration(s, Registration(chat_id=7, group_name="Finanz"))
    _ticket(s)
    msg = fake_message(user_id=100, text="/closeall")
    await admin_flow.cmd_closeall(msg, db_session=s, config=config)
    # The channel log line carries the developer group attribution.
    texts = [call.kwargs.get("text", "") for call in msg.bot.send_message.await_args_list]
    assert any("Entwickler" in t for t in texts)
