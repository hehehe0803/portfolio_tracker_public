from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings
from app.services import scheduler_jobs
from fakeredis import FakeStrictRedis
from rq import Queue

from worker import jobs as worker_jobs
from worker import scheduler as worker_scheduler


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[object, dict]] = []

    def enqueue(self, func, **kwargs):
        self.enqueued.append((func, kwargs))
        return SimpleNamespace(id=kwargs.get("job_id"), func=func)


def _settings(**overrides) -> Settings:
    values = {
        "OWNED_POLLING_ENABLED": True,
        "OWNED_POLLING_CADENCE_SECONDS": 900,
        "OWNED_POLLING_MAX_CATCH_UP_WINDOWS": 3,
        "BINANCE_AUTO_SYNC_ENABLED": True,
        "BINANCE_AUTO_SYNC_CADENCE_SECONDS": 3600,
        "WATCHLIST_ALERTS_ENABLED": False,
        "WATCHLIST_ALERTS_CADENCE_SECONDS": 3600,
        "DATABASE_URL": "postgresql+asyncpg://localhost/portfolio_scheduler_test",
    }
    values.update(overrides)
    return Settings(**values)


def test_scheduler_enqueues_enabled_jobs_and_respects_disabled_flags():
    redis = FakeStrictRedis()
    queue = FakeQueue()
    now = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)

    summary = worker_scheduler.enqueue_due_jobs(
        queue=queue,
        redis_connection=redis,
        now=now,
        settings=_settings(BINANCE_AUTO_SYNC_ENABLED=False),
    )

    assert summary == {
        "owned_refresh": 1,
        "binance_auto_sync": 0,
        "watchlist_alerts": 0,
    }
    assert [func for func, _ in queue.enqueued] == [worker_jobs.run_owned_refresh]


def test_scheduler_enqueues_watchlist_alert_evaluation_when_enabled():
    redis = FakeStrictRedis()
    queue = FakeQueue()
    now = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)

    summary = worker_scheduler.enqueue_due_jobs(
        queue=queue,
        redis_connection=redis,
        now=now,
        settings=_settings(
            OWNED_POLLING_ENABLED=False,
            BINANCE_AUTO_SYNC_ENABLED=False,
            WATCHLIST_ALERTS_ENABLED=True,
            WATCHLIST_ALERTS_CADENCE_SECONDS=3600,
        ),
    )

    assert summary == {
        "owned_refresh": 0,
        "binance_auto_sync": 0,
        "watchlist_alerts": 1,
    }
    assert [func for func, _ in queue.enqueued] == [worker_jobs.run_alert_evaluation]
    assert queue.enqueued[0][1]["job_id"].startswith("watchlist-alerts-")
    assert ":" not in queue.enqueued[0][1]["job_id"]


def test_scheduler_uses_rq_safe_job_ids():
    redis = FakeStrictRedis()
    queue = Queue(connection=redis)
    now = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)

    summary = worker_scheduler.enqueue_due_jobs(
        queue=queue,
        redis_connection=redis,
        now=now,
        settings=_settings(BINANCE_AUTO_SYNC_ENABLED=False),
    )

    assert summary == {
        "owned_refresh": 1,
        "binance_auto_sync": 0,
        "watchlist_alerts": 0,
    }
    job_ids = [job.id for job in queue.jobs]
    assert len(job_ids) == 1
    assert ":" not in job_ids[0]


def test_scheduler_bounded_catch_up_never_replays_unlimited_windows():
    redis = FakeStrictRedis()
    queue = FakeQueue()
    now = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    redis.set(
        scheduler_jobs.OWNED_REFRESH_LAST_ENQUEUED_KEY,
        (now - timedelta(days=2)).isoformat(),
    )

    summary = worker_scheduler.enqueue_due_jobs(
        queue=queue,
        redis_connection=redis,
        now=now,
        settings=_settings(OWNED_POLLING_MAX_CATCH_UP_WINDOWS=2, BINANCE_AUTO_SYNC_ENABLED=False),
    )

    assert summary["owned_refresh"] == 2
    assert len(queue.enqueued) == 2
    assert redis.get(scheduler_jobs.OWNED_REFRESH_LAST_ENQUEUED_KEY).decode() == now.isoformat()


def test_owned_refresh_job_uses_refresh_path_and_aggregate_refresh(monkeypatch):
    calls: list[str] = []
    fake_session = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.add = lambda obj: calls.append(f"activity:{obj.status}")
    fake_result = SimpleNamespace(
        captured_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
        asset_count=2,
        snapshot_count=2,
        benchmark_count=3,
    )

    async def fake_repair(session):
        calls.append("repair")

    async def fake_refresh(session, *, captured_at):
        calls.append("refresh")
        return fake_result

    async def fake_aggregates(session, *, start_at, end_at):
        calls.append("aggregates")

    monkeypatch.setattr(scheduler_jobs, "repair_xtb_split_transactions", fake_repair)
    monkeypatch.setattr(scheduler_jobs, "refresh_portfolio_state", fake_refresh)
    monkeypatch.setattr(scheduler_jobs, "refresh_time_series_aggregates", fake_aggregates)

    result = worker_jobs._run_owned_refresh_async(
        session=fake_session,
        redis_connection=FakeStrictRedis(),
        captured_at=fake_result.captured_at,
    )

    assert result["status"] == "success"
    assert calls[:3] == ["repair", "refresh", "aggregates"]
    assert fake_session.commit.await_count == 2


def test_single_flight_lock_prevents_overlapping_owned_refresh(monkeypatch):
    redis = FakeStrictRedis()
    assert redis.set(scheduler_jobs.OWNED_REFRESH_LOCK_KEY, "other", nx=True, ex=60)
    fake_session = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()

    async def should_not_refresh(*args, **kwargs):  # pragma: no cover - proves lock behavior
        raise AssertionError("refresh should not run while lock is held")

    monkeypatch.setattr(scheduler_jobs, "refresh_portfolio_state", should_not_refresh)

    result = worker_jobs._run_owned_refresh_async(
        session=fake_session,
        redis_connection=redis,
        captured_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
    )

    assert result == {"status": "skipped", "reason": "lock_held"}


def test_binance_auto_sync_missing_credentials_degrades_safely(monkeypatch):
    fake_session = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.rollback = AsyncMock()
    fake_session.add = lambda obj: None

    async def missing_credentials(session):
        return {"error": "Binance encrypted API credentials not configured", "synced": 0}

    monkeypatch.setattr(scheduler_jobs, "sync_binance", missing_credentials)

    result = worker_jobs._run_binance_auto_sync_async(
        session=fake_session,
        redis_connection=FakeStrictRedis(),
        app_settings=_settings(BINANCE_AUTO_SYNC_ENABLED=True),
    )

    assert result["status"] == "degraded"
    assert result["error"] == "Binance encrypted API credentials not configured"
    assert fake_session.commit.await_count == 1
