import asyncio

import pytest

from app.services.tinyfish.base import CheckResult, TinyFishError
from app.services.tinyfish.shared_cache import SharedCheckCache


class FakeClient:
    mode = "simulated"

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def check(self, platform, pincode, query, url=None, on_step=None):
        self.calls += 1
        await asyncio.sleep(0.01)
        if self.fail:
            raise TinyFishError("blocked", retryable=False)
        return CheckResult(product=query, price=99.0, in_stock=True, credits_used=1)


@pytest.mark.asyncio
async def test_same_product_is_fetched_once_across_users() -> None:
    inner = FakeClient()
    cache = SharedCheckCache(inner, ttl_seconds=7200)
    first = await cache.check("zepto", "110001", "Guitar")
    second = await SharedCheckCache(inner, ttl_seconds=7200).check("zepto", "110001", "  guitar ")
    assert inner.calls == 1
    assert first.credits_used == 1 and second.credits_used == 0
    assert second.price == 99.0 and second.raw["source"] == "shared_cache"


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_live_call() -> None:
    inner = FakeClient()
    cache = SharedCheckCache(inner, ttl_seconds=7200)
    await asyncio.gather(*(cache.check("zepto", "110001", "Guitar") for _ in range(5)))
    assert inner.calls == 1


@pytest.mark.asyncio
async def test_different_pincode_and_expired_entries_refetch() -> None:
    inner = FakeClient()
    cache = SharedCheckCache(inner, ttl_seconds=7200)
    await cache.check("zepto", "110001", "Guitar")
    await cache.check("zepto", "110003", "Guitar")
    assert inner.calls == 2
    expired = SharedCheckCache(inner, ttl_seconds=0)
    await expired.check("zepto", "110001", "Guitar")
    assert inner.calls == 3


@pytest.mark.asyncio
async def test_failures_are_never_cached() -> None:
    inner = FakeClient(fail=True)
    cache = SharedCheckCache(inner, ttl_seconds=7200)
    for _ in range(2):
        with pytest.raises(TinyFishError):
            await cache.check("blinkit", "110001", "Guitar")
    assert inner.calls == 2
