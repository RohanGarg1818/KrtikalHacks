from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.checks import CheckResult
from ..models.product import Product, ProductPincode
from ..models.user import Subscription, User
from ..schemas.me import MeResponse, ProfileResponse, UsageResponse

router = APIRouter(tags=["account"])


@router.get("/me", response_model=MeResponse)
async def get_me(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> MeResponse:
    plan = await session.scalar(
        select(Subscription.plan)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.id)
    )
    products = await session.scalar(
        select(func.count()).select_from(Product).where(Product.user_id == user.id)
    )
    pincodes = await session.scalar(
        select(func.count(func.distinct(ProductPincode.pincode)))
        .select_from(ProductPincode)
        .join(Product, Product.id == ProductPincode.product_id)
        .where(Product.user_id == user.id)
    )
    since = datetime.now(UTC) - timedelta(days=7)
    checks = await session.scalar(
        select(func.count())
        .select_from(CheckResult)
        .join(Product, Product.id == CheckResult.product_id)
        .where(Product.user_id == user.id, CheckResult.checked_at >= since)
    )
    return MeResponse(
        profile=ProfileResponse.model_validate(user),
        plan=plan or "free",
        usage=UsageResponse(
            products=products or 0, pincodes=pincodes or 0, checks_this_week=checks or 0
        ),
    )
