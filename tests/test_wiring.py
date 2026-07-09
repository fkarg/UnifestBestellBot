"""Smoke tests for the runtime wiring. Catch import-time errors and
ensure the dispatcher builds with every router registered."""

import uvicorn
from unifestbestellbot.events import EventBus


def test_build_dispatcher_wires_routers_and_workflow_data(wired):
    """Routers are module-level singletons in aiogram, so the dispatcher can
    only be built once per process — the shared `wired` fixture is that one
    build. Assert every router is attached and each dependency is injected."""
    dp = wired.dp

    names = [r.name for r in dp.sub_routers]
    assert {"register", "request", "orga", "admin"}.issubset(set(names))

    assert dp["config"] is wired.config
    assert dp["events"] is wired.events
    assert dp["shift_lookup"] is wired.shift_lookup


def test_main_module_imports():
    """If the entrypoint module imports cleanly, the wiring is at least
    syntactically and statically sound."""
    import importlib

    importlib.import_module("unifestbestellbot.__main__")


def test_web_server_config_bounds_graceful_shutdown(config):
    from unifestbestellbot.__main__ import _build_uvicorn_config
    from unifestbestellbot.events import EventBus
    from unifestbestellbot.web import build_web_app

    uvicorn_config = _build_uvicorn_config(
        build_web_app(EventBus()),
        web_bind="127.0.0.1:9000",
        log_level="INFO",
    )

    assert uvicorn_config.host == "127.0.0.1"
    assert uvicorn_config.port == 9000
    assert uvicorn_config.timeout_graceful_shutdown == 2


async def test_dashboard_server_closes_events_before_uvicorn_shutdown(monkeypatch):
    from unifestbestellbot.__main__ import _build_uvicorn_config, _DashboardServer
    from unifestbestellbot.web import build_web_app

    events = EventBus()
    observed_closed = None

    async def fake_shutdown(self, sockets=None):
        nonlocal observed_closed
        observed_closed = events._closed

    monkeypatch.setattr(uvicorn.Server, "shutdown", fake_shutdown)
    server = _DashboardServer(
        _build_uvicorn_config(
            build_web_app(events),
            web_bind="127.0.0.1:9000",
            log_level="INFO",
        ),
        events,
    )

    await server.shutdown()

    assert observed_closed is True


def test_build_bot_has_no_default_parse_mode():
    """Channel logs and group notifications include verbatim strings like
    `<@username>` that would crash Telegram's HTML parser. The bot must
    NOT be constructed with a default parse_mode; sites that need HTML
    pass it explicitly."""
    from unifestbestellbot.bot import build_bot

    bot = build_bot()
    try:
        # aiogram exposes the configured default on bot.default; either
        # the property is absent or its parse_mode is None.
        default = getattr(bot, "default", None)
        if default is not None:
            assert getattr(default, "parse_mode", None) is None
    finally:
        # Don't try to close a session we never opened.
        pass
