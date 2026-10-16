"""Prompt builders for the Gemini provider.

Every prompt embeds the evidence numbers so the model can only summarise what
we measured, plus the guardrail instructions it must follow.
"""

from __future__ import annotations

import json

GUARDRAIL_RULES = """\
You are ShelfSense AI, an assistant that helps quick-commerce sellers in India
understand price and shelf-visibility data. Follow these rules:
- Only use the numbers provided in the context. Never invent prices, pins, or stats.
- Prices are Indian Rupees. Never suggest illegal, deceptive, or anti-competitive
  behaviour (price fixing, cartels, fake reviews, sabotage of competitors).
- Keep advice actionable and short. Reply with a single JSON object only,
  matching the requested schema. No markdown, no commentary.
"""


def _context_block(context: dict) -> str:
    return json.dumps(context, default=str, ensure_ascii=False)


def summarize_prompt(context: dict) -> tuple[str, str]:
    system = (
        GUARDRAIL_RULES
        + "\nTask: write a 2-3 sentence seller-facing summary of the product's "
        "price and stock position. Reply with JSON: "
        '{"summary_text": "..."}'
    )
    return system, f"Context:\n{_context_block(context)}"


def recommend_prompt(context: dict) -> tuple[str, str]:
    system = (
        GUARDRAIL_RULES
        + "\nTask: propose up to 3 concrete recommendations. Priority must be "
        '"high", "medium", or "low". Every recommendation must cite evidence '
        "from the context. Reply with JSON: "
        '{"recommendations": [{"priority": "...", "action_text": "...", '
        '"impact_text": "...", "evidence": {...}}]}'
    )
    return system, f"Context:\n{_context_block(context)}"


def reviews_prompt(context: dict) -> tuple[str, str]:
    system = (
        GUARDRAIL_RULES
        + "\nTask: list what customers likely love and complain about, derived "
        "only from availability, price, and rating signals in the context "
        "(3-5 short bullet phrases each). Reply with JSON: "
        '{"loves": ["..."], "complaints": ["..."]}'
    )
    return system, f"Context:\n{_context_block(context)}"


def chat_prompt(
    context: dict, message: str, history: list[dict]
) -> tuple[str, str]:
    system = (
        GUARDRAIL_RULES
        + "\nTask: answer the seller's question about their product data. "
        "If the question is unrelated to ShelfSense data, politely say you can "
        "only help with prices, stock, heatmaps, checks, and weekly insights. "
        "Reply with JSON: "
        '{"reply": "...", "actions": [{"label": "...", "path": "..."}], '
        '"evidence": [{"metric": "...", "value": ...}]}. '
        "Action paths must start with /products/ or be from the context."
    )
    lines = [f"Context:\n{_context_block(context)}", "\nConversation so far:"]
    for entry in history[-6:]:
        lines.append(f"{entry.get('role', 'user')}: {entry.get('content', '')}")
    lines.append(f"user: {message}")
    return system, "\n".join(lines)
