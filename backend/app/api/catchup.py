"""Mochi's "while you were away" recap: what moved since the seller was last online."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.checks import CheckResult, CheckRun
from ..models.intelligence import Alert, Recommendation
from ..models.product import Product
from ..models.user import User
from ..services.heatmap import take_latest
from ..services.intelligence import recommendation_kind

router = APIRouter(tags=["catch-up"])

# Ignore sub-rupee noise when calling a price "moved".
PRICE_EPSILON = 0.5


class ProductChange(BaseModel):
    product_id: str
    name: str
    price_before: float | None
    price_now: float | None
    price_change_pct: float | None
    went_out: list[str]
    came_back: list[str]
    out_now: int
    pairs_now: int
    alerts: int
    headline: str


class RecVerdict(BaseModel):
    id: str
    product_id: str
    product_name: str
    kind: str
    priority: str
    action_text: str
    verdict: str  # approve | skip
    reason: str
    is_new: bool


class CatchUpResponse(BaseModel):
    since: datetime
    now: datetime
    runs: int
    new_alerts: int
    unread_alerts: int
    products: list[ProductChange]
    recommendations: list[RecVerdict]


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _pair(row: CheckResult) -> str:
    return f"{row.platform.capitalize()} {row.pincode}"


def _verdict(kind: str, priority: str, evidence: dict) -> tuple[str, str]:
    """Mochi's advice: approve what is safe and urgent, skip what isn't worth a tap yet."""
    if kind == "margin_risk":
        return "skip", "Matching this rival would push you below your safe floor — hold your price."
    if kind == "price":
        gap = evidence.get("gap_pct")
        if isinstance(gap, (int, float)) and gap > 50:
            return "approve", f"You're {gap:.0f}% above the cheapest rival — shoppers will notice. The new price stays inside your guardrails."
        return "approve", "The new price stays inside your guardrails and closes the gap."
    if kind == "restock":
        return "approve", "You're losing orders in these pincodes right now — fix stock first."
    if kind == "recheck":
        return "approve", "Some checks failed or are stale; a re-check is cheap and fixes the blind spots."
    if priority == "low":
        return "skip", "Low urgency — safe to leave for later."
    if kind == "rating":
        return "skip", "Worth a look this week, but it won't cost you sales today."
    return ("approve", "High impact — worth doing now.") if priority == "high" else ("skip", "Nice to have; not urgent.")


@router.get("/catch-up", response_model=CatchUpResponse)
async def get_catch_up(
    since: datetime | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CatchUpResponse:
    now = datetime.now(UTC)
    if since is None:
        since = now - timedelta(hours=24)
    elif since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    since = max(since, now - timedelta(days=30))

    products = list(
        (await session.scalars(select(Product).where(Product.user_id == user.id))).all()
    )
    names = {p.id: p.name for p in products}

    runs = await session.scalar(
        select(func.count())
        .select_from(CheckRun)
        .join(Product, Product.id == CheckRun.product_id)
        .where(Product.user_id == user.id, CheckRun.started_at >= since)
    ) or 0
    alert_rows = list(
        (
            await session.scalars(
                select(Alert).where(Alert.user_id == user.id, Alert.created_at >= since)
            )
        ).all()
    )
    unread = await session.scalar(
        select(func.count()).select_from(Alert).where(Alert.user_id == user.id, Alert.read.is_(False))
    ) or 0

    changes: list[ProductChange] = []
    for product in products:
        rows = list(
            (
                await session.scalars(
                    select(CheckResult)
                    .where(
                        CheckResult.product_id == product.id,
                        CheckResult.competitor_id.is_(None),
                        CheckResult.status == "ok",
                    )
                    .order_by(CheckResult.checked_at.desc())
                )
            ).all()
        )
        key = lambda r: (r.platform, r.pincode)
        latest = take_latest(rows, key)
        before = take_latest([r for r in rows if r.checked_at < since], key)
        if not any(r.checked_at >= since for r in latest.values()):
            continue
        price_now = _avg([r.price for r in latest.values() if r.price is not None])
        price_before = _avg([r.price for r in before.values() if r.price is not None])
        pct = (
            round((price_now - price_before) / price_before * 100, 1)
            if price_now is not None and price_before and abs(price_now - price_before) >= PRICE_EPSILON
            else None
        )
        went_out = sorted(_pair(r) for k, r in latest.items() if r.in_stock is False and (k not in before or before[k].in_stock is not False))
        came_back = sorted(_pair(r) for k, r in latest.items() if r.in_stock and k in before and before[k].in_stock is False)
        out_now = sum(1 for r in latest.values() if r.in_stock is False)
        n_alerts = sum(1 for a in alert_rows if a.product_id == product.id)

        parts: list[str] = []
        if not before:
            parts.append(f"first check done — in stock in {len(latest) - out_now} of {len(latest)}")
        elif pct is not None:
            parts.append(f"your price {'rose' if pct > 0 else 'fell'} {abs(pct):.1f}% (₹{price_before:.2f} → ₹{price_now:.2f})")
        if went_out:
            parts.append(f"out of stock in {', '.join(went_out[:3])}{' +more' if len(went_out) > 3 else ''}")
        if came_back:
            parts.append(f"back in stock in {', '.join(came_back[:3])}")
        if not parts:
            parts.append("steady — no real change")
        changes.append(
            ProductChange(
                product_id=product.id,
                name=product.name,
                price_before=price_before,
                price_now=price_now,
                price_change_pct=pct,
                went_out=went_out,
                came_back=came_back,
                out_now=out_now,
                pairs_now=len(latest),
                alerts=n_alerts,
                headline="; ".join(parts),
            )
        )
    # Biggest movers first.
    changes.sort(key=lambda c: (-(len(c.went_out) + len(c.came_back)), -abs(c.price_change_pct or 0), -c.alerts))

    pending = list(
        (
            await session.scalars(
                select(Recommendation)
                .join(Product, Product.id == Recommendation.product_id)
                .where(Product.user_id == user.id, Recommendation.status == "pending")
                .order_by(Recommendation.created_at.desc())
            )
        ).all()
    )
    rank = {"high": 0, "medium": 1, "low": 2}
    verdicts = []
    for rec in pending:
        evidence = rec.evidence or {}
        kind = recommendation_kind(rec.action_text, evidence)
        verdict, reason = _verdict(kind, rec.priority, evidence)
        created = rec.created_at if rec.created_at.tzinfo else rec.created_at.replace(tzinfo=UTC)
        verdicts.append(
            RecVerdict(
                id=rec.id,
                product_id=rec.product_id,
                product_name=names.get(rec.product_id, ""),
                kind=kind,
                priority=rec.priority,
                action_text=rec.action_text,
                verdict=verdict,
                reason=reason,
                is_new=created >= since,
            )
        )
    verdicts.sort(key=lambda v: (v.verdict != "approve", rank.get(v.priority, 3), not v.is_new))

    return CatchUpResponse(
        since=since,
        now=now,
        runs=runs,
        new_alerts=len(alert_rows),
        unread_alerts=unread,
        products=changes,
        recommendations=verdicts,
    )
