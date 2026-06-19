"""
Portfolio Tracker API - FastAPI Application Factory.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import app.db  # noqa: F401 – registers all ORM models
from app.config import settings
from app.db.base import Base
from app.db.session import async_session_factory, check_database_health, engine
from app.observability import (
    TelemetryCollector,
    build_rate_limiter_settings,
    client_identifier,
)
from app.schemas import BaseSchema  # noqa: F401
from app.services.xtb_ingest import repair_xtb_split_transactions

logger = logging.getLogger(__name__)

ReadinessCheck = Callable[[], Awaitable[None]]


async def _run_alert_check():
    from app.services.alerts import evaluate_alerts

    async with async_session_factory() as session:
        try:
            fired = await evaluate_alerts(session)
            if fired:
                logger.info(f"Alert check: {fired} alerts fired")
        except Exception as e:
            logger.error(f"Alert check failed: {e}")


async def _run_startup_xtb_split_repair() -> int:
    async with async_session_factory() as session:
        repaired = await repair_xtb_split_transactions(session)
        if repaired:
            await session.commit()
            logger.info(
                f"Repaired {repaired} legacy XTB split transaction(s) on startup"
            )
        return repaired


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting Portfolio Tracker API v{settings.VERSION}")
    app.state.lifespan_started = True

    if app.state.run_startup_db_init:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        app.state.startup_db_init_ran = True
        logger.info("Database tables verified/created")

    if app.state.run_startup_repairs:
        app.state.startup_xtb_split_repair_count = await _run_startup_xtb_split_repair()
    else:
        app.state.startup_xtb_split_repair_count = 0

    if app.state.run_scheduler:
        scheduler = app.state.scheduler
        # Schedule alert checks every 10 minutes.
        scheduler.add_job(_run_alert_check, "interval", minutes=10, id="alert_check")
        scheduler.start()
        app.state.scheduler_started = True
        logger.info("Scheduler started (alerts every 10 min)")

    yield

    # Shutdown
    scheduler = app.state.scheduler
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
        app.state.scheduler_started = False

    app.state.lifespan_started = False
    await engine.dispose()
    logger.info("Shutdown complete")


def create_application(
    *,
    run_startup_db_init: bool = True,
    run_startup_repairs: bool = True,
    run_scheduler: bool = True,
    readiness_check: ReadinessCheck = check_database_health,
) -> FastAPI:
    app = FastAPI(
        title="Portfolio Tracker API",
        description="Command center for Binance + XTB portfolio tracking",
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.run_startup_db_init = run_startup_db_init
    app.state.run_startup_repairs = run_startup_repairs
    app.state.run_scheduler = run_scheduler
    app.state.readiness_check = readiness_check
    app.state.lifespan_started = False
    app.state.startup_db_init_ran = False
    app.state.startup_xtb_split_repair_count = 0
    app.state.scheduler_started = False
    app.state.scheduler = AsyncIOScheduler() if run_scheduler else None
    app.state.telemetry = TelemetryCollector(max_events=settings.TELEMETRY_MAX_EVENTS)
    app.state.rate_limiter = build_rate_limiter_settings(
        auth_limit=settings.RATE_LIMIT_AUTH_REQUESTS,
        auth_window_seconds=settings.RATE_LIMIT_AUTH_WINDOW_SECONDS,
        sensitive_limit=settings.RATE_LIMIT_SENSITIVE_REQUESTS,
        sensitive_window_seconds=settings.RATE_LIMIT_SENSITIVE_WINDOW_SECONDS,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS + settings.EXTRA_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def telemetry_and_rate_limit_middleware(request: Request, call_next):
        started_at = time.perf_counter()
        path = request.url.path
        route = path
        client = client_identifier(
            request.headers,
            request.client.host if request.client is not None else None,
            trust_forwarded_for=settings.RATE_LIMIT_TRUST_PROXY_HEADERS,
        )
        decision = app.state.rate_limiter.evaluate(path, client)
        sensitive = decision is not None

        if decision is not None and not decision.allowed:
            app.state.telemetry.record_request(
                method=request.method,
                path=path,
                route=route,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                client=client,
                rate_limited=True,
                sensitive=True,
                rule_name=decision.rule_name,
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(decision.retry_after_seconds),
                    "X-RateLimit-Limit": str(decision.limit),
                    "X-RateLimit-Remaining": str(decision.remaining),
                    "X-RateLimit-Rule": decision.rule_name,
                },
            )

        try:
            response = await call_next(request)
        except Exception:
            if (route_obj := request.scope.get("route")) is not None:
                route = getattr(route_obj, "path", path)
            app.state.telemetry.record_request(
                method=request.method,
                path=path,
                route=route,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                duration_ms=(time.perf_counter() - started_at) * 1000,
                client=client,
                rate_limited=False,
                sensitive=sensitive,
                rule_name=decision.rule_name if decision is not None else None,
            )
            raise
        if (route_obj := request.scope.get("route")) is not None:
            route = getattr(route_obj, "path", path)

        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            response.headers["X-RateLimit-Rule"] = decision.rule_name

        app.state.telemetry.record_request(
            method=request.method,
            path=path,
            route=route,
            status_code=response.status_code,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            client=client,
            rate_limited=False,
            sensitive=sensitive,
            rule_name=decision.rule_name if decision is not None else None,
        )
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    @app.get("/health", tags=["health"])
    async def health_check() -> dict[str, Any]:
        return {"status": "healthy", "version": settings.VERSION}

    @app.get("/readiness", tags=["health"])
    async def readiness_check() -> dict[str, Any]:
        try:
            await app.state.readiness_check()
        except Exception:
            logger.warning("Readiness check failed", exc_info=True)
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "not_ready", "database": "disconnected"},
            )
        return {"status": "ready", "database": "connected"}

    # Register v1 routers
    from app.api.v1.alert_rules import router as alerts_router
    from app.api.v1.auth import router as auth_router
    from app.api.v1.imports import router as imports_router
    from app.api.v1.intelligence import router as intelligence_router
    from app.api.v1.portfolio import router as portfolio_router
    from app.api.v1.review import router as review_router
    from app.api.v1.settings_router import router as settings_router
    from app.api.v1.sync import router as sync_router
    from app.api.v1.watchlist import router as watchlist_router

    for r in [
        auth_router,
        portfolio_router,
        sync_router,
        imports_router,
        intelligence_router,
        review_router,
        watchlist_router,
        alerts_router,
        settings_router,
    ]:
        app.include_router(r, prefix="/v1")

    return app


app = create_application(
    run_startup_db_init=settings.STARTUP_DB_INIT_ENABLED,
    run_startup_repairs=settings.STARTUP_REPAIRS_ENABLED,
    run_scheduler=settings.API_SCHEDULER_ENABLED,
)
