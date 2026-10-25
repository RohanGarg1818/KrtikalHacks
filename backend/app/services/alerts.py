"""Alert rule evaluation after runs, plus delivery to linked channels.

Rules live in ``alert_rules`` per product. The defaults below apply only while
a product has no rule rows at all, so disabling every rule really silences it.

Kinds:
  oos_any           seller out of stock at any selected pin
  oos_area          seller out of stock at pins in ``rule_json.pincodes`` or
                    whose area/city matches ``rule_json.areas``
  price_change_pct  a price change event above the threshold (last 24h)
  price_gap_pct     seller priced above the cheapest in-stock rival
  rating_below      seller rating under the threshold (``rating_drop`` alias)
  rival_oos         a rival out of stock — a chance to capture the shelf
  custom            keyword fallback: the rule text is parsed with the
                    deterministic plain-English parser and, when it maps to a
                    concrete kind, evaluated as that kind (alerts keep kind
                    "custom" and quote the rule); otherwise it never fires.

Every alert carries a dedupe_key. Condition alerts include the day, so a
persisting problem alerts at most once a day; price-change alerts are keyed
by their change event, so every new move alerts again. Delivery respects the
user's Telegram channel switch and defers alerts raised during quiet hours
until ``deliver_deferred_alerts`` runs after the quiet window.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..models.base import utcnow
from ..models.checks import ChangeEvent, CheckResult
from ..models.intelligence import Alert, AlertRule
from ..models.product import Pincode, Product
from ..models.telegram import TelegramLink
from ..models.user import User, UserSettings
from ..utils.geo import in_city_zone
from .ai.fallback import FallbackAIProvider
from .heatmap import selected_pairs
from .insights import _latest_rival_rows, _latest_seller_rows
from .price_thresholds import SENSITIVITY_THRESHOLDS, product_threshold_pct

logger = logging.getLogger("shelfsense.alerts")

ALERT_KINDS = (
    "oos_any",
    "oos_area",
    "price_change_pct",
    "rating_below",
    "rating_drop",
    "price_gap_pct",
    "rival_oos",
    "custom",
)
KIND_ALIASES = {"rating_drop": "rating_below"}
DEFAULT_RATING_THRESHOLD = 4.0
# Rules without their own threshold use the product's price-sensitivity
# threshold (essential 4%, regular 7%, premium 10%), the same bar the price
# recommendations use. Explicit user thresholds are never changed.
DEFAULT_GAP_THRESHOLD_PCT = SENSITIVITY_THRESHOLDS["regular"]


def default_gap_threshold(product: Product) -> float:
    return product_threshold_pct(product)

ALERT_MESSAGE_LIMIT = 2000
DEFERRED_ALERT_WINDOW = timedelta(hours=24)


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
            "threshold": default_gap_threshold(product),
            "rule_text": (
                f"Price is more than {default_gap_threshold(product):g}% above the rival"
            ),
        },
    ]


# Kind of the placeholder row written when the seller removes every rule, so an
# emptied list stays empty instead of falling back to the defaults. It is not
# an alert kind, so evaluation and the API never surface it.
RULES_CLEARED_KIND = "rules_cleared"

# Kinds a chat can receive on Telegram, plus the two non-alert streams.
TELEGRAM_ALERT_KINDS = (
    "oos_any",
    "oos_area",
    "price_change_pct",
    "price_gap_pct",
    "rating_below",
    "rival_oos",
    "custom",
)
TELEGRAM_STREAMS = (*TELEGRAM_ALERT_KINDS, "recommendations", "briefing")
# Stored ``TelegramLink.alert_types`` (a NOT NULL JSON list):
#   []        every alert kind and stream (the default for new links)
#   ["none"]  nothing at all — the seller unselected every option
#   [...]     exactly those kinds / streams
# The API exposes the same as ``null`` (everything), ``[]`` (nothing), or a list.
TELEGRAM_NOTHING = "none"


def telegram_types_out(stored: list | None) -> list[str] | None:
    """Stored ``alert_types`` → API value (None = everything, [] = nothing)."""
    if not stored:
        return None
    return [str(item) for item in stored if item != TELEGRAM_NOTHING]


def telegram_types_in(value: list[str] | None) -> list[str]:
    """API value → stored ``alert_types``."""
    if value is None:
        return []
    chosen = list(dict.fromkeys(str(item) for item in value))
    if not chosen:
        return [TELEGRAM_NOTHING]
    if set(TELEGRAM_STREAMS) <= set(chosen):
        return []
    return chosen


def link_wants(link: TelegramLink, stream: str) -> bool:
    """Whether a linked chat opted into an alert kind, "recommendations" or "briefing"."""
    stored = link.alert_types or []
    if not stored:
        return True
    return KIND_ALIASES.get(stream, stream) in {
        KIND_ALIASES.get(str(item), str(item)) for item in stored
    }


async def stored_rules(
    session: AsyncSession, product: Product
) -> list[AlertRule | dict]:
    """Every rule the seller sees, active or not.

    Defaults apply only while the product has never had rules saved; once the
    seller removed them all, a placeholder row keeps the list empty.
    """
    stored = list(
        (
            await session.scalars(
                select(AlertRule).where(AlertRule.product_id == product.id)
            )
        ).all()
    )
    if not stored:
        return default_alert_rules(product)
    return [rule for rule in stored if rule.kind != RULES_CLEARED_KIND]


async def effective_rules(
    session: AsyncSession, product: Product
) -> list[AlertRule | dict]:
    """Rules to evaluate: the active subset of ``stored_rules``."""
    return [
        rule
        for rule in await stored_rules(session, product)
        if _rule_field(rule, "active", True)
    ]


async def replace_alert_rules(
    session: AsyncSession, product_id: str, rules: list[dict]
) -> None:
    """Replace a product's rules; an empty list is remembered as "no rules"."""
    await session.execute(delete(AlertRule).where(AlertRule.product_id == product_id))
    if rules:
        session.add_all(AlertRule(product_id=product_id, **rule) for rule in rules)
    else:
        session.add(
            AlertRule(
                product_id=product_id,
                kind=RULES_CLEARED_KIND,
                rule_text="All alert rules removed",
                rule_json={},
                active=False,
            )
        )
    await session.commit()


def _rule_field(rule: AlertRule | dict, name: str, default=None):
    if isinstance(rule, dict):
        return rule.get(name, default)
    value = getattr(rule, name, default)
    return default if value is None else value


def _rule_threshold(rule: AlertRule | dict, default: float | None) -> float | None:
    threshold = _rule_field(rule, "threshold")
    return float(threshold) if threshold is not None else default


def _matches_area(
    area: str, city: str, wanted: str, coords: tuple[float, float] | None = None
) -> bool:
    wanted = wanted.strip().lower()
    if not wanted:
        return False
    zone = in_city_zone(wanted, city, coords)
    if zone is not None:
        return zone
    area, city = area.lower(), city.lower()
    # Never match on the city name inside a longer phrase: "South Delhi" holds
    # "delhi" but must not select every Delhi pincode.
    return wanted == city or wanted == area or wanted in area or area in wanted


async def resolve_rule_pincodes(session: AsyncSession, areas: list[str]) -> list[str]:
    """Pincodes whose area or city matches any of the named areas."""
    if not areas:
        return []
    rows = (await session.scalars(select(Pincode))).all()
    return sorted(
        row.code
        for row in rows
        if any(
            _matches_area(row.area_name, row.city, wanted, (row.lat, row.lng))
            for wanted in areas
        )
    )


class _Evaluation:
    """Latest data for one product, shared by every rule evaluator."""

    def __init__(
        self,
        product: Product,
        now: datetime,
        seller_latest: dict[tuple, CheckResult],
        rival_latest: dict[tuple, CheckResult],
        places: dict[str, tuple[str, str]],
        coords: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self.product = product
        self.now = now
        self.day = now.date().isoformat()
        self.seller_latest = seller_latest
        self.rival_latest = rival_latest
        self.places = places
        self.coords = coords or {}
        self.cheapest_rival: dict[tuple[str, str], float] = {}
        for (_competitor_id, platform, pincode), row in rival_latest.items():
            if row.status != "ok" or row.in_stock is not True or row.price is None:
                continue
            current = self.cheapest_rival.get((platform, pincode))
            if current is None or row.price < current:
                self.cheapest_rival[(platform, pincode)] = row.price

    def area(self, pincode: str) -> str:
        place = self.places.get(pincode)
        return place[0] if place else pincode


def _candidate(
    kind: str, message: str, evidence: dict, severity: str, dedupe_key: str
) -> dict:
    return {
        "kind": kind,
        "message": message[:ALERT_MESSAGE_LIMIT],
        "evidence": evidence,
        "severity": severity,
        "dedupe_key": dedupe_key[:500],
    }


# ---------------------------------------------------------------- noise control
#
# Each rule kind used to emit one alert per (platform, pincode) pair, every time
# the condition was still true. That is why a single out-of-stock product could
# raise a dozen identical-looking alerts. The functions below instead:
#
#   1. combine every affected pincode/platform into ONE alert per product per
#      run (``_*_items`` collect the raw hits; ``_combined_candidate`` turns
#      them into one candidate);
#   2. alert only when the problem *enters*, *gets meaningfully worse*, or
#      *recovers* — not on every run it is merely still true ("state machine"
#      kept as the previous Alert row's ``evidence.state``, see
#      ``_last_open_alert``);
#   3. round price gaps into bands (slightly / notably / far above) instead of
#      keying on exact rupee values, and ignore rupee-tiny moves, so a few
#      paise of noise never counts as "worse".
#
# ``severity`` (urgent / important / info) decides delivery speed, not whether
# the alert is kept — every alert still lands in the inbox either way.

# Price moves/gaps under this many rupees are noise, however large the % looks
# on a cheap item (e.g. a ₹0.20 move on a ₹0.50 product is technically "40%").
MIN_PRICE_MOVE_RUPEES = 2.0
# An open problem re-alerts only once it has grown by at least half the rule's
# own threshold (e.g. a 7%-threshold product needs the gap to widen by 3.5pp).
WORSEN_FRACTION = 0.5
# A rating has to fall by this much since the last alert to be worth a new one.
RATING_DROP_STEP = 0.2
# Share of checked pincodes out of stock before "out of stock" counts as urgent.
OOS_URGENT_FRACTION = 0.3
# Price-gap / price-change percentage points above which the alert is urgent.
GAP_URGENT_PCT = 50.0
PRICE_CHANGE_URGENT_PCT = 30.0
# A rating sitting this far under the threshold is worth a push, not just the inbox.
RATING_IMPORTANT_DROP = 0.5

_BAND_RANK = {"slightly": 0, "notably": 1, "far": 2}
_BAND_LABEL = {"slightly": "above", "notably": "well above", "far": "far above"}


def _gap_band(gap_pct: float) -> str:
    if gap_pct >= 50:
        return "far"
    if gap_pct >= 20:
        return "notably"
    return "slightly"


def _oos_items(ev: _Evaluation, pins: set[str] | None = None) -> list[dict]:
    return [
        {"platform": platform, "pincode": pincode, "price": row.price}
        for (platform, pincode), row in ev.seller_latest.items()
        if row.in_stock is False and (pins is None or pincode in pins)
    ]


def _area_pins(ev: _Evaluation, rule: AlertRule | dict) -> set[str]:
    rule_json = _rule_field(rule, "rule_json", {}) or {}
    pins = {str(code) for code in rule_json.get("pincodes") or []}
    areas = [str(area) for area in rule_json.get("areas") or []]
    for code, (area, city) in ev.places.items():
        coords = ev.coords.get(code)
        if any(_matches_area(area, city, wanted, coords) for wanted in areas):
            pins.add(code)
    return pins


def _gap_items(ev: _Evaluation, threshold: float) -> list[dict]:
    items = []
    for (platform, pincode), row in ev.seller_latest.items():
        if row.price is None or row.status != "ok":
            continue
        rival_price = ev.cheapest_rival.get((platform, pincode))
        if not rival_price or row.price - rival_price < MIN_PRICE_MOVE_RUPEES:
            continue
        gap = (row.price / rival_price - 1) * 100
        if gap < threshold:
            continue
        items.append(
            {
                "platform": platform,
                "pincode": pincode,
                "price": row.price,
                "rival_price": rival_price,
                "gap_pct": round(gap, 2),
            }
        )
    return items


def _rating_items(ev: _Evaluation, threshold: float) -> list[dict]:
    return [
        {"platform": platform, "pincode": pincode, "rating": row.rating}
        for (platform, pincode), row in ev.seller_latest.items()
        if row.rating is not None and row.rating < threshold
    ]


def _rival_oos_items(ev: _Evaluation) -> list[dict]:
    return [
        {"competitor_id": competitor_id, "platform": platform, "pincode": pincode}
        for (competitor_id, platform, pincode), row in ev.rival_latest.items()
        if row.in_stock is False
    ]


async def _price_change_items(
    session: AsyncSession, ev: _Evaluation, threshold: float
) -> list[dict]:
    events = (
        await session.scalars(
            select(ChangeEvent)
            .where(
                ChangeEvent.product_id == ev.product.id,
                ChangeEvent.kind.in_(("price_rise", "price_drop")),
                ChangeEvent.detected_at >= ev.now - timedelta(hours=24),
            )
            .order_by(ChangeEvent.detected_at.desc())
        )
    ).all()
    items = []
    for event in events:
        if event.old_value in (None, 0) or event.new_value is None:
            continue
        delta = abs(event.new_value - event.old_value)
        if delta < MIN_PRICE_MOVE_RUPEES:
            continue
        pct = delta / event.old_value * 100
        if pct < threshold:
            continue
        items.append(
            {
                "event_id": event.id,
                "platform": event.platform,
                "pincode": event.pincode,
                "old_value": event.old_value,
                "new_value": event.new_value,
                "pct": round(pct, 2),
                "direction": "up" if event.new_value > event.old_value else "down",
            }
        )
    return items


def _state_of(kind: str, items: list[dict]) -> dict:
    """A JSON-safe snapshot of "how bad is it right now", compared against the
    previous alert's state to tell enter / worse / unchanged / recovered apart."""
    if kind in ("oos_any", "oos_area", "rival_oos"):
        return {"pairs": sorted(f"{i['platform']}:{i['pincode']}" for i in items)}
    if kind == "price_gap_pct":
        return {
            "max_gap_pct": round(max((i["gap_pct"] for i in items), default=0.0), 2),
            "pairs": sorted(f"{i['platform']}:{i['pincode']}" for i in items),
        }
    if kind == "rating_below":
        return {"min_rating": round(min((i["rating"] for i in items), default=5.0), 2)}
    return {}


def _is_worse(kind: str, old_state: dict, new_state: dict, threshold: float) -> bool:
    if kind in ("oos_any", "oos_area", "rival_oos"):
        return not set(new_state.get("pairs", [])) <= set(old_state.get("pairs", []))
    if kind == "price_gap_pct":
        old_gap = old_state.get("max_gap_pct", 0.0)
        new_gap = new_state.get("max_gap_pct", 0.0)
        if new_gap <= old_gap:
            return False
        if _gap_band(new_gap) != _gap_band(old_gap):
            return True
        return (new_gap - old_gap) >= threshold * WORSEN_FRACTION
    if kind == "rating_below":
        old_r, new_r = old_state.get("min_rating"), new_state.get("min_rating")
        if old_r is None or new_r is None:
            return True
        return (old_r - new_r) >= RATING_DROP_STEP
    return True


def _severity_for(kind: str, ev: _Evaluation, items: list[dict], threshold: float) -> str:
    if kind in ("oos_any", "oos_area"):
        # The seller's own store running dry is always worth an instant push.
        if any(i["platform"] == "store" for i in items):
            return "urgent"
        fraction = len(items) / max(1, len(ev.seller_latest))
        return "urgent" if fraction >= OOS_URGENT_FRACTION else "important"
    if kind == "price_gap_pct":
        worst = max(i["gap_pct"] for i in items)
        return "urgent" if worst >= GAP_URGENT_PCT else "important"
    if kind == "rating_below":
        worst_drop = threshold - min(i["rating"] for i in items)
        return "important" if worst_drop >= RATING_IMPORTANT_DROP else "info"
    if kind == "rival_oos":
        return "info"
    return "important"


def _platform_name(platform: str) -> str:
    return "your ShelfSense Store" if platform == "store" else platform.capitalize()


def _oos_message(ev: _Evaluation, items: list[dict], event: str) -> str:
    by_platform: dict[str, list[str]] = {}
    for i in items:
        by_platform.setdefault(i["platform"], []).append(ev.area(i["pincode"]))
    where = "; ".join(
        f"{_platform_name(platform)} ({', '.join(sorted(set(areas)))})"
        for platform, areas in sorted(by_platform.items())
    )
    n = len(items)
    lead = "Still worsening — " if event == "worsened" else ""
    if any(i["platform"] == "store" for i in items):
        lead = "🚨 " + lead
    return f"{lead}{ev.product.name} is out of stock in {n} spot{'s' if n != 1 else ''}: {where}."


def _gap_message(ev: _Evaluation, items: list[dict], event: str) -> str:
    by_platform: dict[str, float] = {}
    for i in items:
        by_platform[i["platform"]] = max(by_platform.get(i["platform"], 0.0), i["gap_pct"])
    parts = ", ".join(
        f"{platform.capitalize()} {gap:.0f}%"
        for platform, gap in sorted(by_platform.items(), key=lambda kv: -kv[1])
    )
    band = _gap_band(max(i["gap_pct"] for i in items))
    lead = "Gap widened further — " if event == "worsened" else ""
    return f"{lead}{ev.product.name} is {_BAND_LABEL[band]} the cheapest rival on {parts}."


def _rating_message(ev: _Evaluation, items: list[dict], event: str, threshold: float) -> str:
    worst = min(i["rating"] for i in items)
    lead = "Rating dropped further — " if event == "worsened" else ""
    return f"{lead}{ev.product.name} rating is {worst:.1f}, below your {threshold:.1f} bar."


def _rival_oos_message(ev: _Evaluation, items: list[dict], event: str) -> str:
    del event  # always a fresh "chance" the moment it opens; no "worsened" wording needed
    n = len(items)
    return (
        f"A rival is out of stock for {ev.product.name} in {n} spot{'s' if n != 1 else ''} "
        "— a chance to capture the shelf."
    )


_RECOVERED_LABEL = {
    "oos_any": "is back in stock everywhere ✅",
    "oos_area": "is back in stock in that area ✅",
    "price_gap_pct": "price gap has closed ✅",
    "rating_below": "rating has recovered ✅",
    "rival_oos": "the rival is back in stock",
}


def _message_for(kind: str, ev: _Evaluation, items: list[dict], event: str, threshold: float) -> str:
    if kind in ("oos_any", "oos_area"):
        return _oos_message(ev, items, event)
    if kind == "price_gap_pct":
        return _gap_message(ev, items, event)
    if kind == "rating_below":
        return _rating_message(ev, items, event, threshold)
    if kind == "rival_oos":
        return _rival_oos_message(ev, items, event)
    return f"{ev.product.name}: {len(items)} update(s)."


async def _last_open_alert(
    session: AsyncSession, product_id: str, kind: str, bucket: str | None
) -> Alert | None:
    """Most recent alert of this kind/bucket still describing an open problem

    (i.e. the most recent one wasn't itself a "recovered" message); None if
    there is no earlier alert, or the problem was last seen resolved.
    """
    rows = (
        await session.scalars(
            select(Alert)
            .where(Alert.product_id == product_id, Alert.kind == kind)
            .order_by(Alert.created_at.desc())
            .limit(10)
        )
    ).all()
    for row in rows:
        if (row.evidence or {}).get("bucket") != bucket:
            continue
        return None if (row.evidence or {}).get("event") == "recovered" else row
    return None


async def _combined_candidate(
    session: AsyncSession,
    ev: _Evaluation,
    kind: str,
    items: list[dict],
    threshold: float,
    run_id: str | None,
    *,
    bucket: str | None = None,
) -> dict | None:
    """One alert for this kind — on enter, on a meaningful worsening, or on
    recovery — or None when the problem is unchanged (so nothing is sent)."""
    last = await _last_open_alert(session, ev.product.id, kind, bucket)
    old_state = (last.evidence or {}).get("state", {}) if last else {}
    new_state = _state_of(kind, items)
    if not items:
        if last is None:
            return None
        dedupe_key = f"{kind}:{ev.product.id}:{bucket or ''}:recovered:{run_id or ev.now.isoformat()}"
        evidence = {"event": "recovered", "state": {}, "bucket": bucket}
        return _candidate(kind, f"{ev.product.name} {_RECOVERED_LABEL.get(kind, 'is back to normal')}", evidence, "info", dedupe_key)
    if last is not None and not _is_worse(kind, old_state, new_state, threshold):
        return None
    event = "worsened" if last is not None else "enter"
    rep = items[0]
    if kind == "price_gap_pct":
        rep = max(items, key=lambda i: i["gap_pct"])
    elif kind == "rating_below":
        rep = min(items, key=lambda i: i["rating"])
    evidence = {
        "event": event,
        "state": new_state,
        "items": items[:25],
        "count": len(items),
        "platform": rep.get("platform"),
        "pincode": rep.get("pincode"),
        "bucket": bucket,
    }
    if kind == "price_gap_pct":
        evidence.update(gap_pct=rep["gap_pct"], price=rep["price"], rival_price=rep["rival_price"])
    elif kind == "rating_below":
        evidence.update(rating=rep["rating"], threshold=threshold)
    message = _message_for(kind, ev, items, event, threshold)
    severity = _severity_for(kind, ev, items, threshold)
    dedupe_key = f"{kind}:{ev.product.id}:{bucket or ''}:{event}:{run_id or ev.now.isoformat()}"
    return _candidate(kind, message, evidence, severity, dedupe_key)


def _price_change_candidate(ev: _Evaluation, items: list[dict], run_id: str | None) -> dict | None:
    """Price-change alerts are an event stream, not a persisting condition: one
    combined alert per run for whatever qualifying moves happened, deduped by
    the underlying change-event ids (so re-evaluating never repeats them)."""
    if not items:
        return None
    up = [i for i in items if i["direction"] == "up"]
    down = [i for i in items if i["direction"] == "down"]
    parts = []
    if up:
        parts.append(f"up {max(i['pct'] for i in up):.0f}% on {len(up)} listing{'s' if len(up) != 1 else ''}")
    if down:
        parts.append(f"down {max(i['pct'] for i in down):.0f}% on {len(down)} listing{'s' if len(down) != 1 else ''}")
    message = f"{ev.product.name} price moved: " + ", ".join(parts) + "."
    worst_pct = max(i["pct"] for i in items)
    severity = "urgent" if worst_pct >= PRICE_CHANGE_URGENT_PCT else "important"
    evidence = {
        "event": "moved",
        "items": items[:25],
        "count": len(items),
        "pct": worst_pct,
        "platform": items[0]["platform"],
        "pincode": items[0]["pincode"],
    }
    dedupe_key = "price_change:" + ev.product.id + ":" + ",".join(sorted(str(i["event_id"]) for i in items))
    return _candidate("price_change_pct", message, evidence, severity, dedupe_key)


async def _rule_candidates(
    session: AsyncSession,
    ev: _Evaluation,
    rule: AlertRule | dict,
    *,
    run_id: str | None = None,
    bucket: str | None = None,
) -> list[dict]:
    kind = KIND_ALIASES.get(_rule_field(rule, "kind"), _rule_field(rule, "kind"))
    rule_id = rule.id if isinstance(rule, AlertRule) else None
    if kind == "oos_any":
        candidate = await _combined_candidate(session, ev, "oos_any", _oos_items(ev), 0.0, run_id, bucket=bucket)
    elif kind == "oos_area":
        candidate = await _combined_candidate(
            session, ev, "oos_area", _oos_items(ev, _area_pins(ev, rule)), 0.0, run_id, bucket=bucket or rule_id
        )
    elif kind == "price_change_pct":
        threshold = _rule_threshold(rule, ev.product.max_change_pct) or 0.0
        candidate = _price_change_candidate(ev, await _price_change_items(session, ev, threshold), run_id)
    elif kind == "rating_below":
        threshold = _rule_threshold(rule, DEFAULT_RATING_THRESHOLD) or 0.0
        candidate = await _combined_candidate(session, ev, "rating_below", _rating_items(ev, threshold), threshold, run_id, bucket=bucket)
    elif kind == "price_gap_pct":
        threshold = _rule_threshold(rule, default_gap_threshold(ev.product)) or 0.0
        candidate = await _combined_candidate(session, ev, "price_gap_pct", _gap_items(ev, threshold), threshold, run_id, bucket=bucket)
    elif kind == "rival_oos":
        candidate = await _combined_candidate(session, ev, "rival_oos", _rival_oos_items(ev), 0.0, run_id, bucket=bucket)
    elif kind == "custom":
        return await _custom_candidates(session, ev, rule, rule_id, run_id=run_id)
    else:
        return []
    return [candidate] if candidate else []


async def _custom_candidates(
    session: AsyncSession,
    ev: _Evaluation,
    rule: AlertRule | dict,
    rule_id: str | None,
    *,
    run_id: str | None = None,
) -> list[dict]:
    text = (_rule_field(rule, "rule_text") or "").strip()
    if not text:
        return []
    parsed = await FallbackAIProvider().parse_alert_rule(text)
    if parsed.kind == "custom":
        return []
    derived = {
        "kind": parsed.kind,
        "threshold": _rule_field(rule, "threshold", parsed.threshold),
        "rule_json": {**parsed.rule_json, **(_rule_field(rule, "rule_json", {}) or {})},
    }
    quoted = text if len(text) <= 80 else text[:79] + "…"
    return [
        {
            **candidate,
            "kind": "custom",
            "message": f"Custom rule “{quoted}”: {candidate['message']}"[:ALERT_MESSAGE_LIMIT],
            "evidence": {**candidate["evidence"], "rule_text": text},
            "dedupe_key": f"custom:{rule_id}:{candidate['dedupe_key']}"[:500],
        }
        # Rides the same enter/worsen/recover engine as its derived kind, bucketed
        # by this rule's own id so it never shares state with a default rule of
        # the same kind (e.g. a custom "oos in South Delhi" rule vs. oos_any).
        for candidate in await _rule_candidates(session, ev, derived, run_id=run_id, bucket=rule_id)
    ]


MUTE_HOURS = 24


def mute_until(now: datetime | None = None) -> datetime:
    return (now or utcnow()) + timedelta(hours=MUTE_HOURS)


def product_muted(product: Product, now: datetime | None = None) -> bool:
    until = product.alert_muted_until
    return until is not None and until > (now or utcnow())


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
    if not rules:
        return []
    pairs = await selected_pairs(session, product.id)
    seller_latest = {
        key: row
        for key, row in (await _latest_seller_rows(session, product.id, now=now)).items()
        if key[0] in pairs.get(key[1], ())
    }
    rival_latest = {
        key: row
        for key, row in (await _latest_rival_rows(session, product.id, now=now)).items()
        if key[1] in pairs.get(key[2], ())
    }
    pincode_rows = (
        await session.scalars(select(Pincode).where(Pincode.code.in_(pairs)))
    ).all()
    places = {row.code: (row.area_name, row.city) for row in pincode_rows}
    coords = {row.code: (row.lat, row.lng) for row in pincode_rows}
    ev = _Evaluation(product, now, seller_latest, rival_latest, places, coords)

    candidates: list[dict] = []
    for rule in rules:
        if _rule_field(rule, "kind") in ALERT_KINDS:
            candidates.extend(await _rule_candidates(session, ev, rule, run_id=run_id))
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
            severity=candidate.get("severity", "important"),
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


def telegram_allowed(user_settings: UserSettings | None) -> bool:
    channels = user_settings.channels if user_settings is not None else None
    return not isinstance(channels, dict) or channels.get("telegram", True) is not False


async def deliver_alerts(
    session: AsyncSession, alerts: list[Alert]
) -> int:
    """Push alerts to linked Telegram chats; returns how many were delivered.

    Skipped entirely for users who switched the Telegram channel off. During
    quiet hours alerts stay unsent and ``deliver_deferred_alerts`` picks them
    up later. A chat only receives alerts raised after it was linked.
    Delivery is a no-op when the bot is not running.
    """
    from ..models.product import Product
    from .telegram_features import alert_photo, send_alert  # local import avoids cycles

    if not alerts:
        return 0
    delivered = 0
    product_ids = {alert.product_id for alert in alerts}
    products = {
        row.id: row
        for row in (
            await session.scalars(select(Product).where(Product.id.in_(product_ids)))
        ).all()
    }
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
                select(User).where(User.id.in_({link.user_id for link in links}))
            )
        ).all()
    }
    settings_rows = {
        row.user_id: row
        for row in (
            await session.scalars(
                select(UserSettings).where(UserSettings.user_id.in_(users.keys()))
            )
        ).all()
    }
    for alert in alerts:
        product = products.get(alert.product_id)
        if product is not None and product_muted(product):
            continue
        photo = await alert_photo(session, alert)
        for link in links_by_product.get(alert.product_id, []):
            if not link_wants(link, alert.kind):
                continue
            if alert.created_at < link.connected_at:
                continue
            user = users.get(link.user_id)
            if user is None:
                continue
            user_settings = settings_rows.get(link.user_id)
            if not telegram_allowed(user_settings):
                continue
            try:
                local_now = datetime.now(ZoneInfo(user.timezone))
            except (ZoneInfoNotFoundError, ValueError):
                local_now = datetime.now(UTC)
            if _within_quiet_hours(user_settings, local_now):
                continue
            sent = await send_alert(
                link.chat_id, f"[ShelfSense] {alert.message}", photo, product_id=alert.product_id
            )
            if sent:
                alert.sent_telegram = True
                delivered += 1
    await session.commit()
    return delivered


def instant_alerts(alerts: list[Alert], alert_level: str) -> list[Alert]:
    """Which of these newly-created alerts should push to Telegram right now.

    "urgent" always pushes instantly (nothing time-critical waits). "important"
    pushes instantly only on the "everything" level; otherwise it waits for the
    periodic digest (``deliver_important_digests``) — "calm" never pushes it at
    all. "info" never pushes; it is inbox + morning-briefing only. Every alert
    is kept in the inbox regardless, so no information is ever lost, only its
    delivery speed changes.
    """
    if alert_level == "calm":
        return [a for a in alerts if a.severity == "urgent"]
    if alert_level == "everything":
        return [a for a in alerts if a.severity in ("urgent", "important")]
    return [a for a in alerts if a.severity == "urgent"]


async def deliver_important_digests(now: datetime | None = None) -> int:
    """Batch "important" alerts (level=balanced) into one message per product,
    every ``DIGEST_INTERVAL_HOURS`` — instead of one push per check run."""
    now = now if now is not None else utcnow()
    async with SessionLocal() as session:
        pending = list(
            (
                await session.scalars(
                    select(Alert).where(
                        Alert.severity == "important",
                        Alert.sent_telegram.is_(False),
                        Alert.created_at >= now - DEFERRED_ALERT_WINDOW,
                    )
                )
            ).all()
        )
        if not pending:
            return 0
        from ..models.product import Product

        product_ids = {a.product_id for a in pending}
        user_ids = {a.user_id for a in pending}
        settings_rows = {
            row.user_id: row
            for row in (
                await session.scalars(
                    select(UserSettings).where(UserSettings.user_id.in_(user_ids))
                )
            ).all()
        }
        products = {
            row.id: row
            for row in (
                await session.scalars(select(Product).where(Product.id.in_(product_ids)))
            ).all()
        }
        by_product: dict[str, list[Alert]] = {}
        for alert in pending:
            level = (settings_rows.get(alert.user_id).alert_level if settings_rows.get(alert.user_id) else "balanced")
            if level != "balanced":
                continue  # "everything" already went instantly; "calm" never pushes "important"
            product = products.get(alert.product_id)
            if product is not None and product_muted(product, now):
                continue
            by_product.setdefault(alert.product_id, []).append(alert)
        if not by_product:
            return 0
        delivered = 0
        for product_id, items in by_product.items():
            product = products.get(product_id)
            name = product.name if product else "your product"
            lines = [f"[ShelfSense] {name} — {len(items)} update{'s' if len(items) != 1 else ''} since last digest:"]
            lines.extend(f"• {a.message}" for a in items[:10])
            sent = await deliver_digest_message(session, product_id, "\n".join(lines))
            if sent:
                for a in items:
                    a.sent_telegram = True
                delivered += sent
        await session.commit()
        return delivered


async def deliver_digest_message(session: AsyncSession, product_id: str, text: str) -> int:
    """Send one already-built digest message to every linked, opted-in chat."""
    from .telegram_features import send_alert

    links = list(
        (
            await session.scalars(
                select(TelegramLink).where(TelegramLink.product_id == product_id)
            )
        ).all()
    )
    sent = 0
    for link in links:
        user = await session.get(User, link.user_id)
        if user is None:
            continue
        user_settings = await session.get(UserSettings, user.id)
        if not telegram_allowed(user_settings):
            continue
        if await send_alert(link.chat_id, text, None, product_id=product_id):
            sent += 1
    return sent


async def deliver_deferred_alerts(now: datetime | None = None) -> int:
    """Retry recent unsent alerts (e.g. raised during quiet hours)."""
    now = now if now is not None else utcnow()
    async with SessionLocal() as session:
        pending = list(
            (
                await session.scalars(
                    select(Alert)
                    .where(
                        Alert.sent_telegram.is_(False),
                        Alert.created_at >= now - DEFERRED_ALERT_WINDOW,
                        or_(
                            Alert.product_id.in_(select(TelegramLink.product_id)),
                        ),
                    )
                    .order_by(Alert.created_at)
                )
            ).all()
        )
        return await deliver_alerts(session, pending)
