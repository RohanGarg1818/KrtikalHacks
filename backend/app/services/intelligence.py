"""AI orchestration: context building, generation, and recommendation guardrails.

Every generated artefact is grounded in measured numbers (KPIs, heatmap,
weekly stats) and passes pure-Python guardrails before being persisted.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.checks import ChangeEvent, CheckResult
from ..models.intelligence import AISummary, Recommendation, ReviewInsight
from ..models.product import Competitor, Product
from .ai import get_ai_provider, with_fallback
from .ai.base import RecommendationCandidate
from .heatmap import compute_heatmap
from .insights import compute_overview, compute_weekly

logger = logging.getLogger("shelfsense.intelligence")

RECOMMENDATION_LIMIT = 5
ACTION_TEXT_LIMIT = 2000
IMPACT_TEXT_LIMIT = 2000
MIN_ACTION_LENGTH = 10
RECENT_EVENTS_LIMIT = 10
VALID_PRIORITIES = {"high", "medium", "low"}
HIGH_PRIORITY_MIN_OOS_PINS = 3
HIGH_PRIORITY_MIN_GAP_PCT = 5.0

BANNED_PHRASES = (
    "price fix",
    "price-fix",
    "fix prices",
    "cartel",
    "collude",
    "collusion",
    "sabotage",
    "fake review",
    "brigade",
    "blackmail",
    "undercut illegally",
)

_RUPEE_PRICE_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_PRESCRIPTIVE_PCT_RE = re.compile(
    r"(drop|reduce|cut|lower|decrease|raise|increase|hike)\D{0,40}?"
    r"(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


async def build_context(
    session: AsyncSession, product_id: str, *, now: datetime | None = None
) -> dict | None:
    """Grounding numbers for the AI providers; None when there is no data."""
    product = await session.get(Product, product_id)
    if product is None:
        return None
    now = now if now is not None else datetime.now(UTC)
    overview = await compute_overview(session, product_id, now=now)
    weekly = await compute_weekly(session, product_id, now=now)
    heatmap = await compute_heatmap(session, product_id, now=now)
    pins = heatmap["pins"]
    oos_pins = [pin["pincode"] for pin in pins if pin["status"] == "out_of_stock"]
    oos_platforms = sorted(
        {pin["platform"] for pin in pins if pin["status"] == "out_of_stock"}
    )
    top_pending = await session.scalar(
        select(Recommendation.action_text)
        .where(
            Recommendation.product_id == product_id,
            Recommendation.status == "pending",
        )
        .order_by(Recommendation.created_at.desc())
        .limit(1)
    )
    recent_events = list(
        (
            await session.scalars(
                select(ChangeEvent)
                .where(ChangeEvent.product_id == product_id)
                .order_by(ChangeEvent.detected_at.desc())
                .limit(RECENT_EVENTS_LIMIT)
            )
        ).all()
    )
    kpis = overview["kpis"]
    return {
        "product_id": product_id,
        "product_name": product.name,
        "avg_price": kpis["avg_price"]["value"],
        "cheapest_rival": kpis["cheapest_rival"]["value"],
        "in_stock": kpis["in_stock"]["value"],
        "total_pins": kpis["in_stock"]["total"],
        "rating": kpis["rating"]["value"],
        "price_gap_pins": heatmap["summary"]["price_gap"],
        "stale_pins": heatmap["summary"]["stale"],
        "hot_zone_count": len(heatmap["hot_zones"]),
        "oos_pins": oos_pins,
        "oos_platforms": oos_platforms,
        "all_pins": sorted({pin["pincode"] for pin in pins}),
        "this_week_avg_price": weekly["this_week"]["avg_price"],
        "last_week_avg_price": weekly["last_week"]["avg_price"],
        "this_week_oos_count": weekly["this_week"]["oos_count"],
        "recommendation_preview": top_pending or "",
        "recent_changes": [
            {
                "kind": row.kind,
                "platform": row.platform,
                "pincode": row.pincode,
                "old_value": row.old_value,
                "new_value": row.new_value,
            }
            for row in recent_events
        ],
    }


def _stats_from_context(context: dict) -> dict:
    return {
        "oos_pins": len(context.get("oos_pins") or []),
        "max_gap_pct": _gap_from_context(context),
    }


def _gap_from_context(context: dict) -> float | None:
    avg_price = context.get("avg_price")
    rival = context.get("cheapest_rival")
    if avg_price is None or rival is None or rival == 0:
        return None
    return round((avg_price / rival - 1) * 100, 2)


def _pricing_violation(
    text: str, pricing: dict, *, current_price: float | None
) -> str | None:
    """Return a reason when text proposes a price outside the product's rules.

    Brief Section 8: drop recommendations below floor_price, below
    cost_price*(1+min_margin_pct/100), or changing price more than
    max_change_pct.
    """
    floor_price = pricing.get("floor_price")
    cost_price = pricing.get("cost_price")
    min_margin_pct = pricing.get("min_margin_pct")
    max_change_pct = pricing.get("max_change_pct")
    for raw in _RUPEE_PRICE_RE.findall(text):
        price = float(raw)
        if floor_price is not None and price < float(floor_price):
            return f"price {price} is below floor_price {floor_price}"
        if cost_price is not None and min_margin_pct is not None:
            minimum = float(cost_price) * (1 + float(min_margin_pct) / 100)
            if price < minimum - 0.005:
                return (
                    f"price {price} is below cost+margin minimum {minimum:.2f}"
                )
        if current_price and max_change_pct is not None:
            change_pct = abs(price / current_price - 1) * 100
            if change_pct > float(max_change_pct) + 0.005:
                return (
                    f"price {price} changes {change_pct:.1f}% from current "
                    f"{current_price} (max {max_change_pct}%)"
                )
    for match in _PRESCRIPTIVE_PCT_RE.finditer(text):
        pct = float(match.group(2))
        if max_change_pct is not None and pct > float(max_change_pct) + 0.005:
            return (
                f"proposes {pct}% price change above max_change_pct {max_change_pct}"
            )
    return None


def apply_recommendation_guardrails(
    candidates: list[RecommendationCandidate],
    *,
    pending_texts: set[str],
    context: dict,
    pricing: dict | None = None,
) -> list[dict]:
    """Pure filter: ban-list, price rules, truncation, priority clamp, dedupe."""
    stats = _stats_from_context(context)
    allowed_high = (
        stats["oos_pins"] >= HIGH_PRIORITY_MIN_OOS_PINS
        or (
            stats["max_gap_pct"] is not None
            and stats["max_gap_pct"] >= HIGH_PRIORITY_MIN_GAP_PCT
        )
    )
    pricing = pricing or {}
    current_price = context.get("avg_price")
    cleaned: list[dict] = []
    seen = {text.strip().lower() for text in pending_texts}
    for candidate in candidates:
        action = candidate.action_text.strip()
        impact = candidate.impact_text.strip()
        combined = f"{action} {impact}".lower()
        if any(phrase in combined for phrase in BANNED_PHRASES):
            logger.info("guardrail dropped banned recommendation: %s", action[:60])
            continue
        if len(action) < MIN_ACTION_LENGTH:
            continue
        violation = _pricing_violation(
            f"{action} {impact}", pricing, current_price=current_price
        )
        if violation is not None:
            logger.info(
                "guardrail dropped price-violating recommendation (%s): %s",
                violation,
                action[:60],
            )
            continue
        priority = candidate.priority.strip().lower()
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        if priority == "high" and not allowed_high:
            priority = "medium"
        normalized = action.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(
            {
                "priority": priority,
                "action_text": action[:ACTION_TEXT_LIMIT],
                "impact_text": impact[:IMPACT_TEXT_LIMIT],
                "evidence": dict(candidate.evidence),
            }
        )
        if len(cleaned) >= RECOMMENDATION_LIMIT:
            break
    return cleaned


async def generate_summary(
    session: AsyncSession, product: Product, *, run_id: str | None = None
) -> AISummary | None:
    context = await build_context(session, product.id)
    if context is None or not await has_check_data(session, product.id):
        return None
    provider = get_ai_provider()
    result, source = await with_fallback(provider, "summarize", context)
    summary = AISummary(
        product_id=product.id,
        run_id=run_id,
        summary_text=result.summary_text[:4000],
        evidence={
            "avg_price": context.get("avg_price"),
            "cheapest_rival": context.get("cheapest_rival"),
            "in_stock": context.get("in_stock"),
            "total_pins": context.get("total_pins"),
            "oos_pins": context.get("oos_pins"),
        },
        source=source,
    )
    session.add(summary)
    await session.commit()
    await session.refresh(summary)
    return summary


async def generate_recommendations(
    session: AsyncSession, product: Product
) -> tuple[list[Recommendation], str]:
    context = await build_context(session, product.id)
    if context is None or not await has_check_data(session, product.id):
        return [], "fallback"
    provider = get_ai_provider()
    result, source = await with_fallback(provider, "recommend", context)
    pending = list(
        (
            await session.scalars(
                select(Recommendation).where(
                    Recommendation.product_id == product.id,
                    Recommendation.status == "pending",
                )
            )
        ).all()
    )
    pending_texts = {row.action_text for row in pending}
    room = RECOMMENDATION_LIMIT - len(pending)
    if room <= 0:
        return [], source
    cleaned = apply_recommendation_guardrails(
        result.recommendations,
        pending_texts=pending_texts,
        context=context,
        pricing={
            "floor_price": product.floor_price,
            "cost_price": product.cost_price,
            "min_margin_pct": product.min_margin_pct,
            "max_change_pct": product.max_change_pct,
        },
    )[:room]
    rows = [
        Recommendation(
            product_id=product.id,
            priority=item["priority"],
            action_text=item["action_text"],
            impact_text=item["impact_text"],
            evidence=item["evidence"],
        )
        for item in cleaned
    ]
    if rows:
        session.add_all(rows)
        await session.commit()
        for row in rows:
            await session.refresh(row)
    return rows, source


async def refresh_review_insights(
    session: AsyncSession, product: Product
) -> tuple[ReviewInsight | None, str]:
    context = await build_context(session, product.id)
    if context is None or not await has_check_data(session, product.id):
        return None, "fallback"
    provider = get_ai_provider()
    result, source = await with_fallback(provider, "reviews", context)
    existing = await session.scalar(
        select(ReviewInsight).where(
            ReviewInsight.product_id == product.id,
            ReviewInsight.competitor_id.is_(None),
        )
    )
    if existing is not None:
        existing.loves = result.loves[:10]
        existing.complaints = result.complaints[:10]
        existing.updated_at = datetime.now(UTC)
        row = existing
    else:
        row = ReviewInsight(
            product_id=product.id,
            competitor_id=None,
            loves=result.loves[:10],
            complaints=result.complaints[:10],
        )
        session.add(row)
    await session.commit()
    await session.refresh(row)
    return row, source


async def has_check_data(session: AsyncSession, product_id: str) -> bool:
    return (
        await session.scalar(
            select(CheckResult.id)
            .where(
                CheckResult.product_id == product_id,
                CheckResult.status == "ok",
            )
            .limit(1)
        )
    ) is not None


async def refresh_intelligence(
    session: AsyncSession, product_id: str, *, run_id: str | None = None
) -> None:
    """Post-run hook: refresh summary, recommendations, and review insights."""
    product = await session.get(Product, product_id)
    if product is None or not await has_check_data(session, product_id):
        return
    try:
        await generate_summary(session, product, run_id=run_id)
        await generate_recommendations(session, product)
        await refresh_review_insights(session, product)
    except Exception:
        logger.exception("intelligence refresh failed for product %s", product_id)


async def decide_recommendation(
    session: AsyncSession,
    recommendation: Recommendation,
    *,
    decision: str,
    decided_via: str = "web",
) -> Recommendation:
    recommendation.status = decision
    recommendation.decided_via = decided_via
    recommendation.decided_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(recommendation)
    return recommendation


async def clear_pending_recommendations(
    session: AsyncSession, product_id: str
) -> int:
    result = await session.execute(
        delete(Recommendation).where(
            Recommendation.product_id == product_id,
            Recommendation.status == "pending",
        )
    )
    await session.commit()
    return result.rowcount or 0


async def list_competitor_names(
    session: AsyncSession, product_id: str
) -> dict[str, str]:
    rows = list(
        (
            await session.scalars(
                select(Competitor).where(Competitor.product_id == product_id)
            )
        ).all()
    )
    return {row.id: row.name for row in rows}
