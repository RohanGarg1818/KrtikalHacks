"""Safe deterministic competitor suggestions until the TinyFish client lands in Stage 3."""

from hashlib import sha256


def discover_competitors(query: str) -> list[dict[str, str]]:
    cleaned = " ".join(query.split())
    digest = sha256(cleaned.lower().encode()).hexdigest()[:6]
    return [
        {
            "name": f"{cleaned} — value alternative",
            "platform": "blinkit",
            "search_query": cleaned,
            "url": f"https://mock.shelfsense.local/blinkit/{digest}",
        },
        {
            "name": f"{cleaned} — popular alternative",
            "platform": "zepto",
            "search_query": cleaned,
            "url": f"https://mock.shelfsense.local/zepto/{digest}",
        },
    ]
