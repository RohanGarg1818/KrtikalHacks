"""AI provider contract and shared output shapes.

Both providers (Gemini and the no-key fallback) answer the same four tasks
with the same Pydantic shapes so callers never branch on provider details.
"""

from __future__ import annotations

import json
import re
from typing import Protocol

from pydantic import BaseModel, Field


class AIProviderError(Exception):
    """Raised when a provider cannot produce a valid answer; callers fall back."""


class SummaryOut(BaseModel):
    summary_text: str


class RecommendationCandidate(BaseModel):
    priority: str = "medium"
    action_text: str
    impact_text: str = ""
    evidence: dict = Field(default_factory=dict)


class RecommendOut(BaseModel):
    recommendations: list[RecommendationCandidate] = Field(default_factory=list)


class ReviewsOut(BaseModel):
    loves: list[str] = Field(default_factory=list)
    complaints: list[str] = Field(default_factory=list)


class ChatAction(BaseModel):
    label: str
    path: str


class ChatEvidence(BaseModel):
    metric: str
    value: float | int | str | None = None


class ChatOut(BaseModel):
    reply: str
    actions: list[ChatAction] = Field(default_factory=list)
    evidence: list[ChatEvidence] = Field(default_factory=list)


class AIProvider(Protocol):
    name: str

    async def summarize(self, context: dict) -> SummaryOut: ...

    async def recommend(self, context: dict) -> RecommendOut: ...

    async def reviews(self, context: dict) -> ReviewsOut: ...

    async def chat(
        self, context: dict, message: str, history: list[dict]
    ) -> ChatOut: ...


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_payload(text: str) -> dict:
    """Extract a JSON object from a model response, tolerating code fences."""
    cleaned = text.strip()
    fenced = _FENCE_RE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AIProviderError("No JSON object found in model response") from None
        try:
            payload = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIProviderError(f"Invalid JSON in model response: {exc}") from exc
    if not isinstance(payload, dict):
        raise AIProviderError("Model response JSON was not an object")
    return payload
