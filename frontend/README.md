# ShelfSense frontend

Next.js 15 (App Router) + React 19 + Tailwind CSS v4 + Leaflet/OpenStreetMap. Talks to the FastAPI backend in `../backend`.

## Run

```bash
# 1. backend (first time: see ../backend/README.md for venv, migrate, seed)
cd ../backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# 2. frontend
cd ../frontend
npm install
npm run dev        # http://localhost:3000
```

Set `NEXT_PUBLIC_API_URL` (see `.env.example`) if the backend is not on `http://localhost:8000`.
With no API keys the backend runs in demo mode (mock checks, rule-based AI, simulated Telegram) and the app shows a "Demo mode" banner.

## Screens

| Route | Screen |
| --- | --- |
| `/` | Home (product story, live map, pricing) |
| `/dashboard` | User dashboard |
| `/products` | Products table + add-product flow |
| `/products/[id]` | Product dashboard (KPIs, AI summary, actions, competitors, weekly, reviews) |
| `/heatmap?product=[id]` | Pincode heatmap with live re-checks over SSE |
| `/help` | Help Centre chatbot |
| `/products/[id]/settings` | Product settings |
| `/settings` | User settings |
| `/products/[id]/telegram` | Telegram connection |

## Design system

Holst palette (Ink Navy, Deep Navy, Slate Blue, Sage, Sand, Linen) as tokens in `src/app/globals.css`, soft-brutalist primitives (`.card`, `.btn`, `.sticker`, `.chip`, `.tab`, `.input`, `.skeleton`, `.stagger`), Fraunces + Inter. Status is always colour + icon + label (`STATUS_META` in `src/components/ui.tsx`).
