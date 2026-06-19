from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from redis import Redis, WatchError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.db.models import ActivityLog
from app.services.binance_sync import sync_binance
from app.services.credentials import CredentialConfigError, InvalidCredentialError
from app.services.portfolio_state import (
    PortfolioStateRefreshResult,
    refresh_portfolio_state,
    refresh_time_series_aggregates,
)
from app.services.xtb_ingest import repair_xtb_split_transactions

OWNED_REFRESH_LOCK_KEY = "portfolio:locks:owned_refresh"
BINANCE_AUTO_SYNC_LOCK_KEY = "portfolio:locks:binance_auto_sync"
SCHEDULER_ENQUEUE_LOCK_KEY = "portfolio:locks:scheduler_enqueue"
OWNED_REFRESH_LAST_ENQUEUED_KEY = "portfolio:scheduler:owned_refresh:last_enqueued_at"
BINANCE_AUTO_SYNC_LAST_ENQUEUED_KEY = (
    "portfolio:scheduler:binance_auto_sync:last_enqueued_at"
)
WATCHLIST_ALERTS_LAST_ENQUEUED_KEY = (
    "portfolio:scheduler:watchlist_alerts:last_enqueued_at"
)


def get_redis_connection(app_settings: Settings = settings) -> Redis:
    return Redis.from_url(app_settings.REDIS_URL)


def _parse_dt(value: bytes | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def acquire_single_flight_lock(
    redis_connection: Redis | None,
    *,
    key: str,
    ttl_seconds: int,
) -> str | None:
    if redis_connection is None:
        return str(uuid.uuid4())
    token = str(uuid.uuid4())
    acquired = redis_connection.set(key, token, nx=True, ex=ttl_seconds)
    return token if acquired else None


def release_single_flight_lock(
    redis_connection: Redis | None,
    *,
    key: str,
    token: str,
) -> None:
    if redis_connection is None:
        return
    while True:
        try:
            with redis_connection.pipeline() as pipe:
                pipe.watch(key)
                current = pipe.get(key)
                if isinstance(current, bytes):
                    current = current.decode("utf-8")
                if current != token:
                    pipe.unwatch()
                    return
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
                return
        except WatchError:
            continue


async def execute_owned_refresh(
    session: AsyncSession,
    *,
    redis_connection: Redis | None = None,
    captured_at: datetime | None = None,
    app_settings: Settings = settings,
    route: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    captured_at = captured_at or datetime.now(UTC)
    token = acquire_single_flight_lock(
        redis_connection,
        key=OWNED_REFRESH_LOCK_KEY,
        ttl_seconds=app_settings.OWNED_POLLING_LOCK_TTL_SECONDS,
    )
    if token is None:
        session.add(
            ActivityLog(
                source="owned_polling.refresh",
                status="skipped",
                message="owned refresh skipped because another refresh is already running",
                user_id=user_id,
            )
        )
        await session.commit()
        return {"status": "skipped", "reason": "lock_held"}

    try:
        await repair_xtb_split_transactions(session)
        result: PortfolioStateRefreshResult = await refresh_portfolio_state(
            session, captured_at=captured_at
        )
        await session.commit()
        await refresh_time_series_aggregates(
            session,
            start_at=captured_at,
            end_at=captured_at + timedelta(seconds=1),
        )
        session.add(
            ActivityLog(
                source="owned_polling.refresh",
                status="success",
                message=f"captured_at={result.captured_at.isoformat()}; route={route or 'worker'}",
                user_id=user_id,
            )
        )
        await session.commit()
        return {
            "status": "success",
            "captured_at": result.captured_at.isoformat(),
            "asset_count": result.asset_count,
            "snapshot_count": result.snapshot_count,
            "benchmark_count": result.benchmark_count,
        }
    except Exception as exc:
        await session.rollback()
        session.add(
            ActivityLog(
                source="owned_polling.refresh",
                status="failed",
                message=type(exc).__name__,
                user_id=user_id,
            )
        )
        await session.commit()
        raise
    finally:
        release_single_flight_lock(
            redis_connection, key=OWNED_REFRESH_LOCK_KEY, token=token
        )


async def execute_binance_auto_sync(
    session: AsyncSession,
    *,
    redis_connection: Redis | None = None,
    app_settings: Settings = settings,
    respect_enabled: bool = True,
    degrade_credential_errors: bool = True,
    source: str = "sync.binance_auto",
) -> dict[str, Any]:
    if respect_enabled and not app_settings.BINANCE_AUTO_SYNC_ENABLED:
        return {"status": "disabled"}
    token = acquire_single_flight_lock(
        redis_connection,
        key=BINANCE_AUTO_SYNC_LOCK_KEY,
        ttl_seconds=app_settings.BINANCE_AUTO_SYNC_LOCK_TTL_SECONDS,
    )
    if token is None:
        session.add(
            ActivityLog(
                source=source,
                status="skipped",
                message="Binance auto-sync skipped because another sync is already running",
            )
        )
        await session.commit()
        return {"status": "skipped", "reason": "lock_held"}

    try:
        result = await sync_binance(session)
        if result.get("error"):
            session.add(
                ActivityLog(
                    source=source,
                    status="degraded",
                    message=str(result["error"]),
                )
            )
            await session.commit()
            return {"status": "degraded", **result}
        status = "degraded" if result.get("degraded") else "success"
        session.add(
            ActivityLog(
                source=source,
                status=status,
                message="; ".join(result.get("warnings") or [])
                or "Binance auto-sync completed",
            )
        )
        await session.commit()
        return {"status": status, **result}
    except (CredentialConfigError, InvalidCredentialError) as exc:
        await session.rollback()
        if not degrade_credential_errors:
            raise
        session.add(
            ActivityLog(
                source=source,
                status="degraded",
                message=type(exc).__name__,
            )
        )
        await session.commit()
        return {"status": "degraded", "error": type(exc).__name__, "synced": 0}
    except Exception as exc:
        await session.rollback()
        session.add(
            ActivityLog(
                source=source,
                status="failed",
                message=type(exc).__name__,
            )
        )
        await session.commit()
        raise
    finally:
        release_single_flight_lock(
            redis_connection, key=BINANCE_AUTO_SYNC_LOCK_KEY, token=token
        )


def due_run_times(
    *,
    last_enqueued_at: datetime | None,
    now: datetime,
    cadence_seconds: int,
    max_catch_up_windows: int,
) -> list[datetime]:
    cadence = timedelta(seconds=cadence_seconds)
    if last_enqueued_at is None:
        return [now]
    next_due = last_enqueued_at + cadence
    if next_due > now:
        return []
    due: list[datetime] = []
    while next_due <= now and len(due) < max_catch_up_windows:
        due.append(next_due)
        next_due += cadence
    return due


def _rq_safe_job_id(job_prefix: str, run_at: datetime) -> str:
    return f"{job_prefix}-{run_at.isoformat().replace(':', '').replace('+', 'Z')}"


def _enqueue_periodic_job(
    *,
    queue: Any,
    redis_connection: Redis,
    key: str,
    func: Any,
    job_prefix: str,
    cadence_seconds: int,
    max_catch_up_windows: int,
    now: datetime,
) -> int:
    last_enqueued_at = _parse_dt(redis_connection.get(key))
    runs = due_run_times(
        last_enqueued_at=last_enqueued_at,
        now=now,
        cadence_seconds=cadence_seconds,
        max_catch_up_windows=max_catch_up_windows,
    )
    for run_at in runs:
        queue.enqueue(
            func,
            job_id=_rq_safe_job_id(job_prefix, run_at),
            captured_at=run_at.isoformat(),
        )
    if runs:
        next_unqueued = runs[-1] + timedelta(seconds=cadence_seconds)
        marker = now if next_unqueued <= now else runs[-1]
        redis_connection.set(key, marker.isoformat())
    return len(runs)


def enqueue_due_jobs(
    *,
    queue: Any,
    redis_connection: Redis,
    now: datetime | None = None,
    app_settings: Settings = settings,
    owned_refresh_func: Any = None,
    binance_auto_sync_func: Any = None,
    watchlist_alerts_func: Any = None,
) -> dict[str, int]:
    from worker.jobs import (
        run_alert_evaluation,
        run_binance_auto_sync,
        run_owned_refresh,
    )

    enqueue_token = acquire_single_flight_lock(
        redis_connection,
        key=SCHEDULER_ENQUEUE_LOCK_KEY,
        ttl_seconds=60,
    )
    if enqueue_token is None:
        return {"owned_refresh": 0, "binance_auto_sync": 0, "watchlist_alerts": 0}
    try:
        now = now or datetime.now(UTC)
        owned_count = 0
        binance_count = 0
        watchlist_count = 0
        if app_settings.OWNED_POLLING_ENABLED:
            owned_count = _enqueue_periodic_job(
                queue=queue,
                redis_connection=redis_connection,
                key=OWNED_REFRESH_LAST_ENQUEUED_KEY,
                func=owned_refresh_func or run_owned_refresh,
                job_prefix="owned-refresh",
                cadence_seconds=app_settings.OWNED_POLLING_CADENCE_SECONDS,
                max_catch_up_windows=app_settings.OWNED_POLLING_MAX_CATCH_UP_WINDOWS,
                now=now,
            )
        if app_settings.BINANCE_AUTO_SYNC_ENABLED:
            binance_count = _enqueue_periodic_job(
                queue=queue,
                redis_connection=redis_connection,
                key=BINANCE_AUTO_SYNC_LAST_ENQUEUED_KEY,
                func=binance_auto_sync_func or run_binance_auto_sync,
                job_prefix="binance-auto-sync",
                cadence_seconds=app_settings.BINANCE_AUTO_SYNC_CADENCE_SECONDS,
                max_catch_up_windows=1,
                now=now,
            )
        if app_settings.WATCHLIST_ALERTS_ENABLED:
            watchlist_count = _enqueue_periodic_job(
                queue=queue,
                redis_connection=redis_connection,
                key=WATCHLIST_ALERTS_LAST_ENQUEUED_KEY,
                func=watchlist_alerts_func or run_alert_evaluation,
                job_prefix="watchlist-alerts",
                cadence_seconds=app_settings.WATCHLIST_ALERTS_CADENCE_SECONDS,
                max_catch_up_windows=1,
                now=now,
            )
        return {
            "owned_refresh": owned_count,
            "binance_auto_sync": binance_count,
            "watchlist_alerts": watchlist_count,
        }
    finally:
        release_single_flight_lock(
            redis_connection, key=SCHEDULER_ENQUEUE_LOCK_KEY, token=enqueue_token
        )


async def get_freshness_status(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    app_settings: Settings = settings,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)

    async def latest(source: str, status: str | None = None) -> ActivityLog | None:
        stmt = select(ActivityLog).where(ActivityLog.source == source)
        if status is not None:
            stmt = stmt.where(ActivityLog.status == status)
        return (
            await session.execute(stmt.order_by(ActivityLog.created_at.desc()).limit(1))
        ).scalars().first()

    owned_success = await latest("owned_polling.refresh", "success")
    owned_failure = await latest("owned_polling.refresh", "failed")
    binance_success = await latest("sync.binance_auto", "success")
    binance_degraded = await latest("sync.binance_auto", "degraded")
    binance_failure = await latest("sync.binance_auto", "failed")
    last_success_at = owned_success.created_at if owned_success is not None else None
    binance_last_ok_at = None
    if binance_success is not None and binance_degraded is not None:
        binance_last_ok_at = max(binance_success.created_at, binance_degraded.created_at)
    elif binance_success is not None:
        binance_last_ok_at = binance_success.created_at
    elif binance_degraded is not None:
        binance_last_ok_at = binance_degraded.created_at
    stale_after = timedelta(seconds=app_settings.OWNED_POLLING_STALE_AFTER_SECONDS)
    next_run_at = (
        last_success_at + timedelta(seconds=app_settings.OWNED_POLLING_CADENCE_SECONDS)
        if last_success_at is not None and app_settings.OWNED_POLLING_ENABLED
        else None
    )
    return {
        "owned_polling": {
            "enabled": app_settings.OWNED_POLLING_ENABLED,
            "cadence_seconds": app_settings.OWNED_POLLING_CADENCE_SECONDS,
            "last_success_at": _iso(last_success_at),
            "last_failure_at": _iso(owned_failure.created_at)
            if owned_failure is not None
            else None,
            "last_failure": owned_failure.message if owned_failure is not None else None,
            "stale": last_success_at is None or now - last_success_at > stale_after,
            "next_run_at": _iso(next_run_at),
        },
        "binance_auto_sync": {
            "enabled": app_settings.BINANCE_AUTO_SYNC_ENABLED,
            "cadence_seconds": app_settings.BINANCE_AUTO_SYNC_CADENCE_SECONDS,
            "last_success_at": _iso(binance_success.created_at)
            if binance_success is not None
            else None,
            "last_degraded_at": _iso(binance_degraded.created_at)
            if binance_degraded is not None
            else None,
            "last_failure_at": _iso(binance_failure.created_at)
            if binance_failure is not None
            else None,
            "last_failure": binance_failure.message if binance_failure is not None else None,
            "stale": binance_last_ok_at is None
            or now - binance_last_ok_at
            > timedelta(seconds=app_settings.BINANCE_AUTO_SYNC_CADENCE_SECONDS * 2),
            "next_run_at": _iso(
                binance_last_ok_at
                + timedelta(seconds=app_settings.BINANCE_AUTO_SYNC_CADENCE_SECONDS)
            )
            if binance_last_ok_at is not None and app_settings.BINANCE_AUTO_SYNC_ENABLED
            else None,
        },
    }
