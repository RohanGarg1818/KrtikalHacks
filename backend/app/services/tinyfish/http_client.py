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
from .agent import AgentTrace, format_rupees
from .base import CheckResult, FetchResult, SearchHit, StepCallback, TinyFishError
from .goals import (
    agent_target_url,
    build_check_goal,
    build_fetch_goal,
    build_search_goal,
    site_domain,
)

logger = logging.getLogger("shelfsense.tinyfish")

REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_AGENT_TIMEOUT_SECONDS = 120.0
CONNECT_TIMEOUT_SECONDS = 5.0
RETRY_BACKOFF_SECONDS = 0.5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class HttpTinyFishClient:
    """Async TinyFish client with timeouts.

    Agent runs are attempted once (the runner owns the single retry so a job
    is billed at most twice); search and fetch retry once on transient
    failures. Agent progress is reported as coarse steps so the live mode
    drives the same agent console as the simulator.
    """

    mode = "live"

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.tinyfish_api_key
        self.agent_base_url = settings.tinyfish_agent_base_url
        self.search_base_url = settings.tinyfish_search_base_url
        self.fetch_base_url = settings.tinyfish_fetch_base_url
        self.agent_timeout = float(
            getattr(
                settings, "tinyfish_agent_timeout_seconds", DEFAULT_AGENT_TIMEOUT_SECONDS
            )
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS
            ),
            headers={
                # TODO(tinyfish): confirm the auth scheme (Bearer? X-API-Key?).
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def check(
        self,
        platform: str,
        pincode: str,
        query: str,
        url: str | None = None,
        on_step: StepCallback | None = None,
    ) -> CheckResult:
        if not self.agent_base_url:
            raise TinyFishError(
                "TINYFISH_AGENT_BASE_URL is not configured", retryable=False
            )
        target_url = agent_target_url(url)
        goal = build_check_goal(platform, pincode, query, target_url)
        trace = AgentTrace(goal=goal, mode="live", on_step=on_step)
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
        await trace.step("session", "Starting browser session", trace.session_id)
        await trace.step(
            "navigate",
            f"Opening {site_domain(platform)}",
            f"Agent working on pincode {pincode}",
        )
        try:
            data = await self._request_json(
                self.agent_base_url,
                body,
                attempts=1,
                timeout=httpx.Timeout(
                    self.agent_timeout, connect=CONNECT_TIMEOUT_SECONDS
                ),
            )
            result = self._map_check(data)
        except TinyFishError as exc:
            await trace.step("error", str(exc))
            exc.agent = trace.as_raw()
            raise
        await trace.step(
            "extract", "Reading price, stock and delivery time", _extract_detail(result)
        )
        if result.screenshot_bytes or result.screenshot_url:
            await trace.step("screenshot", "Capturing evidence screenshot")
        plural = "" if result.credits_used == 1 else "s"
        await trace.step("done", "Check complete", f"{result.credits_used} credit{plural}")
        result.raw = {**result.raw, "agent": trace.as_raw()}
        return result

    async def search(self, query: str) -> list[SearchHit]:
        if not self.search_base_url:
            raise TinyFishError(
                "TINYFISH_SEARCH_BASE_URL is not configured", retryable=False
            )
        body = {"query": query, "goal": build_search_goal(query)}
        data = await self._request_json(self.search_base_url, body)
        return self._map_search(data)

    async def fetch(self, url: str) -> FetchResult:
        if not self.fetch_base_url:
            raise TinyFishError(
                "TINYFISH_FETCH_BASE_URL is not configured", retryable=False
            )
        body = {"url": url, "goal": build_fetch_goal(url)}
        data = await self._request_json(self.fetch_base_url, body)
        return self._map_fetch(url, data)

    async def _request_json(
        self,
        endpoint: str,
        body: dict,
        *,
        attempts: int = 2,
        timeout: httpx.Timeout | None = None,
    ) -> dict:
        # TODO(tinyfish): confirm the HTTP method (POST assumed) and path joining.
        last_error: TinyFishError | None = None
        options = {} if timeout is None else {"timeout": timeout}
        for attempt in range(attempts):
            try:
                response = await self._client.post(endpoint, json=body, **options)
            except httpx.TimeoutException as exc:
                # A timed-out agent may already have spent its budget; another
                # attempt would only double the wait.
                raise TinyFishError(
                    f"TinyFish timed out ({exc.__class__.__name__})", retryable=False
                ) from exc
            except httpx.HTTPError as exc:
                last_error = TinyFishError(f"TinyFish transport error: {exc}")
                logger.warning("%s (attempt %d)", last_error, attempt + 1)
            else:
                if response.status_code in RETRYABLE_STATUS_CODES:
                    last_error = TinyFishError(
                        f"TinyFish returned HTTP {response.status_code}"
                    )
                    logger.warning("%s (attempt %d)", last_error, attempt + 1)
                elif response.status_code >= 400:
                    raise TinyFishError(
                        f"TinyFish rejected the request: HTTP {response.status_code}",
                        retryable=False,
                    )
                else:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise TinyFishError(
                            "TinyFish returned non-JSON content",
                            retryable=False,
                            credits_used=1,
                        ) from exc
                    if not isinstance(payload, dict):
                        raise TinyFishError(
                            "TinyFish response was not a JSON object",
                            retryable=False,
                            credits_used=1,
                        )
                    return payload
            if attempt + 1 < attempts:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
        raise last_error or TinyFishError("TinyFish request failed")

    def _map_check(self, data: dict) -> CheckResult:
        # TODO(tinyfish): replace this guessed mapping with the documented
        # response fields once docs.tinyfish.ai is available.
        screenshot_bytes = None
        inline = data.get("screenshot_base64")
        if isinstance(inline, str) and inline:
            try:
                screenshot_bytes = base64.b64decode(inline)
            except (ValueError, TypeError) as exc:
                raise TinyFishError(
                    "Invalid screenshot_base64 payload",
                    retryable=False,
                    credits_used=_as_int_or_none(data.get("credits_used")) or 1,
                ) from exc
        return CheckResult(
            product=_as_str_or_none(data.get("product")),
            in_stock=_as_bool_or_none(data.get("in_stock")),
            price=_as_float_or_none(data.get("price")),
            mrp=_as_float_or_none(data.get("mrp")),
            eta_minutes=_as_int_or_none(data.get("eta_minutes")),
            rating=_as_float_or_none(data.get("rating")),
            screenshot_bytes=screenshot_bytes,
            # TODO(tinyfish): confirm the screenshot format (PNG assumed).
            screenshot_content_type="image/png",
            screenshot_url=_as_str_or_none(data.get("screenshot_url")),
            credits_used=_as_int_or_none(data.get("credits_used")) or 1,
            raw=data,
        )

    def _map_search(self, data: dict) -> list[SearchHit]:
        # TODO(tinyfish): confirm the results array field name and item shape.
        results = data.get("results")
        if not isinstance(results, list):
            raise TinyFishError(
                "TinyFish search response has no results list", retryable=False
            )
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


def _extract_detail(result: CheckResult) -> str:
    parts: list[str] = []
    if result.price is not None:
        parts.append(format_rupees(result.price))
    if result.mrp is not None:
        parts.append(f"MRP {format_rupees(result.mrp)}")
    if result.in_stock is not None:
        parts.append("In stock" if result.in_stock else "Out of stock")
    if result.eta_minutes is not None:
        parts.append(f"{result.eta_minutes} min")
    return " · ".join(parts) or "Product not found"


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
