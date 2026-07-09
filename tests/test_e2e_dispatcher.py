"""End-to-end tests that feed real Telegram `Update` objects through the real
dispatcher (`dp.feed_update`). Unlike the per-handler tests, these exercise the
layers between the wire and the handler body: the SessionMiddleware, the
IsOrga/IsDeveloper filters, aiogram's Command parsing, FSM state persistence
across updates, and router precedence (unknown.router must lose to real flows).

Nothing hits the network — `bot.session` is mocked, so every outgoing Telegram
method is captured instead of sent. See the E2E harness in conftest.py."""

from sqlmodel import Session
from unifestbestellbot import i18n, repo
from unifestbestellbot.db import get_engine
from unifestbestellbot.models import TicketStatus


def _session() -> Session:
    """A session on the same global engine the dispatcher's middleware uses."""
    return Session(get_engine())


# --- middleware + persistence --------------------------------------------


async def test_unregistered_status_gets_no_membership(e2e):
    texts = await e2e.send("/status")
    assert texts == [i18n.STATUS_NO_REGISTRATION]


async def test_registration_persists_across_updates(e2e):
    # Two independent updates: the first commits a registration through the
    # middleware's session, the second must see it. Proves the per-update
    # session lifecycle commits and the next update reads its own writes.
    await e2e.send("/register Cocktailbar 1")
    texts = await e2e.send("/status")
    assert any("Cocktailbar 1" in t for t in texts)


# --- permission gating + fallthrough -------------------------------------


async def test_isorga_gates_a_stand_user_into_unknown(e2e):
    # A registered *stand* is not orga; /all must be gated out of the orga
    # router and fall through to unknown.router, not list tickets.
    await e2e.send("/register Cocktailbar 1")
    texts = await e2e.send("/all")
    assert texts == [i18n.UNKNOWN_COMMAND]


async def test_isorga_allows_an_orga_user(e2e):
    await e2e.send("/register Finanz")
    texts = await e2e.send("/all")
    assert texts == [i18n.NO_OPEN_TICKETS_ANYWHERE]


async def test_isdeveloper_gates_non_developer_into_unknown(e2e):
    # /system is developer-only (developer_chat_id == 100 in tests).
    texts = await e2e.send("/system", user_id=1)
    assert texts == [i18n.UNKNOWN_COMMAND]


async def test_isdeveloper_allows_the_developer(e2e):
    sent = await e2e.send("/system", user_id=100)
    # The developer gets the snapshot: at least one message, and it is not the
    # unknown-command fallthrough.
    assert sent
    assert i18n.UNKNOWN_COMMAND not in e2e.texts()


async def test_unknown_command_falls_through(e2e):
    await e2e.send("/register Cocktailbar 1")
    texts = await e2e.send("/zzznotacommand")
    assert texts == [i18n.UNKNOWN_COMMAND]


# --- full FSM happy path through the real dispatcher ----------------------


async def test_request_fsm_then_wip_and_close(e2e):
    # Stand registers and walks the multi-step /request conversation. Each step
    # is a separate update; FSM state must persist across them via MemoryStorage
    # keyed on (chat, user) — something no single-handler test covers.
    await e2e.send("/register Cocktailbar 1", user_id=1)

    intro = await e2e.send("/request", user_id=1)
    assert i18n.REQUEST_INTRO in intro

    ask_money = await e2e.send("Geld", user_id=1)
    assert ask_money  # advanced to the money step

    created = await e2e.send("Geld Abholen", user_id=1)
    assert any("Ticket #" in t for t in created)

    with _session() as s:
        open_tickets = repo.active_tickets(s)
        assert len(open_tickets) == 1
        ticket = open_tickets[0]
        assert ticket.group_requesting == "Cocktailbar 1"
        assert ticket.group_tasked == "Finanz"  # "Geld" routes to Finanz
        assert ticket.status == TicketStatus.OPEN
        tid = ticket.id

    # A Finanz orga claims and closes it — through the real dispatcher, so the
    # IsOrga filter, arg parsing and the atomic WIP claim all run for real.
    await e2e.send("/register Finanz", user_id=2)

    wip = await e2e.send(f"/wip {tid}", user_id=2)
    assert i18n.TICKET_WIP_NOTICE.format(uid=tid) in wip
    with _session() as s:
        assert repo.get_ticket(s, tid).status == TicketStatus.WIP

    closed = await e2e.send(f"/close {tid}", user_id=2)
    assert i18n.TICKET_CLOSED_NOTICE.format(uid=tid) in closed
    with _session() as s:
        assert repo.get_ticket(s, tid).status == TicketStatus.CLOSED


async def test_cancel_clears_fsm_state(e2e):
    await e2e.send("/register Cocktailbar 1", user_id=1)
    await e2e.send("/request", user_id=1)
    await e2e.send("/cancel", user_id=1)
    # After cancel, a bare word is no longer a category answer — it falls
    # through to unknown, proving the FSM state was cleared.
    texts = await e2e.send("Geld", user_id=1)
    assert texts == [i18n.UNKNOWN_COMMAND]


# --- inline picker (callback query) --------------------------------------


async def test_register_via_inline_picker(e2e):
    prompt = await e2e.send("/register", user_id=3)
    assert i18n.REGISTER_PROMPT in prompt

    texts = await e2e.click("reg:Cocktailbar 1", user_id=3)
    assert i18n.REGISTER_SUCCESS.format(group="Cocktailbar 1") in texts
    with _session() as s:
        reg = repo.registration_for(s, 3)
        assert reg is not None and reg.group_name == "Cocktailbar 1"
