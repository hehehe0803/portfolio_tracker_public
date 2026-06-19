from __future__ import annotations

import asyncio
from datetime import datetime

from redis import Redis

from app.config import settings
from app.db.session import async_session_factory
from app.services.alerts import evaluate_alerts
from app.services.scheduler_jobs import execute_binance_auto_sync, execute_owned_refresh
from worker.app import get_redis_connection


def ping() -> str:
    return "pong"


def run_alert_evaluation() -> int:
    async def _run() -> int:
        async with async_session_factory() as session:
            return await evaluate_alerts(session)

    return asyncio.run(_run())


def _parse_captured_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


async def _run_owned_refresh_coroutine(
    *,
    session=None,
    redis_connection: Redis | None = None,
    captured_at: datetime | None = None,
) -> dict:
    if session is not None:
        return await execute_owned_refresh(
            session,
            redis_connection=redis_connection,
            captured_at=captured_at,
        )
    async with async_session_factory() as db_session:
        return await execute_owned_refresh(
            db_session,
            redis_connection=redis_connection or get_redis_connection(),
            captured_at=captured_at,
        )


def _run_owned_refresh_async(
    *,
    session=None,
    redis_connection: Redis | None = None,
    captured_at: datetime | None = None,
) -> dict:
    return asyncio.run(
        _run_owned_refresh_coroutine(
            session=session,
            redis_connection=redis_connection,
            captured_at=captured_at,
        )
    )


def run_owned_refresh(captured_at: str | None = None) -> dict:
    return _run_owned_refresh_async(captured_at=_parse_captured_at(captured_at))


async def _run_binance_auto_sync_coroutine(
    *,
    session=None,
    redis_connection: Redis | None = None,
    app_settings=None,
) -> dict:
    if session is not None:
        return await execute_binance_auto_sync(
            session,
            redis_connection=redis_connection,
            app_settings=app_settings or settings,
        )
    async with async_session_factory() as db_session:
        return await execute_binance_auto_sync(
            db_session,
            redis_connection=redis_connection or get_redis_connection(),
            app_settings=app_settings or settings,
        )


def _run_binance_auto_sync_async(
    *,
    session=None,
    redis_connection: Redis | None = None,
    app_settings=None,
) -> dict:
    return asyncio.run(
        _run_binance_auto_sync_coroutine(
            session=session,
            redis_connection=redis_connection,
            app_settings=app_settings,
        )
    )


def run_binance_auto_sync(captured_at: str | None = None) -> dict:
    _ = captured_at
    return _run_binance_auto_sync_async()
