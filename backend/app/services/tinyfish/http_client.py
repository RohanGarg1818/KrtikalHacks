"""Real TinyFish HTTP client.

This is the ONLY file allowed to know TinyFish's wire format. Every request
shape, header, and response field below is a best-effort placeholder and must
be confirmed against docs.tinyfish.ai before the client is enabled with a real
TINYFISH_API_KEY. Base URLs come from settings; nothing is hard-coded.

TODO(tinyfish): confirm from docs.tinyfish.ai
  1. Agent endpoint path, HTTP method, and authentication header/scheme.
  2. Agent request body fields (goal text, platform, pincode, target URL,
     output schema hints, screenshot capture flag).
  3. Agent response JSON field names and their mapping onto CheckResult,
     including where the screenshot arrives (inline base64 vs URL) and where
     the consumed credits are reported.
  4. Search endpoint path/body/response mapping used by search().
  5. Fetch endpoint path/body/response mapping used by fetch().
  6. Timeout budget, retryable status codes (429/5xx?), and any rate-limit
     headers that should drive backoff.
"""

from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from ...config import Settings
from .base import CheckResult, FetchResult, SearchHit, TinyFishError
from .goals import build_check_goal, build_fetch_goal, build_search_goal

logger = logging.getLogger("shelfsense.tinyfish")

REQUEST_TIMEOUT_SECONDS = 30.0
RETRY_BACKOFF_SECONDS = 0.5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class HttpTinyFishClient:
    """Async TinyFish client with timeouts and one retry on transient failures."""

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.tinyfish_api_key
        self.agent_base_url = settings.tinyfish_agent_base_url
        self.search_base_url = settings.tinyfish_search_base_url
        self.fetch_base_url = settings.tinyfish_fetch_base_url
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=5.0),
            headers={
                # TODO(tinyfish): confirm the auth scheme (Bearer? X-API-Key?).
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def check(
        self, platform: str, pincode: str, query: str, url: str | None = None
    ) -> CheckResult:
        if not self.agent_base_url:
            raise TinyFishError("TINYFISH_AGENT_BASE_URL is not configured")
        # Non-http(s) URLs are internal identity placeholders from the runner;
        # they exist only to keep mock results distinct, so the real agent
        # never sees them and falls back to searching by query.
        target_url = (
            url if url and url.startswith(("http://", "https://")) else None
        )
        goal = build_check_goal(platform, pincode, query, target_url)
        body = {
            # TODO(tinyfish): confirm body field names for the agent endpoint.
            "goal": goal,
            "platform": platform,
            "pincode": pincode,
            "query": query,
            "url": target_url,
            "response_format": "json",
            "capture_screenshot": True,
        }
        data = await self._request_json(self.agent_base_url, body)
        return self._map_check(data)

    async def search(self, query: str) -> list[SearchHit]:
        if not self.search_base_url:
            raise TinyFishError("TINYFISH_SEARCH_BASE_URL is not configured")
        body = {"query": query, "goal": build_search_goal(query)}
        data = await self._request_json(self.search_base_url, body)
        return self._map_search(data)

    async def fetch(self, url: str) -> FetchResult:
        if not self.fetch_base_url:
            raise TinyFishError("TINYFISH_FETCH_BASE_URL is not configured")
        body = {"url": url, "goal": build_fetch_goal(url)}
        data = await self._request_json(self.fetch_base_url, body)
        return self._map_fetch(url, data)

    async def _request_json(self, endpoint: str, body: dict) -> dict:
        # TODO(tinyfish): confirm the HTTP method (POST assumed) and path joining.
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = await self._client.post(endpoint, json=body)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("TinyFish transport error (attempt %d): %s", attempt + 1, exc)
            else:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = TinyFishError(
                        f"TinyFish returned HTTP {response.status_code}"
                    )
                    logger.warning("%s (attempt %d)", last_error, attempt + 1)
                elif response.status_code >= 400:
                    raise TinyFishError(
                        f"TinyFish rejected the request: HTTP {response.status_code}"
                    )
                else:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise TinyFishError("TinyFish returned non-JSON content") from exc
                    if not isinstance(payload, dict):
                        raise TinyFishError("TinyFish response was not a JSON object")
                    return payload
            if attempt == 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        raise TinyFishError(str(last_error) if last_error else "TinyFish request failed")

    def _map_check(self, data: dict) -> CheckResult:
        # TODO(tinyfish): replace this guessed mapping with the documented
        # response fields once docs.tinyfish.ai is available.
        screenshot_bytes = None
        inline = data.get("screenshot_base64")
        if isinstance(inline, str) and inline:
            try:
                screenshot_bytes = base64.b64decode(inline)
            except (ValueError, TypeError) as exc:
                raise TinyFishError("Invalid screenshot_base64 payload") from exc
        return CheckResult(
            product=_as_str_or_none(data.get("product")),
            in_stock=_as_bool_or_none(data.get("in_stock")),
            price=_as_float_or_none(data.get("price")),
            mrp=_as_float_or_none(data.get("mrp")),
            eta_minutes=_as_int_or_none(data.get("eta_minutes")),
            rating=_as_float_or_none(data.get("rating")),
            screenshot_bytes=screenshot_bytes,
            screenshot_url=_as_str_or_none(data.get("screenshot_url")),
            credits_used=_as_int_or_none(data.get("credits_used")) or 1,
            raw=data,
        )

    def _map_search(self, data: dict) -> list[SearchHit]:
        # TODO(tinyfish): confirm the results array field name and item shape.
        results = data.get("results")
        if not isinstance(results, list):
            raise TinyFishError("TinyFish search response has no results list")
        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            hits.append(
                SearchHit(
                    name=str(item["name"]),
                    url=_as_str_or_none(item.get("url")),
                    platform=_as_str_or_none(item.get("platform")),
                    price=_as_float_or_none(item.get("price")),
                    snippet=_as_str_or_none(item.get("snippet")),
                    raw=item,
                )
            )
        return hits

    def _map_fetch(self, url: str, data: dict) -> FetchResult:
        # TODO(tinyfish): confirm the fetch response shape.
        return FetchResult(
            url=url,
            status=str(data.get("status") or "ok"),
            text=_as_str_or_none(data.get("text")),
            credits_used=_as_int_or_none(data.get("credits_used")) or 1,
            raw=data,
        )


def _as_str_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


def _as_float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _as_int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool_or_none(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None
