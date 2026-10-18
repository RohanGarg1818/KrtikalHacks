"""Static in-app help topics served to the chat sidebar and /help endpoints."""

from __future__ import annotations

HELP_TOPICS: list[dict] = [
    {
        "slug": "getting-started",
        "title": "Getting started",
        "body": (
            "Add a product with its name, category, and the pincodes you sell "
            "in. Pick the quick-commerce platforms you compete on (Blinkit, "
            "Zepto, Instamart) and launch your first check. ShelfSense streams "
            "live results, then fills the heatmap, weekly trends, and AI "
            "summary automatically."
        ),
    },
    {
        "slug": "runs",
        "title": "Checks and runs",
        "body": (
            "A run checks your product and each confirmed competitor across "
            "every selected platform and pincode. Free plans run weekly, Pro "
            "every 3 hours. Zepto and Instamart checks are TinyFish agent "
            "runs (3-8 minutes each, one credit each, including a failed "
            "attempt); Amazon and Flipkart pages are read with the Fetch API "
            "in seconds at no credit cost. Blinkit blocks automated browsers, "
            "so it is not checked live. Watch every step live on the Agents page."
        ),
    },
    {
        "slug": "heatmap",
        "title": "Reading the heatmap",
        "body": (
            "Each pin is classified from its freshest check: out_of_stock "
            "when the shelf is empty, price_gap when your price is 5% or more "
            "above the cheapest in-stock rival, stale when data is older than "
            "24 hours, otherwise in_stock. Hot zones mark clusters of three "
            "or more out-of-stock pins within 3 km."
        ),
    },
    {
        "slug": "weekly",
        "title": "Weekly report",
        "body": (
            "The weekly view compares the last 7 days against the previous 7: "
            "average price, out-of-stock count, rating, and a price-rank "
            "proxy. The changelog lists every detected price, stock, and "
            "rating change. Download the CSV for spreadsheets or finance."
        ),
    },
    {
        "slug": "recommendations",
        "title": "AI summaries and recommendations",
        "body": (
            "After each run ShelfSense writes a short summary and a handful of "
            "recommendations grounded in your check numbers. Accept or decline "
            "each one; accepted items stay in history for your team. With no "
            "Gemini key configured a deterministic rule-based engine produces "
            "the same structure offline."
        ),
    },
    {
        "slug": "credits",
        "title": "Credits and plans",
        "body": (
            "Every successful check costs one credit and is recorded in the "
            "ledger. Free includes 3 products and weekly checks, Pro covers 25 "
            "products with 3-hourly checks, and Brand removes limits. Change "
            "plans locally from settings; no payment provider is involved."
        ),
    },
]


def list_help_topics() -> list[dict]:
    return [dict(topic) for topic in HELP_TOPICS]


def get_help_topic(slug: str) -> dict | None:
    for topic in HELP_TOPICS:
        if topic["slug"] == slug:
            return dict(topic)
    return None
