"""Read-only catalog endpoints plus per-product selection and listing links."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..db import get_session
from ..deps import get_current_user
from ..models.product import Pincode, ProductListing, ProductPincode
from ..models.telegram import TelegramLinkCode
from ..models.user import User
from ..schemas.products import AlertRuleInput, PincodeSelection
from ..services.ai import get_ai_provider, with_fallback
from ..services.plans import PLAN_LIMITS
from ..services.telegram import redeem_link_code
from .products import get_owned_product, get_user_plan

router = APIRouter(tags=["catalog"])

PLATFORMS = ["blinkit", "zepto", "instamart", "amazon", "flipkart"]


class PincodeOut(BaseModel):
    code: str
    area_name: str
    city: str
    lat: float
    lng: float


class PlanLimitsOut(BaseModel):
    plan: str
    products: int | None
    pincodes: int | None
    minimum_frequency_hours: int | None
    daily_credit_budget: int | None


class PlansResponse(BaseModel):
    current: str
    plans: list[PlanLimitsOut]
    platforms: list[str]


class ListingItem(BaseModel):
    platform: str
    url: str | None = Field(default=None, max_length=1000)


class ListingsUpdate(BaseModel):
    listings: list[ListingItem]


class SimulateLinkRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    chat_type: str = "personal"


class AlertRuleParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@router.get("/pincodes", response_model=list[PincodeOut])
async def list_pincodes(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[PincodeOut]:
    rows = await session.scalars(select(Pincode).order_by(Pincode.code))
    return [
        PincodeOut(
            code=row.code, area_name=row.area_name, city=row.city, lat=row.lat, lng=row.lng
        )
        for row in rows
    ]


@router.get("/plans", response_model=PlansResponse)
async def list_plans(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PlansResponse:
    return PlansResponse(
        current=await get_user_plan(session, user.id),
        plans=[
            PlanLimitsOut(
                plan=name,
                products=limits.products,
                pincodes=limits.pincodes,
                minimum_frequency_hours=limits.minimum_frequency_hours,
                daily_credit_budget=limits.daily_credit_budget,
            )
            for name, limits in PLAN_LIMITS.items()
        ],
        platforms=PLATFORMS,
    )


@router.get("/products/{product_id}/pincodes", response_model=PincodeSelection)
async def get_pincode_selection(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PincodeSelection:
    await get_owned_product(session, user.id, product_id)
    rows = (
        await session.execute(
            select(ProductPincode.pincode, ProductPincode.platform).where(
                ProductPincode.product_id == product_id
            )
        )
    ).all()
    # model_construct skips the non-empty validation meant for writes; a new product has none.
    pincodes = sorted({row.pincode for row in rows})
    platforms = sorted({row.platform for row in rows})
    return PincodeSelection.model_construct(platforms=platforms, pincodes=pincodes)


@router.get("/products/{product_id}/listings", response_model=list[ListingItem])
async def get_listings(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ListingItem]:
    await get_owned_product(session, user.id, product_id)
    rows = await session.scalars(
        select(ProductListing)
        .where(ProductListing.product_id == product_id)
        .order_by(ProductListing.platform)
    )
    return [ListingItem(platform=row.platform, url=row.url) for row in rows]


@router.put("/products/{product_id}/listings", response_model=list[ListingItem])
async def replace_listings(
    product_id: str,
    payload: ListingsUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ListingItem]:
    await get_owned_product(session, user.id, product_id)
    await session.execute(
        delete(ProductListing).where(ProductListing.product_id == product_id)
    )
    items = [item for item in payload.listings if item.platform in PLATFORMS]
    session.add_all(
        ProductListing(product_id=product_id, platform=item.platform, url=item.url)
        for item in items
    )
    await session.commit()
    return items


@router.post("/products/{product_id}/alert-rules/parse", response_model=AlertRuleInput)
async def parse_alert_rule(
    product_id: str,
    payload: AlertRuleParseRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AlertRuleInput:
    """Turn a plain-English rule into a structured one; the client saves it via PUT."""
    await get_owned_product(session, user.id, product_id)
    rule, _source = await with_fallback(get_ai_provider(), "parse_alert_rule", payload.text)
    return AlertRuleInput(
        kind=rule.kind,
        threshold=rule.threshold,
        rule_text=rule.rule_text or payload.text,
        rule_json=rule.rule_json,
    )


@router.post("/products/{product_id}/telegram/simulate-link", status_code=204)
async def simulate_telegram_link(
    product_id: str,
    payload: SimulateLinkRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> None:
    """Mock mode only: redeem a link code as if the bot had received `/start <code>`."""
    if settings.telegram_enabled:
        raise HTTPException(status_code=409, detail="A real Telegram bot is configured")
    await get_owned_product(session, user.id, product_id)
    code = await session.get(TelegramLinkCode, payload.code)
    if code is None or code.product_id != product_id or code.user_id != user.id:
        raise HTTPException(status_code=404, detail="Link code not found")
    is_group = payload.chat_type == "group"
    link = await redeem_link_code(
        session,
        code_value=payload.code,
        chat_id=f"demo-{'group' if is_group else 'chat'}-{user.id[:8]}",
        chat_title="Demo sales group" if is_group else f"{user.name} (demo)",
    )
    if link is None:
        raise HTTPException(status_code=422, detail="Link code expired or already used")
