"""Telegram bot features: menu, /compare, /check (live TinyFish run), photo alerts.

Kept apart from ``telegram.py`` (linking, lifecycle, delivery) so each stays
readable. Every handler checks that the chat is linked to the product it acts
on; in groups only the person who linked the group may start a paid check.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal
from ..models.checks import CheckResult
from ..models.intelligence import Alert
from ..models.product import Pincode, Product, ProductPincode
from ..models.telegram import TelegramLink
from ..models.user import Subscription
from .events import run_events
from .plans import remaining_credits_today
from .runner import create_run, schedule_run

logger = logging.getLogger("shelfsense.telegram")

APP_LABELS = {
    "zepto": "Zepto",
    "instamart": "Instamart",
    "amazon": "Amazon",
    "flipkart": "Flipkart",
    "blinkit": "Blinkit",
}
PHOTO_TYPES = {".png", ".jpg", ".jpeg", ".webp"}
PROGRESS_EDIT_SECONDS = 4.0
CHECK_WATCH_SECONDS = 15 * 60
MAX_PINCODE_BUTTONS = 6

BOT_COMMANDS = [
    ("menu", "Show the ShelfSense menu"),
    ("status", "Stock and price summary for your products"),
    ("compare", "Compare prices across Zepto, Instamart, Amazon, Flipkart"),
    ("check", "Run a live TinyFish check now"),
    ("ask", "Ask a question about your products"),
    ("link", "Connect this chat with a code from the website"),
    ("stop", "Disconnect this chat"),
]
BOT_SHORT_DESCRIPTION = (
    "Price and stock alerts for Zepto, Instamart, Amazon and Flipkart, pincode by pincode."
)
BOT_DESCRIPTION = (
    "ShelfSense watches your products on Zepto, Instamart, Amazon and Flipkart across "
    "Delhi pincodes using TinyFish web agents.\n\n"
    "• Alerts when you go out of stock or a rival undercuts you, with screenshot proof\n"
    "• /compare prices across apps\n"
    "• /check runs a live agent check from Telegram\n"
    "• Approve recommendations with one tap\n\n"
    "Open your product's Telegram tab on the ShelfSense website and tap the link to connect."
)


async def configure_bot_profile(bot) -> None:
    """Set the "/" command list and the bot's descriptions (best effort)."""
    from telegram import BotCommand

    try:
        await bot.set_my_commands([BotCommand(name, text) for name, text in BOT_COMMANDS])
        await bot.set_my_short_description(BOT_SHORT_DESCRIPTION)
        await bot.set_my_description(BOT_DESCRIPTION)
    except Exception:
        logger.warning("could not set bot commands/description", exc_info=True)


# --------------------------------------------------------------------- helpers


def _keyboard(rows):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text, url=data[4:])
                if data.startswith("url:")
                else InlineKeyboardButton(text, callback_data=data)
                for text, data in row
            ]
            for row in rows
        ]
    )


def main_menu():
    origin = get_settings().frontend_origin.rstrip("/")
    rows = [
        [("📊 Status", "menu:status"), ("💰 Compare", "menu:compare")],
        [("🔍 Check now", "menu:check")],
    ]
    # Telegram only accepts public http(s) URLs on buttons, not localhost.
    if origin.startswith("https://"):
        rows.append([("🗺 Open heatmap", f"url:{origin}/heatmap")])
    return _keyboard(rows)


async def _linked_products(session: AsyncSession, chat_id: str) -> list[Product]:
    links = (
        await session.scalars(
            select(TelegramLink)
            .where(TelegramLink.chat_id == chat_id)
            .order_by(TelegramLink.connected_at.desc())
        )
    ).all()
    products = []
    for link in links:
        product = await session.get(Product, link.product_id)
        if product is not None:
            products.append(product)
    return products


async def _link_for(session: AsyncSession, chat_id: str, product_id: str) -> TelegramLink | None:
    return await session.scalar(
        select(TelegramLink).where(
            TelegramLink.chat_id == chat_id, TelegramLink.product_id == product_id
        )
    )


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"₹{value:,.0f}" if value == int(value) else f"₹{value:,.2f}"


# --------------------------------------------------------------------- /compare


@dataclass
class AppSummary:
    platform: str
    cheapest: float | None
    in_stock: int
    total: int
    listing_wide: bool


async def compare_summary(session: AsyncSession, product_id: str) -> list[AppSummary]:
    """Latest result per (app, pincode) for the seller's own listing, rolled up per app."""
    rows = (
        await session.scalars(
            select(CheckResult)
            .where(CheckResult.product_id == product_id, CheckResult.competitor_id.is_(None))
            .order_by(CheckResult.checked_at.desc())
        )
    ).all()
    latest: dict[tuple[str, str], CheckResult] = {}
    for row in rows:
        latest.setdefault((row.platform, row.pincode), row)
    apps: dict[str, AppSummary] = {}
    for (platform, _pincode), row in latest.items():
        app = apps.setdefault(
            platform,
            AppSummary(platform, None, 0, 0, (row.raw or {}).get("pincode_specific") is False),
        )
        if row.status != "ok":
            continue
        app.total += 1
        if row.in_stock:
            app.in_stock += 1
            if row.price is not None and (app.cheapest is None or row.price < app.cheapest):
                app.cheapest = row.price
    return sorted(apps.values(), key=lambda a: (a.cheapest is None, a.cheapest or 0))


def compare_text(product_name: str, apps: list[AppSummary]) -> str:
    if not apps:
        return f"{product_name}: no check results yet. Tap 🔍 Check now."
    best = next((a for a in apps if a.cheapest is not None), None)
    lines = [f"💰 {product_name}"]
    for app in apps:
        label = APP_LABELS.get(app.platform, app.platform)
        if app.cheapest is None:
            stock = "out of stock" if app.total else "no data"
            lines.append(f"• {label}: {stock}")
            continue
        mark = " ⭐ cheapest" if app is best else ""
        scope = " (listing-wide)" if app.listing_wide else f" · {app.in_stock}/{app.total} pins in stock"
        lines.append(f"• {label}: {_money(app.cheapest)}{scope}{mark}")
    return "\n".join(lines)


async def send_compare(message, chat_id: str) -> None:
    async with SessionLocal() as session:
        products = await _linked_products(session, chat_id)
        if not products:
            await message.reply_text("This chat is not connected. Use /link <code> first.")
            return
        blocks = [
            compare_text(product.name, await compare_summary(session, product.id))
            for product in products[:5]
        ]
    await message.reply_text("\n\n".join(blocks))


# --------------------------------------------------------------------- /check


async def start_check_flow(message, chat_id: str) -> None:
    async with SessionLocal() as session:
        products = await _linked_products(session, chat_id)
    if not products:
        await message.reply_text("This chat is not connected. Use /link <code> first.")
        return
    if len(products) == 1:
        await _ask_app(message, products[0])
        return
    rows = [[(p.name[:40], f"chk:p:{p.id}")] for p in products[:8]]
    await message.reply_text("Which product should I check?", reply_markup=_keyboard(rows))


async def _ask_app(message, product: Product, *, edit: bool = False) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        platforms = sorted(
            {
                row.platform
                for row in (
                    await session.scalars(
                        select(ProductPincode).where(ProductPincode.product_id == product.id)
                    )
                ).all()
            }
        )
    live = [p for p in platforms if not settings.tinyfish_enabled or p in settings.live_platforms]
    if not live:
        text = f"{product.name} has no apps that can be checked live. Add apps on the website."
        await (message.edit_text(text) if edit else message.reply_text(text))
        return
    rows = [[(APP_LABELS.get(p, p), f"chk:a:{product.id}:{p}") for p in live[i : i + 2]] for i in range(0, len(live), 2)]
    text = f"🔍 Live check for {product.name}\nWhich app?"
    await (message.edit_text(text, reply_markup=_keyboard(rows)) if edit else message.reply_text(text, reply_markup=_keyboard(rows)))


def _cost_note(platform: str) -> str:
    from .tinyfish.tinyfish_client import CHECK_STRATEGY

    if not get_settings().tinyfish_enabled:
        return "Simulated check (no TinyFish key), a few seconds."
    if CHECK_STRATEGY.get(platform) == "fetch":
        return "TinyFish Fetch: free, about 10 seconds. Same result for every pincode."
    return "TinyFish agent: uses 1 credit and takes 3–8 minutes."


async def handle_check_callback(update, context) -> bool:
    """chk:p / chk:a / chk:c / chk:r / chk:x callbacks; True when handled."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not (query.data or "").startswith("chk:"):
        return False
    parts = query.data.split(":")
    action, product_id = parts[1], parts[2] if len(parts) > 2 else ""
    chat_id = str(chat.id)
    if action == "x":
        await query.answer("Cancelled")
        await query.edit_message_text("Check cancelled. Nothing was run.")
        return True
    async with SessionLocal() as session:
        link = await _link_for(session, chat_id, product_id)
        product = await session.get(Product, product_id) if link else None
        if link is None or product is None:
            await query.answer("This chat is not linked to that product.")
            return True
        if action == "p":
            await query.answer()
            await _ask_app(query.message, product, edit=True)
            return True
        platform = parts[3] if len(parts) > 3 else ""
        if action == "a":
            pins = (
                await session.scalars(
                    select(ProductPincode.pincode)
                    .where(ProductPincode.product_id == product_id, ProductPincode.platform == platform)
                    .order_by(ProductPincode.pincode)
                )
            ).all()
            areas = {
                row.code: row.area_name
                for row in (await session.scalars(select(Pincode).where(Pincode.code.in_(pins)))).all()
            }
            rows = [
                [(f"{pin} · {areas.get(pin, '')}".strip(" ·")[:30], f"chk:c:{product_id}:{platform}:{pin}")]
                for pin in pins[:MAX_PINCODE_BUTTONS]
            ]
            await query.answer()
            await query.edit_message_text(
                f"🔍 {product.name} on {APP_LABELS.get(platform, platform)}\nWhich pincode?",
                reply_markup=_keyboard(rows or [[("Cancel", "chk:x")]]),
            )
            return True
        pincode = parts[4] if len(parts) > 4 else ""
        if action == "c":
            await query.answer()
            await query.edit_message_text(
                f"Run a live check?\n\n{product.name}\n{APP_LABELS.get(platform, platform)} · {pincode}\n\n"
                f"{_cost_note(platform)}",
                reply_markup=_keyboard([[("✅ Run check", f"chk:r:{product_id}:{platform}:{pincode}"), ("✖ Cancel", "chk:x")]]),
            )
            return True
        if action != "r":
            return False
        if chat.type in ("group", "supergroup"):
            actor = update.effective_user
            if actor is None or str(actor.id) != link.linked_by_telegram_user_id:
                await query.answer("Only the person who connected this group can run checks.")
                return True
        plan = await session.scalar(select(Subscription.plan).where(Subscription.user_id == product.user_id)) or "free"
        remaining = await remaining_credits_today(session, product.user_id, plan)
        if remaining is not None and remaining < 1:
            await query.answer("No credits left today.")
            return True
        try:
            run, jobs = await create_run(
                session, product, trigger="manual", platforms=[platform], pincodes=[pincode]
            )
        except HTTPException as exc:
            detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail
            await query.answer()
            await query.edit_message_text(f"Could not start the check: {detail}")
            return True
        except Exception:
            logger.exception("telegram check failed to start product=%s", product_id)
            await query.answer()
            await query.edit_message_text(
                "A check is already running for this product. Try again when it finishes."
            )
            return True
        schedule_run(run.id, product_id=product.id, user_id=product.user_id, jobs=jobs)
    await query.answer("Check started")
    await query.edit_message_text(
        f"⏳ Checking {product.name} on {APP_LABELS.get(platform, platform)} · {pincode}…"
    )
    task = asyncio.create_task(_follow_check(query.message, run.id, product.name, platform, pincode))
    _watchers.add(task)
    task.add_done_callback(_watchers.discard)
    return True


_watchers: set[asyncio.Task] = set()


async def _follow_check(message, run_id: str, product_name: str, platform: str, pincode: str) -> None:
    """Edit the progress message as agent steps arrive, then send the result."""
    past, queue = run_events.subscribe(run_id)
    header = f"⏳ Checking {product_name} on {APP_LABELS.get(platform, platform)} · {pincode}"
    steps: list[str] = []
    last_edit = 0.0
    deadline = time.monotonic() + CHECK_WATCH_SECONDS
    try:
        pending = list(past)
        while time.monotonic() < deadline:
            if not pending:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                except TimeoutError:
                    continue
                if event is None:
                    break
                pending.append(event)
            event = pending.pop(0)
            if event.get("type") == "agent_step":
                step = event.get("step") or {}
                steps.append(f"• {step.get('label', '')}"[:90])
                if time.monotonic() - last_edit >= PROGRESS_EDIT_SECONDS:
                    last_edit = time.monotonic()
                    with contextlib.suppress(Exception):
                        await message.edit_text("\n".join([header, "", *steps[-6:]]))
            elif event.get("type") == "run_done":
                break
    finally:
        run_events.unsubscribe(run_id, queue)
    await _send_check_result(message, run_id, product_name, platform, pincode)


async def _send_check_result(message, run_id: str, product_name: str, platform: str, pincode: str) -> None:
    async with SessionLocal() as session:
        row = await session.scalar(
            select(CheckResult)
            .where(CheckResult.run_id == run_id, CheckResult.competitor_id.is_(None))
            .order_by(CheckResult.checked_at.desc())
        )
    label = APP_LABELS.get(platform, platform)
    if row is None:
        await message.edit_text(f"⌛ {product_name} on {label} · {pincode}: still running. See the Agents page.")
        return
    if row.status != "ok":
        text = f"❌ {product_name} on {label} · {pincode}\nCheck failed: {row.error or 'unknown error'}"
    else:
        stock = "✅ In stock" if row.in_stock else ("❌ Out of stock" if row.in_stock is False else "❔ Stock unknown")
        eta = ""
        if row.eta_minutes is not None:
            eta = f"\n🚚 {row.eta_minutes} min" if row.eta_minutes < 120 else f"\n🚚 ~{round(row.eta_minutes / 1440)} days"
        source = (row.raw or {}).get("source")
        how = "TinyFish Fetch (listing-wide)" if source == "tinyfish_fetch_api" else (
            "Cached result" if source == "demo_cache" else "TinyFish agent"
        )
        text = f"{stock} · {product_name}\n{label} · {pincode}\n💰 {_money(row.price)}{eta}\nvia {how}"
    with contextlib.suppress(Exception):
        await message.edit_text(text)
    photo = _photo_path(row.screenshot_url)
    if photo is not None:
        with contextlib.suppress(Exception):
            await message.reply_photo(photo=photo.read_bytes(), caption=f"Proof: {label} · {pincode}")


# --------------------------------------------------------------------- photo alerts


def _photo_path(url: str | None) -> Path | None:
    from ..api.media import local_media_path

    path = local_media_path(url)
    if path is None or path.suffix.lower() not in PHOTO_TYPES or not path.exists():
        return None
    return path


async def alert_photo(session: AsyncSession, alert: Alert) -> Path | None:
    """Evidence screenshot for an alert: latest result at its app and pincode."""
    evidence = alert.evidence or {}
    platform, pincode = evidence.get("platform"), evidence.get("pincode")
    if not platform or not pincode:
        return None
    url = await session.scalar(
        select(CheckResult.screenshot_url)
        .where(
            CheckResult.product_id == alert.product_id,
            CheckResult.platform == platform,
            CheckResult.pincode == pincode,
            CheckResult.screenshot_url.is_not(None),
        )
        .order_by(CheckResult.checked_at.desc())
        .limit(1)
    )
    return _photo_path(url)


async def send_alert(chat_id: str, text: str, photo: Path | None) -> bool:
    """Alert with its screenshot attached when one exists; text-only otherwise."""
    from .telegram import get_bot_application, send_telegram_message

    application = get_bot_application()
    if photo is not None and application is not None:
        try:
            await application.bot.send_photo(chat_id=chat_id, photo=photo.read_bytes(), caption=text[:1000])
            return True
        except Exception:
            logger.warning("alert photo failed chat=%s; sending text", chat_id, exc_info=True)
    return await send_telegram_message(chat_id, text)
