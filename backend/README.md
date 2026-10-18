# ShelfSense backend

FastAPI backend for the ShelfSense seller price and shelf-visibility assistant: it tracks a seller's products and competitors on Blinkit, Zepto, Instamart, Amazon, and Flipkart, checks price/stock/delivery across pincodes, and turns the results into heatmaps, AI summaries, recommendations, alerts, and a Telegram bot.

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime: requirements.txt
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs`. The API serves dashboard, product and competitor management, manual/SSE check runs, heatmaps and weekly insights, AI summaries/recommendations/chat, alert rules and inbox, user settings, and Telegram linking.

Run the tests and linter:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

## Endpoints added for the frontend

- `GET /api/pincodes`, `GET /api/plans` — pincode catalogue and plan limits.
- `GET /api/products/{id}/pincodes` — current pincode/platform selection.
- `GET|PUT /api/products/{id}/listings` — per-platform product links.
- `POST /api/products/{id}/alert-rules/parse` — plain-English rule → structured rule (Gemini or rule-based).
- `PATCH /api/me` — profile, language, timezone, default city.
- `POST /api/products/{id}/telegram/simulate-link` — mock mode only: redeem a link code as if the bot received `/start <code>`.
- `DELETE /api/products/{id}/telegram/links/{link_id}` — disconnect one chat (`DELETE /api/products/{id}/telegram` disconnects all).
- `GET /api/runs?product_id=&limit=` — recent runs with mode; `GET /api/runs/{id}` adds per-job `results` and `mode`.
- `GET /api/check-results/{id}` — one result with its agent trace (`agent.steps`, `true_price`); `GET /api/check-results/{id}/screenshot` — owner-checked evidence image.
- `GET /api/tinyfish/usage` — mode, concurrency, credits today vs budget, runs today, 7-day success rate.
- `GET /api/me/export?format=json` — full account export (CSV of results without `format`).

Chats without a product focus are grounded in the product the message names (else the one with the most stock-outs), plus plan credit usage.

## Current plan limits

- Free: 3 products, 5 pincodes and 3 competitors per product, weekly checks, 100 credits/day.
- Pro: 25 products, 100 pincodes and 10 competitors per product, checks as often as every 3 hours, 1000 credits/day.
- Brand: no product, pincode, frequency, or credit limit; 25 competitors per product.

New products default to the fastest frequency the plan allows. Manual runs are refused with `429 credit_budget_exceeded` when their job count exceeds today's remaining credits.

`POST /api/me/plan` is a test-mode switch (refused in production); it never charges. Downgrading clamps product frequencies and pauses the newest products beyond the cap, reporting `adjusted_products` / `paused_products`.

## Safe local mode (no keys needed)

Copy `.env.example` only if configuration is needed; do not commit a `.env`. With no keys at all, ShelfSense runs fully:

- **Database**: SQLite at `./shelfsense.db` (no `DATABASE_URL`).
- **Auth**: development auth maps every request to the seeded Riya Sharma demo user (no `SUPABASE_JWT_SECRET`, `APP_ENV` not `production`). `DELETE /api/me` returns 409 in this mode; `python -m scripts.seed` restores any missing demo data and is safe to re-run.
- **Checks**: `MockTinyFishClient` returns deterministic fake results per query/platform/pincode with a 0.5–2s delay, ~15% out-of-stock, ~5% transient failures, and simulated agent steps and SVG evidence screenshots in `./media/screenshots` (served at `/media` outside production only) (no `TINYFISH_API_KEY`).
- **AI**: a rule-based fallback produces the same response schemas as Gemini from the measured numbers (no `GEMINI_API_KEY`).
- **Telegram**: the bot does not start; link codes are still issued, messages are logged instead of sent (no `TELEGRAM_BOT_TOKEN`).
- `/api/health` reports the mock flags and whether the bot and scheduler are running.

Each integration switches on with its own key; `MOCK_MODE=true` forces all of them back to mocks. `/api/health` reports `auth_mode` (`dev`/`supabase`) and `tinyfish_mode` (`live`/`simulated`).

## Integration switches

Set these environment variables (see `.env.example`) to move each integration from mock to real:

| Variable | Switches |
| --- | --- |
| `TINYFISH_API_KEY` + `TINYFISH_*_BASE_URL` | Real TinyFish agent/search/fetch HTTP client |
| `GEMINI_API_KEY` (optionally `GEMINI_MODEL`) | Gemini summaries, recommendations, chat, alert-rule parsing |
| `TELEGRAM_BOT_TOKEN` (+ `TELEGRAM_BOT_USERNAME`) | Long-polling bot and real message delivery |
| `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` | Remote screenshot storage |
| `SUPABASE_JWT_SECRET` | Bearer JWT authentication (required when `APP_ENV=production`; SSE and screenshot URLs also accept `?access_token=`) |
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

Set `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname` to run against Postgres instead of SQLite; the engine selects the driver from the URL and no code changes are needed. Alembic runs through the same async driver as the app (aiosqlite/asyncpg), so no sync driver is needed. The initial revision is explicit `op.create_table` DDL using only generic types (`String`, `Float`, `JSON`, timezone-aware `DateTime`), with `ON DELETE` rules and a partial unique index allowing one active run per product; SQLite runs in batch mode and enforces foreign keys (`PRAGMA foreign_keys=ON`). UUID primary keys are stored as 36-character strings for portability.

## Operations

- Each response carries an `X-Request-ID` header; every error, including 404/405, validation (422, with `fields: [{loc, msg}]`), conflicts (409) and 500s (which keep CORS headers), uses `{"error": {"code", "message", "fields"?}}`.
- One process runs everything: API, asyncio check runner, the 15-minute due-run scheduler, the daily briefing job, and the Telegram bot. No Redis, Celery, or separate worker.
- Check runs execute in the background (`asyncio.create_task`); `POST /api/products/{id}/runs` returns immediately with a `run_id` and estimated credits, and progress streams on `GET /api/runs/{run_id}/stream` (SSE).
- After each run the pipeline detects change events, evaluates alert rules (with per-day dedupe and quiet hours), regenerates the AI summary/recommendations/review insights, and delivers alerts to linked Telegram chats.
- Telegram link codes are random `SS-…` tokens that expire in 10 minutes, are single-use, and replace the product's earlier unused codes; failed `/start` attempts are rate-limited per chat. The bot supports `/start <code>`, `/link <code>`, `/status`, `/ask <question>`, and `/stop`; recommendation messages carry inline Approve and Details buttons.
