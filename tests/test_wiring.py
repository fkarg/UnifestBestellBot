"""Smoke tests for the runtime wiring. Catch import-time errors and
ensure the dispatcher builds with every router registered."""

from unifestbestellbot.bot import build_dispatcher
from unifestbestellbot.events import EventBus


async def _noop_shift_lookup(group, config):
    return ""


def test_build_dispatcher_wires_routers_and_workflow_data(config):
    """Routers are module-level singletons in aiogram, so the dispatcher
    can only be built once per process. Cover both invariants in a single
    test to avoid a 'router already attached' error from the second build."""
    events = EventBus()
    dp = build_dispatcher(config=config, events=events, shift_lookup=_noop_shift_lookup)

    names = [r.name for r in dp.sub_routers]
    assert {"register", "request", "orga", "admin"}.issubset(set(names))

    assert dp["config"] is config
    assert dp["events"] is events
    assert dp["shift_lookup"] is _noop_shift_lookup


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
