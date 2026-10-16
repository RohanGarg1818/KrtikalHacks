"""Schemas for AI summaries, recommendations, and review insights."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SummaryResponse(BaseModel):
    id: str
    product_id: str
    run_id: str | None = None
    summary_text: str
    evidence: dict = Field(default_factory=dict)
    source: str
    created_at: datetime


class RecommendationResponse(BaseModel):
    id: str
    product_id: str
    priority: str
    action_text: str
    impact_text: str
    evidence: dict = Field(default_factory=dict)
    status: str
    decided_via: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class RecommendationListResponse(BaseModel):
    items: list[RecommendationResponse]


class DecisionResponse(BaseModel):
    id: str
    status: str
    decided_via: str | None = None
    decided_at: datetime | None = None


class GenerateResponse(BaseModel):
    source: str
    summary: SummaryResponse | None = None
    recommendations: list[RecommendationResponse] = Field(default_factory=list)


class ReviewItem(BaseModel):
    entity_id: str | None = None
    name: str
    loves: list[str] = Field(default_factory=list)
    complaints: list[str] = Field(default_factory=list)
    updated_at: datetime


class ReviewRefreshResponse(BaseModel):
    source: str
    loves: list[str] = Field(default_factory=list)
    complaints: list[str] = Field(default_factory=list)
    items: list[ReviewItem] = Field(default_factory=list)
