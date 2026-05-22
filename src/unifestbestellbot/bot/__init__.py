"""Build the aiogram Bot and Dispatcher with routers, middleware, and
workflow_data dependencies wired up."""

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from ..config import AppConfig
from ..engelsystem import ShiftLookup
from ..events import EventBus
from ..settings import get_settings
from . import admin, errors, orga, register, request, unknown
from .middleware import SessionMiddleware


def build_bot() -> Bot:
    # No default parse_mode: ticket text and group notifications contain
    # things like "<@username>" verbatim, which Telegram would otherwise
    # try to parse as HTML and reject. Sites that genuinely need HTML
    # (currently only bot/errors.py) pass parse_mode explicitly.
    return Bot(token=get_settings().telegram_token)


def build_dispatcher(
    *,
    config: AppConfig,
    events: EventBus,
    shift_lookup: ShiftLookup,
) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    dp["config"] = config
    dp["events"] = events
    dp["shift_lookup"] = shift_lookup

    dp.update.outer_middleware(SessionMiddleware())
    dp.errors.register(errors.on_error)

    dp.include_routers(
        register.router,
        request.router,
        orga.router,
        admin.router,
        # `unknown.router` MUST be included last so it doesn't preempt the
        # flow routers above.
        unknown.router,
    )
    return dp
