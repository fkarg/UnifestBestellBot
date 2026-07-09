"""Engelsystem shift-start digest.

Periodically polls Engelsystem for shifts starting soon and DMs the
orga group that handles `Helfer` requests with the rota of each
upcoming shift. The "starting soon" window and the operational-hours
window come from `config.shift_digest`."""

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta

from aiogram import Bot

from .. import i18n
from ..config import AppConfig
from ..db import session_scope
from ..engelsystem import EngelsystemClient, iter_rota
from ..models import now_utc, to_local
from ..settings import get_settings
from . import notify

log = logging.getLogger(__name__)


def is_within_window(now_local: time, start: time, end: time) -> bool:
    """Whether `now_local` falls inside the configured operational window.

    `start == end` is treated as "always on" so an operator who hasn't
    configured a window doesn't get a permanently-disabled feature."""
    if start == end:
        return True
    if start < end:
        return start <= now_local < end
    # window wraps midnight
    return now_local >= start or now_local < end


def _parse_iso_to_naive_utc(s: str) -> datetime:
    """Engelsystem returns aware ISO timestamps. Bring them into the
    project's naive-UTC convention so they're comparable with `now_utc()`."""
    return datetime.fromisoformat(s).astimezone(UTC).replace(tzinfo=None)


def format_shift_announcement(shift: dict, location_name: str) -> str:
    """Build the DM body for a single upcoming shift. Local time, plus
    the rota with each entry's user and role."""
    start_local = (
        datetime.fromisoformat(shift["starts_at"])
        .astimezone(get_settings().local_tz())
        .strftime("%H:%M")
    )
    lines = [
        i18n.DIGEST_NEXT_SHIFT.format(location=location_name, time=start_local),
    ]
    has_entries = False
    for name, role in iter_rota(shift):
        lines.append(f"- {name} [{role}]")
        has_entries = True
    if not has_entries:
        lines.append(i18n.DIGEST_NO_ENTRIES)
    return "\n".join(lines)


async def digest_once(
    *,
    bot: Bot,
    config: AppConfig,
    client: EngelsystemClient,
    announced: set[int],
    now: datetime | None = None,
) -> int:
    """One pass: for every configured location, fetch shifts and DM the
    Helfer-orga about any shift that starts within the lookahead window
    and hasn't already been announced. Returns the number of new shifts
    announced this pass."""
    now = now if now is not None else now_utc()
    lookahead = timedelta(minutes=config.shift_digest.lookahead_minutes)
    cutoff = now + lookahead
    helfer_orga = config.route_category("Helfer")
    new_count = 0

    for location_name, location_id in config.locations.items():
        try:
            shifts = await client.shifts_at(location_id)
        except Exception:
            log.exception("digest: shift fetch for %r (id=%s) failed",
                          location_name, location_id)
            continue

        for shift in shifts:
            shift_id = shift.get("id")
            if shift_id is None or shift_id in announced:
                continue
            try:
                start = _parse_iso_to_naive_utc(shift["starts_at"])
            except (KeyError, ValueError):
                continue
            if not (now <= start < cutoff):
                continue

            body = format_shift_announcement(shift, location_name)
            with session_scope() as s:
                await notify.group_msg(bot, s, helfer_orga, body)
            announced.add(shift_id)
            new_count += 1
            log.info(
                "digest: announced shift %s at %s starting %s",
                shift_id, location_name, shift["starts_at"],
            )

    return new_count


async def shift_digest_loop(
    *,
    bot: Bot,
    config: AppConfig,
    client: EngelsystemClient,
) -> None:
    """Long-running task. Cancellation drops out cleanly."""
    sd = config.shift_digest
    if not sd.enabled:
        log.info("shift digest disabled in config")
        return

    log.info(
        "shift digest active: window %s–%s local, every %d min, lookahead %d min",
        sd.window_start.strftime("%H:%M"),
        sd.window_end.strftime("%H:%M"),
        sd.check_interval_minutes,
        sd.lookahead_minutes,
    )
    # Dedup of already-announced shift ids is in-memory only: a process
    # restart re-announces any shift still inside the lookahead window. The
    # supervisor (see __main__) makes restarts rare, the window is minutes
    # wide, and a duplicate "shift starting" DM is harmless, so this is left
    # unpersisted deliberately rather than adding a table.
    announced: set[int] = set()
    interval_sec = sd.check_interval_minutes * 60

    try:
        while True:
            now_naive = now_utc()
            now_local = to_local(now_naive).time()
            if is_within_window(now_local, sd.window_start, sd.window_end):
                try:
                    await digest_once(
                        bot=bot, config=config, client=client, announced=announced,
                        now=now_naive,
                    )
                except Exception:
                    log.exception("digest pass failed")
            await asyncio.sleep(interval_sec)
    except asyncio.CancelledError:
        log.info("shift digest loop cancelled")
        raise
