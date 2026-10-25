"""My Store: seller-set stock feeds the heatmap and alerts; stock 0 is an urgent alert."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models.checks import CheckResult
from app.models.intelligence import Alert
from tests.test_stage6 import app_for, make_user

PINS = ["110016", "110017"]


@pytest.fixture(autouse=True)
async def _pincodes():
    from app.models.product import Pincode

    async with SessionLocal() as s:
        for code in (*PINS, "110001", "110003", "110005"):
            if await s.get(Pincode, code) is None:
                s.add(Pincode(code=code, area_name=f"Area {code}", city="Delhi", lat=28.6, lng=77.2))
        await s.commit()


@pytest.mark.asyncio
async def test_stock_zero_raises_urgent_store_alert_and_restock_recovers() -> None:
    user = await make_user()
    async with AsyncClient(transport=ASGITransport(app=app_for(user)), base_url="http://test") as c:
        r = await c.post(
            "/api/store/products",
            json={"name": "Amul Pure Ghee 1 L", "brand": "Amul", "price": 615, "mrp": 650, "stock": 40, "pincodes": PINS},
        )
        assert r.status_code == 201, r.text
        item = r.json()
        pid = item["product_id"]
        assert item["stock"] == 40 and item["pincodes"] == PINS

        heat = await c.get(f"/api/products/{pid}/heatmap")
        assert heat.status_code == 200

        zero = await c.patch(f"/api/store/products/{pid}", json={"stock": 0})
        assert zero.status_code == 200 and zero.json()["stock"] == 0

        async with SessionLocal() as s:
            results = (await s.scalars(select(CheckResult).where(CheckResult.product_id == pid, CheckResult.platform == "store"))).all()
            assert {r.in_stock for r in results} == {True, False}
            alerts = (await s.scalars(select(Alert).where(Alert.product_id == pid, Alert.kind == "oos_any"))).all()
        assert len(alerts) == 1
        assert alerts[0].severity == "urgent"
        assert "ShelfSense Store" in alerts[0].message

        back = await c.patch(f"/api/store/products/{pid}", json={"stock": 12})
        assert back.status_code == 200
        async with SessionLocal() as s:
            msgs = [a.message for a in (await s.scalars(select(Alert).where(Alert.product_id == pid))).all()]
        assert any("back in stock" in m for m in msgs)

        rerun = await c.post(f"/api/products/{pid}/runs", json={})
        assert rerun.status_code == 422 and rerun.json()["error"]["code"] == "store_only"


@pytest.mark.asyncio
async def test_demo_store_loads_once() -> None:
    user = await make_user()
    async with AsyncClient(transport=ASGITransport(app=app_for(user)), base_url="http://test") as c:
        first = await c.post("/api/store/demo")
        assert first.status_code == 200 and len(first.json()) == 4
        again = await c.post("/api/store/demo")
        assert again.json() == []
        listing = await c.get("/api/store")
        assert len(listing.json()) == 4
