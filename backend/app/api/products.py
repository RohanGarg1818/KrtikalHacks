"""User-scoped product, pincode, and alert-rule endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.checks import ChangeEvent, CheckResult, CheckRun
from ..models.intelligence import (
    AISummary,
    Alert,
    AlertRule,
    Recommendation,
    ReviewInsight,
)
from ..models.product import (
    Competitor,
    Pincode,
    Product,
    ProductListing,
    ProductPincode,
)
from ..models.telegram import TelegramLink, TelegramLinkCode
from ..models.user import Subscription, User
from ..schemas.products import (
    AlertRuleInput,
    AlertRulesUpdate,
    PincodeSelection,
    ProductCard,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)
from ..services.plans import (
    enforce_frequency,
    enforce_pincode_limit,
    enforce_product_limit,
)

router = APIRouter(tags=["products"])


async def get_user_plan(session: AsyncSession, user_id: str) -> str:
    return (
        await session.scalar(
            select(Subscription.plan).where(Subscription.user_id == user_id)
        )
    ) or "free"


async def get_owned_product(
    session: AsyncSession, user_id: str, product_id: str
) -> Product:
    product = await session.scalar(
        select(Product).where(Product.id == product_id, Product.user_id == user_id)
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def card_status(result: CheckResult) -> str:
    if result.status != "ok":
        return "stale"
    if result.in_stock is False:
        return "out_of_stock"
    return "in_stock"


async def as_card(session: AsyncSession, product: Product) -> ProductCard:
    result_rows = list(
        (
            await session.scalars(
                select(CheckResult)
                .where(
                    CheckResult.product_id == product.id,
                    CheckResult.competitor_id.is_(None),
                )
                .order_by(CheckResult.checked_at.desc())
            )
        ).all()
    )
    seen: set[tuple[str, str]] = set()
    status_strip: list[dict[str, str]] = []
    for row in result_rows:
        key = (row.platform, row.pincode)
        if key in seen:
            continue
        seen.add(key)
        status_strip.append(
            {
                "platform": row.platform,
                "pincode": row.pincode,
                "status": card_status(row),
            }
        )
        if len(status_strip) == 12:
            break
    own_prices = [row.price for row in result_rows[:100] if row.price is not None]
    rival_prices = list(
        (
            await session.scalars(
                select(CheckResult.price)
                .where(
                    CheckResult.product_id == product.id,
                    CheckResult.competitor_id.is_not(None),
                    CheckResult.price.is_not(None),
                )
                .order_by(CheckResult.checked_at.desc())
                .limit(100)
            )
        ).all()
    )
    position = None
    if own_prices and rival_prices:
        position = round(
            (
                (sum(own_prices) / len(own_prices))
                / (sum(rival_prices) / len(rival_prices))
                - 1
            )
            * 100,
            2,
        )
    linked = await session.scalar(
        select(TelegramLink.id).where(TelegramLink.product_id == product.id).limit(1)
    )
    return ProductCard(
        **ProductResponse.model_validate(product).model_dump(),
        status_strip=status_strip,
        price_position_vs_avg_rival=position,
        last_checked=result_rows[0].checked_at if result_rows else None,
        telegram_connected=linked is not None,
    )


@router.get("/products", response_model=list[ProductCard])
async def list_products(
    filter: str | None = Query(default=None, pattern="^(attention|healthy|paused)$"),
    q: str | None = Query(default=None, max_length=300),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProductCard]:
    statement = (
        select(Product)
        .where(Product.user_id == user.id)
        .order_by(Product.created_at.desc())
    )
    if q:
        statement = statement.where(Product.name.ilike(f"%{q}%"))
    products = list((await session.scalars(statement)).all())
    cards = [await as_card(session, product) for product in products]
    if filter == "paused":
        cards = [card for card in cards if card.paused]
    elif filter == "attention":
        cards = [
            card
            for card in cards
            if not card.paused
            and any(item["status"] != "in_stock" for item in card.status_strip)
        ]
    elif filter == "healthy":
        cards = [
            card
            for card in cards
            if not card.paused
            and all(item["status"] == "in_stock" for item in card.status_strip)
        ]
    return cards


@router.post(
    "/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED
)
async def create_product(
    payload: ProductCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Product:
    plan = await get_user_plan(session, user.id)
    product_count = await session.scalar(
        select(func.count()).select_from(Product).where(Product.user_id == user.id)
    )
    enforce_product_limit(plan, product_count or 0)
    enforce_frequency(plan, payload.check_frequency)
    product = Product(user_id=user.id, **payload.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Product:
    return await get_owned_product(session, user.id, product_id)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    payload: ProductUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Product:
    product = await get_owned_product(session, user.id, product_id)
    changes = payload.model_dump(exclude_unset=True)
    if "check_frequency" in changes:
        enforce_frequency(
            await get_user_plan(session, user.id), changes["check_frequency"]
        )
    for field, value in changes.items():
        setattr(product, field, value)
    await session.commit()
    await session.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await get_owned_product(session, user.id, product_id)
    competitor_ids = select(Competitor.id).where(Competitor.product_id == product_id)
    run_ids = select(CheckRun.id).where(CheckRun.product_id == product_id)
    # Ordered cleanup is portable to SQLite and Postgres without relying on DB-specific cascades.
    await session.execute(
        delete(CheckResult).where(CheckResult.product_id == product_id)
    )
    await session.execute(
        delete(ChangeEvent).where(ChangeEvent.product_id == product_id)
    )
    await session.execute(delete(AISummary).where(AISummary.product_id == product_id))
    await session.execute(delete(Alert).where(Alert.product_id == product_id))
    await session.execute(delete(AlertRule).where(AlertRule.product_id == product_id))
    await session.execute(
        delete(Recommendation).where(Recommendation.product_id == product_id)
    )
    await session.execute(
        delete(ReviewInsight).where(ReviewInsight.product_id == product_id)
    )
    await session.execute(
        delete(TelegramLinkCode).where(TelegramLinkCode.product_id == product_id)
    )
    await session.execute(
        delete(TelegramLink).where(TelegramLink.product_id == product_id)
    )
    await session.execute(
        delete(ProductListing).where(ProductListing.product_id == product_id)
    )
    await session.execute(
        delete(ProductPincode).where(ProductPincode.product_id == product_id)
    )
    await session.execute(delete(Competitor).where(Competitor.id.in_(competitor_ids)))
    await session.execute(delete(CheckRun).where(CheckRun.id.in_(run_ids)))
    await session.execute(
        delete(Product).where(Product.id == product_id, Product.user_id == user.id)
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/products/{product_id}/pincodes", response_model=PincodeSelection)
async def replace_pincodes(
    product_id: str,
    payload: PincodeSelection,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PincodeSelection:
    await get_owned_product(session, user.id, product_id)
    pincodes = sorted(set(payload.pincodes))
    platforms = sorted(set(payload.platforms))
    existing = await session.scalar(
        select(func.count()).select_from(Pincode).where(Pincode.code.in_(pincodes))
    )
    if existing != len(pincodes):
        raise HTTPException(status_code=422, detail="One or more pincodes are unknown")
    enforce_pincode_limit(await get_user_plan(session, user.id), len(pincodes))
    await session.execute(
        delete(ProductPincode).where(ProductPincode.product_id == product_id)
    )
    session.add_all(
        ProductPincode(product_id=product_id, pincode=code, platform=platform)
        for code in pincodes
        for platform in platforms
    )
    await session.commit()
    return PincodeSelection(platforms=platforms, pincodes=pincodes)


@router.put("/products/{product_id}/alert-rules", response_model=list[AlertRuleInput])
async def replace_alert_rules(
    product_id: str,
    payload: AlertRulesUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AlertRuleInput]:
    await get_owned_product(session, user.id, product_id)
    await session.execute(delete(AlertRule).where(AlertRule.product_id == product_id))
    session.add_all(
        AlertRule(product_id=product_id, **rule.model_dump()) for rule in payload.rules
    )
    await session.commit()
    return payload.rules
