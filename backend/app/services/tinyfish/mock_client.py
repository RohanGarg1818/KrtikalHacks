"""Deterministic mock TinyFish client used whenever the API key is absent.

Results are stable per (query, pincode, platform, url): ~5% of checks fail,
~15% of checks come back out of stock, and prices drift enough to produce
price gaps. Each check sleeps 0.5-2s so SSE streaming can be exercised.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import struct
import zlib

from .base import CheckResult, FetchResult, SearchHit, TinyFishError

QUICK_COMMERCE = {"blinkit", "zepto", "instamart"}
MOCK_DOMAIN = "mock.shelfsense.local"
SEARCH_PLATFORMS = ("blinkit", "zepto", "instamart", "amazon", "flipkart")


def placeholder_png() -> bytes:
    """Build a valid 1x1 grey PNG without third-party imaging libraries."""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(
            ">I", checksum
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    scanline = zlib.compress(b"\x00\x9e\x9e\x9e\xff")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(
        b"IDAT", scanline
    ) + chunk(b"IEND", b"")


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class MockTinyFishClient:
    def __init__(self, delay: tuple[float, float] = (0.5, 2.0)) -> None:
        self.delay = delay

    async def check(
        self, platform: str, pincode: str, query: str, url: str | None = None
    ) -> CheckResult:
        await self._delay()
        clean_query = " ".join(query.split())
        digest = _digest(f"{clean_query.lower()}|{pincode}|{platform}|{url or ''}")
        roll = int(digest[0:6], 16) % 100
        price_units = int(digest[6:12], 16) % 4500
        misc = int(digest[12:18], 16)
        if roll < 5:
            raise TinyFishError(
                f"Mock agent failure for {platform}/{pincode} (deterministic)"
            )
        price = round(15 + price_units / 100, 2)
        mrp = round(price + 3 + misc % 7, 2)
        if platform in QUICK_COMMERCE:
            eta_minutes = 8 + misc % 24
        else:
            eta_minutes = 1440 + misc % 2880
        return CheckResult(
            product=clean_query,
            in_stock=roll >= 20,
            price=price,
            mrp=mrp,
            eta_minutes=eta_minutes,
            rating=round(3.6 + (misc // 7) % 15 / 10, 1),
            screenshot_bytes=placeholder_png(),
            credits_used=1,
            raw={
                "mock": True,
                "platform": platform,
                "pincode": pincode,
                "url": url,
                "failure_roll": roll,
            },
        )

    async def search(self, query: str) -> list[SearchHit]:
        await self._delay()
        clean_query = " ".join(query.split())
        digest = _digest(clean_query.lower())
        hits: list[SearchHit] = []
        for index, platform in enumerate(SEARCH_PLATFORMS[:3]):
            window = digest[index * 4 : index * 4 + 4]
            price = round(15 + int(window, 16) % 4500 / 100, 2)
            slug = _digest(f"{clean_query}|{platform}")[:8]
            hits.append(
                SearchHit(
                    name=f"{clean_query} - alternative {index + 1}",
                    url=f"https://{MOCK_DOMAIN}/{platform}/{slug}",
                    platform=platform,
                    price=price,
                    snippet=f"Mock discovery result on {platform}",
                    raw={"mock": True},
                )
            )
        return hits

    async def fetch(self, url: str) -> FetchResult:
        await self._delay()
        return FetchResult(
            url=url,
            status="ok",
            text=f"Mock page content for {url}",
            credits_used=1,
            raw={"mock": True},
        )

    async def _delay(self) -> None:
        low, high = self.delay
        if high > 0:
            await asyncio.sleep(random.uniform(low, high))
