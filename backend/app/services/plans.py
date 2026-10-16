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
    minimum_frequency_hours: int | None
    daily_credit_budget: int | None


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(
        products=3, pincodes=5, minimum_frequency_hours=168, daily_credit_budget=100
    ),
    "pro": PlanLimits(
        products=25, pincodes=100, minimum_frequency_hours=3, daily_credit_budget=1000
    ),
    "brand": PlanLimits(
        products=None,
        pincodes=None,
        minimum_frequency_hours=None,
        daily_credit_budget=None,
    ),
}
FREQUENCY_HOURS = {"3h": 3, "6h": 6, "12h": 12, "daily": 24, "weekly": 168}


def limits_for(plan: str) -> PlanLimits:
    return PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])


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


async def daily_credits_used(session: AsyncSession, user_id: str) -> int:
    """Total credits recorded in the ledger since UTC midnight."""
    from ..models.checks import CreditLedger

    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = await session.scalar(
        select(func.coalesce(func.sum(CreditLedger.credits), 0)).where(
            CreditLedger.user_id == user_id, CreditLedger.created_at >= start
        )
    )
    return int(total or 0)


def credits_exhausted(plan: str, used: int) -> bool:
    budget = limits_for(plan).daily_credit_budget
    return budget is not None and used >= budget
