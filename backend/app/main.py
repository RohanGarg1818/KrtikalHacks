"""ShelfSense FastAPI application factory."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.chat import router as chat_router
from .api.competitors import router as competitors_router
from .api.dashboard import router as dashboard_router
from .api.health import router as health_router
from .api.heatmap import router as heatmap_router
from .api.insights import router as insights_router
from .api.intelligence import router as intelligence_router
from .api.me import router as me_router
from .api.products import router as products_router
from .api.runs import router as runs_router
from .api.settings import router as settings_router
from .config import get_settings
from .db import dispose_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Scheduler and Telegram lifecycle are deliberately no-ops until Stage 6.
    app.state.scheduler_running = False
    app.state.bot_running = False
    yield
    await dispose_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ShelfSense API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": str(exc)}},
        )

    media_dir = Path("media")
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")
    app.include_router(health_router, prefix="/api")
    app.include_router(me_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(products_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(competitors_router, prefix="/api")
    app.include_router(heatmap_router, prefix="/api")
    app.include_router(insights_router, prefix="/api")
    app.include_router(intelligence_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    return app


app = create_app()
