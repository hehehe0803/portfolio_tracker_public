# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest_asyncio
from app.api import deps
from app.db.base import Base
from app.db.models import (
    AccountingExternalCashflowClassification,
    AccountingReconciliationTask,
    User,
)
from app.main import create_application
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.tests.db.test_schema_alignment import temporary_database_url

NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture()
async def session_factory():
    with temporary_database_url() as database_url:
        engine = create_async_engine(database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                User(
                    id=1,
                    username="api-accounting-tester",
                    password_hash="test",  # noqa: S106 - inert test fixture hash
                )
            )
            await session.commit()
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()


@pytest_asyncio.fixture
async def app(session_factory) -> FastAPI:
    async def readiness_probe() -> None:
        return None

    application = create_application(
        run_startup_db_init=False,
        run_startup_repairs=False,
        run_scheduler=False,
        readiness_check=readiness_probe,
    )

    async def _override_user():
        return SimpleNamespace(
            id=1,
            username="api-accounting-tester",
            telegram_chat_id=None,
            totp_enabled=False,
        )

    async def _override_db():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[deps.get_current_user] = _override_user
    application.dependency_overrides[deps.get_db] = _override_db
    return application


def _task() -> AccountingReconciliationTask:
    return AccountingReconciliationTask(
        task_id="task_unknown_outgoing_transfer_api",
        task_key="task:unknown_outgoing_transfer:api-usdt-withdrawal",
        task_type="unknown_outgoing_transfer",
        status="open",
        severity="review_required",
        source="binance",
        asset_symbol="USDT",
        quantity=Decimal("42"),
        amount_usd=Decimal("42"),
        occurred_at=NOW,
        evidence={
            "source_evidence_key": "api-usdt-withdrawal",
            "reasons": ["unknown_outgoing_crypto"],
        },
        candidate_actions=[
            {"action": "personal_withdrawal", "effect": "capital_effect_usd<0"}
        ],
        affected_metric_scopes=["net_capital", "lifetime_pnl"],
        created_by="system",
    )


async def test_accounting_review_queue_is_separate_from_investment_review(
    async_client,
    session_factory,
) -> None:
    async with session_factory() as session:
        session.add(_task())
        await session.commit()

    response = await async_client.get("/v1/review/accounting/tasks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_type"] == "accounting"
    assert "hold" not in payload["allowed_actions"]
    assert payload["allowed_actions"] == [
        "internal_transfer",
        "personal_withdrawal",
        "import_approval",
        "manual_cost_basis",
        "unknown_cost_basis",
        "unknown",
    ]
    assert payload["tasks"][0]["task_id"] == "task_unknown_outgoing_transfer_api"
    assert payload["tasks"][0]["task_type"] == "unknown_outgoing_transfer"


async def test_accounting_review_decision_endpoint_resolves_task_durably(
    async_client,
    session_factory,
) -> None:
    async with session_factory() as session:
        session.add(_task())
        await session.commit()

    response = await async_client.post(
        "/v1/review/accounting/decisions",
        json={
            "task_id": "task_unknown_outgoing_transfer_api",
            "action": "personal_withdrawal",
            "idempotency_key": "api-personal-withdrawal",
            "rationale": "Confirmed outside tracked portfolio.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision_type"] == "accounting_external_cashflow_classification"
    assert payload["task_status"] == "resolved"
    assert payload["replayed"] is False

    replay = await async_client.post(
        "/v1/review/accounting/decisions",
        json={
            "task_id": "task_unknown_outgoing_transfer_api",
            "action": "personal_withdrawal",
            "idempotency_key": "api-personal-withdrawal",
            "rationale": "Confirmed outside tracked portfolio.",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["decision_id"] == payload["decision_id"]
    assert replay.json()["replayed"] is True

    async with session_factory() as session:
        task = await session.scalar(
            select(AccountingReconciliationTask).where(
                AccountingReconciliationTask.task_id
                == "task_unknown_outgoing_transfer_api"
            )
        )
        cashflows = (
            (await session.execute(select(AccountingExternalCashflowClassification)))
            .scalars()
            .all()
        )

    assert task is not None
    assert task.status == "resolved"
    assert len(cashflows) == 1
    assert cashflows[0].review_task_id == "task_unknown_outgoing_transfer_api"


async def test_accounting_review_rejects_investment_review_actions(
    async_client,
) -> None:
    response = await async_client.post(
        "/v1/review/accounting/decisions",
        json={
            "task_id": "task_unknown_outgoing_transfer_api",
            "action": "hold",
            "idempotency_key": "not-accounting",
        },
    )

    assert response.status_code == 422
