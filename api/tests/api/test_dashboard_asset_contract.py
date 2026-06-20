# ruff: noqa: S101

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from app.api import deps
from app.api.v1 import portfolio
from app.db.base import Base
from app.db.models import (
    AccountingExternalCashflowClassification,
    AccountingReconciliationTask,
    Asset,
    PositionSnapshot,
    Transaction,
    User,
)
from app.main import create_application
from app.services.accounting_holding_drivers import calculate_holding_drivers
from app.services.portfolio_state import EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api.tests.db.test_schema_alignment import temporary_database_url
from shared.python.contracts import (
    AccountingReviewTask,
    AssetCurrentPosition,
    AssetDetailContract,
    AssetDriverExplanation,
    AssetLifetimeContribution,
    AssetRecentMovement,
    CashReserveContract,
    DashboardContract,
    DashboardLifetimeSummary,
    DashboardRollingPeriod,
    DistributionBucketContract,
    HoldingDriverContract,
)

AS_OF = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
START_30D = AS_OF - timedelta(days=30)


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
                    username="dashboard-contract-tester",
                    password_hash="test",  # noqa: S106 - inert test fixture hash
                )
            )
            await session.commit()
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()


@pytest_asyncio.fixture
async def db_backed_app(session_factory) -> FastAPI:
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
            username="dashboard-contract-tester",
            telegram_chat_id=None,
            totp_enabled=False,
        )

    async def _override_db():
        async with session_factory() as session:
            yield session

    application.dependency_overrides[deps.get_current_user] = _override_user
    application.dependency_overrides[deps.get_db] = _override_db
    return application


@pytest_asyncio.fixture
async def db_backed_client(db_backed_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=db_backed_app)
    async with db_backed_app.router.lifespan_context(db_backed_app):
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client


@pytest_asyncio.fixture
async def portfolio_contract_client(app: FastAPI) -> AsyncIterator[FastAPI]:
    async def _override_user():
        return SimpleNamespace(
            id=1,
            username="dashboard-contract-tester",
            telegram_chat_id=None,
            totp_enabled=False,
        )

    async def _override_db():
        yield SimpleNamespace()

    app.dependency_overrides[deps.get_current_user] = _override_user
    app.dependency_overrides[deps.get_db] = _override_db
    try:
        yield app
    finally:
        app.dependency_overrides.pop(deps.get_current_user, None)
        app.dependency_overrides.pop(deps.get_db, None)


async def test_dashboard_contract_returns_trusted_wire_shape(
    async_client,
    portfolio_contract_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_dashboard = AsyncMock(return_value=_trusted_dashboard_contract())
    monkeypatch.setattr(
        "app.api.v1.portfolio._compose_dashboard_contract",
        compose_dashboard,
        raising=False,
    )

    response = await async_client.get("/v1/portfolio/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["current_total_value_usd"], str)
    assert Decimal(payload["current_total_value_usd"]) == Decimal("10000")
    assert payload["confidence_state"] == "trusted"
    assert payload["reason_codes"] == []
    assert payload["top_reconciliation_action"] is None

    rolling_30d = payload["rolling_30d"]
    assert rolling_30d["label"] == "30D"
    assert Decimal(rolling_30d["external_contributions_usd"]) == Decimal("1000")
    assert Decimal(rolling_30d["external_withdrawals_usd"]) == Decimal("500")
    assert Decimal(rolling_30d["investment_gain_usd"]) == Decimal("4000")

    lifetime = payload["lifetime"]
    assert Decimal(lifetime["gross_contributions_usd"]) == Decimal("8000")
    assert Decimal(lifetime["gross_withdrawals_usd"]) == Decimal("500")
    assert Decimal(lifetime["net_capital_at_work_usd"]) == Decimal("7500")
    assert Decimal(lifetime["lifetime_pnl_usd"]) == Decimal("2500")
    assert lifetime["visible"] is True

    distribution = {
        bucket["asset_type"]: bucket for bucket in payload["asset_type_distribution"]
    }
    assert Decimal(distribution["crypto"]["value_usd"]) == Decimal("7000")
    assert Decimal(distribution["cash"]["value_usd"]) == Decimal("1000")
    assert Decimal(distribution["stocks_etfs"]["value_usd"]) == Decimal("2000")
    assert Decimal(payload["cash_reserve"]["stablecoin_usd"]) == Decimal("1000")
    assert Decimal(payload["cash_reserve"]["total_usd"]) == Decimal("1000")

    assert payload["holding_drivers"][0]["symbol"] == "BTC"
    assert Decimal(payload["holding_drivers"][0]["movement_usd"]) == Decimal("3000")
    compose_dashboard.assert_awaited_once()


async def test_dashboard_contract_hides_sensitive_stats_when_blocked_issue_is_open(
    async_client,
    portfolio_contract_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_dashboard = AsyncMock(return_value=_blocked_dashboard_contract())
    monkeypatch.setattr(
        "app.api.v1.portfolio._compose_dashboard_contract",
        compose_dashboard,
        raising=False,
    )

    response = await async_client.get("/v1/portfolio/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert Decimal(payload["current_total_value_usd"]) == Decimal("10000")
    assert payload["confidence_state"] == "blocked"
    assert "missing_cost_basis" in payload["reason_codes"]
    assert payload["rolling_30d"]["investment_gain_usd"] is None
    assert payload["lifetime"]["lifetime_pnl_usd"] is None
    assert payload["lifetime"]["visible"] is False
    assert Decimal(payload["lifetime"]["gross_contributions_usd"]) == Decimal("8000")
    assert payload["top_reconciliation_action"]["task_id"] == "task_btc_cost_basis"
    compose_dashboard.assert_awaited_once()


async def test_asset_detail_contract_separates_current_position_and_lifetime_pnl(
    async_client,
    portfolio_contract_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_detail = AsyncMock(return_value=_trusted_asset_detail_contract())
    monkeypatch.setattr(
        "app.api.v1.portfolio._compose_asset_detail_contract",
        compose_detail,
        raising=False,
    )

    response = await async_client.get("/v1/portfolio/assets/BTC/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "BTC"
    assert Decimal(payload["current_position"]["quantity"]) == Decimal("0.1")
    assert Decimal(payload["current_position"]["current_position_pnl_usd"]) == Decimal(
        "2000"
    )
    assert Decimal(payload["capital_allocated_usd"]) == Decimal("5000")
    assert Decimal(payload["lifetime"]["contribution_pnl_usd"]) == Decimal("2800")
    assert payload["lifetime"]["visible"] is True
    assert (
        payload["lifetime"]["contribution_pnl_usd"]
        != payload["current_position"]["current_position_pnl_usd"]
    )
    assert "current_position_pnl_usd" not in payload["lifetime"]
    assert _json_key_absent(payload, "total_pnl_usd")
    assert Decimal(payload["recent_movement"]["movement_usd"]) == Decimal("3000")
    assert payload["driver_explanation"]["symbol"] == "BTC"
    assert payload["trust_blockers"] == []
    compose_detail.assert_awaited_once()


async def test_asset_detail_hides_lifetime_contribution_pnl_when_asset_is_blocked(
    async_client,
    portfolio_contract_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_detail = AsyncMock(return_value=_blocked_asset_detail_contract())
    monkeypatch.setattr(
        "app.api.v1.portfolio._compose_asset_detail_contract",
        compose_detail,
        raising=False,
    )

    response = await async_client.get("/v1/portfolio/assets/BTC/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_position"]["current_position_pnl_usd"] is None
    assert payload["current_position"]["current_position_pnl_pct"] is None
    assert payload["lifetime"]["contribution_pnl_usd"] is None
    assert payload["lifetime"]["visible"] is False
    assert payload["trust_blockers"][0]["task_id"] == "task_btc_cost_basis"
    compose_detail.assert_awaited_once()


async def test_db_backed_dashboard_contract_composes_trusted_accounting_state(
    db_backed_client,
    session_factory,
) -> None:
    await _seed_portfolio(session_factory)

    response = await db_backed_client.get("/v1/portfolio/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert Decimal(payload["current_total_value_usd"]) == Decimal("10000.000000")
    assert payload["confidence_state"] == "trusted"

    rolling_30d = payload["rolling_30d"]
    assert Decimal(rolling_30d["external_contributions_usd"]) == Decimal("1500")
    assert Decimal(rolling_30d["external_withdrawals_usd"]) == Decimal("500")
    assert Decimal(rolling_30d["investment_gain_usd"]) == Decimal("3500.000000")

    btc_driver = _driver_for(payload, "BTC")
    assert Decimal(btc_driver["movement_usd"]) == Decimal("2500.000000")
    assert btc_driver["value_state"] == "visible"
    assert Decimal(payload["cash_reserve"]["stablecoin_usd"]) == Decimal("1000.000000")


async def test_db_backed_real_cost_basis_scopes_hide_asset_sensitive_stats(
    db_backed_client,
    session_factory,
) -> None:
    await _seed_portfolio(session_factory)
    await _seed_real_cost_basis_blocker(session_factory)

    dashboard_response = await db_backed_client.get("/v1/portfolio/dashboard")
    detail_response = await db_backed_client.get("/v1/portfolio/assets/BTC/detail")

    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()
    btc_driver = _driver_for(dashboard_payload, "BTC")
    assert btc_driver["movement_usd"] is None
    assert btc_driver["value_state"] == "hidden"
    assert btc_driver["confidence_state"] == "blocked"

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["current_position"]["current_value_usd"] is not None
    assert detail_payload["current_position"]["current_position_pnl_usd"] is None
    assert detail_payload["current_position"]["current_position_pnl_pct"] is None
    assert detail_payload["current_position"]["confidence_state"] == "blocked"
    assert detail_payload["lifetime"]["contribution_pnl_usd"] is None
    assert detail_payload["lifetime"]["visible"] is False
    assert detail_payload["recent_movement"]["movement_usd"] is None
    assert detail_payload["recent_movement"]["value_state"] == "hidden"
    assert detail_payload["driver_explanation"]["movement_usd"] is None
    assert detail_payload["trust_blockers"][0]["task_id"] == "task_btc_cost_basis"


async def test_db_backed_dashboard_treats_sentinel_only_latest_snapshot_as_empty(
    db_backed_client,
    session_factory,
) -> None:
    await _seed_empty_portfolio_marker(session_factory)

    response = await db_backed_client.get("/v1/portfolio/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["as_of"].startswith("2026-06-19T12:00:00")
    assert Decimal(payload["current_total_value_usd"]) == Decimal("0")
    assert "missing_current_value" not in payload["reason_codes"]
    assert "current_value" not in payload["blocked_metric_scopes"]
    assert payload["asset_type_distribution"] == []
    assert Decimal(payload["cash_reserve"]["total_usd"]) == Decimal("0")


def test_adapter_real_cost_basis_scopes_hide_asset_sensitive_stats() -> None:
    asset = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
    snapshot = _snapshot(
        asset=asset,
        captured_at=AS_OF,
        quantity="0.1",
        total_cost_usd="5000",
        current_price_usd="70000",
        current_value_usd="7000",
        unrealized_pnl_usd="2000",
    )
    blocker = _real_cost_basis_review_task()

    current_position = portfolio._asset_current_position(
        snapshot,
        trust_blockers=[blocker],
    )

    assert current_position.current_value_usd == Decimal("7000")
    assert current_position.current_position_pnl_usd is None
    assert current_position.current_position_pnl_pct is None
    assert current_position.confidence_state == "blocked"
    assert current_position.reason_codes == ["missing_cost_basis"]
    assert portfolio._asset_lifetime_blocking_reasons([blocker]) == [
        "missing_cost_basis"
    ]


async def test_adapter_holding_driver_inputs_use_asset_issues_and_cashflows() -> None:
    btc = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
    starting_snapshot = _snapshot(
        asset=btc,
        captured_at=START_30D,
        quantity="0.1",
        total_cost_usd="4000",
        current_price_usd="40000",
        current_value_usd="4000",
        unrealized_pnl_usd="0",
    )
    latest_snapshot = _snapshot(
        asset=btc,
        captured_at=AS_OF,
        quantity="0.1",
        total_cost_usd="5000",
        current_price_usd="70000",
        current_value_usd="7000",
        unrealized_pnl_usd="2000",
    )
    inputs = await portfolio._holding_driver_inputs(
        _FakeSnapshotDb(rows=[(starting_snapshot, btc)]),
        [(latest_snapshot, btc)],
        as_of=AS_OF,
        cashflows=[
            _cashflow(
                key="btc-deposit",
                cashflow_type="external_deposit",
                asset_symbol="BTC",
                quantity="0.01",
                amount_usd="500",
                capital_effect_usd="500",
                occurred_at=START_30D + timedelta(days=15),
            ),
            _cashflow(
                key="usd-deposit",
                cashflow_type="external_deposit",
                asset_symbol="USD",
                quantity="1000",
                amount_usd="1000",
                capital_effect_usd="1000",
                occurred_at=START_30D + timedelta(days=15),
            ),
        ],
        open_tasks=[_real_cost_basis_model_task()],
    )

    assert len(inputs) == 1
    assert inputs[0].deposits_usd == Decimal("500")
    assert inputs[0].confidence_state == "blocked"
    assert inputs[0].reason_codes == ("missing_cost_basis",)

    driver_period = calculate_holding_drivers(
        as_of=AS_OF,
        holdings=inputs,
        periods_days=(30,),
        default_period_days=30,
    ).default_period
    assert driver_period is not None
    driver = driver_period.drivers[0]
    assert driver.movement_usd is None
    assert driver.value_state == "hidden"
    assert driver.reason_codes == ("missing_cost_basis",)


async def test_adapter_sentinel_only_anchor_maps_empty_current_value_to_zero() -> None:
    boundary = await portfolio._historical_boundary(
        _FakeSnapshotDb(captured_at=AS_OF, rows=[]),
        AS_OF,
    )

    assert portfolio._sum_current_value_usd(
        [], empty_value_when_captured=True
    ) == Decimal("0")
    assert portfolio._sum_current_value_usd([], empty_value_when_captured=False) is None
    assert boundary.value_usd == Decimal("0")
    assert boundary.confidence_state == "trusted"
    assert boundary.sensitive_metrics_visible is True


async def test_adapter_stale_historical_anchor_hides_period_sensitive_metrics() -> None:
    btc = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
    stale_at = START_30D - timedelta(days=20)
    stale_snapshot = _snapshot(
        asset=btc,
        captured_at=stale_at,
        quantity="0.1",
        total_cost_usd="4000",
        current_price_usd="40000",
        current_value_usd="4000",
        unrealized_pnl_usd="0",
    )
    boundary = await portfolio._historical_boundary(
        _FakeSnapshotDb(captured_at=stale_at, rows=[(stale_snapshot, btc)]),
        START_30D,
    )
    inputs = await portfolio._holding_driver_inputs(
        _FakeSnapshotDb(captured_at=stale_at, rows=[(stale_snapshot, btc)]),
        [
            (
                _snapshot(
                    asset=btc,
                    captured_at=AS_OF,
                    quantity="0.1",
                    total_cost_usd="5000",
                    current_price_usd="70000",
                    current_value_usd="7000",
                    unrealized_pnl_usd="2000",
                ),
                btc,
            )
        ],
        as_of=AS_OF,
        cashflows=[],
        open_tasks=[],
    )

    assert boundary.value_usd is None
    assert boundary.confidence_state == "provisional"
    assert boundary.reason_codes == ("stale_anchor",)
    assert boundary.sensitive_metrics_visible is False
    assert inputs[0].starting_value_usd is None


def test_adapter_cost_basis_fields_hide_under_real_cost_basis_blocker() -> None:
    asset = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
    snapshot = _snapshot(
        asset=asset,
        captured_at=AS_OF,
        quantity="0.1",
        total_cost_usd="5000",
        current_price_usd="70000",
        current_value_usd="7000",
        unrealized_pnl_usd="2000",
    )
    blocker = _real_cost_basis_review_task()

    current_position = portfolio._asset_current_position(
        snapshot,
        trust_blockers=[blocker],
    )

    assert current_position.average_cost_usd is None
    assert (
        portfolio._asset_capital_allocated_usd(
            snapshot,
            trust_blockers=[blocker],
        )
        is None
    )


async def test_adapter_missing_current_value_hides_asset_lifetime() -> None:
    asset = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
    snapshot = PositionSnapshot(
        asset=asset,
        captured_at=AS_OF,
        quantity=Decimal("0.1"),
        avg_buy_price_usd=Decimal("50000"),
        total_cost_usd=Decimal("5000"),
        current_price_usd=None,
        current_value_usd=None,
        unrealized_pnl_usd=None,
        unrealized_pnl_pct=None,
    )

    lifetime = await portfolio._asset_lifetime_contribution(
        _FakeSnapshotDb(rows=[(snapshot, asset)]),
        symbol="BTC",
        latest_rows=[(snapshot, asset)],
        trust_blockers=[],
    )

    assert lifetime.contribution_pnl_usd is None
    assert lifetime.confidence_state == "blocked"
    assert lifetime.reason_codes == ["missing_current_value"]
    assert lifetime.visible is False


async def test_adapter_missing_current_price_hides_asset_lifetime() -> None:
    asset = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
    snapshot = PositionSnapshot(
        asset=asset,
        captured_at=AS_OF,
        quantity=Decimal("0.1"),
        avg_buy_price_usd=Decimal("50000"),
        total_cost_usd=Decimal("5000"),
        current_price_usd=None,
        current_value_usd=Decimal("7000"),
        unrealized_pnl_usd=Decimal("2000"),
        unrealized_pnl_pct=Decimal("40"),
    )

    lifetime = await portfolio._asset_lifetime_contribution(
        _FakeSnapshotDb(rows=[(snapshot, asset)]),
        symbol="BTC",
        latest_rows=[(snapshot, asset)],
        trust_blockers=[],
    )

    assert lifetime.contribution_pnl_usd is None
    assert lifetime.confidence_state == "blocked"
    assert lifetime.reason_codes == ["missing_current_price"]
    assert lifetime.visible is False


def _trusted_dashboard_contract() -> DashboardContract:
    return DashboardContract(
        as_of=AS_OF,
        current_total_value_usd=Decimal("10000"),
        rolling_30d=DashboardRollingPeriod(
            label="30D",
            days=30,
            start_at=START_30D,
            end_at=AS_OF,
            starting_value_usd=Decimal("5500"),
            ending_value_usd=Decimal("10000"),
            external_contributions_usd=Decimal("1000"),
            external_withdrawals_usd=Decimal("500"),
            investment_gain_usd=Decimal("4000"),
            confidence_state="trusted",
            reason_codes=[],
            visible=True,
        ),
        lifetime=DashboardLifetimeSummary(
            gross_contributions_usd=Decimal("8000"),
            gross_withdrawals_usd=Decimal("500"),
            net_capital_at_work_usd=Decimal("7500"),
            lifetime_pnl_usd=Decimal("2500"),
            return_pct=Decimal("33.33333333333333333333333333"),
            confidence_state="trusted",
            reason_codes=[],
            visible=True,
        ),
        confidence_state="trusted",
        reason_codes=[],
        blocked_metric_scopes=[],
        asset_type_distribution=[
            DistributionBucketContract(
                asset_type="crypto",
                value_usd=Decimal("7000"),
                percentage=Decimal("70"),
                percentage_state="visible",
                confidence_state="trusted",
                reason_codes=[],
            ),
            DistributionBucketContract(
                asset_type="cash",
                value_usd=Decimal("1000"),
                percentage=Decimal("10"),
                percentage_state="visible",
                confidence_state="trusted",
                reason_codes=[],
            ),
            DistributionBucketContract(
                asset_type="stocks_etfs",
                value_usd=Decimal("2000"),
                percentage=Decimal("20"),
                percentage_state="visible",
                confidence_state="trusted",
                reason_codes=[],
            ),
        ],
        cash_reserve=CashReserveContract(
            stablecoin_usd=Decimal("1000"),
            broker_cash_usd=Decimal("0"),
            other_tracked_cash_usd=Decimal("0"),
            total_usd=Decimal("1000"),
            confidence_state="trusted",
            reason_codes=[],
        ),
        holding_drivers=[
            HoldingDriverContract(
                symbol="BTC",
                movement_usd=Decimal("3000"),
                share_of_known_movement_pct=Decimal("75"),
                direction="positive",
                confidence_state="trusted",
                reason_codes=[],
                value_state="visible",
            )
        ],
        top_reconciliation_action=None,
    )


def _blocked_dashboard_contract() -> DashboardContract:
    trusted = _trusted_dashboard_contract()
    return trusted.model_copy(
        update={
            "rolling_30d": trusted.rolling_30d.model_copy(
                update={
                    "investment_gain_usd": None,
                    "confidence_state": "blocked",
                    "reason_codes": ["missing_cost_basis"],
                    "visible": False,
                }
            ),
            "lifetime": trusted.lifetime.model_copy(
                update={
                    "lifetime_pnl_usd": None,
                    "return_pct": None,
                    "confidence_state": "blocked",
                    "reason_codes": ["missing_cost_basis"],
                    "visible": False,
                }
            ),
            "confidence_state": "blocked",
            "reason_codes": ["missing_cost_basis"],
            "blocked_metric_scopes": [
                "lifetime_pnl",
                "period_performance",
                "asset_level_lifetime_pnl",
            ],
            "top_reconciliation_action": _blocking_review_task(),
        }
    )


def _trusted_asset_detail_contract() -> AssetDetailContract:
    return AssetDetailContract(
        symbol="BTC",
        asset_type="crypto",
        as_of=AS_OF,
        current_position=AssetCurrentPosition(
            quantity=Decimal("0.1"),
            current_price_usd=Decimal("70000"),
            current_value_usd=Decimal("7000"),
            average_cost_usd=Decimal("50000"),
            current_position_pnl_usd=Decimal("2000"),
            current_position_pnl_pct=Decimal("40"),
            confidence_state="trusted",
            reason_codes=[],
        ),
        capital_allocated_usd=Decimal("5000"),
        lifetime=AssetLifetimeContribution(
            contribution_basis_usd=Decimal("3200"),
            contribution_pnl_usd=Decimal("2800"),
            confidence_state="trusted",
            reason_codes=[],
            visible=True,
        ),
        recent_movement=AssetRecentMovement(
            period_label="30D",
            movement_usd=Decimal("3000"),
            direction="positive",
            confidence_state="trusted",
            reason_codes=[],
            value_state="visible",
        ),
        driver_explanation=AssetDriverExplanation(
            symbol="BTC",
            period_label="30D",
            movement_usd=Decimal("3000"),
            share_of_known_movement_pct=Decimal("75"),
            direction="positive",
            explanation="BTC gained $3000 over 30D after external flows.",
            confidence_state="trusted",
            reason_codes=[],
        ),
        trust_blockers=[],
    )


def _blocked_asset_detail_contract() -> AssetDetailContract:
    trusted = _trusted_asset_detail_contract()
    return trusted.model_copy(
        update={
            "current_position": trusted.current_position.model_copy(
                update={
                    "current_position_pnl_usd": None,
                    "current_position_pnl_pct": None,
                    "confidence_state": "blocked",
                    "reason_codes": ["missing_cost_basis"],
                }
            ),
            "lifetime": trusted.lifetime.model_copy(
                update={
                    "contribution_pnl_usd": None,
                    "confidence_state": "blocked",
                    "reason_codes": ["missing_cost_basis"],
                    "visible": False,
                }
            ),
            "trust_blockers": [_blocking_review_task()],
        }
    )


def _blocking_review_task() -> AccountingReviewTask:
    return AccountingReviewTask(
        task_id="task_btc_cost_basis",
        task_type="missing_cost_basis",
        status="open",
        severity="blocked",
        source="binance",
        asset_symbol="BTC",
        quantity=Decimal("0.02"),
        amount_usd=Decimal("1200"),
        occurred_at=AS_OF - timedelta(days=5),
        evidence={
            "source_evidence_key": "btc-sell",
            "reasons": ["missing_cost_basis"],
        },
        candidate_actions=[
            {"action": "manual_cost_basis", "effect": "restore_asset_pnl"}
        ],
        affected_metric_scopes=[
            "lifetime_pnl",
            "period_performance",
            "asset_level_lifetime_contribution",
            "asset_level_lifetime_pnl",
        ],
        created_at=AS_OF - timedelta(days=5),
    )


def _real_cost_basis_review_task() -> AccountingReviewTask:
    task = _blocking_review_task()
    return task.model_copy(
        update={
            "affected_metric_scopes": [
                "cost_basis",
                "unrealized_pnl",
                "lifetime_pnl",
                "period_performance",
            ]
        }
    )


def _real_cost_basis_model_task() -> AccountingReconciliationTask:
    return AccountingReconciliationTask(
        task_id="task_btc_cost_basis",
        task_key="task:missing-cost-basis:btc",
        task_type="missing_cost_basis",
        status="open",
        severity="blocked",
        source="binance",
        asset_symbol="BTC",
        quantity=Decimal("0.02"),
        amount_usd=Decimal("1200"),
        occurred_at=AS_OF - timedelta(days=5),
        evidence={
            "source_evidence_key": "btc-sell",
            "reasons": ["missing_cost_basis"],
        },
        candidate_actions=[
            {"action": "manual_cost_basis", "effect": "restore_asset_pnl"}
        ],
        affected_metric_scopes=[
            "cost_basis",
            "unrealized_pnl",
            "lifetime_pnl",
            "period_performance",
        ],
        created_by="system",
    )


async def _seed_portfolio(session_factory) -> None:
    async with session_factory() as session:
        btc = Asset(symbol="BTC", asset_type="crypto", last_seen_at=AS_OF)
        usdt = Asset(symbol="USDT", asset_type="crypto", last_seen_at=AS_OF)
        aapl = Asset(symbol="AAPL", asset_type="equity", last_seen_at=AS_OF)
        session.add_all([btc, usdt, aapl])
        await session.flush()

        session.add_all(
            [
                _snapshot(
                    asset=btc,
                    captured_at=START_30D,
                    quantity="0.1",
                    total_cost_usd="4000",
                    current_price_usd="40000",
                    current_value_usd="4000",
                    unrealized_pnl_usd="0",
                ),
                _snapshot(
                    asset=usdt,
                    captured_at=START_30D,
                    quantity="500",
                    total_cost_usd="500",
                    current_price_usd="1",
                    current_value_usd="500",
                    unrealized_pnl_usd="0",
                ),
                _snapshot(
                    asset=aapl,
                    captured_at=START_30D,
                    quantity="5",
                    total_cost_usd="1000",
                    current_price_usd="200",
                    current_value_usd="1000",
                    unrealized_pnl_usd="0",
                ),
                _snapshot(
                    asset=btc,
                    captured_at=AS_OF,
                    quantity="0.1",
                    total_cost_usd="5000",
                    current_price_usd="70000",
                    current_value_usd="7000",
                    unrealized_pnl_usd="2000",
                ),
                _snapshot(
                    asset=usdt,
                    captured_at=AS_OF,
                    quantity="1000",
                    total_cost_usd="1000",
                    current_price_usd="1",
                    current_value_usd="1000",
                    unrealized_pnl_usd="0",
                ),
                _snapshot(
                    asset=aapl,
                    captured_at=AS_OF,
                    quantity="5",
                    total_cost_usd="1800",
                    current_price_usd="400",
                    current_value_usd="2000",
                    unrealized_pnl_usd="200",
                ),
            ]
        )
        session.add_all(
            [
                _cashflow(
                    key="deposit-before-period",
                    cashflow_type="external_deposit",
                    asset_symbol="USD",
                    quantity="7000",
                    amount_usd="7000",
                    capital_effect_usd="7000",
                    occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                _cashflow(
                    key="deposit-inside-period",
                    cashflow_type="external_deposit",
                    asset_symbol="USD",
                    quantity="1000",
                    amount_usd="1000",
                    capital_effect_usd="1000",
                    occurred_at=START_30D + timedelta(days=10),
                ),
                _cashflow(
                    key="btc-deposit-inside-period",
                    cashflow_type="external_deposit",
                    asset_symbol="BTC",
                    quantity="0.01",
                    amount_usd="500",
                    capital_effect_usd="500",
                    occurred_at=START_30D + timedelta(days=15),
                ),
                _cashflow(
                    key="withdrawal-inside-period",
                    cashflow_type="external_withdrawal",
                    asset_symbol="USD",
                    quantity="500",
                    amount_usd="500",
                    capital_effect_usd="-500",
                    occurred_at=START_30D + timedelta(days=20),
                ),
                _transaction(
                    fingerprint="btc-buy",
                    tx_type="buy",
                    asset_symbol="BTC",
                    quantity="0.1",
                    price_usd="40000",
                    total_usd="4000",
                    timestamp=datetime(2026, 1, 10, tzinfo=UTC),
                ),
                _transaction(
                    fingerprint="btc-sell",
                    tx_type="sell",
                    asset_symbol="BTC",
                    quantity="0.02",
                    price_usd="60000",
                    total_usd="1200",
                    timestamp=datetime(2026, 2, 10, tzinfo=UTC),
                ),
            ]
        )
        await session.commit()


async def _seed_real_cost_basis_blocker(session_factory) -> None:
    async with session_factory() as session:
        session.add(
            AccountingReconciliationTask(
                task_id="task_btc_cost_basis",
                task_key="task:missing-cost-basis:btc",
                task_type="missing_cost_basis",
                status="open",
                severity="blocked",
                source="binance",
                asset_symbol="BTC",
                quantity=Decimal("0.02"),
                amount_usd=Decimal("1200"),
                occurred_at=AS_OF - timedelta(days=5),
                evidence={
                    "source_evidence_key": "btc-sell",
                    "reasons": ["missing_cost_basis"],
                },
                candidate_actions=[
                    {"action": "manual_cost_basis", "effect": "restore_asset_pnl"}
                ],
                affected_metric_scopes=[
                    "cost_basis",
                    "unrealized_pnl",
                    "lifetime_pnl",
                    "period_performance",
                ],
                created_by="system",
            )
        )
        await session.commit()


async def _seed_empty_portfolio_marker(session_factory) -> None:
    async with session_factory() as session:
        marker = Asset(
            symbol=EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
            asset_type="system",
            last_seen_at=None,
        )
        session.add(marker)
        await session.flush()
        session.add(
            PositionSnapshot(
                asset=marker,
                captured_at=AS_OF,
                quantity=Decimal("0"),
                avg_buy_price_usd=None,
                total_cost_usd=Decimal("0"),
                current_price_usd=None,
                current_value_usd=None,
                unrealized_pnl_usd=None,
                unrealized_pnl_pct=None,
            )
        )
        await session.commit()


def _snapshot(
    *,
    asset: Asset,
    captured_at: datetime,
    quantity: str,
    total_cost_usd: str,
    current_price_usd: str,
    current_value_usd: str,
    unrealized_pnl_usd: str,
) -> PositionSnapshot:
    return PositionSnapshot(
        asset=asset,
        captured_at=captured_at,
        quantity=Decimal(quantity),
        avg_buy_price_usd=Decimal(total_cost_usd) / Decimal(quantity),
        total_cost_usd=Decimal(total_cost_usd),
        current_price_usd=Decimal(current_price_usd),
        current_value_usd=Decimal(current_value_usd),
        unrealized_pnl_usd=Decimal(unrealized_pnl_usd),
        unrealized_pnl_pct=(
            Decimal(unrealized_pnl_usd) / Decimal(total_cost_usd) * Decimal("100")
            if Decimal(total_cost_usd) != Decimal("0")
            else None
        ),
    )


def _cashflow(
    *,
    key: str,
    cashflow_type: str,
    asset_symbol: str,
    quantity: str,
    amount_usd: str,
    capital_effect_usd: str,
    occurred_at: datetime,
) -> AccountingExternalCashflowClassification:
    return AccountingExternalCashflowClassification(
        classification_key=key,
        evidence={"source_evidence_key": key},
        evidence_key=key,
        cashflow_type=cashflow_type,
        movement_type="external_cashflow",
        source="manual",
        asset_symbol=asset_symbol,
        quantity=Decimal(quantity),
        amount_usd=Decimal(amount_usd),
        occurred_at=occurred_at,
        capital_effect_usd=Decimal(capital_effect_usd),
        confidence_state="trusted",
        materiality_usd=Decimal(amount_usd),
        review_task_id=None,
        created_by="system",
        decision_source="manual",
        status="active",
        decision_reason="test_fixture",
    )


def _transaction(
    *,
    fingerprint: str,
    tx_type: str,
    asset_symbol: str,
    quantity: str,
    price_usd: str,
    total_usd: str,
    timestamp: datetime,
) -> Transaction:
    return Transaction(
        institution="binance",
        tx_type=tx_type,
        asset_symbol=asset_symbol,
        asset_type="crypto",
        quantity=Decimal(quantity),
        price_usd=Decimal(price_usd),
        total_usd=Decimal(total_usd),
        fee=Decimal("0"),
        fee_currency="USD",
        timestamp=timestamp,
        fingerprint=fingerprint,
        raw_data={},
    )


def _driver_for(payload: dict[str, Any], symbol: str) -> dict[str, Any]:
    return next(
        driver for driver in payload["holding_drivers"] if driver["symbol"] == symbol
    )


class _FakeSnapshotDb:
    def __init__(
        self,
        *,
        captured_at: datetime = START_30D,
        rows: list[tuple[PositionSnapshot, Asset]],
    ) -> None:
        self.captured_at = captured_at
        self.rows = rows

    async def scalar(self, _query: Any) -> datetime:
        return self.captured_at

    async def execute(self, _query: Any) -> _FakeSnapshotResult:
        return _FakeSnapshotResult(self.rows)


class _FakeSnapshotResult:
    def __init__(self, rows: list[tuple[PositionSnapshot, Asset]]) -> None:
        self.rows = rows

    def all(self) -> list[tuple[PositionSnapshot, Asset]]:
        return self.rows


def _json_key_absent(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key not in value and all(
            _json_key_absent(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return all(_json_key_absent(item, key) for item in value)
    return True
