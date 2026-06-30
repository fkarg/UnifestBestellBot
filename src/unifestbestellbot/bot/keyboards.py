"""Reply-keyboard factories. The bot uses persistent reply keyboards for
top-level navigation (initial / main / orga) and per-step prompts inside
the /request conversation. Inline keyboards live in the flows that build
them ad-hoc from data the bot just fetched."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from ..config import AppConfig
from ..models import Registration


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
    )


INITIAL = _kb([["/help", "/register"]])
MAIN = _kb([["/help", "/status"], ["/request"]])
ORGA = _kb(
    [
        ["/help", "/help2"],
        ["/all", "/tickets", "/move"],
        ["/wip", "/close", "/self"],
    ]
)


def for_user(reg: Registration | None, config: AppConfig) -> ReplyKeyboardMarkup:
    if reg is None:
        return INITIAL
    if config.is_orga(reg.group_name):
        return ORGA
    return MAIN
