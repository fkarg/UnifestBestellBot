"""FastAPI app serving the dashboard: snapshot endpoint, SSE stream, and
the static frontend. One process, no broker."""

import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import session_scope
from .events import EventBus
from .repo import active_tickets

STATIC_DIR = Path(__file__).parent / "static"


def _matches_group(payload_json: str, group: str | None) -> bool:
    if group is None:
        return True
    try:
        return json.loads(payload_json).get("group_tasked", "").lower() == group.lower()
    except json.JSONDecodeError:
        return False


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
    async def stream(group: str | None = Query(None)):
        async def generator():
            async for payload in events.subscribe():
                if _matches_group(payload, group):
                    yield f"event: ticket\ndata: {payload}\n\n"

        return StreamingResponse(
            generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/health")
    def health():
        return {"ok": True, "subscribers": events.subscriber_count()}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
