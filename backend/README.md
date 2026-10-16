# ShelfSense backend

FastAPI backend for the ShelfSense seller price and shelf-visibility assistant.

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

Open `http://localhost:8000/docs`. Current endpoints include `GET /api/health`, `GET /api/me`, product and competitor management under `/api/products`, and settings under `/api/me/settings`.

## Current plan limits

- Free: 3 products, 5 pincodes per product, weekly checks.
- Pro: 25 products, 100 pincodes per product, checks as often as every 3 hours.
- Brand: no product, pincode, or frequency limit.

`POST /api/me/plan` changes plans locally for development; it never charges or invokes a payment provider.

## Safe local mode

Copy `.env.example` only if configuration is needed; do not commit a `.env`. With no keys, ShelfSense uses SQLite at `./shelfsense.db`, development auth maps every request to the seeded Riya Sharma demo user, and `/api/health` reports mock mode. Future stages will use a mock TinyFish client, local screenshot storage, fallback AI, and disabled/no-op Telegram until their matching keys are provided.

## Integration switches

- `TINYFISH_API_KEY` plus its base URLs enables the real TinyFish client once Stage 3 lands.
- `GEMINI_API_KEY` enables Gemini once Stage 5 lands.
- `TELEGRAM_BOT_TOKEN` enables the bot once Stage 6 lands.
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` enable remote screenshot storage once Stage 3 lands.
- `SUPABASE_JWT_SECRET` enables JWT auth once Stage 2 lands.

## TinyFish documentation TODOs

The real TinyFish client has not been added until Stage 3. It will isolate all provider details in `app/services/tinyfish/http_client.py`; before enabling it, confirm the agent endpoint, search endpoint, fetch endpoint, authentication headers, request bodies, response JSON mapping, screenshot delivery, credits field, timeout policy, and retryable status codes from `docs.tinyfish.ai`.
