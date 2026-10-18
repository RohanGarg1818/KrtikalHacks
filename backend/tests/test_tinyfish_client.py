"""Live TinyFish client: card parsing, error mapping, check_pincode (offline)."""

from __future__ import annotations

import httpx
import pytest
from tinyfish import (
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)

from app.config import Settings
from app.services.tinyfish import MockTinyFishClient, TinyFishError
from app.services.tinyfish.tinyfish_client import (
    TinyFishLiveClient,
    check_pincode,
    map_sdk_error,
    parse_card,
    pick_card,
)

QUERY = "Amul Taaza Toned Milk 500 ml"


def _response(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, headers=headers, request=httpx.Request("POST", "https://example.test")
    )


def test_parse_card_reads_price_mrp_stock_and_eta() -> None:
    card = "8 MINS\nAmul Taaza Toned Fresh Milk\n500 ml\n₹27\n₹29\nADD"
    parsed = parse_card(card)
    assert parsed.name == "Amul Taaza Toned Fresh Milk"
    assert parsed.price == 27.0
    assert parsed.mrp == 29.0
    assert parsed.in_stock is True
    assert parsed.eta_minutes == 8


def test_parse_card_ignores_discount_amounts_and_detects_out_of_stock() -> None:
    card = "₹5 OFF\nAmul Taaza Milk\n₹1,024.50 ₹1,099\nOut of Stock"
    parsed = parse_card(card)
    assert parsed.price == 1024.5
    assert parsed.mrp == 1099.0
    assert parsed.in_stock is False
    assert parsed.name == "Amul Taaza Milk"


def test_pick_card_prefers_best_match_and_rejects_unrelated() -> None:
    cards = ["Mother Dairy Toned Milk 500 ml ₹28 ADD", "Amul Taaza Toned Milk 500 ml ₹27 ADD"]
    picked = pick_card(cards, QUERY)
    assert picked is not None and picked[0].startswith("Amul")
    assert pick_card(["Tata Salt 1 kg ₹28 ADD"], QUERY) is None
    assert pick_card([], QUERY) is None


def test_map_sdk_error_classifies_auth_credits_rate_limits_and_outages() -> None:
    auth = map_sdk_error(AuthenticationError("bad key", response=_response(401)))
    assert not auth.retryable and "TINYFISH_API_KEY" in str(auth)

    wallet = map_sdk_error(
        APIStatusError("empty", response=_response(402), status_code=402)
    )
    assert not wallet.retryable and "credits" in str(wallet)

    limited = map_sdk_error(
        RateLimitError("slow down", response=_response(429, {"Retry-After": "5"}))
    )
    assert limited.retryable

    assert map_sdk_error(InternalServerError("boom", response=_response(503))).retryable
    assert map_sdk_error(APIConnectionError("offline")).retryable


@pytest.mark.asyncio
async def test_live_client_refuses_unsupported_apps_without_calling_tinyfish() -> None:
    client = TinyFishLiveClient(Settings(tinyfish_api_key="test-key", mock_mode=False))
    with pytest.raises(TinyFishError) as caught:
        await client.check("amazon", "110017", QUERY)
    assert not caught.value.retryable


def test_live_client_requires_a_key() -> None:
    with pytest.raises(TinyFishError):
        TinyFishLiveClient(Settings(tinyfish_api_key="", mock_mode=False))


@pytest.mark.asyncio
async def test_check_pincode_returns_validated_json_with_saved_screenshot() -> None:
    result = await check_pincode(
        "blinkit", "110017", QUERY, client=MockTinyFishClient(delay=(0, 0))
    )
    assert set(result) >= {"app", "pincode", "in_stock", "price", "eta", "screenshot_url"}
    assert result["app"] == "blinkit"
    assert result["pincode"] == "110017"
    assert result["mode"] == "simulated"
    assert result["screenshot_url"].startswith("/media/screenshots/adhoc/")


@pytest.mark.asyncio
async def test_check_pincode_rejects_bad_input() -> None:
    client = MockTinyFishClient(delay=(0, 0))
    with pytest.raises(ValueError):
        await check_pincode("myntra", "110017", QUERY, client=client)
    with pytest.raises(ValueError):
        await check_pincode("blinkit", "1100", QUERY, client=client)


@pytest.mark.asyncio
async def test_live_runs_over_the_job_limit_are_refused(monkeypatch) -> None:
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models.product import Product, ProductPincode
    from app.services.runner import create_run

    settings = get_settings()
    monkeypatch.setattr(settings, "tinyfish_api_key", "test-key")
    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "tinyfish_live_max_jobs_per_run", 1)
    async with SessionLocal() as session:
        product = (await session.scalars(select(Product).where(Product.paused.is_(False)))).first()
        pairs = (
            await session.scalars(
                select(ProductPincode).where(ProductPincode.product_id == product.id)
            )
        ).all()
        with pytest.raises(HTTPException) as caught:
            await create_run(
                session,
                product,
                trigger="manual",
                platforms=sorted({pair.platform for pair in pairs}),
                pincodes=sorted({pair.pincode for pair in pairs}),
            )
    assert caught.value.detail["code"] == "live_job_limit"


def test_agent_goal_is_read_only_and_names_the_pincode() -> None:
    from app.services.tinyfish.tinyfish_client import AgentCheckOutput, build_agent_goal

    goal = build_agent_goal("zepto", "110017", QUERY, None)
    assert "110017" in goal and QUERY in goal
    for rule in ("Never click ADD", "Never log in", "checkout", "blocked=true"):
        assert rule in goal
    parsed = AgentCheckOutput.model_validate(
        {"location_set": True, "product_name": "Amul", "in_stock": True, "price": 40,
         "mrp": None, "eta_minutes": 13, "blocked": False, "notes": None}
    )
    assert parsed.price == 40.0 and parsed.eta_minutes == 13


@pytest.mark.asyncio
async def test_failed_live_check_falls_back_to_cached_result(tmp_path, monkeypatch) -> None:
    import json

    from app.services.tinyfish import demo_cache

    cache = tmp_path / "demo_results.json"
    cache.write_text(json.dumps([{
        "platform": "zepto", "pincode": "110017", "query": QUERY, "product": "Amul Taaza",
        "in_stock": True, "price": 77.0, "mrp": None, "eta_minutes": 21,
        "screenshot": None, "run_id": "r1", "checked_at": "2026-10-18T14:00:00",
    }]))
    monkeypatch.setattr(demo_cache, "CACHE_PATH", cache)
    demo_cache.load_cache.cache_clear()
    monkeypatch.setattr(demo_cache, "load_cache", lambda path=cache: tuple(json.loads(cache.read_text())))

    class Blocked:
        mode = "live"

        async def check(self, *args, **kwargs):
            raise TinyFishError("blocked", retryable=False, credits_used=1)

    fallback = demo_cache.CachedFallbackClient(Blocked(), demo=False)
    result = await fallback.check("zepto", "110017", QUERY)
    assert result.price == 77.0 and result.raw["source"] == "demo_cache"
    with pytest.raises(TinyFishError):  # nothing cached for this pincode
        await fallback.check("zepto", "110001", QUERY)
    demo = demo_cache.CachedFallbackClient(Blocked(), demo=True)
    assert (await demo.check("zepto", "110017", QUERY)).raw["reason"] == "demo mode"


FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_amazon_parser_reads_real_fetch_output() -> None:
    from app.services.tinyfish.marketplace import parse_amazon

    page = parse_amazon(
        (FIXTURES / "amazon_bhujia.txt").read_text(),
        "Haldiram's Delhi Bhujia, 200g : Amazon.in: Grocery & Gourmet Foods",
    )
    assert page.name == "Haldiram's Delhi Bhujia, 200g"
    assert page.price == 56.0 and page.in_stock is True
    assert page.mrp is None  # the ₹290 MRP on the page belongs to a 1 kg pack below
    assert page.delivery_fee == 60.0 and page.delivery_date is not None
    assert page.delivery_date.day == 20 and page.delivery_date.month == 11

    gone = parse_amazon((FIXTURES / "amazon_unavailable.txt").read_text(), "Amul Taaza Pouch")
    assert gone.in_stock is False and gone.price is None


def test_flipkart_parser_reads_real_fetch_output() -> None:
    from app.services.tinyfish.marketplace import parse_flipkart

    page = parse_flipkart((FIXTURES / "flipkart_bhujia.txt").read_text(), "{TITLE} Price in India")
    assert page.name == "Haldiram's Plain Bhujia Sev (200 g)"
    assert page.price == 53.0 and page.mrp == 58.0
    assert page.in_stock is False  # the page's button said "Notify Me"



@pytest.mark.asyncio
async def test_app_status_endpoint_lists_every_app() -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://t") as client:
        res = await client.get("/api/tinyfish/apps")
    assert res.status_code == 200
    apps = {row["platform"]: row for row in res.json()}
    assert set(apps) == {"blinkit", "zepto", "instamart", "amazon", "flipkart"}
    assert all(row["status"] in ("live", "cached", "unavailable", "simulated") for row in apps.values())
