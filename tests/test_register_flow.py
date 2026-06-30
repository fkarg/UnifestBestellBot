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


async def test_register_picker_only_shows_visible_groups(s, config):
    msg = fake_message(user_id=1, text="/register")
    await register_flow.cmd_register(msg, db_session=s, config=config)
    kb = msg.answer.call_args.kwargs["reply_markup"]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "Cocktailbar 1" in labels
    assert "Biertheke 1" in labels
    # Orga groups are intentionally absent from the picker — they're
    # reachable only via the textual /register <name> argument.
    assert "Finanz" not in labels
    assert "BiMi" not in labels
    # Hidden groups are also absent.
    assert "Tickets" not in labels
    assert "❌ Abbrechen" in labels


async def test_register_textual_argument_registers_orga_group(s, config):
    msg = fake_message(user_id=1, text="/register Finanz")
    await register_flow.cmd_register(msg, db_session=s, config=config)
    saved = repo.registration_for(s, 1)
    assert saved is not None
    assert saved.group_name == "Finanz"


async def test_register_textual_argument_registers_hidden_group(s, config):
    msg = fake_message(user_id=1, text="/register Tickets")
    await register_flow.cmd_register(msg, db_session=s, config=config)
    saved = repo.registration_for(s, 1)
    assert saved is not None
    assert saved.group_name == "Tickets"


async def test_register_textual_argument_is_case_insensitive(s, config):
    msg = fake_message(user_id=1, text="/register finanz")
    await register_flow.cmd_register(msg, db_session=s, config=config)
    saved = repo.registration_for(s, 1)
    assert saved is not None
    assert saved.group_name == "Finanz"  # canonical casing preserved


async def test_register_textual_argument_unknown_group_rejected(s, config):
    msg = fake_message(user_id=1, text="/register NoSuchGroup")
    await register_flow.cmd_register(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    body = msg.answer.call_args.args[0]
    assert "Unbekannte" in body


async def test_register_choice_persists_and_announces(s, config):
    cb = fake_callback(user_id=1, data="reg:Cocktailbar 1")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    saved = repo.registration_for(s, 1)
    assert saved is not None
    assert saved.group_name == "Cocktailbar 1"
    cb.message.edit_text.assert_awaited_once()
    edit_text = cb.message.edit_text.call_args.args[0]
    assert "Cocktailbar 1" in edit_text and "erfolgreich" in edit_text
    # Follow-up DM updates the reply keyboard to the registered user's menu.
    dm = next(
        c for c in cb.bot.send_message.await_args_list
        if c.kwargs.get("text") == "Tastatur aktualisiert."
    )
    assert dm.kwargs["chat_id"] == 1
    buttons = [
        b.text for row in dm.kwargs["reply_markup"].keyboard for b in row
    ]
    assert "/request" in buttons  # the stall-user MAIN keyboard
    cb.answer.assert_awaited_once()


async def test_register_choice_cancel_does_not_persist(s, config):
    cb = fake_callback(user_id=1, data="reg:_cancel")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    cb.message.edit_text.assert_awaited_once()
    cb.answer.assert_awaited_once()


async def test_register_callback_rejects_orga_group(s, config):
    """Defence in depth: even a hand-crafted callback can't put a user
    in an orga group via the picker callback path."""
    cb = fake_callback(user_id=1, data="reg:Finanz")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    cb.answer.assert_awaited_once_with("Unbekannte Gruppe.", show_alert=True)


async def test_register_callback_rejects_hidden_group(s, config):
    cb = fake_callback(user_id=1, data="reg:Tickets")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    cb.answer.assert_awaited_once_with("Unbekannte Gruppe.", show_alert=True)


async def test_register_choice_unknown_group_alerts_user(s, config):
    cb = fake_callback(user_id=1, data="reg:HackerGroup")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1) is None
    cb.answer.assert_awaited_once_with("Unbekannte Gruppe.", show_alert=True)


async def test_register_overwrites_previous_group(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Biertheke 1"))
    cb = fake_callback(user_id=1, data="reg:Cocktailbar 1")
    await register_flow.on_register_choice(cb, db_session=s, config=config)
    assert repo.registration_for(s, 1).group_name == "Cocktailbar 1"


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


# --- /name -----------------------------------------------------------------


async def test_name_requires_registration(s, config):
    msg = fake_message(user_id=1, text="/name Felix")
    await register_flow.cmd_name(msg, db_session=s, config=config)
    assert "registriere" in msg.answer.call_args.args[0].lower()
    assert repo.registration_for(s, 1) is None


async def test_name_sets_display_override(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    msg = fake_message(user_id=1, text="/name Felix von der Bar")
    await register_flow.cmd_name(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1).display_override == "Felix von der Bar"
    assert "Felix von der Bar" in msg.answer.call_args.args[0]


async def test_name_without_arg_shows_current(s, config):
    repo.upsert_registration(
        s, Registration(chat_id=1, group_name="Cocktailbar", display_override="Bar-Chef")
    )
    msg = fake_message(user_id=1, text="/name")
    await register_flow.cmd_name(msg, db_session=s, config=config)
    assert "Bar-Chef" in msg.answer.call_args.args[0]


async def test_name_dash_clears_override(s, config):
    repo.upsert_registration(
        s, Registration(chat_id=1, group_name="Cocktailbar", display_override="Bar-Chef")
    )
    msg = fake_message(user_id=1, text="/name -")
    await register_flow.cmd_name(msg, db_session=s, config=config)
    assert repo.registration_for(s, 1).display_override is None


async def test_name_is_length_capped(s, config):
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))
    msg = fake_message(user_id=1, text="/name " + "x" * 200)
    await register_flow.cmd_name(msg, db_session=s, config=config)
    assert len(repo.registration_for(s, 1).display_override) == register_flow.MAX_DISPLAY_NAME
