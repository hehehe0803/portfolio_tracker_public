from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.config import settings
from app.main import _run_startup_xtb_split_repair, create_application
from app.observability import client_identifier
from fastapi import status


async def test_health_endpoint_reports_healthy(async_client, app):
    assert app.state.lifespan_started is True
    assert app.state.startup_db_init_ran is False
    assert app.state.scheduler_started is False

    response = await async_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": settings.VERSION}
    telemetry_events = app.state.telemetry.snapshot()
    assert telemetry_events[-1]["event_type"] == "request"
    assert telemetry_events[-1]["route"] == "/health"
    assert telemetry_events[-1]["status_code"] == 200
    assert telemetry_events[-1]["sensitive"] is False


async def test_readiness_endpoint_reports_ready_with_injected_probe(async_client, app):
    assert app.state.readiness_probe_state["calls"] == 0

    response = await async_client.get("/readiness")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "connected"}
    assert app.state.readiness_probe_state["calls"] == 1


async def test_readiness_endpoint_fails_closed_when_probe_raises(async_client, app):
    async def failing_readiness_probe() -> None:
        app.state.readiness_probe_state["calls"] += 1
        raise RuntimeError("database unavailable")

    app.state.readiness_check = failing_readiness_probe
    app.state.readiness_probe_state["calls"] = 0

    response = await async_client.get("/readiness")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"status": "not_ready", "database": "disconnected"}
    assert app.state.readiness_probe_state["calls"] == 1


def test_client_identifier_ignores_spoofable_forwarded_headers_by_default() -> None:
    assert (
        client_identifier(
            {"x-forwarded-for": "203.0.113.10, 198.51.100.5"},
            "127.0.0.1",
        )
        == "127.0.0.1"
    )


def test_client_identifier_can_use_forwarded_headers_when_explicitly_trusted() -> None:
    assert (
        client_identifier(
            {"x-forwarded-for": "203.0.113.10, 198.51.100.5"},
            "127.0.0.1",
            trust_forwarded_for=True,
        )
        == "203.0.113.10"
    )


async def test_request_telemetry_records_failed_requests_when_handler_raises(
    async_client, app
):
    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await async_client.get("/boom")

    telemetry_events = app.state.telemetry.snapshot()
    assert telemetry_events[-1]["event_type"] == "request"
    assert telemetry_events[-1]["route"] == "/boom"
    assert telemetry_events[-1]["status_code"] == 500
    assert telemetry_events[-1]["rate_limited"] is False


@pytest.mark.asyncio
async def test_run_startup_xtb_split_repair_commits_when_rows_are_repaired(
    monkeypatch: pytest.MonkeyPatch,
):
    session = SimpleNamespace(commit=AsyncMock())

    class _SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    repair_mock = AsyncMock(return_value=2)
    monkeypatch.setattr("app.main.async_session_factory", lambda: _SessionContext())
    monkeypatch.setattr("app.main.repair_xtb_split_transactions", repair_mock)

    repaired = await _run_startup_xtb_split_repair()

    assert repaired == 2
    assert repair_mock.await_count == 1
    session.commit.assert_awaited_once()


async def test_sequential_app_lifespans_can_each_start_scheduler_without_job_conflicts():
    async def readiness_probe() -> None:
        return None

    @asynccontextmanager
    async def app_lifespan():
        application = create_application(
            run_startup_db_init=False,
            run_startup_repairs=False,
            run_scheduler=True,
            readiness_check=readiness_probe,
        )
        async with application.router.lifespan_context(application):
            assert application.state.scheduler_started is True
            yield application
        assert application.state.scheduler_started is False

    async with app_lifespan():
        pass

    async with app_lifespan():
        pass
