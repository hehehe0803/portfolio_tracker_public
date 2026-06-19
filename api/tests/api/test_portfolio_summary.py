from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from app.api import deps
from app.services.analytics import HoldingStats
from fastapi import FastAPI


@pytest_asyncio.fixture
async def summary_client(app: FastAPI) -> AsyncIterator[FastAPI]:
    async def _override_user():
        return SimpleNamespace(
            id=1,
            username="summary-tester",
            totp_enabled=False,
            telegram_chat_id=None,
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


async def test_portfolio_summary_includes_benchmarks_without_holding_proxies(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    holdings = [
        HoldingStats(
            symbol="AAPL",
            asset_type="equity",
            quantity=Decimal("2"),
            avg_buy_price_usd=Decimal("150"),
            total_cost_usd=Decimal("300"),
            institution="fidelity",
        ),
        HoldingStats(
            symbol="SGOV",
            asset_type="etf",
            quantity=Decimal("10"),
            avg_buy_price_usd=Decimal("100"),
            total_cost_usd=Decimal("1000"),
            institution="ibkr",
        ),
    ]

    prices = {
        "AAPL": 200.0,
        "SGOV": 100.03,
        "SPY": 500.0,
        "BTC": 65000.0,
        "XAU": 2500.0,
    }

    get_holdings_mock = AsyncMock(return_value=holdings)
    get_prices_mock = AsyncMock(return_value=prices)

    monkeypatch.setattr("app.services.analytics.get_holdings", get_holdings_mock)
    monkeypatch.setattr("app.services.pricing.get_prices_bulk", get_prices_mock)

    response = await async_client.get("/v1/portfolio/summary")

    assert response.status_code == 200
    payload = response.json()

    assert get_holdings_mock.await_count == 1
    assert get_prices_mock.await_count == 1
    assert set(get_prices_mock.await_args.args[0]) == {
        "AAPL",
        "SGOV",
        "SPY",
        "BTC",
        "XAU",
    }

    assert payload["total_value_usd"] == 1400.3
    assert payload["total_cost_usd"] == 1300.0
    assert payload["total_pnl_usd"] == 100.3
    assert payload["holding_count"] == 2
    assert payload["benchmarks"]["spx_in_btc"] == pytest.approx(500 / 65000, rel=1e-3)
    assert payload["benchmarks"]["spx_in_gold"] == pytest.approx(0.2, rel=1e-3)
    assert len(payload["holdings"]) == 2


async def test_portfolio_summary_prices_binance_long_tail_holdings_without_nulls(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    holdings = [
        HoldingStats(
            symbol="WBETH",
            asset_type="crypto",
            quantity=Decimal("0.95"),
            avg_buy_price_usd=Decimal("2100"),
            total_cost_usd=Decimal("1995"),
            institution="binance",
        ),
        HoldingStats(
            symbol="FET",
            asset_type="crypto",
            quantity=Decimal("100"),
            avg_buy_price_usd=Decimal("1.1"),
            total_cost_usd=Decimal("110"),
            institution="binance",
        ),
        HoldingStats(
            symbol="AAPL",
            asset_type="equity",
            quantity=Decimal("1"),
            avg_buy_price_usd=Decimal("150"),
            total_cost_usd=Decimal("150"),
            institution="fidelity",
        ),
    ]

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.setex = AsyncMock()
    mock_redis.aclose = AsyncMock()

    monkeypatch.setattr(
        "app.services.analytics.get_holdings", AsyncMock(return_value=holdings)
    )

    with (
        patch("app.services.pricing._redis_client", return_value=mock_redis),
        patch(
            "app.services.pricing.binance_price_client.get_prices_bulk",
            new_callable=AsyncMock,
            return_value={
                "WBETH": None,
                "BETH": 2145.5,
                "ETH": 2200.0,
                "FET": 1.25,
                "AAPL": None,
            },
        ),
        patch(
            "app.services.pricing._fetch_yahoo",
            new_callable=AsyncMock,
            side_effect=lambda symbol: {"AAPL": 185.0, "SPY": 500.0, "XAU": 2500.0}.get(
                symbol
            ),
        ),
    ):
        response = await async_client.get("/v1/portfolio/summary")

    assert response.status_code == 200
    payload = response.json()
    holdings_by_symbol = {holding["symbol"]: holding for holding in payload["holdings"]}

    assert holdings_by_symbol["WBETH"]["current_price_usd"] == pytest.approx(2145.5)
    assert holdings_by_symbol["FET"]["current_price_usd"] == pytest.approx(1.25)
    assert holdings_by_symbol["AAPL"]["current_price_usd"] == pytest.approx(185.0)
    assert payload["holding_count"] == 3


async def test_portfolio_summary_attaches_freshness_metadata_to_current_values(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    holdings = [
        HoldingStats(
            symbol="BTC",
            asset_type="crypto",
            quantity=Decimal("0.5"),
            avg_buy_price_usd=Decimal("50000"),
            total_cost_usd=Decimal("25000"),
            institution="binance",
            source_drilldown=[{"source": "spot_wallet", "value_usd": Decimal("35000")}],
        )
    ]
    monkeypatch.setattr(
        "app.services.analytics.get_holdings", AsyncMock(return_value=holdings)
    )
    monkeypatch.setattr(
        "app.services.pricing.get_prices_bulk",
        AsyncMock(return_value={"BTC": 70000.0, "SPY": 500.0, "XAU": 2500.0}),
    )

    response = await async_client.get("/v1/portfolio/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["freshness"]["current_snapshot"]["source"] == "live_price_provider"
    assert payload["freshness"]["current_snapshot"]["as_of"] is not None
    assert payload["freshness"]["current_snapshot"]["degraded"] is False
    assert payload["freshness"]["warnings"] == []

    holding = payload["holdings"][0]
    assert holding["current_value_usd"] == 35000.0
    assert holding["freshness"]["source"] == "live_price_provider"
    assert (
        holding["freshness"]["as_of"]
        == payload["freshness"]["current_snapshot"]["as_of"]
    )
    assert holding["freshness"]["stale"] is False
    assert holding["freshness"]["degraded"] is False
    assert holding["freshness"]["warnings"] == []


async def test_portfolio_summary_warns_when_value_has_no_price_metadata(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    holdings = [
        HoldingStats(
            symbol="MISSING",
            asset_type="equity",
            quantity=Decimal("3"),
            avg_buy_price_usd=Decimal("10"),
            total_cost_usd=Decimal("30"),
            institution="manual",
        )
    ]
    monkeypatch.setattr(
        "app.services.analytics.get_holdings", AsyncMock(return_value=holdings)
    )
    monkeypatch.setattr(
        "app.services.pricing.get_prices_bulk",
        AsyncMock(
            return_value={
                "MISSING": None,
                "SPY": 500.0,
                "BTC": 70000.0,
                "XAU": 2500.0,
            }
        ),
    )

    response = await async_client.get("/v1/portfolio/summary")

    assert response.status_code == 200
    payload = response.json()
    holding = payload["holdings"][0]
    assert holding["current_value_usd"] is None
    assert holding["freshness"]["source"] == "missing_price"
    assert holding["freshness"]["degraded"] is True
    assert "MISSING has no current price metadata" in holding["freshness"]["warnings"]
    assert payload["freshness"]["current_snapshot"]["degraded"] is True
    assert "MISSING has no current price metadata" in payload["freshness"]["warnings"]


async def test_portfolio_capital_truth_endpoint_returns_headline_metrics_and_audit_rows(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    transactions = [
        SimpleNamespace(institution="xtb", asset_symbol="USD", fee_currency="USD")
    ]
    capital_truth = {
        "money_in_usd": Decimal("39000"),
        "money_out_usd": Decimal("1000"),
        "net_capital_in_usd": Decimal("38000"),
        "current_value_usd": Decimal("32500"),
        "lifetime_pnl_usd": Decimal("-5500"),
        "lifetime_return_pct": Decimal("-14.47368421052631578947368421"),
        "current_value_source": "latest_position_snapshot",
        "excluded_row_count": 0,
        "unclassified_transfer_count": 0,
        "warnings": [],
        "capital_flow_audit": [
            {
                "institution": "xtb",
                "tx_type": "deposit",
                "asset_symbol": "USD",
                "economic_category": "external_capital_in",
                "amount_usd": Decimal("39000"),
                "included_in_capital_totals": True,
                "exclusion_reason": None,
            }
        ],
    }
    fetch_transactions_mock = AsyncMock(return_value=transactions)
    latest_snapshot_mock = AsyncMock(return_value=Decimal("32500"))
    calculate_capital_truth_mock = AsyncMock(return_value=capital_truth)

    monkeypatch.setattr(
        "app.services.analytics.fetch_transactions",
        fetch_transactions_mock,
    )
    monkeypatch.setattr(
        "app.api.v1.portfolio._latest_snapshot_current_value_usd",
        latest_snapshot_mock,
    )
    monkeypatch.setattr(
        "app.services.analytics.calculate_capital_truth_summary",
        calculate_capital_truth_mock,
    )

    response = await async_client.get("/v1/portfolio/capital-truth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["money_in_usd"] == 39000.0
    assert payload["money_out_usd"] == 1000.0
    assert payload["net_capital_in_usd"] == 38000.0
    assert payload["current_value_usd"] == 32500.0
    assert payload["lifetime_pnl_usd"] == -5500.0
    assert payload["lifetime_return_pct"] == pytest.approx(-14.4736842105)
    assert payload["current_value_source"] == "latest_position_snapshot"
    assert (
        payload["capital_flow_audit"][0]["economic_category"] == "external_capital_in"
    )
    fetch_transactions_mock.assert_awaited_once()
    latest_snapshot_mock.assert_awaited_once()
    calculate_capital_truth_mock.assert_awaited_once_with(
        transactions,
        current_value_usd=Decimal("32500"),
        current_value_source="latest_position_snapshot",
    )


async def test_portfolio_asset_contributions_endpoint_returns_sorted_winners_losers(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    transactions = [
        SimpleNamespace(institution="binance", asset_symbol="BTC", fee_currency="BNB"),
        SimpleNamespace(institution="xtb", asset_symbol="SPY", fee_currency="USD"),
    ]
    get_prices_bulk_mock = AsyncMock(
        return_value={"BTC": 70000.0, "SPY": 550.0, "BNB": 300.0, "USD": 1.0}
    )
    contribution = {
        "assets": [
            {
                "symbol": "BTC",
                "asset_type": "crypto",
                "institution": "binance",
                "institutions": ["binance"],
                "quantity": Decimal("0.01"),
                "total_cost_usd": Decimal("600"),
                "current_value_usd": Decimal("700"),
                "realized_pnl_usd": Decimal("0"),
                "unrealized_pnl_usd": Decimal("100"),
                "reward_income_usd": Decimal("0"),
                "fees_usd": Decimal("1"),
                "net_lifetime_pnl_usd": Decimal("100"),
            }
        ],
        "totals": {
            "current_value_usd": Decimal("700"),
            "realized_pnl_usd": Decimal("0"),
            "unrealized_pnl_usd": Decimal("100"),
            "reward_income_usd": Decimal("0"),
            "fees_usd": Decimal("1"),
            "net_lifetime_pnl_usd": Decimal("100"),
        },
        "sort": {"sort_by": "current_value_usd", "order": "asc"},
    }
    calculate_mock = AsyncMock(return_value=contribution)
    monkeypatch.setattr(
        "app.services.analytics.fetch_transactions",
        AsyncMock(return_value=transactions),
    )
    monkeypatch.setattr("app.services.pricing.get_prices_bulk", get_prices_bulk_mock)
    monkeypatch.setattr(
        "app.services.analytics.calculate_asset_contribution_summary",
        calculate_mock,
    )

    response = await async_client.get(
        "/v1/portfolio/asset-contributions?sort_by=current_value_usd&order=asc"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["assets"][0]["symbol"] == "BTC"
    assert payload["assets"][0]["net_lifetime_pnl_usd"] == 100.0
    assert payload["totals"]["current_value_usd"] == 700.0
    get_prices_bulk_mock.assert_awaited_once_with(["BNB", "BTC", "SPY", "USD"])
    calculate_mock.assert_awaited_once_with(
        transactions,
        {"BTC": 70000.0, "SPY": 550.0, "BNB": 300.0, "USD": 1.0},
        sort_by="current_value_usd",
        order="asc",
    )


async def test_portfolio_performance_summary_returns_institution_and_combined_metrics(
    async_client,
    summary_client,
    monkeypatch: pytest.MonkeyPatch,
):
    transactions = [
        SimpleNamespace(institution="binance", asset_symbol="BTC", fee_currency="BNB"),
        SimpleNamespace(institution="xtb", asset_symbol="SPY", fee_currency="USD"),
    ]
    prices = {"BTC": 70000.0, "SPY": 550.0, "BNB": 300.0, "USD": 1.0}
    get_prices_bulk_mock = AsyncMock(return_value=prices)
    performance = {
        "institutions": {
            "binance": {
                "gross_deposits_usd": Decimal("1000"),
                "gross_withdrawals_usd": Decimal("0"),
                "net_invested_capital_usd": Decimal("1000"),
                "bridge_transfer_out_usd": Decimal("250"),
                "bridge_transfer_in_usd": Decimal("250"),
                "unclassified_transfer_usd": Decimal("0"),
                "reward_income_usd": Decimal("0"),
                "fees_usd": Decimal("0"),
                "realized_pnl_usd": Decimal("52.27"),
                "total_cost_usd": Decimal("327.27"),
                "current_value_usd": Decimal("420"),
                "unrealized_pnl_usd": Decimal("92.73"),
                "total_pnl_usd": Decimal("145.0"),
                "xirr": Decimal("0.12"),
            }
        },
        "combined": {
            "gross_deposits_usd": Decimal("6000"),
            "gross_withdrawals_usd": Decimal("0"),
            "net_invested_capital_usd": Decimal("6000"),
            "bridge_transfer_out_usd": Decimal("250"),
            "bridge_transfer_in_usd": Decimal("250"),
            "unclassified_transfer_usd": Decimal("0"),
            "reward_income_usd": Decimal("0"),
            "fees_usd": Decimal("0"),
            "realized_pnl_usd": Decimal("52.27"),
            "total_cost_usd": Decimal("2827.27"),
            "current_value_usd": Decimal("3170"),
            "unrealized_pnl_usd": Decimal("342.73"),
            "total_pnl_usd": Decimal("395.0"),
            "xirr": Decimal("0.09"),
        },
        "comparisons": {
            "binance_vs_xtb": {
                "total_pnl_delta_usd": Decimal("-105"),
                "net_invested_delta_usd": Decimal("-4000"),
            }
        },
    }

    monkeypatch.setattr(
        "app.services.analytics.fetch_transactions",
        AsyncMock(return_value=transactions),
    )
    monkeypatch.setattr("app.services.pricing.get_prices_bulk", get_prices_bulk_mock)
    monkeypatch.setattr(
        "app.services.analytics.calculate_performance_summary",
        AsyncMock(return_value=performance),
    )

    response = await async_client.get("/v1/portfolio/performance-summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["combined"]["total_pnl_usd"] == 395.0
    assert payload["institutions"]["binance"]["current_value_usd"] == 420.0
    assert payload["comparisons"]["binance_vs_xtb"]["total_pnl_delta_usd"] == -105.0
    get_prices_bulk_mock.assert_awaited_once_with(["BNB", "BTC", "SPY", "USD"])
