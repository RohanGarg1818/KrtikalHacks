"""ShelfSense FastAPI application factory."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.catalog import router as catalog_router
from .api.chat import router as chat_router
from .api.competitors import router as competitors_router
from .api.dashboard import router as dashboard_router
from .api.health import router as health_router
from .api.heatmap import router as heatmap_router
from .api.insights import router as insights_router
from .api.intelligence import router as intelligence_router
from .api.me import router as me_router
from .api.notifications import router as notifications_router
from .api.products import router as products_router
from .api.runs import router as runs_router
from .api.settings import router as settings_router
from .config import get_settings
from .db import dispose_db

logger = logging.getLogger("shelfsense")


def configure_logging() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .services.scheduler import shutdown_scheduler, start_scheduler
    from .services.telegram import start_bot, stop_bot

    configure_logging()
    settings = get_settings()
    app.state.scheduler_running = False
    app.state.bot_running = False
    if settings.telegram_enabled:
        app.state.bot_running = await start_bot()
    else:
        logger.info("telegram disabled; bot not started")
    try:
        start_scheduler()
        app.state.scheduler_running = True
    except Exception:
        logger.exception("scheduler failed to start")
    try:
        yield
    finally:
        await stop_bot()
        shutdown_scheduler()
        await dispose_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ShelfSense API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        # Any local port in development, so `next dev` on 3001 or 127.0.0.1 still connects.
        allow_origin_regex=(
            r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
            if settings.app_env == "development"
            else None
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            round((time.perf_counter() - started) * 1000),
        )
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {"code": f"http_{exc.status_code}", "message": message},
                # Kept during the hackathon build for clients using FastAPI's usual error field.
                "detail": exc.detail,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                },
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "request_id=%s unhandled error",
            getattr(request.state, "request_id", "unknown"),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Unexpected server error",
                }
            },
        )

    media_dir = Path("media")
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media_dir), name="media")
    app.include_router(health_router, prefix="/api")
    app.include_router(me_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(catalog_router, prefix="/api")
    app.include_router(products_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(competitors_router, prefix="/api")
    app.include_router(heatmap_router, prefix="/api")
    app.include_router(insights_router, prefix="/api")
    app.include_router(intelligence_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(notifications_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    return app


app = create_app()
