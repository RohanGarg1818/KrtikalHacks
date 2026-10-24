"""Plan limits and credit ledger helpers enforced by endpoints and the scheduler."""

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class PlanLimits:
    products: int | None
    pincodes: int | None
    competitors: int
    minimum_frequency_hours: int | None
    daily_credit_budget: int | None


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        products=3,
        pincodes=5,
        competitors=3,
        minimum_frequency_hours=168,
        daily_credit_budget=100,
    ),
    "pro": PlanLimits(
        products=25,
        pincodes=100,
        competitors=10,
        minimum_frequency_hours=3,
        daily_credit_budget=1000,
    ),
    "brand": PlanLimits(
        products=None,
        pincodes=None,
        competitors=25,
        minimum_frequency_hours=None,
        daily_credit_budget=None,
    ),
}
# Ordered fastest to slowest; the fastest entry is the floor for unlimited plans.
FREQUENCY_HOURS = {"3h": 3, "6h": 6, "12h": 12, "daily": 24, "weekly": 168}


def limits_for(plan: str) -> PlanLimits:
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


def competitor_limit(plan: str) -> int:
    """Maximum competitors tracked per product on this plan."""
    return limits_for(plan).competitors


def minimum_frequency(plan: str) -> str:
    """Fastest check frequency the plan allows (also the default for new products)."""
    floor = limits_for(plan).minimum_frequency_hours or 0
    for name, hours in FREQUENCY_HOURS.items():
        if hours >= floor:
            return name
    return "weekly"


def clamp_frequency(plan: str, frequency: str) -> str:
    """Return ``frequency`` if the plan allows it, else the plan's fastest allowed one."""
    hours = FREQUENCY_HOURS.get(frequency)
    floor = limits_for(plan).minimum_frequency_hours or 0
    if hours is None or hours < floor:
        return minimum_frequency(plan)
    return frequency


def enforce_product_limit(plan: str, current_count: int) -> None:
    limit = limits_for(plan).products
    if limit is not None and current_count >= limit:
        raise HTTPException(
            status_code=422, detail=f"The {plan} plan allows up to {limit} products"
        )


def enforce_pincode_limit(plan: str, selected_count: int) -> None:
    limit = limits_for(plan).pincodes
    if limit is not None and selected_count > limit:
        raise HTTPException(
            status_code=422,
            detail=f"The {plan} plan allows up to {limit} pincodes per product",
        )


def enforce_frequency(plan: str, frequency: str) -> None:
    hours = FREQUENCY_HOURS.get(frequency)
    if hours is None:
        raise HTTPException(status_code=422, detail="Unsupported check frequency")
    minimum = limits_for(plan).minimum_frequency_hours
    if minimum is not None and hours < minimum:
        raise HTTPException(
            status_code=422,
            detail=f"The {plan} plan supports checks no more often than weekly"
            if plan == "free"
            else f"The {plan} plan does not support that frequency",
        )


def credit_day_start(now: datetime | None = None) -> datetime:
    """Credit budgets reset at UTC midnight."""
    base = now if now is not None else datetime.now(UTC)
    return base.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


async def daily_credits_used(session: AsyncSession, user_id: str) -> int:
    """Total credits recorded in the ledger since UTC midnight."""
    from ..models.checks import CreditLedger

    total = await session.scalar(
        select(func.coalesce(func.sum(CreditLedger.credits), 0)).where(
            CreditLedger.user_id == user_id,
            CreditLedger.created_at >= credit_day_start(),
        )
    )
    return int(total or 0)


async def remaining_credits_today(
    session: AsyncSession, user_id: str, plan: str
) -> int | None:
    """Credits left in today's budget; None means the plan is unlimited."""
    budget = limits_for(plan).daily_credit_budget
    if budget is None:
        return None
    return max(budget - await daily_credits_used(session, user_id), 0)


def credits_exhausted(plan: str, used: int) -> bool:
    budget = limits_for(plan).daily_credit_budget
    return budget is not None and used >= budget


# ---------------------------------------------------------------- check frequency caps
# Automated (scheduled) checks run at most twice a day per product, whatever the plan or
# frequency setting says; manual re-checks ("Re-check now", Telegram, approving a re-check
# recommendation) are capped per product per calendar month (UTC).
SCHEDULED_CHECKS_PER_DAY = 2
SCHEDULED_MIN_INTERVAL_HOURS = 24 / SCHEDULED_CHECKS_PER_DAY
MANUAL_CHECKS_PER_MONTH = 10


def month_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


async def manual_checks_used(
    session: AsyncSession, product_id: str, now: datetime | None = None
) -> int:
    from sqlalchemy import or_

    from ..models.checks import CheckRun

    start, _ = month_bounds(now)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(CheckRun)
            .where(
                CheckRun.product_id == product_id,
                CheckRun.trigger == "manual",
                # Queued runs have no start time yet but still count.
                or_(CheckRun.started_at >= start, CheckRun.started_at.is_(None)),
            )
        )
        or 0
    )


def out_of_checks_message(resets_at: datetime) -> str:
    return (
        f"Out of check now: all {MANUAL_CHECKS_PER_MONTH} manual checks for this product are "
        f"used this month. They reset on {resets_at:%d %b}. Automatic checks still run "
        f"{SCHEDULED_CHECKS_PER_DAY} times a day."
    )


async def enforce_manual_check_limit(session: AsyncSession, product_id: str) -> int:
    """Raise 429 ``manual_check_limit`` when the month's manual checks are used; else return used."""
    used = await manual_checks_used(session, product_id)
    if used >= MANUAL_CHECKS_PER_MONTH:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "manual_check_limit",
                "message": out_of_checks_message(month_bounds()[1]),
            },
        )
    return used
