"""Shared fixtures. Sets test env vars before any unifestbestellbot import
so `Settings()` does not look for a real .env file."""

import os

os.environ.setdefault("TELEGRAM_TOKEN", "12345:test-token")
os.environ.setdefault("DEVELOPER_CHAT_ID", "100")
os.environ.setdefault("UPDATES_CHANNEL_ID", "200")
os.environ.setdefault("ENGELSYSTEM_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("CONFIG_PATH", "./config.yaml")

import pytest  # noqa: E402
from unifestbestellbot.config import AppConfig  # noqa: E402


@pytest.fixture
def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "stalls": [
                {"location": "Innenhof", "type": "Cocktail"},
                {"location": "Außenbereich", "type": "Bier"},
                {"location": "Eingang", "type": "Tickets", "hidden": True},
            ],
            "orga_groups": [
                {"name": "Finanz", "categories": ["Geld"]},
                {"name": "BiMi", "categories": ["Bier", "Cocktail", "Becher"]},
                {"name": "Helfen", "categories": ["Helfer"]},
                {"name": "Zentrale", "categories": ["Sonstiges"], "default": True},
            ],
            "locations": {
                "Innenhof": 12,
                "Außenbereich": 15,
            },
        }
    )
