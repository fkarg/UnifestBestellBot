import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from unifestbestellbot import repo
from unifestbestellbot.bot import register as register_flow
from unifestbestellbot.models import Registration

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


# --- /start ----------------------------------------------------------------


async def test_start_sends_greeting_with_initial_keyboard(s, config):
    msg = fake_message(user_id=1)
    await register_flow.cmd_start(msg, db_session=s, config=config)
    msg.answer.assert_awaited_once()
    text, kwargs = msg.answer.call_args.args[0], msg.answer.call_args.kwargs
    assert "UnifestBestellBot" in text
    # Unregistered user gets the initial (register-only) keyboard.
    kb = kwargs["reply_markup"]
    flat = [b.text for row in kb.keyboard for b in row]
    assert "/register" in flat
    assert "/request" not in flat


async def test_start_for_registered_user_shows_main_keyboard(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    msg = fake_message(user_id=1)
    await register_flow.cmd_start(msg, db_session=s, config=config)
    kb = msg.answer.call_args.kwargs["reply_markup"]
    flat = [b.text for row in kb.keyboard for b in row]
    assert "/request" in flat


async def test_start_for_orga_user_shows_orga_keyboard(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    msg = fake_message(user_id=1)
    await register_flow.cmd_start(msg, db_session=s, config=config)
    kb = msg.answer.call_args.kwargs["reply_markup"]
    flat = [b.text for row in kb.keyboard for b in row]
    assert "/wip" in flat
    assert "/help2" in flat


# --- /help -----------------------------------------------------------------


async def test_help_returns_user_help_when_not_orga(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    msg = fake_message(user_id=1)
    await register_flow.cmd_help(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "/request" in body
    assert "/move" not in body  # orga-only commands not shown


async def test_help_returns_orga_help_for_orga_member(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
    msg = fake_message(user_id=1)
    await register_flow.cmd_help(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "/move" in body
    assert "/wip" in body


# --- /register -------------------------------------------------------------


async def test_register_shows_inline_keyboard_with_visible_groups(s, config):
    msg = fake_message(user_id=1)
    await register_flow.cmd_register(msg, config=config)
    kb = msg.answer.call_args.kwargs["reply_markup"]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "Cocktailbar" in labels
    assert "Finanz" in labels  # orga groups also offered
    assert "Tickets" not in labels  # hidden stall excluded
    assert "❌ Abbrechen" in labels


async def test_register_choice_persists_and_announces(s, config):
    cb = fake_callback(user_id=1, data="reg:Cocktailbar")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    saved = repo.registration_for(s, 1)
    assert saved is not None
    assert saved.group_name == "Cocktailbar"
    cb.message.edit_text.assert_awaited_once()
    edit_text = cb.message.edit_text.call_args.args[0]
    assert "Cocktailbar" in edit_text and "erfolgreich" in edit_text
    # Follow-up DM updates the reply keyboard, then the channel log fires.
    cb.bot.send_message.assert_any_await(
        chat_id=1,
        text="Tastatur aktualisiert.",
        reply_markup=cb.bot.send_message.call_args_list[0].kwargs["reply_markup"],
    )
    cb.answer.assert_awaited_once()


async def test_register_choice_cancel_does_not_persist(s, config):
    cb = fake_callback(user_id=1, data="reg:_cancel")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    cb.message.edit_text.assert_awaited_once()
    cb.answer.assert_awaited_once()


async def test_register_choice_unknown_group_alerts_user(s, config):
    cb = fake_callback(user_id=1, data="reg:HackerGroup")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    cb.answer.assert_awaited_once_with("Unbekannte Gruppe.", show_alert=True)


async def test_register_overwrites_previous_group(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Biertheke 1"))
    cb = fake_callback(user_id=1, data="reg:Cocktailbar")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1).group_name == "Cocktailbar"


# --- /unregister ----------------------------------------------------------


async def test_unregister_removes_registration(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    msg = fake_message(user_id=1)
    await register_flow.cmd_unregister(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    body = msg.answer.call_args.args[0]
    assert "Cocktailbar" in body


async def test_unregister_when_not_registered_is_safe(s, config):
    msg = fake_message(user_id=1)
    await register_flow.cmd_unregister(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Nichts zu entfernen" in body


# --- /status ---------------------------------------------------------------


async def test_status_no_registration(s, config):
    msg = fake_message(user_id=1)
    await register_flow.cmd_status(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Keine Gruppenmitgliedschaft" in body


async def test_status_no_tickets(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    msg = fake_message(user_id=1)
    await register_flow.cmd_status(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Cocktailbar" in body
    assert "keine offenen Tickets" in body


async def test_status_lists_open_tickets_for_group(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    repo.create_ticket(
        s,
        category="Geld",
        text="Wechselgeld Münzen",
        group_requesting="Cocktailbar",
        group_tasked="Finanz",
        actor_chat_id=1,
    )
    msg = fake_message(user_id=1)
    await register_flow.cmd_status(msg, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "Wechselgeld Münzen" in body
    assert "1 Ticket" in body
