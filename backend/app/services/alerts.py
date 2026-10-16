"""Alert rule evaluation after runs, plus delivery to linked channels.

Rules live in ``alert_rules`` per product; when none are configured the
defaults below apply. Every alert carries a dedupe_key so repeat conditions
across runs do not spam the user. Delivery is a no-op until Telegram is
configured, but alerts are always persisted for the dashboard and API.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.base import utcnow
from ..models.checks import ChangeEvent
from ..models.intelligence import Alert, AlertRule
from ..models.product import Pincode, Product
from ..models.telegram import TelegramLink
from ..models.user import User, UserSettings
from .insights import _latest_rival_rows, _latest_seller_rows

logger = logging.getLogger("shelfsense.alerts")

ALERT_KINDS = (
    "oos_any",
    "price_change_pct",
    "rating_below",
    "price_gap_pct",
    "rival_oos",
    "custom",
)
DEFAULT_RATING_THRESHOLD = 4.0
DEFAULT_GAP_THRESHOLD_PCT = 5.0
ALERT_MESSAGE_LIMIT = 2000


def default_alert_rules(product: Product) -> list[dict]:
    return [
        {"kind": "oos_any", "threshold": None, "rule_text": "Any pin is out of stock"},
        {
            "kind": "price_change_pct",
            "threshold": product.max_change_pct,
            "rule_text": f"Price moved by more than {product.max_change_pct}%",
        },
        {
            "kind": "rating_below",
            "threshold": DEFAULT_RATING_THRESHOLD,
            "rule_text": f"Rating drops below {DEFAULT_RATING_THRESHOLD}",
        },
        {
            "kind": "price_gap_pct",
            "threshold": DEFAULT_GAP_THRESHOLD_PCT,
            "rule_text": f"Price is more than {DEFAULT_GAP_THRESHOLD_PCT}% above the rival",
        },
    ]


async def effective_rules(
    session: AsyncSession, product: Product
) -> list[AlertRule | dict]:
    stored = list(
        (
            await session.scalars(
                select(AlertRule).where(
                    AlertRule.product_id == product.id, AlertRule.active.is_(True)
                )
            )
        ).all()
    )
    if stored:
        return stored
    return default_alert_rules(product)


def _rule_threshold(rule: AlertRule | dict, default: float | None) -> float | None:
    threshold = getattr(rule, "threshold", None)
    if threshold is None and isinstance(rule, dict):
        threshold = rule.get("threshold")
    return float(threshold) if threshold is not None else default


async def _areas_for(session: AsyncSession, codes: set[str]) -> dict[str, str]:
    if not codes:
        return {}
    rows = list(
        (await session.scalars(select(Pincode).where(Pincode.code.in_(codes)))).all()
    )
    return {row.code: row.area_name for row in rows}


async def evaluate_alerts(
    session: AsyncSession,
    product: Product,
    *,
    run_id: str | None = None,
    now: datetime | None = None,
) -> list[Alert]:
    """Evaluate rules against the latest data and persist unseen alerts."""
    now = now if now is not None else utcnow()
    rules = await effective_rules(session, product)
    seller_latest = await _latest_seller_rows(session, product.id)
    rival_latest = await _latest_rival_rows(session, product.id)

    cheapest_rival: dict[tuple[str, str], float] = {}
    for (competitor_id, platform, pincode), row in rival_latest.items():
        del competitor_id
        if row.status != "ok" or row.in_stock is not True or row.price is None:
            continue
        key = (platform, pincode)
        current = cheapest_rival.get(key)
        if current is None or row.price < current:
            cheapest_rival[key] = row.price

    areas = await _areas_for(
        session,
        {pincode for (_platform, pincode) in seller_latest},
    )

    candidates: list[dict] = []
    for rule in rules:
        kind = getattr(rule, "kind", None) or rule.get("kind")
        active = getattr(rule, "active", True)
        if isinstance(rule, dict):
            active = rule.get("active", True)
        if not active or kind not in ALERT_KINDS:
            continue
        if kind == "oos_any":
            for (platform, pincode), row in seller_latest.items():
                if row.in_stock is False:
                    area = areas.get(pincode, pincode)
                    candidates.append(
                        {
                            "kind": "oos_any",
                            "message": (
                                f"{product.name} is out of stock in {area} "
                                f"({pincode}) on {platform}."
                            )[:ALERT_MESSAGE_LIMIT],
                            "evidence": {
                                "platform": platform,
                                "pincode": pincode,
                                "price": row.price,
                            },
                            "dedupe_key": (
                                f"oos:{product.id}:{platform}:{pincode}:"
                                f"{now.date().isoformat()}"
                            ),
                        }
                    )
        elif kind == "price_change_pct":
            threshold = _rule_threshold(rule, product.max_change_pct) or 0.0
            events = list(
                (
                    await session.scalars(
                        select(ChangeEvent)
                        .where(
                            ChangeEvent.product_id == product.id,
                            ChangeEvent.kind.in_(("price_rise", "price_drop")),
                            ChangeEvent.detected_at >= now - timedelta(hours=24),
                        )
                        .order_by(ChangeEvent.detected_at.desc())
                    )
                ).all()
            )
            for event in events:
                if event.old_value in (None, 0) or event.new_value is None:
                    continue
                pct = abs(event.new_value - event.old_value) / event.old_value * 100
                if pct < threshold:
                    continue
                direction = "up" if event.new_value > event.old_value else "down"
                candidates.append(
                    {
                        "kind": "price_change_pct",
                        "message": (
                            f"{product.name} price is {direction} {pct:.1f}% on "
                            f"{event.platform}/{event.pincode} "
                            f"(₹{event.old_value:.2f} → ₹{event.new_value:.2f})."
                        )[:ALERT_MESSAGE_LIMIT],
                        "evidence": {
                            "platform": event.platform,
                            "pincode": event.pincode,
                            "old_value": event.old_value,
                            "new_value": event.new_value,
                            "pct": round(pct, 2),
                        },
                        "dedupe_key": (
                            f"price_change:{product.id}:{event.platform}:"
                            f"{event.pincode}:{round(event.old_value, 2)}:"
                            f"{round(event.new_value, 2)}"
                        ),
                    }
                )
        elif kind == "rating_below":
            threshold = _rule_threshold(rule, DEFAULT_RATING_THRESHOLD) or 0.0
            for (platform, pincode), row in seller_latest.items():
                if row.rating is not None and row.rating < threshold:
                    area = areas.get(pincode, pincode)
                    candidates.append(
                        {
                            "kind": "rating_below",
                            "message": (
                                f"{product.name} rating {row.rating:.1f} is below "
                                f"{threshold:.1f} in {area} ({pincode}) on {platform}."
                            )[:ALERT_MESSAGE_LIMIT],
                            "evidence": {
                                "platform": platform,
                                "pincode": pincode,
                                "rating": row.rating,
                                "threshold": threshold,
                            },
                            "dedupe_key": (
                                f"rating:{product.id}:{platform}:{pincode}:"
                                f"{round(float(row.rating), 2)}"
                            ),
                        }
                    )
        elif kind == "price_gap_pct":
            threshold = _rule_threshold(rule, DEFAULT_GAP_THRESHOLD_PCT) or 0.0
            for (platform, pincode), row in seller_latest.items():
                if row.price is None or row.status != "ok":
                    continue
                rival_price = cheapest_rival.get((platform, pincode))
                if rival_price is None or rival_price == 0:
                    continue
                gap = (row.price / rival_price - 1) * 100
                if gap < threshold:
                    continue
                area = areas.get(pincode, pincode)
                candidates.append(
                    {
                        "kind": "price_gap_pct",
                        "message": (
                            f"{product.name} on {platform} in {area} is priced "
                            f"{gap:.1f}% above the rival "
                            f"(₹{row.price:.2f} vs ₹{rival_price:.2f})."
                        )[:ALERT_MESSAGE_LIMIT],
                        "evidence": {
                            "platform": platform,
                            "pincode": pincode,
                            "price": row.price,
                            "rival_price": rival_price,
                            "gap_pct": round(gap, 2),
                        },
                        "dedupe_key": (
                            f"price_gap:{product.id}:{platform}:{pincode}:"
                            f"{round(row.price, 2)}:{round(rival_price, 2)}"
                        ),
                    }
                )

        elif kind == "rival_oos":
            for (competitor_id, platform, pincode), row in rival_latest.items():
                if row.in_stock is not False:
                    continue
                area = areas.get(pincode, pincode)
                candidates.append(
                    {
                        "kind": "rival_oos",
                        "message": (
                            f"A competitor is out of stock for {product.name} "
                            f"in {area} ({pincode}) on {platform} — "
                            "chance to capture the shelf."
                        )[:ALERT_MESSAGE_LIMIT],
                        "evidence": {
                            "competitor_id": competitor_id,
                            "platform": platform,
                            "pincode": pincode,
                        },
                        "dedupe_key": (
                            f"rival_oos:{product.id}:{competitor_id}:"
                            f"{platform}:{pincode}:"
                            f"{now.date().isoformat()}"
                        ),
                    }
                )
        elif kind == "custom":
            # Custom rules carry structured conditions in rule_json; without
            # them there is nothing deterministic to evaluate, so they are
            # stored for the UI but do not fire automatically.
            continue

    if not candidates:
        return []
    keys = {candidate["dedupe_key"] for candidate in candidates}
    existing = set(
        (
            await session.scalars(
                select(Alert.dedupe_key).where(Alert.dedupe_key.in_(keys))
            )
        ).all()
    )
    created: list[Alert] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate["dedupe_key"]
        if key in existing or key in seen:
            continue
        seen.add(key)
        alert = Alert(
            user_id=product.user_id,
            product_id=product.id,
            kind=candidate["kind"],
            message=candidate["message"],
            evidence=candidate["evidence"],
            dedupe_key=key,
        )
        session.add(alert)
        created.append(alert)
    if created:
        await session.commit()
        for alert in created:
            await session.refresh(alert)
        logger.info(
            "created %s alert(s) product=%s run=%s",
            len(created),
            product.id,
            run_id,
        )
    return created


def _within_quiet_hours(user_settings: UserSettings | None, now_local) -> bool:
    if user_settings is None:
        return False
    start = user_settings.quiet_hours_start
    end = user_settings.quiet_hours_end
    if not start or not end:
        return False
    try:
        start_minutes = int(start[:2]) * 60 + int(start[3:5])
        end_minutes = int(end[:2]) * 60 + int(end[3:5])
        current = now_local.hour * 60 + now_local.minute
    except (ValueError, IndexError):
        return False
    if start_minutes <= end_minutes:
        return start_minutes <= current < end_minutes
    return current >= start_minutes or current < end_minutes


async def deliver_alerts(
    session: AsyncSession, alerts: list[Alert]
) -> int:
    """Push alerts to linked Telegram chats; respects quiet hours.

    Returns the number of alerts delivered. Delivery is a no-op when the
    bot is not running; alerts stay available via the dashboard and API.
    """
    from .telegram import send_telegram_message  # local import avoids cycles

    if not alerts:
        return 0
    delivered = 0
    product_ids = {alert.product_id for alert in alerts}
    links = list(
        (
            await session.scalars(
                select(TelegramLink).where(TelegramLink.product_id.in_(product_ids))
            )
        ).all()
    )
    if not links:
        return 0
    links_by_product: dict[str, list[TelegramLink]] = {}
    for link in links:
        links_by_product.setdefault(link.product_id, []).append(link)
    users = {
        row.id: row
        for row in (
            await session.scalars(
                select(User).where(
                    User.id.in_({link.user_id for link in links})
                )
            )
        ).all()
    }
    settings_rows = {
        row.user_id: row
        for row in (
            await session.scalars(
                select(UserSettings).where(
                    UserSettings.user_id.in_(users.keys())
                )
            )
        ).all()
    }
    for alert in alerts:
        for link in links_by_product.get(alert.product_id, []):
            if link.alert_types and alert.kind not in link.alert_types:
                continue
            user = users.get(link.user_id)
            if user is None:
                continue
            try:
                local_now = datetime.now(ZoneInfo(user.timezone))
            except (ZoneInfoNotFoundError, ValueError):
                local_now = datetime.now(UTC)
            if _within_quiet_hours(settings_rows.get(link.user_id), local_now):
                continue
            text = f"[ShelfSense] {alert.message}"
            sent = await send_telegram_message(link.chat_id, text)
            if sent:
                alert.sent_telegram = True
                delivered += 1
    await session.commit()
    return delivered
