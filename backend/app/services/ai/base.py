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


class AlertRuleOut(BaseModel):
    kind: str
    threshold: float | None = None
    rule_text: str = ""
    rule_json: dict = Field(default_factory=dict)


class AIProvider(Protocol):
    name: str

    async def summarize(self, context: dict) -> SummaryOut: ...

    async def recommend(self, context: dict) -> RecommendOut: ...

    async def reviews(self, context: dict) -> ReviewsOut: ...

    async def chat(
        self, context: dict, message: str, history: list[dict]
    ) -> ChatOut: ...

    async def parse_alert_rule(self, text: str) -> AlertRuleOut: ...


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_PINCODE_RE = re.compile(r"\b1[1-9]\d{4}\b")
_RUPEE_PRICE_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


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


def grounding_violations(text: str, context: dict) -> list[str]:
    """Return violations when text mentions pincodes/prices absent from context.

    The brief requires rejecting model outputs that invent pincodes or prices;
    callers fall back to the rule-based provider when this list is non-empty.
    """
    allowed_pins = {str(pin) for pin in context.get("all_pins", [])}
    allowed_pins.update(str(pin) for pin in context.get("oos_pins", []))
    for change in context.get("recent_changes", []):
        if change.get("pincode"):
            allowed_pins.add(str(change["pincode"]))
    allowed_prices = {
        round(float(context[key]), 2)
        for key in (
            "avg_price",
            "cheapest_rival",
            "this_week_avg_price",
            "last_week_avg_price",
        )
        if isinstance(context.get(key), (int, float))
    }
    for change in context.get("recent_changes", []):
        for field in ("old_value", "new_value"):
            value = change.get(field)
            if isinstance(value, (int, float)):
                allowed_prices.add(round(float(value), 2))
    violations: list[str] = []
    for pin in _PINCODE_RE.findall(text):
        if allowed_pins and pin not in allowed_pins:
            violations.append(f"unknown pincode {pin}")
        elif not allowed_pins:
            violations.append(f"pincode mentioned {pin} but none were provided")
    for raw in _RUPEE_PRICE_RE.findall(text):
        price = round(float(raw), 2)
        if allowed_prices and not any(
            abs(price - known) < 0.011 for known in allowed_prices
        ):
            violations.append(f"unknown price {price}")
    return violations


def result_text(task: str, result: BaseModel) -> str:
    """Flatten a provider result to the text the grounding check inspects."""
    if task == "summarize":
        return result.summary_text
    if task == "recommend":
        return " ".join(
            f"{item.action_text} {item.impact_text}" for item in result.recommendations
        )
    if task == "reviews":
        return " ".join([*result.loves, *result.complaints])
    if task == "chat":
        return result.reply
    if task == "parse_alert_rule":
        return result.rule_text
    return ""
