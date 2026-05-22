"""Engelsystem shift lookup. Splits the HTTP boundary from the rendering
so the formatting can be unit-tested without the network."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx

from .config import AppConfig

log = logging.getLogger(__name__)

ShiftLookup = Callable[[str, AppConfig], Awaitable[str]]


# --- HTTP client ---------------------------------------------------------


class EngelsystemClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 5.0):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept": "application/json", "x-api-key": api_key},
            timeout=timeout,
        )

    async def shifts_at(self, location_id: int) -> list[dict]:
        r = await self._client.get(f"locations/{location_id}/shifts")
        r.raise_for_status()
        return r.json()["data"]

    async def aclose(self) -> None:
        await self._client.aclose()


# --- Pure rendering ------------------------------------------------------


def _fmt_delta(td: timedelta) -> str:
    seconds = int(td.total_seconds())
    if seconds < 0:
        seconds = 0
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def summarize_shifts(
    shifts: list[dict],
    *,
    now: datetime,
    next_window: timedelta = timedelta(minutes=20),
) -> str:
    """Render a German summary of currently-running and imminent shifts.
    Pure function; takes `now` so it can be unit-tested deterministically."""

    def _start(s: dict) -> datetime:
        return datetime.fromisoformat(s["starts_at"])

    def _end(s: dict) -> datetime:
        return datetime.fromisoformat(s["ends_at"])

    current = [s for s in shifts if _start(s) <= now < _end(s)]
    upcoming = [s for s in shifts if now < _start(s) <= now + next_window]

    lines: list[str] = []
    for shift in current:
        remaining = _end(shift) - now
        lines.append(f"Momentane Schicht noch {_fmt_delta(remaining)}:")
        for entry in shift.get("entries", []):
            kind = entry.get("type", {}).get("name", "?")
            for user in entry.get("users", []):
                lines.append(f"- {user.get('name', '?')} [{kind}]")
        lines.append("")

    for shift in upcoming:
        until = _start(shift) - now
        lines.append(f"Nächste Schicht in {_fmt_delta(until)}:")
        for entry in shift.get("entries", []):
            kind = entry.get("type", {}).get("name", "?")
            for user in entry.get("users", []):
                lines.append(f"- {user.get('name', '?')} [{kind}]")
        lines.append("")

    if not lines:
        return "Keine aktuellen oder bevorstehenden Schichten am Standort."

    return "\n".join(lines).rstrip()


# --- Composition ---------------------------------------------------------


def make_shift_lookup(client: EngelsystemClient) -> ShiftLookup:
    """Build a ShiftLookup that queries Engelsystem and renders the result.
    Used by handlers as an injected dependency so tests can swap it out."""

    async def lookup(group: str, config: AppConfig) -> str:
        loc_id = config.location_id_for_group(group)
        if loc_id is None:
            return (
                "Deine Gruppe hat keine Schichten im Engelsystem oder der "
                "Standort ist nicht korrekt konfiguriert."
            )
        try:
            shifts = await client.shifts_at(loc_id)
        except Exception:
            log.exception("engelsystem lookup for %s (loc=%s) failed", group, loc_id)
            return "Engelsystem-Abfrage fehlgeschlagen. Bitte später erneut versuchen."
        return summarize_shifts(shifts, now=datetime.now(UTC))

    return lookup
