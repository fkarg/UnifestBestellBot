"""In-process pub/sub bus. The bot publishes ticket updates; the FastAPI
SSE endpoint subscribes. No broker, no persistence — subscribers that
fall behind get dropped and recover via re-snapshot."""

import asyncio
from collections.abc import AsyncIterator

from .models import Ticket

# Sentinel pushed by `aclose()` to make every subscriber's generator exit
# its loop cleanly. Browsers reconnect on their own via EventSource.
_SHUTDOWN: str = "__shutdown__"


class EventBus:
    """Fan-out queue. Each subscriber gets its own bounded queue so a slow
    consumer cannot block publishers."""

    def __init__(self, *, queue_size: int = 128) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._closed = False

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish_ticket(self, ticket: Ticket) -> None:
        if self._closed:
            return
        payload = ticket.model_dump_json()
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                self._subscribers.discard(q)

    async def subscribe(self) -> AsyncIterator[str]:
        if self._closed:
            return
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(q)
        try:
            while True:
                item = await q.get()
                if item is _SHUTDOWN:
                    return
                yield item
        finally:
            self._subscribers.discard(q)

    async def aclose(self) -> None:
        """Signal every subscriber to exit. Called once during shutdown.
        Falls back to discarding a queue if its consumer is too slow to
        accept the sentinel — the generator will still wake on the next
        cancellation."""
        self._closed = True
        for q in list(self._subscribers):
            try:
                q.put_nowait(_SHUTDOWN)
            except asyncio.QueueFull:
                self._subscribers.discard(q)
