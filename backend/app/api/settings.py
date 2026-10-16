"""User settings, export, and mock subscription controls."""

import csv
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.chat import ChatConversation, ChatMessage
from ..models.checks import ChangeEvent, CheckResult, CheckRun, CreditLedger
from ..models.intelligence import (
    AISummary,
    Alert,
    AlertRule,
    Recommendation,
    ReviewInsight,
)
from ..models.product import Competitor, Product, ProductListing, ProductPincode
from ..models.telegram import TelegramLink, TelegramLinkCode
from ..models.user import Subscription, User, UserSettings
from ..schemas.settings import (
    PlanChangeRequest,
    PlanChangeResponse,
    UserSettingsResponse,
    UserSettingsUpdate,
)
from ..services.plans import PLAN_LIMITS

router = APIRouter(tags=["settings"])


async def get_or_create_settings(session: AsyncSession, user_id: str) -> UserSettings:
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


@router.get("/me/settings", response_model=UserSettingsResponse)
async def get_settings(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> UserSettings:
    return await get_or_create_settings(session, user.id)


@router.patch("/me/settings", response_model=UserSettingsResponse)
async def update_settings(
    payload: UserSettingsUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserSettings:
    settings = await get_or_create_settings(session, user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await session.commit()
    await session.refresh(settings)
    return settings


@router.post("/me/plan", response_model=PlanChangeResponse)
async def change_plan(
    payload: PlanChangeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PlanChangeResponse:
    if payload.plan not in PLAN_LIMITS:
        raise HTTPException(status_code=422, detail="Unknown plan")
    subscription = await session.scalar(
        select(Subscription).where(Subscription.user_id == user.id)
    )
    if subscription is None:
        subscription = Subscription(user_id=user.id, plan=payload.plan, status="active")
        session.add(subscription)
    else:
        subscription.plan = payload.plan
        subscription.status = "active"
    await session.commit()
    return PlanChangeResponse(plan=payload.plan, status="active")


@router.get("/me/export")
async def export_data(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    rows = list(
        (
            await session.execute(
                select(
                    Product.name,
                    CheckResult.platform,
                    CheckResult.pincode,
                    CheckResult.in_stock,
                    CheckResult.price,
                    CheckResult.eta_minutes,
                    CheckResult.checked_at,
                )
                .join(Product, Product.id == CheckResult.product_id)
                .where(Product.user_id == user.id)
                .order_by(CheckResult.checked_at.desc())
            )
        ).all()
    )
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "product",
            "platform",
            "pincode",
            "in_stock",
            "price",
            "eta_minutes",
            "checked_at",
        ]
    )
    writer.writerows(rows)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=shelfsense-export.csv"},
    )


@router.delete("/me", status_code=204)
async def delete_me(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> Response:
    product_ids = select(Product.id).where(Product.user_id == user.id)
    conversation_ids = select(ChatConversation.id).where(
        ChatConversation.user_id == user.id
    )
    await session.execute(
        delete(ChatMessage).where(ChatMessage.conversation_id.in_(conversation_ids))
    )
    await session.execute(
        delete(ChatConversation).where(ChatConversation.user_id == user.id)
    )
    await session.execute(delete(CreditLedger).where(CreditLedger.user_id == user.id))
    await session.execute(
        delete(CheckResult).where(CheckResult.product_id.in_(product_ids))
    )
    await session.execute(
        delete(ChangeEvent).where(ChangeEvent.product_id.in_(product_ids))
    )
    await session.execute(
        delete(AISummary).where(AISummary.product_id.in_(product_ids))
    )
    await session.execute(delete(Alert).where(Alert.user_id == user.id))
    await session.execute(
        delete(AlertRule).where(AlertRule.product_id.in_(product_ids))
    )
    await session.execute(
        delete(Recommendation).where(Recommendation.product_id.in_(product_ids))
    )
    await session.execute(
        delete(ReviewInsight).where(ReviewInsight.product_id.in_(product_ids))
    )
    await session.execute(
        delete(TelegramLinkCode).where(TelegramLinkCode.user_id == user.id)
    )
    await session.execute(delete(TelegramLink).where(TelegramLink.user_id == user.id))
    await session.execute(
        delete(ProductListing).where(ProductListing.product_id.in_(product_ids))
    )
    await session.execute(
        delete(ProductPincode).where(ProductPincode.product_id.in_(product_ids))
    )
    await session.execute(
        delete(Competitor).where(Competitor.product_id.in_(product_ids))
    )
    await session.execute(delete(CheckRun).where(CheckRun.product_id.in_(product_ids)))
    await session.execute(delete(Product).where(Product.user_id == user.id))
    await session.execute(delete(UserSettings).where(UserSettings.user_id == user.id))
    await session.execute(delete(Subscription).where(Subscription.user_id == user.id))
    await session.delete(user)
    await session.commit()
    return Response(status_code=204)
