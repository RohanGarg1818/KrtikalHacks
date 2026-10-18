"""Telegram bot features: /compare text, check flow guards, command list."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.telegram_features import (
    BOT_COMMANDS,
    AppSummary,
    compare_text,
    handle_check_callback,
)


def test_compare_text_marks_the_cheapest_in_stock_app() -> None:
    text = compare_text(
        "Amul Taaza",
        [
            AppSummary("zepto", 17.0, 3, 3, False),
            AppSummary("flipkart", 29.0, 3, 3, True),
            AppSummary("amazon", None, 0, 3, True),
        ],
    )
    assert "Zepto: ₹17 · 3/3 pins in stock ⭐ cheapest" in text
    assert "Flipkart: ₹29 (listing-wide)" in text
    assert "Amazon: out of stock" in text
    assert "no check results yet" in compare_text("X", [])


def test_bot_command_menu_lists_every_feature() -> None:
    names = {name for name, _ in BOT_COMMANDS}
    assert {"menu", "status", "compare", "check", "ask", "link", "stop"} <= names


class _Query:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answers: list[str] = []
        self.edits: list[str] = []
        self.message = None

    async def answer(self, text: str = "") -> None:
        self.answers.append(text)

    async def edit_message_text(self, text: str, **_kwargs) -> None:
        self.edits.append(text)


@pytest.mark.asyncio
async def test_check_buttons_refuse_chats_not_linked_to_the_product() -> None:
    query = _Query("chk:r:not-a-product:zepto:110017")
    update = SimpleNamespace(
        callback_query=query,
        effective_chat=SimpleNamespace(id=999, type="private"),
        effective_user=None,
    )
    assert await handle_check_callback(update, None) is True
    assert query.answers == ["This chat is not linked to that product."]
    assert query.edits == []  # nothing started


@pytest.mark.asyncio
async def test_cancel_button_runs_nothing() -> None:
    query = _Query("chk:x")
    update = SimpleNamespace(callback_query=query, effective_chat=SimpleNamespace(id=1, type="private"))
    assert await handle_check_callback(update, None) is True
    assert query.edits == ["Check cancelled. Nothing was run."]
