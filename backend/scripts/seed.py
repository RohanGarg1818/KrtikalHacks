"""Idempotently seed the local ShelfSense demo workspace.

Run from backend/: ``python -m scripts.seed`` after ``alembic upgrade head``.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.deps import DEMO_EMAIL
from app.models.base import utcnow
from app.models.checks import ChangeEvent, CheckResult, CheckRun
from app.models.intelligence import AISummary, Alert, Recommendation, ReviewInsight
from app.models.product import Competitor, Pincode, Product, ProductPincode
from app.models.user import Subscription, User, UserSettings

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "pincodes_delhi.csv"
SEED_CODES = [
    "110003",
    "110014",
    "110016",
    "110017",
    "110019",
    "110021",
    "110023",
    "110024",
    "110025",
    "110029",
    "110030",
    "110048",
    "110049",
    "110057",
    "110065",
]
PRODUCTS = [
    ("Amul Taaza Toned Milk 500 ml", "Amul", 26.0, 30.0),
    ("Haldiram Bhujia 200 g", "Haldiram", 47.0, 55.0),
    ("Paper Boat Aamras 250 ml", "Paper Boat", 31.0, 40.0),
]


def deterministic_result(
    product: Product, pincode: str, platform: str, competitor_offset: float, sample: int
) -> tuple[bool, float, float, int, float]:
    """Deterministic, plausible history without using a real external service."""
    key = f"{product.id}:{pincode}:{platform}:{competitor_offset}:{sample}".encode()
    value = int(hashlib.sha256(key).hexdigest()[:12], 16)
    base = (product.floor_price or 30.0) + 4.5
    price = round(base + ((value % 1400) / 100) - 7 + competitor_offset, 2)
    # Seed a visible South Delhi Blinkit availability cluster for Amul.
    cluster = (
        product.name.startswith("Amul")
        and platform == "blinkit"
        and pincode in {"110017", "110019", "110048", "110049"}
    )
    in_stock = not cluster and value % 100 >= 15
    return (
        in_stock,
        max(1.0, price),
        round(price + 5 + (value % 6), 2),
        8 + value % 24,
        round(3.8 + (value % 12) / 10, 1),
    )


async def seed() -> None:
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is not None:
            print("Demo data already exists; no changes made.")
            return

        user = User(
            name="Riya Sharma",
            email=DEMO_EMAIL,
            business_name="Riya Store",
            business_type="marketplace_seller",
            default_city="Delhi",
        )
        session.add(user)
        await session.flush()
        session.add_all(
            [
                Subscription(user_id=user.id, plan="pro", status="active"),
                UserSettings(user_id=user.id, briefing_time="09:00"),
            ]
        )
        rows: list[dict[str, str]] = []
        with DATA_PATH.open(newline="", encoding="utf-8") as csv_file:
            rows = list(csv.DictReader(csv_file))
        session.add_all(
            [
                Pincode(
                    code=row["code"],
                    area_name=row["area_name"],
                    city=row["city"],
                    lat=float(row["lat"]),
                    lng=float(row["lng"]),
                )
                for row in rows
            ]
        )
        await session.flush()

        product_rows: list[Product] = []
        for name, brand, cost, floor in PRODUCTS:
            product = Product(
                user_id=user.id,
                name=name,
                brand=brand,
                search_query=name,
                cost_price=cost,
                floor_price=floor,
                check_frequency="6h",
            )
            product_rows.append(product)
            session.add(product)
        await session.flush()

        now = utcnow()
        for product in product_rows:
            competitors = [
                Competitor(
                    product_id=product.id,
                    name=f"{product.brand} Value Pack",
                    platform="blinkit",
                    search_query=product.search_query,
                    confirmed=True,
                ),
                Competitor(
                    product_id=product.id,
                    name=f"{product.brand} Market Choice",
                    platform="zepto",
                    search_query=product.search_query,
                    confirmed=True,
                ),
            ]
            session.add_all(competitors)
            session.add_all(
                ProductPincode(product_id=product.id, pincode=code, platform=platform)
                for code in SEED_CODES
                for platform in ("blinkit", "zepto")
            )
            await session.flush()

            for day_sample in range(28):
                checked_at = now - timedelta(hours=(27 - day_sample) * 12)
                run = CheckRun(
                    product_id=product.id,
                    trigger="scheduled",
                    status="done",
                    total_jobs=60,
                    done_jobs=60,
                    credits_used=60,
                    started_at=checked_at,
                    finished_at=checked_at + timedelta(minutes=2),
                )
                session.add(run)
                await session.flush()
                results: list[CheckResult] = []
                for platform in ("blinkit", "zepto"):
                    platform_competitor = next(
                        item for item in competitors if item.platform == platform
                    )
                    for code in SEED_CODES:
                        for competitor_id, offset in (
                            (None, 0.0),
                            (platform_competitor.id, -2.5),
                        ):
                            stock, price, mrp, eta, rating = deterministic_result(
                                product, code, platform, offset, day_sample
                            )
                            results.append(
                                CheckResult(
                                    run_id=run.id,
                                    product_id=product.id,
                                    competitor_id=competitor_id,
                                    platform=platform,
                                    pincode=code,
                                    in_stock=stock,
                                    price=price,
                                    mrp=mrp,
                                    eta_minutes=eta,
                                    rating=rating,
                                    status="ok",
                                    raw={"seeded": True},
                                    checked_at=checked_at,
                                )
                            )
                session.add_all(results)

            session.add_all(
                [
                    AISummary(
                        product_id=product.id,
                        summary_text=f"{product.name} has stable Delhi coverage with watch points in South Delhi.",
                        evidence={"seeded": True},
                        source="fallback",
                    ),
                    Recommendation(
                        product_id=product.id,
                        priority="medium",
                        action_text="Monitor competitor price changes before the next check.",
                        impact_text="Protect margin while retaining local competitiveness.",
                        evidence={"source": "seed"},
                    ),
                    ReviewInsight(
                        product_id=product.id,
                        competitor_id=None,
                        loves=["Reliable quality", "Good value"],
                        complaints=["Occasional availability gaps"],
                    ),
                ]
            )

        first_product = product_rows[0]
        session.add_all(
            [
                ChangeEvent(
                    product_id=first_product.id,
                    platform="blinkit",
                    pincode="110017",
                    kind="went_oos",
                    old_value=1.0,
                    new_value=0.0,
                ),
                ChangeEvent(
                    product_id=first_product.id,
                    platform="blinkit",
                    pincode="110048",
                    kind="price_rise",
                    old_value=34.0,
                    new_value=36.0,
                ),
                Alert(
                    user_id=user.id,
                    product_id=first_product.id,
                    kind="oos_any",
                    message="Amul Taaza is out of stock in Saket.",
                    evidence={"pincode": "110017"},
                    dedupe_key="seed:amul:110017",
                ),
                Alert(
                    user_id=user.id,
                    product_id=first_product.id,
                    kind="oos_any",
                    message="Amul Taaza is out of stock in Greater Kailash.",
                    evidence={"pincode": "110048"},
                    dedupe_key="seed:amul:110048",
                ),
                Alert(
                    user_id=user.id,
                    product_id=product_rows[1].id,
                    kind="price_change_pct",
                    message="A rival price changed for Haldiram Bhujia.",
                    evidence={},
                    dedupe_key="seed:bhujia:price",
                ),
                Alert(
                    user_id=user.id,
                    product_id=product_rows[2].id,
                    kind="price_change_pct",
                    message="Paper Boat has a price gap on Zepto.",
                    evidence={},
                    dedupe_key="seed:paperboat:gap",
                ),
                Alert(
                    user_id=user.id,
                    product_id=product_rows[2].id,
                    kind="rating_below",
                    message="A competitor rating needs attention.",
                    evidence={},
                    dedupe_key="seed:paperboat:rating",
                ),
            ]
        )
        await session.commit()
        print(
            "Seeded Riya Sharma, 3 products, 15 Delhi pincodes, and 14 days of mock history."
        )


if __name__ == "__main__":
    asyncio.run(seed())
