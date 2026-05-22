
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import request as request_flow
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


@pytest.fixture
def state():
    storage = MemoryStorage()
    return FSMContext(storage=storage, key=StorageKey(bot_id=0, chat_id=1, user_id=1))


@pytest.fixture
def events():
    return EventBus()


@pytest.fixture
def shift_lookup():
    async def lookup(group: str, config) -> str:
        return f"Schichten für {group}"

    return lookup


@pytest.fixture(autouse=True)
def registered_user(s):
    """Most request-flow tests assume the user is already registered at a stall."""
    repo.upsert_registration(s, Registration(chat_id=1, group_name="Cocktailbar"))


# --- Entry / cancel -------------------------------------------------------


async def test_cmd_request_without_registration_prompts_to_register(
    s, state, config
):
    repo.unregister(s, 1)
    msg = fake_message(user_id=1)
    await request_flow.cmd_request(msg, state, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "/register" in body
    assert await state.get_state() is None


async def test_cmd_request_starts_at_category(s, state, config):
    msg = fake_message(user_id=1)
    await request_flow.cmd_request(msg, state, db_session=s, config=config)
    assert await state.get_state() == request_flow.RequestFSM.category.state
    data = await state.get_data()
    assert data["group"] == "Cocktailbar"


async def test_cmd_request_already_in_progress(s, state, config):
    await state.set_state(request_flow.RequestFSM.category)
    msg = fake_message(user_id=1)
    await request_flow.cmd_request(msg, state, db_session=s, config=config)
    body = msg.answer.call_args.args[0]
    assert "noch nicht abgeschlossen" in body


async def test_cancel_clears_state(s, state, config):
    await state.set_state(request_flow.RequestFSM.money)
    msg = fake_message(user_id=1)
    await request_flow.cmd_cancel(msg, state, db_session=s, config=config)
    assert await state.get_state() is None


# --- Category -------------------------------------------------------------


async def test_pick_category_unknown_re_prompts(state):
    await state.set_state(request_flow.RequestFSM.category)
    msg = fake_message(user_id=1, text="garbage")
    await request_flow.category_unrecognized(msg)
    body = msg.answer.call_args.args[0]
    assert "Option" in body or "cancel" in body


# --- End-to-end per category ----------------------------------------------


async def _start(state, group: str = "Cocktailbar 1"):
    await state.set_state(request_flow.RequestFSM.category)
    await state.update_data(group=group)


async def test_geld_wechselgeld_muenzen_routes_to_finanz(s, state, config, events, shift_lookup):
    await _start(state)
    # Geld → money state
    msg1 = fake_message(user_id=1, text="Geld")
    await request_flow.pick_category(msg1, state)
    assert await state.get_state() == request_flow.RequestFSM.money.state

    # Wechselgeld → money_change state
    msg2 = fake_message(user_id=1, text="Wechselgeld")
    await request_flow.money_change_branch(msg2, state)
    assert await state.get_state() == request_flow.RequestFSM.money_change.state

    # Münzen → finalize, routes to Finanz
    msg3 = fake_message(user_id=1, text="Münzen")
    await request_flow.money_change_pick(
        msg3, state, db_session=s, config=config, events=events
    )
    tickets = repo.active_tickets(s, group_tasked="Finanz")
    assert len(tickets) == 1
    assert "Münzen" in tickets[0].text
    # BiMi-style display: location and type in brackets, no team identity.
    assert "Innenhof [Cocktail]" in tickets[0].text
    assert await state.get_state() is None


async def test_geld_abholen_routes_to_finanz_as_collection(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Geld"), state)
    msg = fake_message(user_id=1, text="Geld Abholen")
    await request_flow.money_collect(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="Finanz")
    assert len(tickets) == 1
    assert "Geld abholen" in tickets[0].text


async def test_becher_normal_with_amount_routes_to_bimi(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Becher"), state)
    await request_flow.cups_kind(fake_message(user_id=1, text="Normale Becher"), state)
    assert await state.get_state() == request_flow.RequestFSM.amount.state
    msg = fake_message(user_id=1, text="~20")
    await request_flow.amount_value(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="BiMi")
    assert len(tickets) == 1
    t = tickets[0]
    assert "Normale Becher" in t.text
    assert "~20" in t.text


async def test_becher_dirty_collect_routes_to_bimi(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Becher"), state)
    msg = fake_message(user_id=1, text="Dreckige Abholen")
    await request_flow.cups_collect(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="BiMi")
    assert len(tickets) == 1
    assert "abholen" in tickets[0].text


async def test_bier_freetext_routes_to_bimi(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Bier"), state)
    assert await state.get_state() == request_flow.RequestFSM.free.state
    msg = fake_message(user_id=1, text="2 Fässer Pils")
    await request_flow.free_text(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="BiMi")
    assert len(tickets) == 1
    assert "2 Fässer Pils" in tickets[0].text
    assert "Bier" in tickets[0].text


async def test_sonstiges_routes_to_default_zentrale(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Sonstiges"), state)
    msg = fake_message(user_id=1, text="Tape, viel Tape")
    await request_flow.free_text(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="Zentrale")
    assert len(tickets) == 1
    assert "Tape" in tickets[0].text


async def test_helfer_zu_wenige_routes_to_helfen(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Helfer"), state)
    # "zu wenige" falls through to amount question
    await request_flow.helper_amount(fake_message(user_id=1, text="zu wenige"), state)
    assert await state.get_state() == request_flow.RequestFSM.amount.state
    msg = fake_message(user_id=1, text="~50")
    await request_flow.amount_value(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="Helfen")
    assert len(tickets) == 1
    assert "zu wenige" in tickets[0].text


async def test_helfer_missing_branches_to_free_text(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Helfer"), state)
    await request_flow.helper_missing(fake_message(user_id=1, text="Helfer nicht da"), state)
    assert await state.get_state() == request_flow.RequestFSM.free.state
    msg = fake_message(user_id=1, text="@bob, @carol")
    await request_flow.free_text(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="Helfen")
    assert len(tickets) == 1
    assert "@bob, @carol" in tickets[0].text


async def test_helfer_liste_schichten_uses_shift_lookup(s, state, config, shift_lookup):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Helfer"), state)
    msg = fake_message(user_id=1, text="Liste Schichten")
    await request_flow.helper_list_shifts(
        msg, state, db_session=s, config=config, shift_lookup=shift_lookup
    )
    body = msg.answer.call_args.args[0]
    assert "Schichten für Cocktailbar 1" in body
    assert await state.get_state() is None  # conversation ends


async def test_amount_freetext_branches_to_free(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Becher"), state)
    await request_flow.cups_kind(fake_message(user_id=1, text="Shotbecher"), state)
    await request_flow.amount_freetext(fake_message(user_id=1, text="Freitext"), state)
    assert await state.get_state() == request_flow.RequestFSM.free.state
    msg = fake_message(user_id=1, text="ca. 250 Stück")
    await request_flow.free_text(msg, state, db_session=s, config=config, events=events)
    tickets = repo.active_tickets(s, group_tasked="BiMi")
    assert len(tickets) == 1
    assert "ca. 250" in tickets[0].text


# --- Side effects on finalize --------------------------------------------


async def test_finalize_publishes_to_event_bus(s, state, config):
    bus = EventBus()
    sub = bus.subscribe()
    received: list[str] = []

    async def collect():
        async for payload in sub:
            received.append(payload)
            break

    import asyncio

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)  # let the subscriber attach

    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Geld"), state)
    await request_flow.money_collect(
        fake_message(user_id=1, text="Geld Abholen"), state, db_session=s, config=config, events=bus
    )
    await asyncio.wait_for(task, timeout=1.0)
    assert received and "Geld abholen" in received[0]


async def test_finalize_sets_ticket_status_open(s, state, config, events):
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Geld"), state)
    await request_flow.money_collect(
        fake_message(user_id=1, text="Geld Abholen"),
        state,
        db_session=s,
        config=config,
        events=events,
    )
    tickets = repo.active_tickets(s)
    assert tickets[0].status == TicketStatus.OPEN


async def test_finalize_confirmation_names_routed_orga_group(s, state, config, events):
    """#19: the user should see which orga group their ticket went to."""
    await _start(state)
    await request_flow.pick_category(fake_message(user_id=1, text="Geld"), state)
    msg = fake_message(user_id=1, text="Geld Abholen")
    await request_flow.money_collect(
        msg, state, db_session=s, config=config, events=events
    )
    body = msg.answer.call_args.args[0]
    assert "Finanz" in body  # Geld routes to Finanz
    assert "Ticket #" in body


# --- Pure renderers (also exercised end-to-end above) --------------------


def test_render_collect():
    assert (
        request_flow.render_collect("Geld", "Innenhof [Cocktail]")
        == "Geld abholen an Innenhof [Cocktail]"
    )


def test_render_amount():
    assert (
        request_flow.render_amount("Innenhof [Cocktail]", "~20", "Normale Becher")
        == "Innenhof [Cocktail] hat noch ~20 Normale Becher"
    )


def test_render_free():
    assert (
        request_flow.render_free("Bier", "Außenbereich [Bier]", "2 Fässer")
        == "Außenbereich [Bier] braucht Bier: '2 Fässer'"
    )


def test_render_change():
    assert (
        request_flow.render_change("Innenhof [Cocktail]", "Münzen")
        == "Innenhof [Cocktail] braucht Münzen"
    )


def test_display_for_falls_back_to_group_name_for_unknown_stand(config):
    # Orga groups don't have a stand; their display is the orga name itself.
    assert config.display_for("OrgaCrew") == "OrgaCrew"
    assert config.display_for("Finanz") == "Finanz"
    # Known stands render as "location [type]"
    assert config.display_for("Cocktailbar 1") == "Innenhof [Cocktail]"
