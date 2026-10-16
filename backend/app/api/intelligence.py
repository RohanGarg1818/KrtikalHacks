"""AI endpoints: summaries, recommendations, and review insights."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.intelligence import AISummary, Recommendation
from ..models.product import Product
from ..models.user import User
from ..schemas.intelligence import (
    DecisionResponse,
    GenerateResponse,
    RecommendationListResponse,
    RecommendationResponse,
    ReviewItem,
    ReviewRefreshResponse,
    SummaryResponse,
)
from ..services.insights import compute_reviews
from ..services.intelligence import (
    clear_pending_recommendations,
    decide_recommendation,
    generate_recommendations,
    generate_summary,
    refresh_review_insights,
)
from .products import get_owned_product

router = APIRouter(tags=["intelligence"])


def _summary_payload(row: AISummary) -> SummaryResponse:
    return SummaryResponse(
        id=row.id,
        product_id=row.product_id,
        run_id=row.run_id,
        summary_text=row.summary_text,
        evidence=row.evidence or {},
        source=row.source,
        created_at=row.created_at,
    )


def _recommendation_payload(row: Recommendation) -> RecommendationResponse:
    return RecommendationResponse(
        id=row.id,
        product_id=row.product_id,
        priority=row.priority,
        action_text=row.action_text,
        impact_text=row.impact_text,
        evidence=row.evidence or {},
        status=row.status,
        decided_via=row.decided_via,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


async def get_owned_recommendation(
    session: AsyncSession, user: User, recommendation_id: str
) -> Recommendation:
    row = await session.scalar(
        select(Recommendation)
        .join(Product, Product.id == Recommendation.product_id)
        .where(
            Recommendation.id == recommendation_id,
            Product.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return row


@router.post(
    "/products/{product_id}/ai/summary", response_model=SummaryResponse
)
async def post_generate_summary(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SummaryResponse:
    product = await get_owned_product(session, user.id, product_id)
    summary = await generate_summary(session, product)
    if summary is None:
        raise HTTPException(
            status_code=422, detail="No check data to summarise yet"
        )
    return _summary_payload(summary)


@router.get(
    "/products/{product_id}/ai/recommendations",
    response_model=RecommendationListResponse,
)
async def list_recommendations(
    product_id: str,
    status: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RecommendationListResponse:
    await get_owned_product(session, user.id, product_id)
    statement = select(Recommendation).where(
        Recommendation.product_id == product_id
    )
    if status is not None:
        statement = statement.where(Recommendation.status == status)
    rows = list(
        (await session.scalars(statement.order_by(Recommendation.created_at.desc()))).all()
    )
    return RecommendationListResponse(
        items=[_recommendation_payload(row) for row in rows]
    )


@router.post(
    "/products/{product_id}/ai/recommendations",
    response_model=GenerateResponse,
)
async def post_generate_recommendations(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> GenerateResponse:
    product = await get_owned_product(session, user.id, product_id)
    rows, source = await generate_recommendations(session, product)
    return GenerateResponse(
        source=source,
        summary=None,
        recommendations=[_recommendation_payload(row) for row in rows],
    )


@router.delete(
    "/products/{product_id}/ai/recommendations/pending",
    response_model=DecisionResponse,
)
async def delete_pending_recommendations(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    await get_owned_product(session, user.id, product_id)
    removed = await clear_pending_recommendations(session, product_id)
    return DecisionResponse(id=product_id, status=f"removed:{removed}")


@router.post(
    "/recommendations/{recommendation_id}/accept",
    response_model=DecisionResponse,
)
async def accept_recommendation(
    recommendation_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    row = await get_owned_recommendation(session, user, recommendation_id)
    row = await decide_recommendation(session, row, decision="accepted")
    return DecisionResponse(
        id=row.id,
        status=row.status,
        decided_via=row.decided_via,
        decided_at=row.decided_at,
    )


@router.post(
    "/recommendations/{recommendation_id}/decline",
    response_model=DecisionResponse,
)
async def decline_recommendation(
    recommendation_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionResponse:
    row = await get_owned_recommendation(session, user, recommendation_id)
    row = await decide_recommendation(session, row, decision="declined")
    return DecisionResponse(
        id=row.id,
        status=row.status,
        decided_via=row.decided_via,
        decided_at=row.decided_at,
    )


@router.post("/products/{product_id}/ai/reviews", response_model=ReviewRefreshResponse)
async def post_refresh_reviews(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReviewRefreshResponse:
    product = await get_owned_product(session, user.id, product_id)
    _row, source = await refresh_review_insights(session, product)
    merged = await compute_reviews(session, product_id)
    items = [
        ReviewItem(
            entity_id=item["entity_id"],
            name=item["name"],
            loves=item["loves"],
            complaints=item["complaints"],
            updated_at=item["updated_at"],
        )
        for item in merged["items"]
    ]
    return ReviewRefreshResponse(
        source=source,
        loves=merged["loves"],
        complaints=merged["complaints"],
        items=items,
    )
