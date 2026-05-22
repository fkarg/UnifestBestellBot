"""Entrypoint. One asyncio loop running aiogram polling alongside uvicorn
serving the FastAPI dashboard. Crashes propagate to asyncio.gather and
kill the process; systemd restarts it."""

import asyncio
import logging
import socket

import uvicorn

from . import i18n
from .bot import build_bot, build_dispatcher, notify
from .config import AppConfig, load_config
from .db import init_db
from .engelsystem import EngelsystemClient, ShiftLookup, make_shift_lookup
from .events import EventBus
from .settings import get_settings
from .web import build_web_app

log = logging.getLogger(__name__)


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
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    config = load_config(settings.config_path)
    init_db()

    events = EventBus()
    shift_lookup, engelsystem_client = _build_shift_lookup()

    bot = build_bot()
    dp = build_dispatcher(config=config, events=events, shift_lookup=shift_lookup)

    web = build_web_app(events)
    host, _, port = settings.web_bind.rpartition(":")
    server = uvicorn.Server(
        uvicorn.Config(
            web,
            host=host or "0.0.0.0",
            port=int(port),
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

    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            server.serve(),
        )
    finally:
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
