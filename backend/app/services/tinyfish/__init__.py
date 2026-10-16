"""TinyFish integration: client interface, mock implementation, HTTP skeleton."""

from .base import (
    CheckResult,
    FetchResult,
    SearchHit,
    TinyFishClient,
    TinyFishError,
    get_tinyfish_client,
)
from .mock_client import MockTinyFishClient

__all__ = [
    "CheckResult",
    "FetchResult",
    "MockTinyFishClient",
    "SearchHit",
    "TinyFishClient",
    "TinyFishError",
    "get_tinyfish_client",
]
