"""In-process pub/sub bus. The bot publishes ticket updates; the FastAPI
SSE endpoint subscribes. No broker, no persistence — subscribers that
fall behind get dropped and recover via re-snapshot."""

import asyncio
from collections.abc import AsyncIterator

from .models import Ticket


class EventBus:
    """Fan-out queue. Each subscriber gets its own bounded queue so a slow
    consumer cannot block publishers."""

    def __init__(self, *, queue_size: int = 128) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[str]] = set()

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish_ticket(self, ticket: Ticket) -> None:
        payload = ticket.model_dump_json()
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                self._subscribers.discard(q)

    async def subscribe(self) -> AsyncIterator[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)
