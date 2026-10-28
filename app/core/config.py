from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str  # required, no default: it may contain credentials
    mongodb_db: str = "tickethub"
    booking_hold_minutes: int = Field(default=15, ge=1)

    jwt_secret: str = Field(min_length=32)  # required, no default
    access_token_minutes: int = Field(default=15, ge=1)  # R2.2
    refresh_token_days: int = Field(default=7, ge=1)  # R2.2


@lru_cache
def get_settings() -> Settings:
    return Settings()
