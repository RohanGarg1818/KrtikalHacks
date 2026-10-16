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
    gemini_api_key: str = ""
    gemini_model: str = ""
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_storage_bucket: str = "screenshots"
    frontend_origin: str = "http://localhost:3000"

    @field_validator("database_url", mode="before")
    @classmethod
    def default_database_url(cls, value: str | None) -> str:
        return value or "sqlite+aiosqlite:///./shelfsense.db"

    @property
    def effective_mock_mode(self) -> bool:
        """Mocks are the safe default until every external integration is configured."""
        if self.mock_mode is not None:
            return self.mock_mode
        return not (self.tinyfish_api_key and self.gemini_api_key)

    @property
    def tinyfish_enabled(self) -> bool:
        return bool(self.tinyfish_api_key) and not self.effective_mock_mode

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key) and not self.effective_mock_mode

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def storage_enabled(self) -> bool:
        return (
            bool(self.supabase_url and self.supabase_service_key)
            and not self.effective_mock_mode
        )

    @property
    def dev_auth_enabled(self) -> bool:
        return not bool(self.supabase_jwt_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
