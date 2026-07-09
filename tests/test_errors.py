from types import SimpleNamespace
from typing import Any, cast

from unifestbestellbot.bot import errors

from .fakes import fake_bot


class _LongUpdate:
    def model_dump_json(self, *, exclude_none: bool, indent: int) -> str:
        return "<" * 6000


async def test_on_error_splits_long_forwarded_messages():
    bot = fake_bot()
    event = SimpleNamespace(
        exception=RuntimeError(">" * 6000),
        update=_LongUpdate(),
    )

    await errors.on_error(cast(Any, event), bot)

    texts = [call.kwargs["text"] for call in bot.send_message.await_args_list]
    assert len(texts) > 1
    assert all(0 < len(text) <= 4096 for text in texts)
    assert "RuntimeError" in "".join(texts)
    assert ">" * 100 in "".join(texts)
