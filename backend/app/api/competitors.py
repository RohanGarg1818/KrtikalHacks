"""User-scoped competitor management and deterministic mock discovery."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models.product import Competitor, Product
from ..models.user import User
from ..schemas.products import (
    CompetitorCreate,
    CompetitorDiscoveryRequest,
    CompetitorDiscoveryResponse,
    CompetitorResponse,
)
from ..services.competitor_discovery import discover_competitors
from .products import get_owned_product

router = APIRouter(tags=["competitors"])


async def get_owned_competitor(
    session: AsyncSession, user_id: str, competitor_id: str
) -> Competitor:
    competitor = await session.scalar(
        select(Competitor)
        .join(Product)
        .where(Competitor.id == competitor_id, Product.user_id == user_id)
    )
    if competitor is None:
        raise HTTPException(status_code=404, detail="Competitor not found")
    return competitor


@router.get(
    "/products/{product_id}/competitors", response_model=list[CompetitorResponse]
)
async def list_competitors(
    product_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[Competitor]:
    await get_owned_product(session, user.id, product_id)
    return list(
        (
            await session.scalars(
                select(Competitor).where(Competitor.product_id == product_id)
            )
        ).all()
    )


@router.post(
    "/products/{product_id}/competitors",
    response_model=CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_competitor(
    product_id: str,
    payload: CompetitorCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Competitor:
    await get_owned_product(session, user.id, product_id)
    competitor = Competitor(product_id=product_id, **payload.model_dump())
    session.add(competitor)
    await session.commit()
    await session.refresh(competitor)
    return competitor


@router.delete("/competitors/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competitor(
    competitor_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    competitor = await get_owned_competitor(session, user.id, competitor_id)
    await session.delete(competitor)
    await session.commit()


@router.post(
    "/products/{product_id}/competitors/discover",
    response_model=CompetitorDiscoveryResponse,
)
async def discover(
    product_id: str,
    payload: CompetitorDiscoveryRequest | None = None,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CompetitorDiscoveryResponse:
    product = await get_owned_product(session, user.id, product_id)
    query = payload.query if payload and payload.query else product.search_query
    return CompetitorDiscoveryResponse(
        suggestions=[
            CompetitorCreate(**suggestion) for suggestion in discover_competitors(query)
        ],
        source="mock",
    )


@router.post("/competitors/{competitor_id}/confirm", response_model=CompetitorResponse)
async def confirm_competitor(
    competitor_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Competitor:
    competitor = await get_owned_competitor(session, user.id, competitor_id)
    competitor.confirmed = True
    await session.commit()
    await session.refresh(competitor)
    return competitor
