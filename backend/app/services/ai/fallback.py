"""Deterministic rule-based AI fallback.

Used whenever Gemini is not configured or fails. Every sentence is built from
the measured context numbers, so the app stays useful with zero API keys.
"""

from __future__ import annotations

import re

from .base import (
    AlertRuleOut,
    ChatAction,
    ChatEvidence,
    ChatOut,
    RecommendationCandidate,
    RecommendOut,
    ReviewsOut,
    SummaryOut,
)

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_BELOW_RE = re.compile(r"below\s+(\d+(?:\.\d+)?)")
_PINCODE_RE = re.compile(r"^[1-9]\d{5}$")
# "out of stock in South Delhi", "OOS at 110017 and 110016 on blinkit".
_AREA_RE = re.compile(
    r"(?:out[\s-]of[\s-]stock|stockouts?|oos)\s+(?:in|at|across|around|for)\s+"
    r"(?P<areas>.+?)(?:\s+on\s+\w+)?\s*[.!?]*$",
    re.IGNORECASE,
)
_AREA_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|&|/)\s*", re.IGNORECASE)
_NOT_AN_AREA = {"any", "all", "every", "some", "a", "the"}


def _fmt_money(value: float | None) -> str:
    return "n/a" if value is None else f"₹{value:.2f}"


def guarded_price_target(context: dict) -> float | None:
    """Rival-matching price clamped to the product's pricing rules.

    None when the clamped price would not actually lower the current price.
    """
    current = context.get("avg_price")
    rival = context.get("cheapest_rival")
    if current is None or rival is None:
        return None
    pricing = context.get("pricing") or {}
    bounds = [float(rival)]
    if pricing.get("floor_price") is not None:
        bounds.append(float(pricing["floor_price"]))
    if pricing.get("cost_price") is not None and pricing.get("min_margin_pct") is not None:
        bounds.append(
            float(pricing["cost_price"]) * (1 + float(pricing["min_margin_pct"]) / 100)
        )
    if pricing.get("max_change_pct") is not None:
        bounds.append(float(current) * (1 - float(pricing["max_change_pct"]) / 100))
    target = round(max(bounds), 2)
    return target if target < float(current) - 0.005 else None


def parse_rule_areas(text: str) -> tuple[list[str], list[str]] | None:
    """Areas and pincodes named after "out of stock in …", or None."""
    match = _AREA_RE.search(text.strip())
    if match is None:
        return None
    areas: list[str] = []
    pincodes: list[str] = []
    for part in _AREA_SPLIT_RE.split(match.group("areas")):
        cleaned = part.strip(" .")
        if not cleaned or cleaned.lower() in _NOT_AN_AREA:
            continue
        if _PINCODE_RE.match(cleaned):
            pincodes.append(cleaned)
        elif not cleaned.lower().startswith(("any ", "all ", "every ")):
            areas.append(cleaned)
    if not areas and not pincodes:
        return None
    return areas, pincodes


def _gap_pct(context: dict) -> float | None:
    avg_price = context.get("avg_price")
    rival = context.get("cheapest_rival")
    if avg_price is None or rival is None or rival == 0:
        return None
    return round((avg_price / rival - 1) * 100, 1)


class FallbackAIProvider:
    name = "fallback"

    async def summarize(self, context: dict) -> SummaryOut:
        name = context.get("product_name", "This product")
        in_stock = context.get("in_stock")
        total = context.get("total_pins")
        oos_pins: list[str] = context.get("oos_pins", [])
        gap = _gap_pct(context)
        sentences = [
            (
                f"{name} averages {_fmt_money(context.get('avg_price'))} across "
                f"{total or 0} checked pins with {in_stock or 0} in stock."
            )
        ]
        rival = context.get("cheapest_rival")
        if rival is not None:
            if gap is not None and gap > 0:
                sentences.append(
                    f"The cheapest rival offer is {_fmt_money(rival)}, "
                    f"about {gap}% below your average price."
                )
            else:
                sentences.append(
                    f"The cheapest rival offer is {_fmt_money(rival)}; your "
                    "pricing is competitive."
                )
        if oos_pins:
            preview = ", ".join(oos_pins[:4])
            more = "" if len(oos_pins) <= 4 else f" (+{len(oos_pins) - 4} more)"
            sentences.append(
                f"Out of stock in {len(oos_pins)} pin(s): {preview}{more} — "
                "prioritise restock and listing checks there."
            )
        if context.get("hot_zone_count"):
            sentences.append(
                f"{context['hot_zone_count']} hot zone(s) of clustered "
                "out-of-stock pins need attention."
            )
        return SummaryOut(summary_text=" ".join(sentences))

    async def recommend(self, context: dict) -> RecommendOut:
        candidates: list[RecommendationCandidate] = []
        oos_pins: list[str] = context.get("oos_pins", [])
        platforms = context.get("oos_platforms") or context.get("platforms") or []
        if oos_pins:
            priority = "high" if len(oos_pins) >= 3 else "medium"
            where = f" on {', '.join(platforms)}" if platforms else ""
            candidates.append(
                RecommendationCandidate(
                    priority=priority,
                    action_text=(
                        f"Check restock and listing health{where} for "
                        f"out-of-stock pins {', '.join(oos_pins[:5])}."
                    ),
                    impact_text=(
                        "Recovering availability in these pins wins back "
                        "quick-commerce sales before rivals fill the gap."
                    ),
                    evidence={"oos_pins": oos_pins, "platforms": platforms},
                )
            )
        gap = _gap_pct(context)
        if gap is not None and gap >= 5:
            target = guarded_price_target(context)
            rival_text = _fmt_money(context.get("cheapest_rival"))
            if target is not None:
                action = (
                    f"Move your price to {_fmt_money(target)} (from "
                    f"{_fmt_money(context.get('avg_price'))}); you are {gap}% above "
                    f"the cheapest rival ({rival_text})."
                )
            else:
                action = (
                    f"Review pricing: your average is {gap}% above the cheapest "
                    f"rival ({rival_text}), and your pricing rules leave no room "
                    "to match it."
                )
            candidates.append(
                RecommendationCandidate(
                    priority="medium",
                    action_text=action,
                    impact_text=(
                        "Closing the gap within your floor and margin rules can "
                        "lift conversion on price-sensitive pins."
                    ),
                    evidence={
                        "avg_price": context.get("avg_price"),
                        "cheapest_rival": context.get("cheapest_rival"),
                        "gap_pct": gap,
                        "proposed_price": target,
                    },
                )
            )
        rating = context.get("rating")
        if rating is not None and rating < 4.2:
            candidates.append(
                RecommendationCandidate(
                    priority="low",
                    action_text=(
                        f"Average rating is {rating:.1f}; inspect recent "
                        "reviews for recurring quality or delivery complaints."
                    ),
                    impact_text="Improving ratings protects visibility in platform ranking.",
                    evidence={"rating": rating},
                )
            )
        failed = context.get("failed_pins") or 0
        if failed:
            candidates.append(
                RecommendationCandidate(
                    priority="low",
                    action_text=(
                        f"{failed} check(s) failed on the latest run; re-run them "
                        "to fill the gaps in the heatmap."
                    ),
                    impact_text="Failed checks leave those pins without fresh data.",
                    evidence={"failed_pins": failed},
                )
            )
        stale = context.get("stale_pins") or 0
        if stale:
            candidates.append(
                RecommendationCandidate(
                    priority="low",
                    action_text=(
                        f"{stale} pin(s) have stale checks; run a fresh check "
                        "to restore heatmap confidence."
                    ),
                    impact_text="Fresh data keeps recommendations and alerts accurate.",
                    evidence={"stale_pins": stale},
                )
            )
        if not candidates:
            candidates.append(
                RecommendationCandidate(
                    priority="low",
                    action_text=(
                        "No urgent issues detected; keep the weekly check "
                        "cadence to maintain coverage."
                    ),
                    impact_text="Steady monitoring prevents surprise stockouts.",
                    evidence={"avg_price": context.get("avg_price")},
                )
            )
        return RecommendOut(recommendations=candidates[:3])

    async def reviews(self, context: dict) -> ReviewsOut:
        loves: list[str] = []
        complaints: list[str] = []
        total = context.get("total_pins") or 0
        in_stock = context.get("in_stock") or 0
        if total and in_stock / total >= 0.8:
            loves.append("Consistent availability across most checked pins")
        gap = _gap_pct(context)
        if gap is not None and gap <= 0:
            loves.append("Competitive pricing versus the cheapest rival")
        rating = context.get("rating")
        if rating is not None and rating >= 4.3:
            loves.append("Strong average product rating")
        if context.get("oos_pins"):
            complaints.append("Out-of-stock pockets in specific pincodes")
        if gap is not None and gap >= 5:
            complaints.append("Priced above rivals on some platforms")
        if rating is not None and rating < 4.2:
            complaints.append("Mixed ratings feedback from customers")
        if not loves and not complaints:
            loves.append("Steady performance across price and stock signals")
        return ReviewsOut(loves=loves[:4], complaints=complaints[:4])

    async def chat(
        self, context: dict, message: str, history: list[dict]
    ) -> ChatOut:
        del history  # the rule-based answer only needs the current message
        text = message.lower()
        name = context.get("product_name", "your product")
        domain_keywords = (
            "price", "stock", "oos", "out of", "availability", "heatmap",
            "pin", "pincode", "run", "check", "weekly", "competitor", "rival",
            "summary", "recommend", "product", "credit", "rating", "eta",
            "delivery", "shelf", "dashboard", "first", "today", "priority",
            "left", "remaining", "plan",
        )
        if not any(keyword in text for keyword in domain_keywords):
            return ChatOut(
                reply=(
                    "I can only help with your ShelfSense data — prices, stock, "
                    "heatmaps, check runs, and weekly insights. Try asking about "
                    f"{name}'s price gap or out-of-stock pins."
                )
            )
        evidence: list[ChatEvidence] = []
        actions: list[ChatAction] = []
        product_id = context.get("product_id")
        parts: list[str] = []
        if any(k in text for k in ("price", "cost", "expensive", "cheap")):
            avg_price = context.get("avg_price")
            rival = context.get("cheapest_rival")
            gap = _gap_pct(context)
            parts.append(
                f"{name} averages {_fmt_money(avg_price)}; the cheapest rival "
                f"is {_fmt_money(rival)}."
            )
            if gap is not None:
                parts.append(f"That is a {gap}% gap versus the rival price.")
            evidence.append(ChatEvidence(metric="avg_price", value=avg_price))
            evidence.append(ChatEvidence(metric="cheapest_rival", value=rival))
        if any(k in text for k in ("stock", "oos", "out of", "availability")):
            parts.append(
                f"{name}: {context.get('in_stock', 0)} of {context.get('total_pins', 0)} "
                "checked pins are in stock."
            )
            oos_pins = context.get("oos_pins", [])
            if oos_pins:
                parts.append("Out of stock in: " + ", ".join(oos_pins[:5]) + ".")
            evidence.append(
                ChatEvidence(metric="in_stock", value=context.get("in_stock"))
            )
        if any(k in text for k in ("heatmap", "zone", "area")):
            parts.append(
                f"Heatmap: {context.get('in_stock', 0)} in stock, "
                f"{len(context.get('oos_pins', []))} out of stock, "
                f"{context.get('price_gap_pins', 0)} price-gap, "
                f"{context.get('stale_pins', 0)} stale pins."
            )
            if product_id:
                actions.append(
                    ChatAction(label="Open heatmap", path=f"/heatmap?product={product_id}")
                )
        if any(k in text for k in ("weekly", "week", "trend", "compare")):
            this_price = context.get("this_week_avg_price")
            last_price = context.get("last_week_avg_price")
            parts.append(
                f"Weekly average price moved from {_fmt_money(last_price)} to "
                f"{_fmt_money(this_price)}."
            )
            evidence.append(
                ChatEvidence(metric="this_week_avg_price", value=this_price)
            )
        if any(k in text for k in ("recommend", "should", "advice", "next", "first", "priority")):
            top = (context.get("recommendation_preview") or "").strip()
            parts.append(top or "Run a fresh check to generate recommendations.")
            if product_id:
                actions.append(
                    ChatAction(
                        label="View recommendations",
                        path=f"/products/{product_id}",
                    )
                )
        if any(k in text for k in ("credit", "left", "remaining", "plan")):
            used = context.get("credits_used_today", 0)
            budget = context.get("daily_credit_budget")
            plan = context.get("plan", "free")
            parts.append(
                f"You've used {used} credits today on the {plan.title()} plan"
                + (f"; {max(budget - used, 0)} of {budget} remain." if budget else " with no daily limit.")
                + " Each pincode check uses one credit."
            )
            evidence.append(ChatEvidence(metric="credits_used_today", value=used))
        elif any(k in text for k in ("run", "check", "scan")):
            parts.append(
                "Start a check from the product page: pick platforms and "
                "pincodes, then launch; progress streams live and the heatmap "
                "updates when it finishes."
            )
        if not parts:
            parts.append(
                f"{name}: {_fmt_money(context.get('avg_price'))} average, "
                f"{context.get('in_stock', 0)}/{context.get('total_pins', 0)} "
                "pins in stock."
            )
            evidence.append(ChatEvidence(metric="avg_price", value=context.get("avg_price")))
        return ChatOut(reply=" ".join(parts), actions=actions, evidence=evidence)

    async def parse_alert_rule(self, text: str) -> AlertRuleOut:
        lowered = text.lower()
        if any(
            word in lowered
            for word in ("out of stock", "out-of-stock", "stockout", "oos")
        ):
            if "rival" in lowered or "competitor" in lowered:
                return AlertRuleOut(
                    kind="rival_oos",
                    rule_text=text,
                    rule_json={"trigger": "competitor out of stock"},
                )
            located = parse_rule_areas(text)
            if located is not None:
                areas, pincodes = located
                return AlertRuleOut(
                    kind="oos_area",
                    rule_text=text,
                    rule_json={"areas": areas, "pincodes": pincodes},
                )
            return AlertRuleOut(
                kind="oos_any", rule_text=text, rule_json={"trigger": "seller oos"}
            )
        if "rating" in lowered:
            match = _BELOW_RE.search(lowered) or _PERCENT_RE.search(lowered)
            threshold = float(match.group(1)) if match else 4.0
            return AlertRuleOut(
                kind="rating_below",
                threshold=threshold,
                rule_text=text,
                rule_json={"trigger": "rating below"},
            )
        if "price" in lowered:
            match = _PERCENT_RE.search(lowered)
            threshold = float(match.group(1)) if match else None
            direction = "drop" if any(
                word in lowered for word in ("drop", "down", "fall", "decrease")
            ) else "change"
            return AlertRuleOut(
                kind="price_change_pct",
                threshold=threshold,
                rule_text=text,
                rule_json={"trigger": f"price {direction}"},
            )
        return AlertRuleOut(
            kind="custom", rule_text=text, rule_json={"trigger": "custom"}
        )
