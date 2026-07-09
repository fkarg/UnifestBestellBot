"""FastAPI app serving the dashboard: snapshot endpoint, SSE stream, and
the static frontend. One process, no broker."""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import session_scope
from .events import EventBus
from .repo import active_tickets

STATIC_DIR = Path(__file__).parent / "static"
SSE_HEARTBEAT_SECONDS = 10.0
SSE_MAX_AGE_SECONDS = 30.0


async def sse_events(
    events: EventBus,
    *,
    heartbeat_seconds: float = SSE_HEARTBEAT_SECONDS,
    max_age_seconds: float = SSE_MAX_AGE_SECONDS,
) -> AsyncGenerator[str]:
    """Yield SSE chunks and close periodically so restarts are not held open."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_age_seconds
    sub = events.subscribe()
    next_payload = asyncio.ensure_future(anext(sub))
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return

            timeout = min(heartbeat_seconds, remaining)
            done, _ = await asyncio.wait({next_payload}, timeout=timeout)
            if not done:
                if loop.time() >= deadline:
                    return
                yield ": heartbeat\n\n"
                continue

            try:
                payload = next_payload.result()
            except StopAsyncIteration:
                return

            yield f"event: ticket\ndata: {payload}\n\n"
            next_payload = asyncio.ensure_future(anext(sub))
    finally:
        next_payload.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await next_payload
        await sub.aclose()


def build_web_app(events: EventBus) -> FastAPI:
    app = FastAPI(title="UnifestBestellBot Dashboard", docs_url=None, redoc_url=None)

    @app.get("/api/tickets")
    def tickets(group: str | None = Query(None)):
        with session_scope() as s:
            ts = active_tickets(s)
        if group is not None:
            ts = [t for t in ts if t.group_tasked.lower() == group.lower()]
        return [json.loads(t.model_dump_json()) for t in ts]

    @app.get("/api/stream")
    async def stream():
        # Every subscriber receives every ticket event; the browser filters
        # by ?group= client-side. This is what lets a group-filtered board
        # *remove* a ticket that was moved away from its group — server-side
        # filtering would never deliver that event to the old group's board.
        return StreamingResponse(
            sse_events(events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/health")
    def health():
        return {"ok": True, "subscribers": events.subscriber_count()}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
