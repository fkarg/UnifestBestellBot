"""Property-based fuzzing of the command-argument parsers.

The bug that motivated this: `/history Cocktailbar 1` briefly mis-parsed the
trailing digit of a group name as the limit. That class of parser edge case is
exactly what property testing catches cheaply. The invariant every command
handler must uphold: for *any* argument string the user can type, the handler
completes without raising and always sends a reply (a usage hint, an
empty-state, or a result) — it never leaves the user with silence or bubbles an
unhandled exception up to the error handler.

Handlers are driven directly (not through the dispatcher) with a fake message,
so the IsOrga filter doesn't run; the caller is pre-registered as orga where the
handler needs it."""

import asyncio

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import repo
from unifestbestellbot.bot import orga as orga_flow
from unifestbestellbot.bot import register as register_flow
from unifestbestellbot.config import AppConfig
from unifestbestellbot.events import EventBus
from unifestbestellbot.models import Registration

from .fakes import fake_message

CONFIG = AppConfig.model_validate(
    {
        "stalls": [
            {"name": "Cocktailbar 1", "location": "Innenhof", "type": "Cocktail"},
            {"name": "Biertheke 1", "location": "Außenbereich", "type": "Bier"},
            {"name": "Tickets", "location": "Eingang", "type": "Tickets", "hidden": True},
        ],
        "orga_groups": [
            {"name": "Finanz", "categories": ["Geld"]},
            {"name": "BiMi", "categories": ["Bier", "Cocktail", "Becher", "Sonstiges"]},
            {"name": "Zentrale", "categories": [], "default": True},
        ],
        "locations": {"Innenhof": 12, "Außenbereich": 15},
    }
)


# Tokens chosen to stress the parsers: exact and wrong-case group names (some
# ending in a digit), boundary and out-of-range limits, huge integers (probe
# for SQLite INTEGER overflow), signs, junk, and empties.
_TOKENS = [
    "Cocktailbar 1", "cocktailbar 1", "COCKTAILBAR 1", "Biertheke 1", "Tickets",
    "Finanz", "finanz", "BiMi", "Zentrale", "Nonexistent",
    "0", "1", "5", "50", "51", "-1", "9999",
    "99999999999999999999999999999", "1e3", "12.5", "٣", "+2", "  ",
    "", "-", "abc", "1 2", "Cocktailbar",
]

# A whitespace-joined bag of tokens, plus fully arbitrary unicode text.
_arg = st.one_of(
    st.lists(st.sampled_from(_TOKENS), min_size=0, max_size=4).map(" ".join),
    st.text(max_size=40),
)

# Hypothesis reuses the function-scoped DB/registration across generated
# examples; that shared state is harmless here (we assert "never crashes",
# not isolation), so silence the health check.
_FUZZ = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@pytest.fixture
def orga_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.upsert_registration(s, Registration(chat_id=1, group_name="Finanz"))
        # One real ticket so happy-path branches (found/close/move) are reachable.
        repo.create_ticket(
            s,
            category="Geld",
            text="probe",
            group_requesting="Cocktailbar 1",
            group_tasked="Finanz",
            actor_chat_id=1,
        )
        yield s


def _drive(coro_factory) -> None:
    """Run one async handler invocation to completion in its own loop."""
    asyncio.run(coro_factory())


# --- pure resolver -------------------------------------------------------


@given(q=st.text())
@settings(max_examples=300, deadline=None)
def test_resolve_group_total_and_sound(q):
    known = set(CONFIG.all_stall_names()) | set(CONFIG.orga_names())
    result = CONFIG.resolve_group(q)
    assert result is None or result in known


# --- orga command parsers ------------------------------------------------


@given(arg=_arg)
@_FUZZ
def test_history_parser_never_crashes(orga_session, arg):
    async def scenario():
        msg = fake_message(user_id=1, text=f"/history {arg}")
        await orga_flow.cmd_history(msg, db_session=orga_session, config=CONFIG)
        assert msg.answer.await_count >= 1

    _drive(scenario)


@given(arg=_arg)
@_FUZZ
def test_move_parser_never_crashes(orga_session, arg):
    events = EventBus()

    async def scenario():
        msg = fake_message(user_id=1, text=f"/move {arg}")
        await orga_flow.cmd_move(
            msg, db_session=orga_session, config=CONFIG, events=events
        )
        assert msg.answer.await_count >= 1

    _drive(scenario)


@given(arg=_arg)
@_FUZZ
def test_message_parser_never_crashes(orga_session, arg):
    async def scenario():
        msg = fake_message(user_id=1, text=f"/message {arg}")
        await orga_flow.cmd_message(msg, db_session=orga_session, config=CONFIG)
        assert msg.answer.await_count >= 1

    _drive(scenario)


# --- register-module command parsers -------------------------------------


@given(arg=_arg)
@_FUZZ
def test_status_parser_never_crashes(orga_session, arg):
    async def scenario():
        msg = fake_message(user_id=1, text=f"/status {arg}")
        await register_flow.cmd_status(msg, db_session=orga_session, config=CONFIG)
        assert msg.answer.await_count >= 1

    _drive(scenario)


@given(arg=_arg)
@_FUZZ
def test_quiet_parser_never_crashes(orga_session, arg):
    async def scenario():
        msg = fake_message(user_id=1, text=f"/quiet {arg}")
        await register_flow.cmd_quiet(msg, db_session=orga_session, config=CONFIG)
        assert msg.answer.await_count >= 1

    _drive(scenario)


@given(arg=_arg)
@_FUZZ
def test_name_parser_never_crashes(orga_session, arg):
    async def scenario():
        msg = fake_message(user_id=1, text=f"/name {arg}")
        await register_flow.cmd_name(msg, db_session=orga_session, config=CONFIG)
        assert msg.answer.await_count >= 1

    _drive(scenario)


@given(arg=_arg)
@_FUZZ
def test_register_parser_never_crashes(orga_session, arg):
    async def scenario():
        msg = fake_message(user_id=1, text=f"/register {arg}")
        await register_flow.cmd_register(msg, db_session=orga_session, config=CONFIG)
        assert msg.answer.await_count >= 1

    _drive(scenario)
