"""TinyFish client interface.

The runner and every other service depend only on this module. All
provider-specific HTTP details live in ``http_client.py``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class CheckResult(BaseModel):
    """Validated outcome of a single price/stock check for one pincode."""

    product: str | None = None
    in_stock: bool | None = None
    price: float | None = Field(default=None, ge=0)
    mrp: float | None = Field(default=None, ge=0)
    eta_minutes: int | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    screenshot_bytes: bytes | None = None
    screenshot_url: str | None = None
    credits_used: int = Field(default=1, ge=0)
    raw: dict = Field(default_factory=dict)


class SearchHit(BaseModel):
    name: str
    url: str | None = None
    platform: str | None = None
    price: float | None = Field(default=None, ge=0)
    snippet: str | None = None
    raw: dict = Field(default_factory=dict)


class FetchResult(BaseModel):
    url: str
    status: str = "ok"
    text: str | None = None
    credits_used: int = Field(default=1, ge=0)
    raw: dict = Field(default_factory=dict)


class TinyFishError(Exception):
    """A TinyFish check, search, or fetch failed after retries."""


@runtime_checkable
class TinyFishClient(Protocol):
    async def check(
        self, platform: str, pincode: str, query: str, url: str | None = None
    ) -> CheckResult: ...

    async def search(self, query: str) -> list[SearchHit]: ...

    async def fetch(self, url: str) -> FetchResult: ...


def get_tinyfish_client() -> TinyFishClient:
    """Return the real client when fully configured, otherwise the mock."""
    from ...config import get_settings
    from .mock_client import MockTinyFishClient

    settings = get_settings()
    if settings.tinyfish_enabled:
        if not settings.tinyfish_agent_base_url:
            raise TinyFishError(
                "TINYFISH_AGENT_BASE_URL must be set when the TinyFish API key is "
                "enabled; see .env.example"
            )
        from .http_client import HttpTinyFishClient

        return HttpTinyFishClient(settings)
    return MockTinyFishClient()
