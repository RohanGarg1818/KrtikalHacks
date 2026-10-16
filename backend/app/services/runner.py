"""Check pipeline: job creation, bounded execution, retries, credits, SSE.

Jobs are (seller product + each confirmed competitor) x selected platforms x
selected pincodes. Runs execute in the background with an asyncio semaphore
gating TinyFish concurrency; progress is published to the in-memory event bus
for SSE subscribers. All database writes during a run are serialised through a
lock so SQLite and Postgres both stay happy.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal
from ..models.base import utcnow
from ..models.checks import CheckResult as CheckResultRow
from ..models.checks import CheckRun, CreditLedger
from ..models.product import Competitor, Product, ProductListing
from .events import run_events
from .insights import detect_changes
from .intelligence import refresh_intelligence
from .storage import save_screenshot
from .tinyfish import TinyFishClient, TinyFishError, get_tinyfish_client
from .tinyfish.base import CheckResult as CheckResultPayload

logger = logging.getLogger("shelfsense.runner")

RETRY_BACKOFF_SECONDS = 0.25
RETRYABLE_ERRORS = (TinyFishError, ValidationError, TimeoutError)
_active_tasks: set[asyncio.Task] = set()


@dataclass(frozen=True)
class Job:
    competitor_id: str | None
    platform: str
    pincode: str
    query: str
    url: str | None


def job_dict(job: Job) -> dict:
    return {
        "platform": job.platform,
        "pincode": job.pincode,
        "competitor_id": job.competitor_id,
    }


def _publish(run_id: str, event_type: str, **data: object) -> None:
    run_events.publish(run_id, {"type": event_type, "run_id": run_id, **data})


async def build_jobs(
    session: AsyncSession, product: Product, platforms: list[str], pincodes: list[str]
) -> list[Job]:
    listings = {
        row.platform: row.url
        for row in (
            await session.scalars(
                select(ProductListing).where(ProductListing.product_id == product.id)
            )
        ).all()
    }
    competitors = list(
        (
            await session.scalars(
                select(Competitor).where(
                    Competitor.product_id == product.id,
                    Competitor.confirmed.is_(True),
                )
            )
        ).all()
    )
    # Without a real listing URL each entity gets a stable identity URL so the
    # mock client returns distinct, repeatable results for seller vs rivals.
    # The HTTP client ignores non-http(s) URLs and searches by query instead.
    jobs = [
        Job(
            None,
            platform,
            pincode,
            product.search_query,
            listings.get(platform) or f"shelfsense://product/{product.name}",
        )
        for platform in platforms
        for pincode in pincodes
    ]
    for competitor in competitors:
        for platform in platforms:
            for pincode in pincodes:
                if competitor.platform == platform:
                    url = competitor.url or (
                        f"shelfsense://competitor/{competitor.name}"
                    )
                else:
                    url = f"shelfsense://competitor/{competitor.name}/{platform}"
                jobs.append(
                    Job(
                        competitor.id,
                        platform,
                        pincode,
                        competitor.search_query or product.search_query,
                        url,
                    )
                )
    return jobs


async def create_run(
    session: AsyncSession,
    product: Product,
    *,
    trigger: str,
    platforms: list[str],
    pincodes: list[str],
) -> tuple[CheckRun, list[Job]]:
    if product.paused:
        raise HTTPException(
            status_code=422, detail="Paused products cannot be checked"
        )
    jobs = await build_jobs(session, product, platforms, pincodes)
    if not jobs:
        raise HTTPException(status_code=422, detail="No check jobs to run")
    run = CheckRun(
        product_id=product.id,
        trigger=trigger,
        status="queued",
        total_jobs=len(jobs),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    logger.info(
        "run created id=%s product=%s trigger=%s jobs=%s",
        run.id,
        product.id,
        trigger,
        len(jobs),
    )
    return run, jobs


def schedule_run(
    run_id: str, *, product_id: str, user_id: str, jobs: list[Job]
) -> asyncio.Task:
    task = asyncio.create_task(
        execute_run(run_id, product_id=product_id, user_id=user_id, jobs=jobs)
    )
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task


async def check_with_retry(client: TinyFishClient, job: Job) -> CheckResultPayload:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            result = await client.check(
                platform=job.platform,
                pincode=job.pincode,
                query=job.query,
                url=job.url,
            )
            return CheckResultPayload.model_validate(result.model_dump())
        except RETRYABLE_ERRORS as exc:
            last_error = exc
            logger.warning(
                "check attempt %s failed platform=%s pincode=%s error=%s",
                attempt + 1,
                job.platform,
                job.pincode,
                exc,
            )
            if attempt == 0:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS)
    if last_error is None:
        raise RuntimeError("TinyFish check failed without an error")
    raise last_error


async def execute_run(
    run_id: str, *, product_id: str, user_id: str, jobs: list[Job]
) -> None:
    settings = get_settings()
    total = len(jobs)
    semaphore = asyncio.Semaphore(settings.tinyfish_max_concurrency)
    write_lock = asyncio.Lock()
    counters = {"done": 0, "failed": 0, "credits": 0}
    final_status = "failed"

    try:
        async with SessionLocal() as session:
            run = await session.get(CheckRun, run_id)
            if run is None:
                logger.warning("run %s disappeared before execution", run_id)
                return
            run.status = "running"
            run.started_at = utcnow()
            await session.commit()
            client = get_tinyfish_client()

            async def record(
                job: Job,
                payload: CheckResultPayload | None,
                error: str | None,
                screenshot_url: str | None,
            ) -> CheckResultRow:
                async with write_lock:
                    row = CheckResultRow(
                        run_id=run_id,
                        product_id=product_id,
                        competitor_id=job.competitor_id,
                        platform=job.platform,
                        pincode=job.pincode,
                        in_stock=payload.in_stock if payload else None,
                        price=payload.price if payload else None,
                        mrp=payload.mrp if payload else None,
                        eta_minutes=payload.eta_minutes if payload else None,
                        rating=payload.rating if payload else None,
                        screenshot_url=screenshot_url,
                        status="ok" if payload else "failed",
                        error=error,
                        raw=payload.raw if payload else {},
                        checked_at=utcnow(),
                    )
                    session.add(row)
                    run.done_jobs += 1
                    counters["done"] += 1
                    if payload is None:
                        run.failed_jobs += 1
                        counters["failed"] += 1
                    else:
                        run.credits_used += payload.credits_used
                        counters["credits"] += payload.credits_used
                        session.add(
                            CreditLedger(
                                user_id=user_id,
                                run_id=run_id,
                                credits=payload.credits_used,
                                reason=f"check:{job.platform}:{job.pincode}",
                            )
                        )
                    await session.commit()
                    return row

            async def execute_job(job: Job) -> None:
                async with semaphore:
                    _publish(run_id, "job_started", job=job_dict(job))
                    started = time.perf_counter()
                    payload: CheckResultPayload | None = None
                    error: str | None = None
                    screenshot_url: str | None = None
                    try:
                        payload = await check_with_retry(client, job)
                    except RETRYABLE_ERRORS as exc:
                        error = (str(exc) or exc.__class__.__name__)[:1000]
                    else:
                        if payload.screenshot_bytes:
                            with contextlib.suppress(Exception):
                                screenshot_url = await save_screenshot(
                                    payload.screenshot_bytes,
                                    product_id=product_id,
                                    platform=job.platform,
                                    pincode=job.pincode,
                                )
                        screenshot_url = screenshot_url or payload.screenshot_url
                    row = await record(job, payload, error, screenshot_url)
                    elapsed_ms = int((time.perf_counter() - started) * 1000)
                    status = row.status
                    logger.info(
                        "job platform=%s pincode=%s competitor=%s status=%s ms=%s credits=%s",
                        job.platform,
                        job.pincode,
                        job.competitor_id,
                        status,
                        elapsed_ms,
                        payload.credits_used if payload else 0,
                    )
                    if payload is None:
                        _publish(
                            run_id,
                            "job_failed",
                            job=job_dict(job),
                            error=error,
                            ms=elapsed_ms,
                        )
                    else:
                        _publish(
                            run_id,
                            "result",
                            result={
                                "id": row.id,
                                **job_dict(job),
                                "in_stock": row.in_stock,
                                "price": row.price,
                                "mrp": row.mrp,
                                "eta_minutes": row.eta_minutes,
                                "rating": row.rating,
                                "status": row.status,
                                "screenshot_url": row.screenshot_url,
                                "checked_at": row.checked_at.isoformat(),
                                "ms": elapsed_ms,
                                "credits": payload.credits_used,
                            },
                        )

            outcomes = await asyncio.gather(
                *(execute_job(job) for job in jobs), return_exceptions=True
            )
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    logger.error("job crashed run=%s error=%s", run_id, outcome)
                    counters["failed"] += 1
                    counters["done"] += 1

            final_status = "failed" if counters["failed"] == total else "done"
            run.status = final_status
            run.done_jobs = counters["done"]
            run.failed_jobs = counters["failed"]
            run.credits_used = counters["credits"]
            run.finished_at = utcnow()
            await session.commit()
            try:
                await detect_changes(session, run_id=run_id, product_id=product_id)
            except Exception:
                logger.exception("change detection failed for run %s", run_id)
            try:
                await refresh_intelligence(session, product_id, run_id=run_id)
            except Exception:
                logger.exception("intelligence refresh failed for run %s", run_id)
            close = getattr(client, "close", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()
    except Exception:
        logger.exception("run %s crashed", run_id)
        final_status = "failed"
        with contextlib.suppress(Exception):
            await _mark_run_failed(run_id, counters)
    finally:
        _publish(
            run_id,
            "run_done",
            status=final_status,
            total_jobs=total,
            done_jobs=counters["done"],
            failed_jobs=counters["failed"],
            credits_used=counters["credits"],
        )
        run_events.finish(run_id)
        logger.info(
            "run finished id=%s status=%s done=%s failed=%s credits=%s",
            run_id,
            final_status,
            counters["done"],
            counters["failed"],
            counters["credits"],
        )


async def _mark_run_failed(run_id: str, counters: dict[str, int]) -> None:
    async with SessionLocal() as session:
        run = await session.get(CheckRun, run_id)
        if run is None or run.status in ("done", "failed"):
            return
        run.status = "failed"
        run.done_jobs = counters["done"]
        run.failed_jobs = counters["failed"]
        run.credits_used = counters["credits"]
        run.finished_at = utcnow()
        await session.commit()
