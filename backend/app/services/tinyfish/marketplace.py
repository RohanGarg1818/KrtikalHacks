"""Amazon.in and Flipkart checks through the TinyFish Fetch and Search APIs.

Fetch returns a product page's extracted text in seconds (no browser, no
clicks, so nothing can reach a cart or checkout). It cannot type a delivery
pincode, so these results describe the national listing as TinyFish's server
sees it: price, MRP, buyability and the default delivery promise. Every result
says so in ``raw["pincode_specific"] = False``.

Parsers are matched to real Fetch output captured on 2026-10-18:
  Amazon:   "##### One-time purchase ₹56.00 ₹28.00 per g ₹60 delivery Friday,
             20 November", "In stock" / "Currently unavailable."
  Flipkart: "# Haldiram's Plain Bhujia Sev (200 g)" then "₹53" "₹58", and a
             bottom "Add to cart" / "Buy Now" / "Notify Me" button.
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

MARKETPLACES = {"amazon": "amazon.in", "flipkart": "flipkart.com"}
PRODUCT_URL_RE = {
    "amazon": re.compile(r"amazon\.in/.*(?:/dp/|/gp/product/)[A-Z0-9]{10}"),
    "flipkart": re.compile(r"flipkart\.com/.+/p/itm[0-9a-z]+"),
}
FETCH_CACHE_SECONDS = 600
BUY_BOX_CHARS = 1500
# An MRP more than 3x the selling price belongs to some other listing.
MAX_MRP_RATIO = 3.0
IST = ZoneInfo("Asia/Kolkata")

_AMOUNT = r"₹\s?(\d[\d,]*(?:\.\d{1,2})?)"
_AMAZON_OFFER_RE = re.compile(
    rf"One-time purchase\s*{_AMOUNT}.*?(?:(FREE)|{_AMOUNT})\s+delivery\s+"
    r"(?:[A-Z][a-z]+day,?\s+)?(\d{1,2})\s+([A-Z][a-z]+)",
    re.DOTALL,
)
_AMAZON_PRICE_LINE_RE = re.compile(rf"^\s*{_AMOUNT}\s*$", re.MULTILINE)
_AMAZON_MRP_RE = re.compile(rf"M\.R\.P\.?:?\s*{_AMOUNT}")
_AMAZON_DELIVERY_RE = re.compile(
    rf"(?:(FREE)|{_AMOUNT})\s+delivery\s+(?:[A-Z][a-z]+day,?\s+)?(\d{{1,2}})\s+([A-Z][a-z]+)"
)
_FLIPKART_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_FLIPKART_PRICE_LINE_RE = re.compile(rf"^\s*{_AMOUNT}\s*$", re.MULTILINE)
_FLIPKART_CTA_RE = re.compile(r"\b(Add to cart|Buy Now|Notify Me|Sold Out)\b", re.IGNORECASE)
_MONTHS = {
    name: index
    for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"),
        start=1,
    )
}


class ListingSnapshot(BaseModel):
    """What one marketplace product page shows, validated before storage."""

    name: str | None = None
    price: float | None = Field(default=None, ge=0)
    mrp: float | None = Field(default=None, ge=0)
    in_stock: bool | None = None
    delivery_date: date | None = None
    delivery_fee: float | None = Field(default=None, ge=0)
    delivery_text: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def eta_minutes(self) -> int | None:
        if self.delivery_date is None:
            return None
        days = (self.delivery_date - datetime.now(IST).date()).days
        return max(days, 0) * 1440


def _amount(value: str | None) -> float | None:
    return round(float(value.replace(",", "")), 2) if value else None


def _delivery_date(day: str, month: str) -> date | None:
    month_number = _MONTHS.get(month.lower())
    if month_number is None:
        return None
    today = datetime.now(IST).date()
    try:
        candidate = date(today.year, month_number, int(day))
    except ValueError:
        return None
    # "20 January" read in December is next year's date.
    if (today - candidate).days > 31:
        candidate = date(today.year + 1, month_number, int(day))
    return candidate


def parse_amazon(text: str, title: str | None) -> ListingSnapshot:
    snapshot = ListingSnapshot(name=(title or "").split(" : ")[0].strip() or None)
    lowered = text.lower()
    if "currently unavailable" in lowered or "out of stock" in lowered:
        snapshot.in_stock = False
    elif "in stock" in lowered:
        snapshot.in_stock = True
    offer = _AMAZON_OFFER_RE.search(text)
    if offer:
        snapshot.price = _amount(offer.group(1))
        snapshot.delivery_fee = 0.0 if offer.group(2) else _amount(offer.group(3))
        snapshot.delivery_date = _delivery_date(offer.group(4), offer.group(5))
    else:
        line = _AMAZON_PRICE_LINE_RE.search(text)
        snapshot.price = _amount(line.group(1)) if line else None
        delivery = _AMAZON_DELIVERY_RE.search(text)
        if delivery:
            snapshot.delivery_fee = 0.0 if delivery.group(1) else _amount(delivery.group(2))
            snapshot.delivery_date = _delivery_date(delivery.group(3), delivery.group(4))
    # Only the buy box's MRP counts; lower down the page lists other products.
    anchor = offer or _AMAZON_PRICE_LINE_RE.search(text)
    buy_box = text[: anchor.end() + BUY_BOX_CHARS] if anchor else text[:BUY_BOX_CHARS]
    mrp = _AMAZON_MRP_RE.search(buy_box)
    if mrp and snapshot.price is not None:
        value = _amount(mrp.group(1))
        if snapshot.price < value <= snapshot.price * MAX_MRP_RATIO:
            snapshot.mrp = value
    if snapshot.delivery_date:
        fee = "FREE" if snapshot.delivery_fee == 0 else f"₹{snapshot.delivery_fee:g}"
        snapshot.delivery_text = f"{fee} delivery {snapshot.delivery_date:%a %d %b}"
    if snapshot.in_stock is False and snapshot.price is None:
        snapshot.notes.append("Listing is currently unavailable on Amazon")
    return snapshot


def parse_flipkart(text: str, title: str | None) -> ListingSnapshot:
    heading = _FLIPKART_HEADING_RE.search(text)
    name = heading.group(1).strip() if heading else None
    if not name and title and "{TITLE}" not in title:
        name = title.split(" Price in India")[0].strip()
    snapshot = ListingSnapshot(name=name)
    after = text[heading.end():] if heading else text
    amounts = [_amount(match) for match in _FLIPKART_PRICE_LINE_RE.findall(after[:600])]
    if amounts:
        snapshot.price = amounts[0]
        if len(amounts) > 1 and amounts[1] > amounts[0]:
            snapshot.mrp = amounts[1]
    # The page's main call to action is the last one (Flipkart's sticky bar).
    actions = _FLIPKART_CTA_RE.findall(text)
    if actions:
        snapshot.in_stock = actions[-1].lower() in ("add to cart", "buy now")
    if "not deliverable in your location" in text.lower():
        snapshot.notes.append("Flipkart reports this item is not deliverable to TinyFish's location")
    return snapshot


PARSERS = {"amazon": parse_amazon, "flipkart": parse_flipkart}


class _TimedCache:
    """Small per-process cache so one run fetches each listing once, not per pincode."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._items: dict[str, tuple[float, object]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def get(self, key: str) -> object | None:
        item = self._items.get(key)
        if item is None or time.monotonic() - item[0] > self.seconds:
            return None
        return item[1]

    def put(self, key: str, value: object) -> None:
        self._items[key] = (time.monotonic(), value)


listing_urls = _TimedCache(FETCH_CACHE_SECONDS * 6)
fetched_pages = _TimedCache(FETCH_CACHE_SECONDS)
