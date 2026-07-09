from datetime import datetime, time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from unifestbestellbot import db as db_mod
from unifestbestellbot import repo
from unifestbestellbot.bot.digest import (
    digest_once,
    format_shift_announcement,
    is_within_window,
)
from unifestbestellbot.config import AppConfig
from unifestbestellbot.engelsystem import EngelsystemClient
from unifestbestellbot.models import Registration

# --- is_within_window ----------------------------------------------------


def test_window_within_same_day():
    start, end = time(9, 0), time(17, 0)
    assert is_within_window(time(12, 0), start, end)
    assert not is_within_window(time(8, 0), start, end)
    assert not is_within_window(time(17, 0), start, end)  # exclusive end


def test_window_wraps_midnight():
    start, end = time(18, 0), time(2, 0)
    assert is_within_window(time(20, 0), start, end)
    assert is_within_window(time(1, 0), start, end)
    assert not is_within_window(time(3, 0), start, end)
    assert not is_within_window(time(17, 59), start, end)


def test_window_equal_start_end_is_always_on():
    t = time(0, 0)
    assert is_within_window(time(7, 0), t, t)
    assert is_within_window(time(23, 59), t, t)


# --- format_shift_announcement ------------------------------------------


def test_format_includes_users_and_roles():
    shift = {
        "starts_at": "2026-05-22T18:00:00+02:00",
        "needed_angel_types": [
            {
                "angel_type": {"name": "Bar"},
                "needs": 2,
                "entries": [
                    {"user": {"name": "Alice"}, "freeloaded": False},
                    {"user": {"name": "Bob"}, "freeloaded": False},
                ],
            },
            {
                "angel_type": {"name": "Kasse"},
                "needs": 1,
                "entries": [{"user": {"name": "Carol"}, "freeloaded": False}],
            },
        ],
    }
    out = format_shift_announcement(shift, "Forum Süd")
    assert "Forum Süd" in out
    assert "Alice [Bar]" in out
    assert "Bob [Bar]" in out
    assert "Carol [Kasse]" in out


def test_format_empty_entries_marks_as_unfilled():
    shift = {"starts_at": "2026-05-22T18:00:00+02:00", "needed_angel_types": []}
    out = format_shift_announcement(shift, "DJ")
    assert "keine Helfer" in out


# --- digest_once --------------------------------------------------------


@pytest.fixture
def cfg_digest():
    """Config with shift_digest enabled and Helfen as the Helfer handler."""
    return AppConfig.model_validate(
        {
            "stalls": [
                {"name": "Crew A", "location": "Forum Süd", "type": "Cocktail"},
            ],
            "orga_groups": [
                {"name": "Helfen", "categories": ["Helfer"]},
                {"name": "Zentrale", "categories": ["Sonstiges"], "default": True},
            ],
            "locations": {"Forum Süd": 12},
            "shift_digest": {
                "enabled": True,
                "window_start": "18:00",
                "window_end": "02:00",
                "check_interval_minutes": 5,
                "lookahead_minutes": 10,
            },
        }
    )


@pytest.fixture
def engine_with_helfen(monkeypatch):
    """In-memory DB with a Helfen member already registered."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        repo.upsert_registration(s, Registration(chat_id=7, group_name="Helfen"))
    db_mod.get_engine.cache_clear()
    monkeypatch.setattr(db_mod, "get_engine", lambda: engine)
    return engine


def _shift_at(start_iso: str, *, id: int = 1, users: tuple[str, ...] = ("Alice",)) -> dict:
    return {
        "id": id,
        "starts_at": start_iso,
        "needed_angel_types": [
            {
                "angel_type": {"name": "Bar"},
                "needs": len(users),
                "entries": [
                    {"user": {"name": u}, "freeloaded": False} for u in users
                ],
            },
        ],
    }


async def test_digest_announces_shift_in_lookahead_window(cfg_digest, engine_with_helfen):
    now = datetime(2026, 5, 22, 16, 0)  # naive UTC
    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(
        return_value=[_shift_at("2026-05-22T16:05:00+00:00")]
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    announced: set[int] = set()

    count = await digest_once(
        bot=bot, config=cfg_digest, client=client, announced=announced, now=now
    )

    assert count == 1
    assert 1 in announced
    bot.send_message.assert_awaited()
    text = bot.send_message.call_args.kwargs["text"]
    assert "Alice" in text


async def test_digest_skips_shifts_outside_window(cfg_digest, engine_with_helfen):
    now = datetime(2026, 5, 22, 16, 0)
    client = AsyncMock(spec=EngelsystemClient)
    # Starts 30 min from now — beyond the 10 min lookahead.
    client.shifts_at = AsyncMock(
        return_value=[_shift_at("2026-05-22T16:30:00+00:00")]
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    announced: set[int] = set()

    count = await digest_once(
        bot=bot, config=cfg_digest, client=client, announced=announced, now=now
    )

    assert count == 0
    assert announced == set()
    bot.send_message.assert_not_awaited()


async def test_digest_does_not_reannounce(cfg_digest, engine_with_helfen):
    now = datetime(2026, 5, 22, 16, 0)
    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(
        return_value=[_shift_at("2026-05-22T16:05:00+00:00")]
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    announced: set[int] = {1}  # already announced

    count = await digest_once(
        bot=bot, config=cfg_digest, client=client, announced=announced, now=now
    )

    assert count == 0
    bot.send_message.assert_not_awaited()


async def test_digest_survives_http_failure(cfg_digest, engine_with_helfen):
    now = datetime(2026, 5, 22, 16, 0)
    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(side_effect=RuntimeError("engelsystem down"))
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    announced: set[int] = set()

    # Doesn't raise.
    count = await digest_once(
        bot=bot, config=cfg_digest, client=client, announced=announced, now=now
    )

    assert count == 0
    bot.send_message.assert_not_awaited()


async def test_digest_routes_to_helfer_handler_by_routing(engine_with_helfen):
    """Routing uses `route_category('Helfer')` — if the orga group is
    renamed in config, the digest follows."""
    cfg = AppConfig.model_validate(
        {
            "stalls": [{"name": "Crew A", "location": "X", "type": "Cocktail"}],
            "orga_groups": [
                {"name": "Volunteer-Crew", "categories": ["Helfer"]},
                {"name": "Zentrale", "categories": ["Sonstiges"], "default": True},
            ],
            "locations": {"X": 12},
            "shift_digest": {"enabled": True},
        }
    )
    # Re-register the test member under the renamed orga group.
    engine = engine_with_helfen
    with Session(engine) as s:
        repo.upsert_registration(s, Registration(chat_id=8, group_name="Volunteer-Crew"))

    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(
        return_value=[_shift_at("2026-05-22T16:05:00+00:00", id=99)]
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    await digest_once(
        bot=bot, config=cfg, client=client,
        announced=set(), now=datetime(2026, 5, 22, 16, 0),
    )

    # Member of "Volunteer-Crew" (chat_id=8) gets the DM.
    recipients = [c.kwargs["chat_id"] for c in bot.send_message.await_args_list]
    assert 8 in recipients


async def test_digest_skips_shifts_with_bad_start(cfg_digest, engine_with_helfen):
    now = datetime(2026, 5, 22, 16, 0)
    client = AsyncMock(spec=EngelsystemClient)
    client.shifts_at = AsyncMock(
        return_value=[{"id": 5, "starts_at": "not-a-timestamp"}]
    )
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    announced: set[int] = set()

    count = await digest_once(
        bot=bot, config=cfg_digest, client=client, announced=announced, now=now
    )

    assert count == 0
    assert announced == set()


# --- AppConfig.shift_digest defaults ------------------------------------


def test_app_config_shift_digest_defaults_to_disabled(config):
    """The default fixture (which doesn't specify shift_digest) should
    leave it off."""
    assert config.shift_digest.enabled is False


def test_app_config_shift_digest_parses_time_strings():
    cfg = AppConfig.model_validate(
        {
            "stalls": [],
            "orga_groups": [{"name": "Z", "categories": ["x"], "default": True}],
            "shift_digest": {
                "enabled": True,
                "window_start": "18:00",
                "window_end": "02:30",
            },
        }
    )
    assert cfg.shift_digest.window_start == time(18, 0)
    assert cfg.shift_digest.window_end == time(2, 30)
