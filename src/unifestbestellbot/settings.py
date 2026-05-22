"""Environment-backed settings. Use `get_settings()` instead of a module-level
instance so tests can populate the environment before the first access."""

from functools import lru_cache

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    telegram_token: str
    developer_chat_id: int
    updates_channel_id: int

    engelsystem_api_key: str = ""
    engelsystem_base_url: HttpUrl = Field(
        default_factory=lambda: HttpUrl("https://helfen.unifest-karlsruhe.de/api/v0-beta/")
    )

    database_url: str = "sqlite:///./bot.db"
    config_path: str = "./config.yaml"
    web_bind: str = "0.0.0.0:8000"
    log_level: str = "INFO"
    log_dir: str = "./logs"
    log_retention_days: int = 14


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
