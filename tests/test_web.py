import asyncio
import contextlib
import inspect
import json

import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import db as db_mod
from unifestbestellbot import repo
from unifestbestellbot.events import EventBus
from unifestbestellbot.models import Ticket, TicketStatus
from unifestbestellbot.web import build_web_app, sse_events


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
def app(events, engine_setup, config):
    return build_web_app(events, config)


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


# --- /api/locations ------------------------------------------------------


async def test_locations_maps_group_to_location(client):
    r = await client.get("/api/locations")
    assert r.status_code == 200
    body = r.json()
    assert body["Cocktailbar 1"] == "Innenhof"
    assert body["Biertheke 1"] == "Außenbereich"
    # Hidden stalls still map — a ticket from one must group correctly.
    assert body["Tickets"] == "Eingang"


async def test_locations_empty_without_config(events, engine_setup):
    app = build_web_app(events)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.get("/api/locations")
    assert r.json() == {}


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


async def test_dropped_subscriber_generator_is_woken_and_exits():
    """An overflowed subscriber is dropped AND its generator woken with the
    shutdown sentinel, so the SSE response closes and the browser reconnects
    instead of hanging on a queue that will never receive another item."""
    bus = EventBus(queue_size=1)
    sub = bus.subscribe()
    items: list[str] = []

    async def consume():
        async for item in sub:
            items.append(item)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert bus.subscriber_count() == 1
    t = Ticket(id=1, status=TicketStatus.OPEN, category="Geld", text="x",
               group_requesting="A", group_tasked="B")
    await bus.publish_ticket(t)  # fills the queue
    await bus.publish_ticket(t)  # QueueFull → drop + wake with sentinel
    # The generator exits on its own; no cancellation needed.
    await asyncio.wait_for(task, timeout=1.0)
    assert bus.subscriber_count() == 0
    assert items == []  # the sentinel is not yielded to the consumer


async def test_event_bus_aclose_exits_subscriber_generator():
    bus = EventBus()
    sub = bus.subscribe()
    items: list[str] = []

    async def consume():
        async for item in sub:
            items.append(item)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    assert bus.subscriber_count() == 1

    await bus.aclose()
    # The generator should exit on its own; wait for it.
    await asyncio.wait_for(task, timeout=1.0)
    assert items == []  # the shutdown sentinel is not yielded to consumers
    assert bus.subscriber_count() == 0


async def test_event_bus_publish_after_aclose_is_a_noop():
    bus = EventBus()
    await bus.aclose()
    t = Ticket(id=1, status=TicketStatus.OPEN, category="Geld", text="x",
               group_requesting="A", group_tasked="B")
    # Doesn't raise, doesn't add subscribers, doesn't fan out anything.
    await bus.publish_ticket(t)
    assert bus.subscriber_count() == 0


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


async def test_main_js_shows_online_and_reconnects_after_10s(client):
    r = await client.get("/main.js")
    assert r.status_code == 200
    assert 'conn.textContent = "online"' in r.text
    assert "RECONNECT_DELAY_MS = 10000" in r.text


async def test_main_js_keeps_reconnect_state_optimistically_online(client):
    r = await client.get("/main.js")
    assert r.status_code == 200
    assert "streamOpened = true" in r.text
    assert "ONLINE_GRACE_MS = 2000" in r.text
    assert 'conn.textContent = "reconnecting…"' in r.text
    assert 'conn.className = "off"' in r.text


async def test_main_js_marks_stale_stream_offline_without_error_event(client):
    r = await client.get("/main.js")
    assert r.status_code == 200
    assert "STALE_AFTER_MS = 25000" in r.text
    assert "heartbeat" in r.text
    assert "lastServerActivityAt" in r.text
    assert "checkStaleConnection" in r.text


# --- stream delivers all events; the browser filters by group -----------
#
# The SSE stream is intentionally unfiltered (group filtering moved to the
# client) so a group-filtered board can drop a ticket moved out of its
# group. The snapshot endpoint still filters server-side for the initial
# load (test_snapshot_filters_by_group above); these confirm the stream
# itself fans out every published ticket regardless of group.


async def test_stream_publishes_all_groups_to_a_subscriber():
    bus = EventBus()
    sub = bus.subscribe()
    received: list[str] = []

    async def consume():
        async for item in sub:
            received.append(item)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    for grp in ("Finanz", "BiMi"):
        await bus.publish_ticket(
            Ticket(id=1, status=TicketStatus.OPEN, category="Geld", text="x",
                   group_requesting="A", group_tasked=grp)
        )
    await asyncio.wait_for(task, timeout=1.0)
    groups = {json.loads(p)["group_tasked"] for p in received}
    assert groups == {"Finanz", "BiMi"}


async def test_sse_stream_sends_heartbeat_while_idle():
    bus = EventBus()
    stream = sse_events(bus, heartbeat_seconds=0.01)

    chunk = await asyncio.wait_for(anext(stream), timeout=0.2)

    assert chunk == "event: heartbeat\ndata: {}\n\n"
    await stream.aclose()


async def test_sse_stream_stays_open_while_idle():
    assert "max_age_seconds" not in inspect.signature(sse_events).parameters

    bus = EventBus()
    stream = sse_events(bus, heartbeat_seconds=0.01)

    chunks = [await asyncio.wait_for(anext(stream), timeout=0.2) for _ in range(3)]

    assert chunks == ["event: heartbeat\ndata: {}\n\n"] * 3
    await stream.aclose()


async def test_sse_stream_closes_cleanly_when_event_bus_closes():
    bus = EventBus()
    stream = sse_events(bus, heartbeat_seconds=1.0)
    next_chunk = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.01)

    await bus.aclose()

    with pytest.raises(StopAsyncIteration):
        await next_chunk


async def test_sse_stream_keeps_ticket_events_immediate():
    bus = EventBus()
    stream = sse_events(bus, heartbeat_seconds=1.0)
    next_chunk = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.01)

    await bus.publish_ticket(
        Ticket(id=1, status=TicketStatus.OPEN, category="Geld", text="x",
               group_requesting="A", group_tasked="Finanz")
    )

    chunk = await asyncio.wait_for(next_chunk, timeout=0.2)
    assert chunk.startswith("event: ticket\n")
    assert '"group_tasked":"Finanz"' in chunk
    await stream.aclose()
