"""Telegram integration: link codes, bot lifecycle, and message delivery.

Everything degrades gracefully: without TELEGRAM_BOT_TOKEN the link-code API
still works (codes are stored for later redemption) but the bot never starts
and delivery is a no-op logger. All bot wiring lives behind this module so the
rest of the app never imports python-telegram-bot.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal
from ..models.base import utcnow
from ..models.intelligence import Recommendation
from ..models.product import Product
from ..models.telegram import TelegramLink, TelegramLinkCode
from .ai import get_ai_provider, with_fallback
from .intelligence import build_context, decide_recommendation

logger = logging.getLogger("shelfsense.telegram")

LINK_CODE_TTL_MINUTES = 10
LINK_CODE_WORDS = (
    "MILK", "SHELF", "CART", "PICK", "DEAL", "ZEBRA", "TIGER", "LOTUS",
    "MANGO", "PEPPER",
)
_bot_application = None

RETRYABLE_TELEGRAM_ERRORS: tuple[type[Exception], ...] = ()


def _load_retryable_errors() -> tuple[type[Exception], ...]:
    try:
        from telegram.error import TelegramError

        return (TelegramError,)
    except ImportError:  # pragma: no cover - dependency always present in prod
        return ()


RETRYABLE_TELEGRAM_ERRORS = _load_retryable_errors()


def generate_link_code_value() -> str:
    number = secrets.randbelow(10000)
    word = secrets.choice(LINK_CODE_WORDS)
    return f"SS-{number:04d}-{word}"


async def create_link_code(
    session: AsyncSession,
    *,
    user_id: str,
    product_id: str,
    chat_type: str = "personal",
) -> TelegramLinkCode:
    from sqlalchemy.exc import IntegrityError

    stored_type = "group" if chat_type == "group" else "private"
    for _attempt in range(5):
        code = TelegramLinkCode(
            code=generate_link_code_value(),
            user_id=user_id,
            product_id=product_id,
            chat_type=stored_type,
            expires_at=utcnow() + timedelta(minutes=LINK_CODE_TTL_MINUTES),
        )
        session.add(code)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(code)
        return code
    raise RuntimeError("Could not generate a unique Telegram link code")


def build_deeplink(code: str, chat_type: str = "personal") -> str:
    settings = get_settings()
    username = settings.telegram_bot_username
    if not username:
        return f"/start {code}"
    param = "startgroup" if chat_type == "group" else "start"
    return f"https://t.me/{username}?{param}={code}"


async def redeem_link_code(
    session: AsyncSession,
    *,
    code_value: str,
    chat_id: str,
    chat_title: str | None = None,
) -> TelegramLink | None:
    """Exchange a code for a TelegramLink; returns None when invalid."""
    row = await session.get(TelegramLinkCode, code_value)
    now = utcnow()
    if row is None or row.used_at is not None or row.expires_at < now:
        return None
    product = await session.get(Product, row.product_id)
    if product is None:
        return None
    existing = await session.scalar(
        select(TelegramLink).where(
            TelegramLink.product_id == row.product_id,
            TelegramLink.chat_id == chat_id,
        )
    )
    if existing is not None:
        row.used_at = now
        await session.commit()
        return existing
    link = TelegramLink(
        user_id=row.user_id,
        product_id=row.product_id,
        chat_id=chat_id,
        chat_title=chat_title,
        alert_types=[],
    )
    session.add(link)
    row.used_at = now
    await session.commit()
    await session.refresh(link)
    return link


async def unlink_chat(session: AsyncSession, *, chat_id: str) -> int:
    result = await session.execute(
        delete(TelegramLink).where(TelegramLink.chat_id == chat_id)
    )
    await session.commit()
    return result.rowcount or 0


def get_bot_application():
    return _bot_application


def bot_is_running() -> bool:
    return _bot_application is not None


async def send_telegram_message(
    chat_id: str, text: str, reply_markup=None
) -> bool:
    """Best-effort send; logs and returns False when the bot is not running."""
    if _bot_application is None:
        logger.info("telegram disabled; would send to %s: %s", chat_id, text[:200])
        return False
    try:
        await _bot_application.bot.send_message(
            chat_id=chat_id, text=text[:4000], reply_markup=reply_markup
        )
        return True
    except RETRYABLE_TELEGRAM_ERRORS:
        logger.warning("telegram send failed chat=%s", chat_id)
        return False
    except Exception:
        logger.exception("telegram send crashed chat=%s", chat_id)
        return False


async def send_recommendation_message(
    chat_id: str, recommendation: Recommendation, *, product_name: str | None = None
) -> bool:
    """Send a recommendation with Approve and Details inline buttons."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    settings = get_settings()
    name = product_name or "your product"
    text = (
        f"[ShelfSense] Recommendation for {name} "
        f"({recommendation.priority} priority):\n"
        f"{recommendation.action_text}\n"
        f"Impact: {recommendation.impact_text}"
    )
    details_url = f"{settings.frontend_origin}/products/{recommendation.product_id}"
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Approve", callback_data=f"approve:{recommendation.id}"
                ),
                InlineKeyboardButton("Details", url=details_url),
            ]
        ]
    )
    return await send_telegram_message(chat_id, text, reply_markup=keyboard)


async def handle_approve_callback(update, context) -> bool:
    """Process approve:<rec_id>; returns True when the callback was handled."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return False
    if not query.data.startswith("approve:"):
        return False
    recommendation_id = query.data.split(":", 1)[1]
    async with SessionLocal() as session:
        link = await session.scalar(
            select(TelegramLink).where(TelegramLink.chat_id == str(chat.id))
        )
        if link is None:
            await query.answer("This chat is not linked to ShelfSense.")
            return True
        recommendation = await session.get(Recommendation, recommendation_id)
        if recommendation is None:
            await query.answer("Recommendation no longer exists.")
            return True
        product = await session.get(Product, recommendation.product_id)
        if product is None or product.user_id != link.user_id:
            await query.answer("Not authorised for this chat.")
            return True
        if recommendation.status == "pending":
            await decide_recommendation(
                session, recommendation, decision="approved", decided_via="telegram"
            )
        await query.edit_message_text("Approved ✓")
        await query.answer("Recommendation approved.")
    return True


async def _handle_start(update, context) -> None:
    """Bot /start <code> and /link <code>: link the chat to a product."""
    args = context.args or []
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    if not args:
        await message.reply_text(
            "Send /start <code> with the code from your ShelfSense product page."
        )
        return
    async with SessionLocal() as session:
        link = await redeem_link_code(
            session,
            code_value=args[0].strip(),
            chat_id=str(chat.id),
            chat_title=chat.title,
        )
        if link is None:
            await message.reply_text(
                "That code is invalid or expired. Generate a fresh one on your "
                "ShelfSense product page and try again."
            )
            return
        product = await session.get(Product, link.product_id)
        name = product.name if product else "your product"
    await message.reply_text(f"Connected ✓ to {name}")


async def _handle_status(update, context) -> None:
    """Bot /status: latest summary for products linked to this chat."""
    del context
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    async with SessionLocal() as session:
        links = list(
            (
                await session.scalars(
                    select(TelegramLink).where(TelegramLink.chat_id == str(chat.id))
                )
            ).all()
        )
        if not links:
            await message.reply_text(
                "This chat is not connected. Use /start <code> from your "
                "ShelfSense product page first."
            )
            return
        lines: list[str] = []
        for link in links[:5]:
            product = await session.get(Product, link.product_id)
            name = product.name if product else "Unknown product"
            context_data = await build_context(session, link.product_id)
            if context_data is None:
                lines.append(f"{name}: no check data yet.")
                continue
            avg = context_data.get("avg_price")
            rival = context_data.get("cheapest_rival")
            stock = context_data.get("in_stock")
            total = context_data.get("total_pins")
            lines.append(
                f"{name}: avg ₹{avg:.2f} (rival ₹{rival:.2f}), "
                f"{stock}/{total} pins in stock."
                if avg is not None and rival is not None
                else f"{name}: {stock or 0}/{total or 0} pins in stock."
            )
    await message.reply_text("\n".join(lines))


async def _handle_ask(update, context) -> None:
    """Bot /ask <question>: answer via the AI chat scoped to linked products."""
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    question = " ".join(context.args or []).strip()
    if not question:
        await message.reply_text("Usage: /ask <question about your products>")
        return
    async with SessionLocal() as session:
        link = await session.scalar(
            select(TelegramLink).where(TelegramLink.chat_id == str(chat.id))
        )
        if link is None:
            await message.reply_text(
                "This chat is not connected. Use /start <code> first."
            )
            return
        context_data = await build_context(session, link.product_id)
        if context_data is None:
            await message.reply_text("No check data yet for your linked product.")
            return
        provider = get_ai_provider()
        result, _source = await with_fallback(
            provider, "chat", context_data, question, []
        )
    await message.reply_text(result.reply[:4000])


async def _handle_stop(update, context) -> None:
    """Bot /stop: disconnect this chat from all products."""
    del context
    message = update.effective_message
    chat = update.effective_chat
    if message is None or chat is None:
        return
    async with SessionLocal() as session:
        removed = await unlink_chat(session, chat_id=str(chat.id))
    if removed:
        await message.reply_text(
            "Disconnected ✓. Alerts and briefings will stop for this chat."
        )
    else:
        await message.reply_text("This chat was not connected.")


async def _handle_callback(update, context) -> None:
    await handle_approve_callback(update, context)


async def start_bot() -> bool:
    """Start polling the Telegram bot; False when no token is configured."""
    global _bot_application
    settings = get_settings()
    if not settings.telegram_enabled:
        return False
    if _bot_application is not None:
        return True
    try:
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
        )

        application = Application.builder().token(settings.telegram_bot_token).build()
        application.add_handler(CommandHandler(["start", "link"], _handle_start))
        application.add_handler(CommandHandler("status", _handle_status))
        application.add_handler(CommandHandler("ask", _handle_ask))
        application.add_handler(CommandHandler("stop", _handle_stop))
        application.add_handler(CallbackQueryHandler(_handle_callback))
        await application.initialize()
        await application.start()
        if application.updater is not None:
            await application.updater.start_polling()
        _bot_application = application
        logger.info("telegram bot started")
        return True
    except Exception:
        logger.exception("telegram bot failed to start")
        _bot_application = None
        return False


async def stop_bot() -> None:
    global _bot_application
    application = _bot_application
    if application is None:
        return
    _bot_application = None
    try:
        if application.updater is not None:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
    except Exception:
        logger.exception("telegram bot shutdown failed")
