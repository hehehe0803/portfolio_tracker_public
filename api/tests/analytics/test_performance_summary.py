from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.services.analytics import (
    calculate_asset_contribution_summary,
    calculate_capital_truth_summary,
    calculate_performance_summary,
)


class DummyTransaction:
    def __init__(
        self,
        *,
        institution: str,
        tx_type: str,
        asset_symbol: str,
        asset_type: str,
        quantity: str,
        timestamp: datetime,
        price_usd: str | None = None,
        total_usd: str | None = None,
        raw_data: dict | None = None,
        fee: str = "0",
        fee_currency: str = "USD",
    ) -> None:
        self.institution = institution
        self.tx_type = tx_type
        self.asset_symbol = asset_symbol
        self.asset_type = asset_type
        self.quantity = Decimal(quantity)
        self.timestamp = timestamp
        self.price_usd = Decimal(price_usd) if price_usd is not None else None
        self.total_usd = Decimal(total_usd) if total_usd is not None else None
        self.raw_data = raw_data or {}
        self.fee = Decimal(fee)
        self.fee_currency = fee_currency


@pytest.mark.asyncio
async def test_calculate_performance_summary_separates_capital_flows_income_and_bridge_transfers():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="external_deposit",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="1000",
            price_usd="1",
            total_usd="1000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.01",
            price_usd="60000",
            total_usd="600",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="earn_reward",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.001",
            timestamp=datetime(2026, 1, 3, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="bridge_transfer_out",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="250",
            price_usd="1",
            total_usd="250",
            timestamp=datetime(2026, 1, 4, tzinfo=UTC),
            raw_data={"bridge_group": "bridge-1"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="bridge_transfer_in",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="250",
            price_usd="1",
            total_usd="250",
            timestamp=datetime(2026, 1, 5, tzinfo=UTC),
            raw_data={"bridge_group": "bridge-1"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_sell",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.005",
            price_usd="65000",
            total_usd="325",
            timestamp=datetime(2026, 1, 6, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="xtb",
            tx_type="deposit",
            asset_symbol="USD",
            asset_type="fiat",
            quantity="5000",
            price_usd="1",
            total_usd="5000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="xtb",
            tx_type="buy",
            asset_symbol="SPY",
            asset_type="equity",
            quantity="5",
            price_usd="500",
            total_usd="2500",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    current_prices = {"BTC": Decimal("70000"), "SPY": Decimal("550")}

    summary = await calculate_performance_summary(transactions, current_prices)

    binance = summary["institutions"]["binance"]
    xtb = summary["institutions"]["xtb"]
    combined = summary["combined"]

    assert binance["gross_deposits_usd"] == Decimal("1000")
    assert binance["gross_withdrawals_usd"] == Decimal("0")
    assert binance["net_invested_capital_usd"] == Decimal("1000")
    assert binance["reward_income_usd"] == Decimal("70.000")
    assert binance["realized_pnl_usd"] == Decimal("20.4545454545454545454545454")
    assert binance["bridge_transfer_out_usd"] == Decimal("250")
    assert binance["bridge_transfer_in_usd"] == Decimal("250")
    assert binance["current_value_usd"] == Decimal("420")
    assert binance["total_cost_usd"] == Decimal("365.4545454545454545454545454")
    assert binance["unrealized_pnl_usd"] == Decimal("54.5454545454545454545454546")
    assert binance["total_pnl_usd"] == Decimal("145.0000000000000000000000000")

    assert xtb["gross_deposits_usd"] == Decimal("5000")
    assert xtb["current_value_usd"] == Decimal("2750")
    assert xtb["unrealized_pnl_usd"] == Decimal("250")

    assert combined["gross_deposits_usd"] == Decimal("6000")
    assert combined["total_pnl_usd"] == Decimal("395.0000000000000000000000004")
    assert summary["comparisons"]["binance_vs_xtb"]["total_pnl_delta_usd"] == Decimal(
        "-105"
    )


@pytest.mark.asyncio
async def test_calculate_performance_summary_accounts_for_trade_fees_and_reward_income_basis():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="external_deposit",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="1000",
            price_usd="1",
            total_usd="1000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.01",
            price_usd="60000",
            total_usd="600",
            fee="0.0001",
            fee_currency="BTC",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="earn_reward",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.001",
            timestamp=datetime(2026, 1, 3, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_sell",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.005",
            price_usd="65000",
            total_usd="325",
            fee="0.50",
            fee_currency="USDT",
            timestamp=datetime(2026, 1, 6, tzinfo=UTC),
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"BTC": Decimal("70000")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["reward_income_usd"] == Decimal("70.000")
    assert binance["fees_usd"] == Decimal("6.5000")
    assert binance["current_value_usd"] == Decimal("413.0000")
    assert binance["realized_pnl_usd"] == Decimal("14.4082568807339449541284404")


@pytest.mark.asyncio
async def test_calculate_performance_summary_values_third_asset_fees_from_market_prices():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.01",
            price_usd="60000",
            total_usd="600",
            fee="0.02",
            fee_currency="BNB",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"BTC": Decimal("70000"), "BNB": Decimal("300")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["fees_usd"] == Decimal("6.00")
    assert binance["total_cost_usd"] == Decimal("606")


@pytest.mark.asyncio
async def test_calculate_performance_summary_moves_cost_for_staking_wraps():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            price_usd="2000",
            total_usd="2000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="staking_subscribe",
            asset_symbol="WBETH",
            asset_type="crypto",
            quantity="0.95",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            raw_data={"stake_asset": "ETH", "stake_amount": "1.0"},
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"WBETH": Decimal("2200")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["current_value_usd"] == Decimal("2090.00")
    assert binance["total_cost_usd"] == Decimal("2000")
    assert binance["unrealized_pnl_usd"] == Decimal("90.00")


@pytest.mark.asyncio
async def test_external_withdrawal_fee_reduces_performance_metrics():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="external_deposit",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="1000",
            price_usd="1",
            total_usd="1000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="external_withdrawal",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="100",
            price_usd="1",
            total_usd="100",
            fee="1",
            fee_currency="USDT",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    summary = await calculate_performance_summary(transactions, {"USDT": Decimal("1")})

    binance = summary["institutions"]["binance"]
    assert binance["gross_withdrawals_usd"] == Decimal("100")
    assert binance["fees_usd"] == Decimal("1")
    assert binance["realized_pnl_usd"] == Decimal("-1")
    assert binance["total_pnl_usd"] == Decimal("-1")


@pytest.mark.asyncio
async def test_external_crypto_deposit_contributes_to_current_value_and_cost_basis():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="external_deposit",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.01",
            total_usd="600",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )
    ]

    summary = await calculate_performance_summary(
        transactions, {"BTC": Decimal("70000")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["gross_deposits_usd"] == Decimal("600")
    assert binance["current_value_usd"] == Decimal("700.00")
    assert binance["total_cost_usd"] == Decimal("600")
    assert binance["unrealized_pnl_usd"] == Decimal("100.00")


@pytest.mark.asyncio
async def test_external_crypto_withdrawal_reduces_current_value_and_cost_basis():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.01",
            price_usd="60000",
            total_usd="600",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="external_withdrawal",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.005",
            total_usd="350",
            fee="0.0001",
            fee_currency="BTC",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"BTC": Decimal("70000")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["current_value_usd"] == Decimal("343.0000")
    assert binance["total_cost_usd"] == Decimal("294")
    assert binance["fees_usd"] == Decimal("7.0000")


@pytest.mark.asyncio
async def test_calculate_performance_summary_accounts_for_non_stable_convert_basis_transfer():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="buy",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            price_usd="2000",
            total_usd="2000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="convert_sell",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            raw_data={"convert_to_asset": "BNB", "convert_to_quantity": "10.0"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="convert_buy",
            asset_symbol="BNB",
            asset_type="crypto",
            quantity="10.0",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            raw_data={"convert_from_asset": "ETH", "convert_from_quantity": "1.0"},
        ),
    ]

    summary = await calculate_performance_summary(transactions, {"BNB": Decimal("220")})

    binance = summary["institutions"]["binance"]
    assert binance["realized_pnl_usd"] == Decimal("0")
    assert binance["total_cost_usd"] == Decimal("2000")
    assert binance["current_value_usd"] == Decimal("2200.0")
    assert binance["unrealized_pnl_usd"] == Decimal("200.0")


@pytest.mark.asyncio
async def test_calculate_performance_summary_preserves_cost_basis_for_bridged_round_trip():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="buy",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            price_usd="2000",
            total_usd="2000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="bridge_transfer_out",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            total_usd="2198.9",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            raw_data={"bridge_group": "bridge-eth-roundtrip"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="bridge_transfer_in",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            total_usd="2198.9",
            timestamp=datetime(2026, 1, 3, tzinfo=UTC),
            raw_data={"bridge_group": "bridge-eth-roundtrip"},
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"ETH": Decimal("2198.9")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["bridge_transfer_out_usd"] == Decimal("2198.9")
    assert binance["bridge_transfer_in_usd"] == Decimal("2198.9")
    assert binance["total_cost_usd"] == Decimal("2000")
    assert binance["current_value_usd"] == Decimal("2198.90")
    assert binance["unrealized_pnl_usd"] == Decimal("198.90")


@pytest.mark.asyncio
async def test_calculate_performance_summary_preserves_cost_basis_across_institutions_for_bridge_transfer():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="buy",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            price_usd="2000",
            total_usd="2000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="bridge_transfer_out",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            total_usd="2198.9",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            raw_data={"bridge_group": "bridge-eth-cross-venue"},
        ),
        DummyTransaction(
            institution="hyperliquid",
            tx_type="bridge_transfer_in",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            total_usd="2198.9",
            timestamp=datetime(2026, 1, 3, tzinfo=UTC),
            raw_data={"bridge_group": "bridge-eth-cross-venue"},
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"ETH": Decimal("2198.9")}
    )

    binance = summary["institutions"]["binance"]
    hyperliquid = summary["institutions"]["hyperliquid"]
    combined = summary["combined"]

    assert binance["bridge_transfer_out_usd"] == Decimal("2198.9")
    assert binance["total_cost_usd"] == Decimal("0")
    assert binance["current_value_usd"] == Decimal("0")
    assert hyperliquid["bridge_transfer_in_usd"] == Decimal("2198.9")
    assert hyperliquid["total_cost_usd"] == Decimal("2000")
    assert hyperliquid["current_value_usd"] == Decimal("2198.90")
    assert hyperliquid["unrealized_pnl_usd"] == Decimal("198.90")
    assert combined["total_cost_usd"] == Decimal("2000")
    assert combined["current_value_usd"] == Decimal("2198.90")
    assert combined["unrealized_pnl_usd"] == Decimal("198.90")


@pytest.mark.asyncio
async def test_calculate_performance_summary_does_not_infer_bridge_without_known_venue_provenance():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="withdrawal",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            price_usd="2000",
            total_usd="2000",
            timestamp=datetime(2026, 2, 1, tzinfo=UTC),
            raw_data={"address": "0xexternalwallet"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="deposit",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="0.9995",
            price_usd="2000",
            total_usd="1999",
            timestamp=datetime(2026, 2, 3, tzinfo=UTC),
            raw_data={"address": "0xback"},
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"ETH": Decimal("2100")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["bridge_transfer_out_usd"] == Decimal("0")
    assert binance["bridge_transfer_in_usd"] == Decimal("0")
    assert binance["gross_deposits_usd"] == Decimal("1999")
    assert binance["gross_withdrawals_usd"] == Decimal("2000")


@pytest.mark.asyncio
async def test_calculate_performance_summary_matches_bridge_transfers_by_asset_amount_and_time_window():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="withdrawal",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1.0",
            price_usd="2000",
            total_usd="2000",
            timestamp=datetime(2026, 2, 1, tzinfo=UTC),
            raw_data={"address": "0xhyperliquid"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="deposit",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="0.9995",
            price_usd="2000",
            total_usd="1999",
            timestamp=datetime(2026, 2, 3, tzinfo=UTC),
            raw_data={"address": "0xback"},
        ),
    ]

    summary = await calculate_performance_summary(
        transactions, {"ETH": Decimal("2100")}
    )

    binance = summary["institutions"]["binance"]
    assert binance["bridge_transfer_out_usd"] == Decimal("2000")
    assert binance["bridge_transfer_in_usd"] == Decimal("1999")
    assert binance["gross_deposits_usd"] == Decimal("0")
    assert binance["gross_withdrawals_usd"] == Decimal("0")
    assert binance["unclassified_transfer_usd"] == Decimal("0")


@pytest.mark.asyncio
async def test_capital_truth_summary_uses_external_flows_and_snapshot_current_value():
    transactions = [
        DummyTransaction(
            institution="xtb",
            tx_type="deposit",
            asset_symbol="USD",
            asset_type="fiat",
            quantity="30000",
            total_usd="30000",
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="external_deposit",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="9000",
            total_usd="9000",
            timestamp=datetime(2025, 1, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="xtb",
            tx_type="withdrawal",
            asset_symbol="USD",
            asset_type="fiat",
            quantity="1000",
            total_usd="1000",
            timestamp=datetime(2025, 2, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="xtb",
            tx_type="buy",
            asset_symbol="CSPX.UK",
            asset_type="etf",
            quantity="20",
            price_usd="500",
            total_usd="10000",
            timestamp=datetime(2025, 3, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="earn_subscribe",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="1000",
            total_usd="1000",
            timestamp=datetime(2025, 4, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="convert_sell",
            asset_symbol="ETH",
            asset_type="crypto",
            quantity="1",
            timestamp=datetime(2025, 5, 1, tzinfo=UTC),
            raw_data={"convert_to_asset": "WBETH", "convert_to_quantity": "0.98"},
        ),
        DummyTransaction(
            institution="binance",
            tx_type="earn_reward",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="25",
            total_usd="25",
            timestamp=datetime(2025, 6, 1, tzinfo=UTC),
        ),
    ]

    summary = await calculate_capital_truth_summary(
        transactions,
        current_value_usd=Decimal("32500"),
    )

    assert summary["money_in_usd"] == Decimal("39000")
    assert summary["money_out_usd"] == Decimal("1000")
    assert summary["net_capital_in_usd"] == Decimal("38000")
    assert summary["current_value_usd"] == Decimal("32500")
    assert summary["lifetime_pnl_usd"] == Decimal("-5500")
    assert summary["lifetime_return_pct"] == Decimal("-14.47368421052631578947368421")

    audit_by_type = {row["tx_type"]: row for row in summary["capital_flow_audit"]}
    assert audit_by_type["deposit"]["economic_category"] == "external_capital_in"
    assert audit_by_type["withdrawal"]["economic_category"] == "external_capital_out"
    assert audit_by_type["buy"]["economic_category"] == "trade_buy"
    assert audit_by_type["earn_subscribe"]["economic_category"] == "internal_movement"
    assert audit_by_type["convert_sell"]["economic_category"] == "convert"
    assert audit_by_type["earn_reward"]["economic_category"] == "income_reward"
    assert audit_by_type["earn_subscribe"]["included_in_capital_totals"] is False
    assert audit_by_type["convert_sell"]["included_in_capital_totals"] is False


@pytest.mark.asyncio
async def test_capital_truth_summary_surfaces_missing_usd_and_unclassified_transfers():
    transactions = [
        DummyTransaction(
            institution="binance",
            tx_type="external_deposit",
            asset_symbol="SOL",
            asset_type="crypto",
            quantity="10",
            timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="transfer_out",
            asset_symbol="USDT",
            asset_type="stablecoin",
            quantity="1000",
            total_usd="1000",
            timestamp=datetime(2025, 1, 2, tzinfo=UTC),
        ),
    ]

    summary = await calculate_capital_truth_summary(
        transactions,
        current_value_usd=Decimal("0"),
    )

    assert summary["money_in_usd"] == Decimal("0")
    assert summary["excluded_row_count"] == 1
    assert summary["unclassified_transfer_count"] == 1
    assert summary["warnings"] == [
        "1 capital-flow row excluded because no reliable USD value was available",
        "1 transfer row requires manual classification before it can affect lifetime P/L",
    ]
    rows_by_type = {row["tx_type"]: row for row in summary["capital_flow_audit"]}
    assert (
        rows_by_type["external_deposit"]["economic_category"] == "data_quality_excluded"
    )
    assert (
        rows_by_type["external_deposit"]["exclusion_reason"]
        == "missing_reliable_usd_value"
    )
    assert rows_by_type["transfer_out"]["economic_category"] == "unclassified_transfer"


@pytest.mark.asyncio
async def test_asset_contribution_summary_ranks_closed_losers_remaining_winners_rewards_and_fees():
    transactions = [
        DummyTransaction(
            institution="xtb",
            tx_type="buy",
            asset_symbol="LOSS",
            asset_type="equity",
            quantity="10",
            price_usd="100",
            total_usd="1000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="xtb",
            tx_type="sell",
            asset_symbol="LOSS",
            asset_type="equity",
            quantity="10",
            price_usd="70",
            total_usd="700",
            fee="5",
            fee_currency="USD",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="WIN",
            asset_type="crypto",
            quantity="2",
            price_usd="100",
            total_usd="200",
            fee="0.10",
            fee_currency="USD",
            timestamp=datetime(2026, 1, 3, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="earn_reward",
            asset_symbol="WIN",
            asset_type="crypto",
            quantity="0.5",
            timestamp=datetime(2026, 1, 4, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="fee",
            asset_symbol="WIN",
            asset_type="crypto",
            quantity="1",
            price_usd="1",
            total_usd="1",
            timestamp=datetime(2026, 1, 5, tzinfo=UTC),
        ),
    ]

    summary = await calculate_asset_contribution_summary(
        transactions,
        {"WIN": Decimal("150"), "LOSS": Decimal("75")},
        sort_by="net_lifetime_pnl_usd",
        order="asc",
    )

    assert summary["sort"] == {"sort_by": "net_lifetime_pnl_usd", "order": "asc"}
    assert summary["assets"][0]["symbol"] == "LOSS"
    loss = summary["assets"][0]
    assert loss["institution"] == "xtb"
    assert loss["quantity"] == Decimal("0")
    assert loss["current_value_usd"] == Decimal("0")
    assert loss["realized_pnl_usd"] == Decimal("-305")
    assert loss["unrealized_pnl_usd"] == Decimal("0")
    assert loss["reward_income_usd"] == Decimal("0")
    assert loss["fees_usd"] == Decimal("5")
    assert loss["net_lifetime_pnl_usd"] == Decimal("-305")

    win = summary["assets"][1]
    assert win["symbol"] == "WIN"
    assert win["institution"] == "binance"
    assert win["quantity"] == Decimal("2.5")
    assert win["total_cost_usd"] == Decimal("275.10")
    assert win["current_value_usd"] == Decimal("375.0")
    assert win["unrealized_pnl_usd"] == Decimal("99.90")
    assert win["reward_income_usd"] == Decimal("75.0")
    assert win["fees_usd"] == Decimal("1.10")
    assert win["net_lifetime_pnl_usd"] == Decimal("173.90")
    assert summary["totals"]["net_lifetime_pnl_usd"] == Decimal("-131.10")


@pytest.mark.asyncio
async def test_asset_contribution_summary_merges_crypto_and_xtb_mixed_institutions():
    transactions = [
        DummyTransaction(
            institution="xtb",
            tx_type="buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.1",
            price_usd="50000",
            total_usd="5000",
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            institution="binance",
            tx_type="spot_trade_buy",
            asset_symbol="BTC",
            asset_type="crypto",
            quantity="0.1",
            price_usd="60000",
            total_usd="6000",
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]

    summary = await calculate_asset_contribution_summary(
        transactions,
        {"BTC": Decimal("70000")},
        sort_by="current_value_usd",
        order="desc",
    )

    btc = summary["assets"][0]
    assert btc["symbol"] == "BTC"
    assert btc["institution"] == "multiple"
    assert btc["institutions"] == ["binance", "xtb"]
    assert btc["quantity"] == Decimal("0.2")
    assert btc["current_value_usd"] == Decimal("14000.0")
    assert btc["unrealized_pnl_usd"] == Decimal("3000.0")
    assert btc["net_lifetime_pnl_usd"] == Decimal("3000.0")
