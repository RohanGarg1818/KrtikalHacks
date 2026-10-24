"""Shared check cache: one live fetch per app + pincode + product, reused by every user.

If two sellers track "Guitar" in 110001 on Zepto, the second one within the TTL gets the
first one's result instead of a new TinyFish run (no credits, no load on the site). Only
successful results are stored; failures and blocks always go to the inner client. A per-key
lock makes concurrent requests for the same key share one live call. In-process memory, so
it resets on restart (``CHECK_CACHE_TTL_SECONDS``, 0 = off).
"""

from __future__ import annotations

import asyncio
import re
import time

from .agent import AgentTrace
from .base import CheckResult, FetchResult, SearchHit, StepCallback, TinyFishClient

_SPACE_RE = re.compile(r"\s+")
# Module-level: the client wrapper is rebuilt per run, the cache must outlive it.
_ITEMS: dict[tuple[str, ...], tuple[float, CheckResult]] = {}
_LOCKS: dict[tuple[str, ...], asyncio.Lock] = {}


def clear_cache() -> None:
    _ITEMS.clear()
    _LOCKS.clear()


def cache_key(platform: str, pincode: str, query: str, url: str | None) -> tuple[str, ...]:
    return (platform, pincode.strip(), _SPACE_RE.sub(" ", query.strip().lower()), url or "")


class SharedCheckCache:
    """Wraps a client: serve a recent identical check from memory instead of re-fetching."""

    def __init__(self, inner: TinyFishClient, *, ttl_seconds: float) -> None:
        self.inner = inner
        self.ttl = ttl_seconds
        self.mode = inner.mode

    def _fresh(self, key: tuple[str, ...]) -> tuple[float, CheckResult] | None:
        item = _ITEMS.get(key)
        if item is None:
            return None
        if time.monotonic() - item[0] > self.ttl:
            del _ITEMS[key]
            return None
        return item

    async def check(
        self,
        platform: str,
        pincode: str,
        query: str,
        url: str | None = None,
        on_step: StepCallback | None = None,
    ) -> CheckResult:
        key = cache_key(platform, pincode, query, url)
        async with _LOCKS.setdefault(key, asyncio.Lock()):
            item = self._fresh(key)
            if item is None:
                result = await self.inner.check(platform, pincode, query, url=url, on_step=on_step)
                _ITEMS[key] = (time.monotonic(), result)
                return result
        stored_at, result = item
        age_min = int((time.monotonic() - stored_at) // 60)
        trace = AgentTrace(goal="Shared cache", mode=self.mode, on_step=on_step)
        await trace.step("done", "Reused a recent check", f"fetched {age_min} min ago for another seller")
        return result.model_copy(
            update={
                "credits_used": 0,
                "raw": {
                    **result.raw,
                    "source": "shared_cache",
                    "cache_age_seconds": int(time.monotonic() - stored_at),
                    "agent": trace.as_raw(),
                },
            }
        )

    async def search(self, query: str) -> list[SearchHit]:
        return await self.inner.search(query)

    async def fetch(self, url: str) -> FetchResult:
        return await self.inner.fetch(url)
