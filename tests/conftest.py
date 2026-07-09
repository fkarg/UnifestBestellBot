"""Shared fixtures. Sets test env vars before any unifestbestellbot import
so `Settings()` does not look for a real .env file."""

import os

os.environ.setdefault("TELEGRAM_TOKEN", "12345:test-token")
os.environ.setdefault("DEVELOPER_CHAT_ID", "100")
os.environ.setdefault("UPDATES_CHANNEL_ID", "200")
os.environ.setdefault("ENGELSYSTEM_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("CONFIG_PATH", "./config.yaml")

import itertools  # noqa: E402
from datetime import datetime  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Message, Update, User  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402
from unifestbestellbot.config import AppConfig  # noqa: E402

# The one config both the function-scoped `config` fixture and the session-wide
# E2E dispatcher validate. Keep it a single source of truth so an E2E test and a
# unit test never disagree about the fixture world.
_CONFIG_DICT = {
    "stalls": [
        {"name": "Cocktailbar 1", "location": "Innenhof", "type": "Cocktail"},
        {"name": "Biertheke 1", "location": "Außenbereich", "type": "Bier"},
        {"name": "Tickets", "location": "Eingang", "type": "Tickets", "hidden": True},
    ],
    "orga_groups": [
        {"name": "Finanz", "categories": ["Geld"]},
        {"name": "BiMi", "categories": ["Bier", "Cocktail", "Becher", "Sonstiges"]},
        {"name": "Helfen", "categories": ["Helfer"]},
        {"name": "Zentrale", "categories": [], "default": True},
    ],
    "locations": {
        "Innenhof": 12,
        "Außenbereich": 15,
    },
}


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.model_validate(_CONFIG_DICT)


# ---------------------------------------------------------------------------
# Real-dispatcher E2E harness
#
# aiogram routers are module-level singletons, so `build_dispatcher` can only
# run once per process (a second call re-attaches already-attached routers and
# raises). Hence a single session-scoped dispatcher, shared by the E2E tests
# and by test_wiring. Feeding real `Update` objects through `dp.feed_update`
# exercises middleware, filters, Command parsing and router precedence — the
# layers the AsyncMock handler tests bypass. Outgoing Telegram calls are
# captured by mocking `bot.session` (the single seam every `bot(method)` goes
# through), so nothing hits the network.
# ---------------------------------------------------------------------------


async def _e2e_shift_lookup(group: str, config: AppConfig) -> str:
    return "Schichten: (test)"


@pytest.fixture(scope="session")
def wired() -> SimpleNamespace:
    """The one dispatcher this process may build. Bot session is mocked so no
    call reaches the network; every outgoing method lands on
    `bot.session.await_args_list`."""
    from unifestbestellbot.bot import build_bot, build_dispatcher
    from unifestbestellbot.events import EventBus

    cfg = AppConfig.model_validate(_CONFIG_DICT)
    events = EventBus()
    dp = build_dispatcher(config=cfg, events=events, shift_lookup=_e2e_shift_lookup)

    bot = build_bot()
    bot.session = AsyncMock(return_value=MagicMock())

    return SimpleNamespace(
        dp=dp, bot=bot, config=cfg, events=events, shift_lookup=_e2e_shift_lookup
    )


class E2EHarness:
    """Drives the real dispatcher with constructed Telegram updates and reports
    what the handlers tried to send back."""

    def __init__(self, wired: SimpleNamespace) -> None:
        self._dp = wired.dp
        self._bot = wired.bot
        self.config = wired.config
        self.events = wired.events
        self._ids = itertools.count(1000)

    def _msg(self, user_id: int, text: str, first_name: str, username: str | None) -> Message:
        return Message(
            message_id=next(self._ids),
            date=datetime(2026, 7, 9, 12, 0, 0),
            chat=Chat(id=user_id, type="private"),
            from_user=User(
                id=user_id, is_bot=False, first_name=first_name, username=username
            ),
            text=text,
        )

    async def send(
        self,
        text: str,
        *,
        user_id: int = 1,
        first_name: str = "Alice",
        username: str | None = "alice",
    ) -> list[str]:
        """Feed a text message and return the text of every reply it produced.
        Use `.sent()` for the raw method objects (reply_markup, chat_id, ...)."""
        self._bot.session.reset_mock()
        msg = self._msg(user_id, text, first_name, username)
        await self._dp.feed_update(self._bot, Update(update_id=next(self._ids), message=msg))
        return self.texts()

    async def click(
        self,
        data: str,
        *,
        user_id: int = 1,
        first_name: str = "Alice",
        username: str | None = "alice",
    ) -> list[str]:
        """Feed an inline-button press (callback query) and return the text of
        every reply it produced."""
        self._bot.session.reset_mock()
        carrier = Message(
            message_id=next(self._ids),
            date=datetime(2026, 7, 9, 12, 0, 0),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=999, is_bot=True, first_name="Bot", username="bot"),
            text="…",
        )
        cb = CallbackQuery(
            id=f"cb{next(self._ids)}",
            from_user=User(
                id=user_id, is_bot=False, first_name=first_name, username=username
            ),
            chat_instance="ci",
            message=carrier,
            data=data,
        )
        await self._dp.feed_update(self._bot, Update(update_id=next(self._ids), callback_query=cb))
        return self.texts()

    def sent(self) -> list:
        """The Telegram method objects sent since the last send/click, e.g.
        SendMessage / EditMessageText / AnswerCallbackQuery."""
        return [c.args[1] for c in self._bot.session.await_args_list]

    def texts(self) -> list[str]:
        """The `.text` of every outgoing method that carries one."""
        return [t for m in self.sent() if (t := getattr(m, "text", None)) is not None]


@pytest.fixture
def e2e(wired: SimpleNamespace) -> E2EHarness:
    """Fresh global DB per test, then a harness over the shared dispatcher.
    The dispatcher's SessionMiddleware opens sessions on the global engine, so
    resetting its schema here isolates each E2E test."""
    from unifestbestellbot.db import get_engine

    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    return E2EHarness(wired)
