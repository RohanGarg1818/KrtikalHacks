# ShelfSense backend

FastAPI backend for the ShelfSense seller price and shelf-visibility assistant: it tracks a seller's products and competitors on Blinkit, Zepto, Instamart, Amazon, and Flipkart, checks price/stock/delivery across pincodes, and turns the results into heatmaps, AI summaries, recommendations, alerts, and a Telegram bot.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs`. The API serves dashboard, product and competitor management, manual/SSE check runs, heatmaps and weekly insights, AI summaries/recommendations/chat, alert rules and inbox, user settings, and Telegram linking.

Run the tests and linter:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests scripts
```

## Current plan limits

- Free: 3 products, 5 pincodes per product, weekly checks.
- Pro: 25 products, 100 pincodes per product, checks as often as every 3 hours.
- Brand: no product, pincode, or frequency limit.

`POST /api/me/plan` changes plans locally for development; it never charges or invokes a payment provider.

## Safe local mode (no keys needed)

Copy `.env.example` only if configuration is needed; do not commit a `.env`. With no keys at all, ShelfSense runs fully:

- **Database**: SQLite at `./shelfsense.db` (no `DATABASE_URL`).
- **Auth**: development auth maps every request to the seeded Riya Sharma demo user (no `SUPABASE_JWT_SECRET`).
- **Checks**: `MockTinyFishClient` returns deterministic fake results per query/platform/pincode with a 0.5–2s delay, ~15% out-of-stock, ~5% transient failures, and placeholder PNG screenshots in `./media/screenshots` (no `TINYFISH_API_KEY`).
- **AI**: a rule-based fallback produces the same response schemas as Gemini from the measured numbers (no `GEMINI_API_KEY`).
- **Telegram**: the bot does not start; link codes are still issued, messages are logged instead of sent (no `TELEGRAM_BOT_TOKEN`).
- `/api/health` reports the mock flags and whether the bot and scheduler are running.

`MOCK_MODE` is derived automatically from which keys are present.

## Integration switches

Set these environment variables (see `.env.example`) to move each integration from mock to real:

| Variable | Switches |
| --- | --- |
| `TINYFISH_API_KEY` + `TINYFISH_*_BASE_URL` | Real TinyFish agent/search/fetch HTTP client |
| `GEMINI_API_KEY` (optionally `GEMINI_MODEL`) | Gemini summaries, recommendations, chat, alert-rule parsing |
| `TELEGRAM_BOT_TOKEN` (+ `TELEGRAM_BOT_USERNAME`) | Long-polling bot and real message delivery |
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` | Remote screenshot storage |
| `SUPABASE_JWT_SECRET` | Bearer JWT authentication |
| `DATABASE_URL` | Postgres/Supabase instead of SQLite |
| `FRONTEND_ORIGIN` | CORS allow-list and Telegram "Details" button URLs |

## TinyFish documentation TODOs

All provider-specific TinyFish HTTP details are isolated in `app/services/tinyfish/http_client.py` behind the `TinyFishClient` interface. The mock client is the source of truth until the real API is confirmed. Before enabling the real client, confirm everything below from `docs.tinyfish.ai`:

- Agent run endpoint: URL path, HTTP method, request body schema (goal/prompt fields), authentication header format.
- Search endpoint: URL, query parameters, response shape for search hits.
- Fetch endpoint: URL, request body, response fields for fetched marketplace pages.
- Response JSON mapping: how `product`, `in_stock`, `price`, `mrp`, `eta_minutes`, `rating` are named in real responses.
- Screenshot delivery: inline base64 vs URL, image format, size limits.
- Credit accounting: which response field reports `credits_used` per job.
- Timeout policy: recommended per-request timeout and run-level deadline.
- Retryable failures: which HTTP status codes or error bodies should be retried.
- Rate limits: requests per minute/second and concurrency guidance.

## Postgres / Supabase

Set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname` to run against Postgres instead of SQLite; the engine selects the driver from the URL and no code changes are needed. Migrations use only generic SQLAlchemy types (`String`, `Float`, `JSON`, timezone-aware `DateTime`) so `alembic upgrade head` works on both SQLite and Postgres — verified by offline SQL rendering for each dialect and by compiling the full model DDL for the Postgres dialect. UUID primary keys are stored as 36-character strings for portability.

## Operations

- Each response carries an `X-Request-ID` header; errors use `{"error": {"code", "message"}}` (validation and HTTP errors also keep FastAPI's `detail` for compatibility).
- One process runs everything: API, asyncio check runner, the 15-minute due-run scheduler, the daily briefing job, and the Telegram bot. No Redis, Celery, or separate worker.
- Check runs execute in the background (`asyncio.create_task`); `POST /api/products/{id}/runs` returns immediately with a `run_id` and estimated credits, and progress streams on `GET /api/runs/{run_id}/stream` (SSE).
- After each run the pipeline detects change events, evaluates alert rules (with per-day dedupe and quiet hours), regenerates the AI summary/recommendations/review insights, and delivers alerts to linked Telegram chats.
- Telegram link codes are `SS-1234-WORD`, expire in 10 minutes, and are single-use. The bot supports `/start <code>`, `/link <code>`, `/status`, `/ask <question>`, and `/stop`; recommendation messages carry inline Approve and Details buttons.
