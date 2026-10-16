"""Telegram integration: link codes, bot lifecycle, and message delivery.

Everything degrades gracefully: without TELEGRAM_BOT_TOKEN the link-code API
still works (codes are stored for later redemption) but the bot never starts
and delivery is a no-op. All bot wiring lives behind this module so the rest
of the app never imports python-telegram-bot.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal
from ..models.base import utcnow
from ..models.product import Product
from ..models.telegram import TelegramLink, TelegramLinkCode

logger = logging.getLogger("shelfsense.telegram")

LINK_CODE_TTL_MINUTES = 10
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
    return secrets.token_urlsafe(9)[:8]


async def create_link_code(
    session: AsyncSession, *, user_id: str, product_id: str
) -> TelegramLinkCode:
    from sqlalchemy.exc import IntegrityError

    for _attempt in range(5):
        code = TelegramLinkCode(
            code=generate_link_code_value(),
            user_id=user_id,
            product_id=product_id,
            chat_type="private",
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


def build_deeplink(code: str) -> str:
    settings = get_settings()
    username = settings.telegram_bot_username
    if not username:
        return f"/start {code}"
    return f"https://t.me/{username}?start={code}"


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


def get_bot_application():
    return _bot_application


def bot_is_running() -> bool:
    return _bot_application is not None


async def send_telegram_message(chat_id: str, text: str) -> bool:
    """Best-effort send; returns False when the bot is not running."""
    if _bot_application is None:
        return False
    try:
        await _bot_application.bot.send_message(chat_id=chat_id, text=text[:4000])
        return True
    except RETRYABLE_TELEGRAM_ERRORS:
        logger.warning("telegram send failed chat=%s", chat_id)
        return False
    except Exception:
        logger.exception("telegram send crashed chat=%s", chat_id)
        return False


async def _handle_start(update, context) -> None:
    """Bot /start <code> handler: links the chat to a product."""
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
    await message.reply_text(
        f"Linked! ShelfSense alerts for {name} will arrive in this chat."
    )


async def start_bot() -> bool:
    """Start polling the Telegram bot; False when no token is configured."""
    global _bot_application
    settings = get_settings()
    if not settings.telegram_enabled:
        return False
    if _bot_application is not None:
        return True
    try:
        from telegram.ext import Application, CommandHandler

        application = Application.builder().token(settings.telegram_bot_token).build()
        application.add_handler(CommandHandler("start", _handle_start))
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
