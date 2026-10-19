"""Competitor suggestions from real search results (TinyFish Search API).

For "Amul Taaza Toned Milk 500 ml" we search Amazon.in and Flipkart for the
category ("Toned Milk 500 ml") and keep product pages from other brands with
the same pack size. Nothing is invented: without a TinyFish key there are no
suggestions, and the seller can still add rivals by hand.
"""

from __future__ import annotations

import logging
import re

from ..config import get_settings
from .tinyfish.marketplace import MARKETPLACES, PRODUCT_URL_RE
from .tinyfish.pack import _ACCESSORY_RE, _SIZE_RE, BRAND_ALIASES, same_pack

logger = logging.getLogger("shelfsense.competitors")

PER_SITE = 3
SEARCH_TIMEOUT_SECONDS = 15.0
_TITLE_TAIL_RE = re.compile(
    r"\s*(?::\s*Amazon\.in.*|\s+Price in India.*|\s*-\s*Buy .* online at Flipkart\.com.*)$", re.IGNORECASE
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Rivals must be the same kind of product, not something made for it.
_NOT_A_RIVAL_RE = re.compile(
    r"\b(compatible|case|cover|glass|protector|cable|charger|adapter|replacement|skin|pouch|strap|stand|holder|replica|clone|copy|first copy)\b",
    re.IGNORECASE,
)
_STOP = {"and", "with", "for", "the", "of", "in"}


def _model_token(word: str) -> bool:
    """"3", "3i", "141" are model tokens; "20000mAh" or "18W" are specs."""
    return bool(re.search(r"\d", word)) and not re.search(r"(?i)\d\s*(mah|w)$", word)


def rival_query(text: str, brand: str | None) -> str:
    """Category words for finding rivals, without the brand or model.

    "Amul Taaza Toned Milk 500 ml" -> "Taaza Toned Milk 500 ml";
    "JBL Go 3 Bluetooth Speaker" -> "Bluetooth Speaker";
    "Xiaomi Power Bank 3i 20000mAh" -> "Power Bank 20000mAh".
    """
    cleaned = re.sub(r"\([^)]*\)", " ", text)  # "(live test)", "(2nd generation)"
    sizes = [m.group(0) for m in _SIZE_RE.finditer(cleaned)]
    cleaned = _SIZE_RE.sub(" ", cleaned)
    words = cleaned.split()
    brand_words = {w.lower() for w in (brand or (words[0] if words else "")).split()}
    words = [w for w in words if w.lower().strip("'’s") not in brand_words]
    specs = [w for w in words if re.search(r"(?i)\d\s*mah$", w)]
    model_at = next((i for i, w in enumerate(words) if _model_token(w)), None)
    if model_at is None:
        category = [w for w in words if w not in specs]
    else:
        after = [w for w in words[model_at + 1 :] if not _model_token(w) and w not in specs]
        before = [w for w in words[:model_at] if w not in specs]
        category = after if len(after) >= 2 or (after and not before) else [*before, *after]
    query = " ".join(dict.fromkeys([*category, *specs, *sizes])).strip()
    return query or text


def clean_title(title: str) -> str:
    title = _TITLE_TAIL_RE.sub("", title.strip()).removeprefix("Buy ").strip()
    # Marketplace titles run on ("..., Small Speaker with Pro Sound | ..."): keep the
    # product name before the first comma or bar when that still names it.
    head = re.split(r"\s*[,|]\s*", title, maxsplit=1)[0]
    if len(head.split()) < 3:
        return title[:120]
    size = _SIZE_RE.search(title)
    if size and not _SIZE_RE.search(head):
        head = f"{head}, {size.group(0)}"  # the pack size matters: keep it
    return head[:120]


def _same_product(a: str, b: str) -> bool:
    ta, tb = set(_TOKEN_RE.findall(a.lower())), set(_TOKEN_RE.findall(b.lower()))
    return bool(ta) and len(ta & tb) / len(ta | tb) > 0.6


async def discover_competitors(
    search_query: str, brand: str | None, product_name: str
) -> tuple[list[dict[str, str]], str]:
    """(suggestions, source). Each suggestion: name, platform, search_query, url."""
    settings = get_settings()
    if not settings.tinyfish_enabled:
        return [], "unavailable"
    from tinyfish import AsyncTinyFish

    query = rival_query(product_name, brand)
    own_brand = (brand or search_query.split()[0]).lower()
    own_names = BRAND_ALIASES.get(own_brand, {own_brand})
    category_words = {
        w for w in _TOKEN_RE.findall(_SIZE_RE.sub(" ", query.lower())) if w not in _STOP and not w.isdigit()
    }
    suggestions: list[dict[str, str]] = []
    async with AsyncTinyFish(
        api_key=settings.tinyfish_api_key, timeout=SEARCH_TIMEOUT_SECONDS, max_retries=1
    ) as client:
        for platform, domain in MARKETPLACES.items():
            try:
                found = await client.search.query(
                    query, location="IN", language="en", include_domains=domain
                )
            except Exception:
                logger.warning("competitor search failed on %s", domain, exc_info=True)
                continue
            kept = 0
            for hit in found.results:
                title = clean_title(hit.title or "")
                if not title or not PRODUCT_URL_RE[platform].search(hit.url):
                    continue
                title_words = set(_TOKEN_RE.findall(title.lower()))
                if title_words & own_names or own_brand in title.lower():
                    continue
                if _ACCESSORY_RE.search(title) or (
                    _NOT_A_RIVAL_RE.search(title) and not _NOT_A_RIVAL_RE.search(query)
                ):
                    continue
                # Must name the category ("power bank", "toned milk"), not just specs.
                if category_words and len(category_words & title_words) < min(2, len(category_words)):
                    continue
                if same_pack(search_query, title) is False:
                    continue
                if any(_same_product(title, s["name"]) for s in suggestions):
                    continue
                suggestions.append(
                    {"name": title, "platform": platform, "search_query": title, "url": hit.url}
                )
                kept += 1
                if kept >= PER_SITE:
                    break
    return suggestions, "tinyfish_search"
