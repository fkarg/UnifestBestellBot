"""Environment-backed settings. Use `get_settings()` instead of a module-level
instance so tests can populate the environment before the first access."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, HttpUrl, field_validator
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

    # Display/window timezone. Stored datetimes are naive UTC (see
    # models.now_utc); this is only used to convert them for human-facing
    # output (/history, the shift digest) and to interpret the digest's
    # operational window. Set explicitly so behaviour does not depend on
    # the VM's ambient timezone.
    timezone: str = "Europe/Berlin"

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, v: str) -> str:
        # Fail fast at startup on a typo'd zone rather than later as a
        # ZoneInfoNotFoundError inside /history or the digest loop. Raise
        # ValueError so pydantic surfaces it as a ValidationError.
        try:
            ZoneInfo(v)
        except Exception as e:
            raise ValueError(f"unknown timezone {v!r}") from e
        return v

    def local_tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
