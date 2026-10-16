"""Deterministic rule-based AI fallback.

Used whenever Gemini is not configured or fails. Every sentence is built from
the measured context numbers, so the app stays useful with zero API keys.
"""

from __future__ import annotations

from .base import (
    ChatAction,
    ChatEvidence,
    ChatOut,
    RecommendationCandidate,
    RecommendOut,
    ReviewsOut,
    SummaryOut,
)


def _fmt_money(value: float | None) -> str:
    return "n/a" if value is None else f"₹{value:.2f}"


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
            candidates.append(
                RecommendationCandidate(
                    priority="medium",
                    action_text=(
                        f"Review pricing: your average is {gap}% above the "
                        f"cheapest rival ({_fmt_money(context.get('cheapest_rival'))})."
                    ),
                    impact_text=(
                        "Matching or selectively undercutting the rival price "
                        "can lift conversion on price-sensitive pins."
                    ),
                    evidence={
                        "avg_price": context.get("avg_price"),
                        "cheapest_rival": context.get("cheapest_rival"),
                        "gap_pct": gap,
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
            "delivery", "shelf", "dashboard",
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
                f"{context.get('in_stock', 0)} of {context.get('total_pins', 0)} "
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
                    ChatAction(label="Open heatmap", path=f"/products/{product_id}/heatmap")
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
        if any(k in text for k in ("recommend", "should", "advice", "next")):
            top = (context.get("recommendation_preview") or "").strip()
            parts.append(top or "Run a fresh check to generate recommendations.")
            if product_id:
                actions.append(
                    ChatAction(
                        label="View recommendations",
                        path=f"/products/{product_id}/overview",
                    )
                )
        if any(k in text for k in ("run", "check", "scan")):
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
