"""Application configuration and credential-derived feature flags."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    mock_mode: bool | None = None
    database_url: str = "sqlite+aiosqlite:///./shelfsense.db"
    tinyfish_api_key: str = ""
    tinyfish_agent_base_url: str = ""
    tinyfish_search_base_url: str = ""
    tinyfish_fetch_base_url: str = ""
    tinyfish_max_concurrency: int = Field(default=2, ge=1)
    tinyfish_agent_timeout_seconds: float = Field(default=120.0, gt=0)
    gemini_api_key: str = ""
    gemini_model: str = ""
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_storage_bucket: str = "screenshots"
    frontend_origin: str = "http://localhost:3000"

    @field_validator("mock_mode", mode="before")
    @classmethod
    def blank_mock_mode_is_auto(cls, value: object) -> object:
        # `.env.example` ships `MOCK_MODE=`; an empty value means "decide from the keys".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def default_database_url(cls, value: str | None) -> str:
        return value or "sqlite+aiosqlite:///./shelfsense.db"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def effective_mock_mode(self) -> bool:
        """True when nothing talks to a real provider.

        `MOCK_MODE=true` forces every integration into mock mode and `false`
        reports real mode; left blank, it reflects whether any key-driven
        integration is live. Integrations are switched individually by their keys.
        """
        if self.mock_mode is not None:
            return self.mock_mode
        return not (self.tinyfish_enabled or self.gemini_enabled or self.storage_enabled)

    @property
    def tinyfish_enabled(self) -> bool:
        return bool(self.tinyfish_api_key) and self.mock_mode is not True

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key) and self.mock_mode is not True

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def storage_enabled(self) -> bool:
        return (
            bool(self.supabase_url and self.supabase_service_key)
            and self.mock_mode is not True
        )

    @property
    def dev_auth_enabled(self) -> bool:
        """Every request maps to the demo user: never in production, never with a JWT secret."""
        return not self.is_production and not self.supabase_jwt_secret

    @property
    def auth_mode(self) -> str:
        return "dev" if self.dev_auth_enabled else "supabase"

    @property
    def tinyfish_mode(self) -> str:
        return "live" if self.tinyfish_enabled else "simulated"

    def validate_for_startup(self) -> None:
        """Refuse to boot a production process that could not authenticate anyone."""
        if self.is_production and not self.supabase_jwt_secret:
            raise RuntimeError("SUPABASE_JWT_SECRET is required when APP_ENV=production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
