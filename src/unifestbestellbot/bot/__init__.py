"""Build the aiogram Bot and Dispatcher with routers, middleware, and
workflow_data dependencies wired up."""

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from ..config import AppConfig
from ..engelsystem import ShiftLookup
from ..events import EventBus
from ..settings import get_settings
from . import admin, errors, orga, register, request, unknown
from .middleware import SessionMiddleware


def build_bot() -> Bot:
    return Bot(
        token=get_settings().telegram_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


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
