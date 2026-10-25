"""My Store: the seller's own mock storefront (price and stock set by hand, alerts on stock-out)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.base import utcnow
from ..models.product import Competitor, Pincode, Product, ProductPincode, StoreListing
from ..models.telegram import TelegramLink
from ..models.user import User
from ..schemas.common import PincodeCode, Platform
from ..schemas.products import BrandName, ProductName
from ..services.competitor_discovery import discover_competitors
from ..services.plans import enforce_product_limit, minimum_frequency
from ..services.store import DEMO_STORE, STORE, record_snapshot, store_pincodes
from .products import get_owned_product, get_user_plan

router = APIRouter(tags=["store"])
DEFAULT_PINS = ("110001", "110003", "110005")
RIVALS_PER_PRODUCT = 3


class StoreItem(BaseModel):
    product_id: str
    name: str
    brand: str | None
    price: float
    mrp: float | None
    stock: int
    eta_minutes: int
    pincodes: list[str]
    telegram_connected: bool
    updated_at: datetime


class StoreProductCreate(BaseModel):
    name: ProductName
    brand: BrandName = None
    price: float = Field(gt=0)
    mrp: float | None = Field(default=None, gt=0)
    stock: int = Field(ge=0, le=1_000_000)
    pincodes: list[PincodeCode] = Field(default_factory=list, max_length=25)
    # Other apps to compare against (rivals are checked there on "Re-check now").
    apps: list[Platform] = Field(default_factory=list, max_length=5)


class StoreProductUpdate(BaseModel):
    price: float | None = Field(default=None, gt=0)
    mrp: float | None = Field(default=None, gt=0)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)


async def _item(session: AsyncSession, product: Product, listing: StoreListing) -> StoreItem:
    linked = await session.scalar(
        select(func.count()).select_from(TelegramLink).where(TelegramLink.product_id == product.id)
    )
    return StoreItem(
        product_id=product.id,
        name=product.name,
        brand=product.brand,
        price=listing.price,
        mrp=listing.mrp,
        stock=listing.stock,
        eta_minutes=listing.eta_minutes,
        pincodes=await store_pincodes(session, product.id),
        telegram_connected=bool(linked),
        updated_at=listing.updated_at,
    )


async def _default_pins(session: AsyncSession) -> list[str]:
    known = set((await session.scalars(select(Pincode.code))).all())
    pins = [p for p in DEFAULT_PINS if p in known]
    return pins or sorted(known)[:3]


async def _create(session: AsyncSession, user: User, payload: StoreProductCreate) -> StoreItem:
    plan = await get_user_plan(session, user.id)
    count = await session.scalar(
        select(func.count()).select_from(Product).where(Product.user_id == user.id)
    )
    enforce_product_limit(plan, count or 0)
    if payload.mrp is not None and payload.mrp < payload.price:
        raise HTTPException(status_code=422, detail="MRP can't be below the selling price")
    pins = list(dict.fromkeys(payload.pincodes)) or await _default_pins(session)
    known = set((await session.scalars(select(Pincode.code).where(Pincode.code.in_(pins)))).all())
    if unknown := [p for p in pins if p not in known]:
        raise HTTPException(status_code=422, detail=f"Unknown pincode(s): {', '.join(unknown)}")
    if not pins:
        raise HTTPException(status_code=422, detail="Pick at least one pincode")
    product = Product(
        user_id=user.id,
        name=payload.name,
        brand=payload.brand,
        search_query=payload.name,
        mrp=payload.mrp,
        check_frequency=minimum_frequency(plan),
    )
    session.add(product)
    await session.flush()
    for platform in [STORE, *dict.fromkeys(a for a in payload.apps if a != STORE)]:
        for pin in pins:
            session.add(ProductPincode(product_id=product.id, pincode=pin, platform=platform))
    listing = StoreListing(
        product_id=product.id, price=payload.price, mrp=payload.mrp, stock=payload.stock
    )
    session.add(listing)
    # Rivals for the competitor table; demo suggestions when TinyFish search is off.
    suggestions, _ = await discover_competitors(payload.name, payload.brand)
    for s in suggestions[:RIVALS_PER_PRODUCT]:
        session.add(
            Competitor(
                product_id=product.id,
                name=s["name"],
                platform=s.get("platform") or "zepto",
                url=s.get("url"),
                search_query=s.get("search_query"),
                confirmed=True,
            )
        )
    await session.commit()
    await record_snapshot(session, product, listing)
    return await _item(session, product, listing)


@router.get("/store", response_model=list[StoreItem])
async def list_store(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[StoreItem]:
    rows = (
        await session.execute(
            select(Product, StoreListing)
            .join(StoreListing, StoreListing.product_id == Product.id)
            .where(Product.user_id == user.id)
            .order_by(Product.created_at)
        )
    ).all()
    return [await _item(session, product, listing) for product, listing in rows]


@router.post("/store/products", response_model=StoreItem, status_code=status.HTTP_201_CREATED)
async def add_store_product(
    payload: StoreProductCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StoreItem:
    return await _create(session, user, payload)


@router.patch("/store/products/{product_id}", response_model=StoreItem)
async def update_store_product(
    product_id: str,
    payload: StoreProductUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StoreItem:
    """Change price/stock. Every change is recorded instantly; stock 0 alerts on Telegram."""
    product = await get_owned_product(session, user.id, product_id)
    listing = await session.get(StoreListing, product_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="This product isn't in your store")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(listing, field, value)
    if listing.mrp is not None and listing.mrp < listing.price:
        raise HTTPException(status_code=422, detail="MRP can't be below the selling price")
    listing.updated_at = utcnow()
    await session.commit()
    await record_snapshot(session, product, listing)
    return await _item(session, product, listing)


@router.post("/store/demo", response_model=list[StoreItem])
async def load_demo_store(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> list[StoreItem]:
    """Add the ready-made demo catalogue (skips names already in the store)."""
    existing = set(
        (
            await session.scalars(
                select(Product.name)
                .join(StoreListing, StoreListing.product_id == Product.id)
                .where(Product.user_id == user.id)
            )
        ).all()
    )
    created = []
    for item in DEMO_STORE:
        if item["name"] in existing:
            continue
        created.append(await _create(session, user, StoreProductCreate(**item)))
    return created
