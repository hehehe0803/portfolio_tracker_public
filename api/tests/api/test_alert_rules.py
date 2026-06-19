from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import app.db.session as db_session
import app.main as main_module
import pytest
import pytest_asyncio
from app.api import deps
from app.db.base import Base
from app.db.models import AlertEvent
from app.db.safety import (
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    pick_safe_test_database_url,
)
from app.main import create_application
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = pick_safe_test_database_url(
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    default_url=DEFAULT_LOCAL_PYTEST_DATABASE_URL,
)


@pytest_asyncio.fixture
async def test_session_factory():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def app(test_session_factory, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def readiness_probe() -> None:
        return None

    engine = test_session_factory.kw["bind"]
    monkeypatch.setattr(db_session, "async_session_factory", test_session_factory)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(main_module, "async_session_factory", test_session_factory)
    monkeypatch.setattr(main_module, "engine", engine)

    return create_application(
        run_startup_db_init=False,
        run_startup_repairs=False,
        run_scheduler=False,
        readiness_check=readiness_probe,
    )


@pytest.fixture
def override_auth(app: FastAPI):
    async def _override_user():
        return SimpleNamespace(
            id=1,
            username="alert-tester",
            totp_enabled=False,
            telegram_chat_id=None,
        )

    app.dependency_overrides[deps.get_current_user] = _override_user
    yield
    app.dependency_overrides.pop(deps.get_current_user, None)


async def test_alert_rule_crud_and_event_history(
    async_client,
    override_auth,
    test_session_factory,
):
    create_response = await async_client.post(
        "/v1/alerts/rules",
        json={
            "asset_symbol": "btc",
            "condition": "price_drop_pct",
            "threshold": 62000,
        },
    )

    assert create_response.status_code == 200
    rule_id = create_response.json()["id"]

    rules_response = await async_client.get("/v1/alerts/rules")

    assert rules_response.status_code == 200
    assert rules_response.json() == [
        {
            "id": rule_id,
            "asset_symbol": "BTC",
            "condition": "price_drop_pct",
            "threshold": 62000.0,
            "is_active": True,
            "created_at": rules_response.json()[0]["created_at"],
        }
    ]

    toggle_response = await async_client.patch(f"/v1/alerts/rules/{rule_id}/toggle")

    assert toggle_response.status_code == 200
    assert toggle_response.json() == {"is_active": False}

    async with test_session_factory() as session:
        session.add(
            AlertEvent(
                rule_id=rule_id,
                message="BTC dropped below threshold",
                telegram_delivered=True,
                delivered_at=datetime(2026, 4, 14, 7, 30, tzinfo=UTC),
                triggered_at=datetime(2026, 4, 14, 7, 30, tzinfo=UTC),
            )
        )
        await session.commit()

    events_response = await async_client.get("/v1/alerts/events")

    assert events_response.status_code == 200
    assert events_response.json() == [
        {
            "id": events_response.json()[0]["id"],
            "rule_id": rule_id,
            "message": "BTC dropped below threshold",
            "telegram_delivered": True,
            "triggered_at": "2026-04-14T07:30:00+00:00",
        }
    ]

    delete_response = await async_client.delete(f"/v1/alerts/rules/{rule_id}")

    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Deleted"}

    rules_after_delete = await async_client.get("/v1/alerts/rules")
    events_after_delete = await async_client.get("/v1/alerts/events")

    assert rules_after_delete.json() == []
    assert events_after_delete.json() == []


async def test_create_rule_rejects_invalid_condition(async_client, override_auth):
    response = await async_client.post(
        "/v1/alerts/rules",
        json={
            "asset_symbol": "ETH",
            "condition": "crosses_moon",
            "threshold": 1,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "condition must be price_drop_pct or price_rise_pct"
    }
