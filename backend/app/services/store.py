"""The seller's own ShelfSense Store: a mock storefront whose price and stock the seller sets.

Every change is written as an instant, free "check" (a finished run with one result per
pincode on the ``store`` platform), so the heatmap, change detection, recommendations,
alerts and Telegram all treat it like any other app. Store stock-outs alert as urgent.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import utcnow
from ..models.checks import CheckResult, CheckRun
from ..models.product import Product, ProductPincode, StoreListing

STORE = "store"


async def store_pincodes(session: AsyncSession, product_id: str) -> list[str]:
    return sorted(
        (
            await session.scalars(
                select(ProductPincode.pincode).where(
                    ProductPincode.product_id == product_id,
                    ProductPincode.platform == STORE,
                )
            )
        ).all()
    )


async def record_snapshot(session: AsyncSession, product: Product, listing: StoreListing) -> str:
    """Write the listing's current price/stock as a finished run, then run the alert pipeline."""
    from .runner import post_run_hooks  # local import avoids a cycle

    pins = await store_pincodes(session, product.id)
    now = utcnow()
    run = CheckRun(
        id=str(uuid4()),
        product_id=product.id,
        trigger="store",
        status="done",
        total_jobs=len(pins),
        done_jobs=len(pins),
        failed_jobs=0,
        credits_used=0,
        started_at=now,
        finished_at=now,
    )
    session.add(run)
    await session.flush()  # results reference the run; no ORM relationship orders the inserts
    in_stock = listing.stock > 0
    for pin in pins:
        session.add(
            CheckResult(
                run_id=run.id,
                product_id=product.id,
                competitor_id=None,
                platform=STORE,
                pincode=pin,
                in_stock=in_stock,
                price=listing.price,
                mrp=listing.mrp,
                eta_minutes=listing.eta_minutes if in_stock else None,
                status="ok",
                raw={"source": "shelfsense_store", "stock": listing.stock},
                checked_at=now,
            )
        )
    await session.commit()
    await post_run_hooks(session, run.id, product.id)
    return run.id


# Ready-made catalogue for "Load demo store" (seller-entered prices, not market data).
DEMO_STORE = [
    {"name": "Amul Pure Ghee 1 L", "brand": "Amul", "price": 615.0, "mrp": 650.0, "stock": 40},
    {"name": "Aashirvaad Shudh Chakki Atta 5 kg", "brand": "Aashirvaad", "price": 289.0, "mrp": 320.0, "stock": 25},
    {"name": "Tata Salt 1 kg", "brand": "Tata", "price": 28.0, "mrp": 30.0, "stock": 120},
    {"name": "Maggi 2-Minute Noodles Masala 12-pack", "brand": "Maggi", "price": 168.0, "mrp": 180.0, "stock": 60},
]
