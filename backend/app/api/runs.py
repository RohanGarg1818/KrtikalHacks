"""Run creation, status, and SSE progress streaming."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ..config import Settings, get_settings
from ..db import SessionLocal, get_session
from ..deps import get_current_user
from ..models.checks import CheckRun
from ..models.product import Product, ProductPincode
from ..models.user import User
from ..schemas.runs import RunCreate, RunCreated, RunResponse
from ..services.events import run_events
from ..services.plans import enforce_pincode_limit
from ..services.runner import create_run, schedule_run
from .products import get_owned_product, get_user_plan

router = APIRouter(tags=["runs"])

FINISHED_STATUSES = ("done", "failed")


async def get_owned_run(
    session: AsyncSession, user_id: str, run_id: str
) -> CheckRun:
    run = await session.scalar(
        select(CheckRun)
        .join(Product, Product.id == CheckRun.product_id)
        .where(CheckRun.id == run_id, Product.user_id == user_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


def sse_message(event: dict) -> dict:
    return {"event": str(event.get("type", "message")), "data": json.dumps(event)}


def run_done_event(run_id: str, run: CheckRun | RunResponse) -> dict:
    return {
        "type": "run_done",
        "run_id": run_id,
        "status": run.status,
        "total_jobs": run.total_jobs,
        "done_jobs": run.done_jobs,
        "failed_jobs": run.failed_jobs,
        "credits_used": run.credits_used,
    }


async def finished_run_event(run_id: str) -> dict | None:
    async with SessionLocal() as session:
        run = await session.get(CheckRun, run_id)
        if run is None or run.status not in FINISHED_STATUSES:
            return None
        return run_done_event(run_id, run)


@router.post(
    "/products/{product_id}/runs",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(
    product_id: str,
    payload: RunCreate | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RunCreated:
    product = await get_owned_product(session, user.id, product_id)
    if product.paused:
        raise HTTPException(
            status_code=422, detail="Paused products cannot be checked"
        )
    if settings.tinyfish_enabled and not settings.tinyfish_agent_base_url:
        raise HTTPException(
            status_code=503,
            detail="TINYFISH_AGENT_BASE_URL is required when TinyFish is enabled",
        )
    selection = list(
        (
            await session.scalars(
                select(ProductPincode).where(ProductPincode.product_id == product_id)
            )
        ).all()
    )
    if not selection:
        raise HTTPException(
            status_code=422,
            detail="Select pincodes and platforms for this product first",
        )
    available_platforms = sorted({row.platform for row in selection})
    available_pincodes = sorted({row.pincode for row in selection})
    platforms = sorted(
        set(payload.platforms)
        if payload and payload.platforms
        else set(available_platforms)
    )
    pincodes = sorted(
        set(payload.pincodes)
        if payload and payload.pincodes
        else set(available_pincodes)
    )
    unknown_platforms = sorted(set(platforms) - set(available_platforms))
    if unknown_platforms:
        raise HTTPException(
            status_code=422,
            detail="Platforms not selected for this product: "
            + ", ".join(unknown_platforms),
        )
    unknown_pincodes = sorted(set(pincodes) - set(available_pincodes))
    if unknown_pincodes:
        raise HTTPException(
            status_code=422,
            detail="Pincodes not selected for this product: "
            + ", ".join(unknown_pincodes),
        )
    enforce_pincode_limit(await get_user_plan(session, user.id), len(pincodes))
    active = await session.scalar(
        select(CheckRun.id)
        .where(
            CheckRun.product_id == product_id,
            CheckRun.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail="A check run is already queued or running for this product",
        )
    run, jobs = await create_run(
        session, product, trigger="manual", platforms=platforms, pincodes=pincodes
    )
    schedule_run(run.id, product_id=product.id, user_id=user.id, jobs=jobs)
    return RunCreated(run_id=run.id, estimated_credits=len(jobs))


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CheckRun:
    return await get_owned_run(session, user.id, run_id)


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    ping: int = Query(default=15, ge=1, le=60),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    run = await get_owned_run(session, user.id, run_id)
    snapshot = RunResponse.model_validate(run)
    already_finished = run.status in FINISHED_STATUSES
    past, queue = run_events.subscribe(run_id)

    async def generator():
        try:
            for event in past:
                yield sse_message(event)
                if event["type"] == "run_done":
                    return
            if already_finished:
                yield sse_message(run_done_event(run_id, snapshot))
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    final = await finished_run_event(run_id)
                    if final is not None:
                        yield sse_message(final)
                        return
                    continue
                if event is None:
                    final = await finished_run_event(run_id)
                    if final is not None:
                        yield sse_message(final)
                    return
                yield sse_message(event)
                if event["type"] == "run_done":
                    return
        finally:
            run_events.unsubscribe(run_id, queue)

    return EventSourceResponse(generator(), ping=ping)
