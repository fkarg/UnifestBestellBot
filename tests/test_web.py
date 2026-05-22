import asyncio
import contextlib
import json

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import db as db_mod
from unifestbestellbot import repo
from unifestbestellbot.events import EventBus
from unifestbestellbot.models import Ticket, TicketStatus
from unifestbestellbot.web import _matches_group, build_web_app


@pytest.fixture
def engine_setup(monkeypatch):
    """Replace the cached engine with one against a shared in-memory SQLite,
    so the web app and the test see the same data."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    db_mod.get_engine.cache_clear()
    monkeypatch.setattr(db_mod, "get_engine", lambda: engine)
    yield engine


@pytest.fixture
def events():
    return EventBus()


@pytest.fixture
def app(events, engine_setup):
    return build_web_app(events)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c


def _ticket(engine, **overrides):
    defaults = dict(
        category="Geld",
        text="needs change",
        group_requesting="Cocktailbar",
        group_tasked="Finanz",
        actor_chat_id=1,
    )
    defaults.update(overrides)
    with Session(engine) as s:
        return repo.create_ticket(s, **defaults)


# --- /api/tickets --------------------------------------------------------


async def test_snapshot_returns_active_tickets(client, engine_setup):
    _ticket(engine_setup, text="a")
    _ticket(engine_setup, text="b")
    r = await client.get("/api/tickets")
    assert r.status_code == 200
    body = r.json()
    assert {t["text"] for t in body} == {"a", "b"}


async def test_snapshot_filters_by_group(client, engine_setup):
    _ticket(engine_setup, group_tasked="Finanz", text="finanz")
    _ticket(engine_setup, group_tasked="BiMi", text="bimi")
    r = await client.get("/api/tickets", params={"group": "Finanz"})
    body = r.json()
    assert [t["text"] for t in body] == ["finanz"]


async def test_snapshot_group_is_case_insensitive(client, engine_setup):
    _ticket(engine_setup, group_tasked="Finanz", text="finanz")
    r = await client.get("/api/tickets", params={"group": "finanz"})
    assert r.json()[0]["text"] == "finanz"


async def test_snapshot_excludes_closed(client, engine_setup):
    t = _ticket(engine_setup, text="will close")
    with Session(engine_setup) as s:
        repo.close_ticket(s, t.id, actor_chat_id=1)
    r = await client.get("/api/tickets")
    assert r.json() == []


# --- /api/stream — route is exercised via the EventBus tests below, since
#     httpx.ASGITransport cannot cleanly drive an infinite SSE stream in tests.


def test_stream_route_is_registered(app):
    paths = {r.path for r in app.routes}
    assert "/api/stream" in paths


# --- EventBus broadcast --------------------------------------------------


async def test_event_bus_delivers_published_payload_to_subscriber():
    bus = EventBus()
    sub = bus.subscribe()
    # Attach the subscriber by stepping the generator once via an
    # awaitable that pulls one item.
    received: list[str] = []

    async def consume():
        async for item in sub:
            received.append(item)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    t = Ticket(id=1, status=TicketStatus.OPEN, category="Geld", text="x",
               group_requesting="Cocktailbar", group_tasked="Finanz")
    await bus.publish_ticket(t)
    await asyncio.wait_for(task, timeout=1.0)
    payload = json.loads(received[0])
    assert payload["text"] == "x"
    assert payload["group_tasked"] == "Finanz"


async def test_event_bus_drops_full_subscriber():
    bus = EventBus(queue_size=1)
    sub = bus.subscribe()
    # Attach without consuming.
    async def attach():
        async for _ in sub:
            return  # never runs in this test

    task = asyncio.create_task(attach())
    await asyncio.sleep(0.01)
    assert bus.subscriber_count() == 1
    t = Ticket(id=1, status=TicketStatus.OPEN, category="Geld", text="x",
               group_requesting="A", group_tasked="B")
    await bus.publish_ticket(t)   # fills the queue
    await bus.publish_ticket(t)   # triggers QueueFull → drop
    assert bus.subscriber_count() == 0
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# --- /api/health ---------------------------------------------------------


async def test_health_reports_subscriber_count(client, events):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "subscribers": 0}


# --- static files --------------------------------------------------------


async def test_root_serves_index_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "UnifestBestellBot" in r.text


async def test_main_js_served(client):
    r = await client.get("/main.js")
    assert r.status_code == 200
    assert "EventSource" in r.text


# --- _matches_group helper -----------------------------------------------


def test_matches_group_none_passes_through():
    assert _matches_group('{"group_tasked": "Finanz"}', None) is True


def test_matches_group_case_insensitive():
    assert _matches_group('{"group_tasked": "Finanz"}', "finanz") is True


def test_matches_group_mismatch():
    assert _matches_group('{"group_tasked": "Finanz"}', "BiMi") is False


def test_matches_group_handles_bad_json():
    assert _matches_group("not json", "Finanz") is False
