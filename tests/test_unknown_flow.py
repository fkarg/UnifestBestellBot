import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import unknown as unknown_flow
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


async def test_unknown_command_replies_with_hint(s, config):
    msg = fake_message(user_id=1, text="/blah")
    await unknown_flow.cmd_unknown(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "nicht erkannt" in body
    assert "/help" in body


async def test_unknown_uses_initial_keyboard_for_unregistered_user(s, config):
    msg = fake_message(user_id=1, text="hi")
    await unknown_flow.cmd_unknown(msg, db_session=s, config=config)
    kb = msg.answer.call_args.kwargs["reply_markup"]
    flat = [b.text for row in kb.keyboard for b in row]
    assert "/register" in flat
    assert "/request" not in flat


async def test_unknown_uses_main_keyboard_for_registered_user(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Innenhof Cocktail"))
    msg = fake_message(user_id=1, text="hi")
    await unknown_flow.cmd_unknown(msg, db_session=s, config=config)
    kb = msg.answer.call_args.kwargs["reply_markup"]
    flat = [b.text for row in kb.keyboard for b in row]
    assert "/request" in flat


async def test_unknown_silently_ignores_messages_without_from_user(s, config):
    msg = fake_message(user_id=1, text="x")
    msg.from_user = None
    await unknown_flow.cmd_unknown(msg, db_session=s, config=config)
    msg.answer.assert_not_awaited()
