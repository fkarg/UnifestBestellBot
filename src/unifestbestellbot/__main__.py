"""Entrypoint. One asyncio loop running aiogram polling alongside uvicorn
serving the FastAPI dashboard. Each of the two long-running coroutines is
supervised: if it crashes it is restarted with backoff and the traceback is
DMed to the developer, so the process stays up under the foreground tmux
deploy (where nothing else would restart it).

Shutdown: a clean Ctrl-C surfaces as KeyboardInterrupt (a BaseException, so
the supervisor's `except Exception` does not swallow it) — it unwinds the
gather and runs the teardown below. Under `systemctl stop` (SIGTERM),
uvicorn re-raises the signal through the default handler and the process
exits before the `finally` runs; the teardown there is best-effort cleanup
the OS reclaims anyway."""

import asyncio
import contextlib
import logging
import socket
from collections.abc import Awaitable, Callable

import uvicorn

from . import i18n
from .bot import build_bot, build_dispatcher, errors, notify
from .bot.digest import shift_digest_loop
from .config import AppConfig, load_config
from .db import init_db
from .engelsystem import EngelsystemClient, ShiftLookup, make_shift_lookup
from .events import EventBus
from .settings import get_settings
from .web import build_web_app

log = logging.getLogger(__name__)

# Restart backoff bounds for a crashed long-running coroutine.
_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0


async def _supervise(
    name: str, factory: Callable[[], Awaitable[None]], bot
) -> None:
    """Run `factory()`, restarting it with exponential backoff only if it
    *crashes* (raises), and DMing the developer the traceback each time.

    A clean return is treated as an orderly stop (e.g. uvicorn/aiogram
    returning on a shutdown signal), NOT a reason to restart — restarting on
    a signal-driven exit would fight Ctrl-C/systemd and respawn the server.
    Cancellation propagates out for the same reason."""
    backoff = _BACKOFF_START
    while True:
        try:
            await factory()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("%s crashed; restarting in %.0fs", name, backoff)
            with contextlib.suppress(Exception):
                await notify.dev_msg(bot, errors.format_crash_report(name, exc))
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
        else:
            log.info("%s stopped cleanly", name)
            return


def _stub_shift_lookup() -> ShiftLookup:
    async def lookup(group: str, config: AppConfig) -> str:
        return "Engelsystem ist in dieser Instanz nicht konfiguriert."

    return lookup


def _build_shift_lookup() -> tuple[ShiftLookup, EngelsystemClient | None]:
    s = get_settings()
    if not s.engelsystem_api_key:
        return _stub_shift_lookup(), None
    client = EngelsystemClient(str(s.engelsystem_base_url), s.engelsystem_api_key)
    return make_shift_lookup(client), client


async def amain() -> None:
    settings = get_settings()
    from .logging_setup import setup_logging

    log_file = setup_logging(
        level=settings.log_level,
        log_dir=settings.log_dir,
        retention_days=settings.log_retention_days,
    )
    log.info("logs rotating daily into %s", log_file)

    config = load_config(settings.config_path)
    init_db()

    events = EventBus()
    shift_lookup, engelsystem_client = _build_shift_lookup()

    bot = build_bot()
    dp = build_dispatcher(config=config, events=events, shift_lookup=shift_lookup)

    web = build_web_app(events)
    bind_host, _, bind_port = settings.web_bind.rpartition(":")

    def _make_server() -> uvicorn.Server:
        # A fresh Server per (re)start: uvicorn.Server carries should_exit
        # state across serve(), so reusing one instance would not restart
        # cleanly after a crash.
        return uvicorn.Server(
            uvicorn.Config(
                web,
                host=bind_host or "0.0.0.0",
                port=int(bind_port),
                log_level=settings.log_level.lower(),
                access_log=False,
            )
        )

    host = socket.gethostname()
    log.info("UnifestBestellBot starting from %s", host)
    try:
        await notify.channel_msg(bot, i18n.CH_BOT_STARTED.format(host=host))
    except Exception:
        log.exception("failed to send startup channel notification")

    digest_task: asyncio.Task[None] | None = None
    if config.shift_digest.enabled and engelsystem_client is not None:
        digest_task = asyncio.create_task(
            shift_digest_loop(bot=bot, config=config, client=engelsystem_client),
            name="shift-digest",
        )
    elif config.shift_digest.enabled:
        log.warning(
            "shift_digest.enabled=true but ENGELSYSTEM_API_KEY is not set; "
            "digest will not run"
        )

    async def _poll() -> None:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

    async def _serve() -> None:
        await _make_server().serve()

    try:
        await asyncio.gather(
            _supervise("telegram-polling", _poll, bot),
            _supervise("web-server", _serve, bot),
        )
    finally:
        if digest_task is not None:
            digest_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await digest_task
        # Tell any connected dashboard browsers to disconnect so the SSE
        # generators exit, then close the network resources we own.
        await events.aclose()
        await bot.session.close()
        if engelsystem_client is not None:
            await engelsystem_client.aclose()


def run() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    run()
