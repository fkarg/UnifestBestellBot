"""In-process pub/sub bus. The bot publishes ticket updates; the FastAPI
SSE endpoint subscribes. No broker, no persistence — subscribers that
fall behind get dropped and recover via re-snapshot."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from .models import Ticket

log = logging.getLogger(__name__)

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
                # A consumer that fell behind by `queue_size` events: drop it
                # so it stops blocking publishers, and wake its generator with
                # the shutdown sentinel so the SSE response closes and the
                # browser's EventSource reconnects + re-snapshots. Without the
                # sentinel the generator would block forever on a queue that
                # never receives another item — a live-but-dead dashboard.
                log.warning("dropping slow SSE subscriber (queue full)")
                self._subscribers.discard(q)
                self._wake_dropped(q)

    @staticmethod
    def _wake_dropped(q: asyncio.Queue[str]) -> None:
        """Make room and deliver the shutdown sentinel to a queue we just
        dropped, so its generator returns instead of blocking forever."""
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()  # free a slot (the queue was full)
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(_SHUTDOWN)

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
