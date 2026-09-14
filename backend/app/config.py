"""Application settings, loaded from the environment."""

from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: PostgresDsn

    # Shared secret for the administrative HTTP API. When unset the admin routes
    # are not mounted at all, so a deployment that never configures one has no
    # administrative surface rather than an unprotected one.
    admin_api_token: str | None = None

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process.

    Tests that change the environment must call ``get_settings.cache_clear()``.
    """
    return Settings()  # type: ignore[call-arg]
