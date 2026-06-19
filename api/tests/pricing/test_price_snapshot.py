from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.services.analytics import (
    calculate_benchmark_ratios,
    calculate_holdings,
    enrich_with_prices,
)


class DummyTransaction:
    def __init__(
        self,
        institution: str,
        tx_type: str,
        asset_symbol: str,
        asset_type: str,
        quantity: str,
        price_usd: str | None,
        timestamp: datetime,
    ) -> None:
        self.institution = institution
        self.tx_type = tx_type
        self.asset_symbol = asset_symbol
        self.asset_type = asset_type
        self.quantity = Decimal(quantity)
        self.price_usd = Decimal(price_usd) if price_usd is not None else None
        self.timestamp = timestamp


def test_portfolio_valuation_matches_expected():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "BTC",
            "crypto",
            "1.0",
            "50000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "buy",
            "BTC",
            "crypto",
            "1.0",
            "70000",
            datetime(2026, 2, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "xtb",
            "buy",
            "SPY",
            "equity",
            "2",
            "500",
            datetime(2026, 1, 15, tzinfo=UTC),
        ),
    ]

    holdings = calculate_holdings(transactions)

    btc = next(holding for holding in holdings if holding.symbol == "BTC")
    spy = next(holding for holding in holdings if holding.symbol == "SPY")

    assert btc.quantity == Decimal("2.0")
    assert btc.total_cost_usd == Decimal("120000")
    assert btc.avg_buy_price_usd == Decimal("60000")
    assert spy.quantity == Decimal("2")
    assert spy.total_cost_usd == Decimal("1000")


def test_xtb_split_transactions_adjust_quantity_without_changing_total_cost():
    transactions = [
        DummyTransaction(
            "xtb",
            "buy",
            "XLU.US",
            "equity",
            "6",
            "86.17",
            datetime(2025, 9, 25, tzinfo=UTC),
        ),
        DummyTransaction(
            "xtb",
            "split",
            "XLU.US",
            "equity",
            "2",
            None,
            datetime(2025, 9, 25, 1, tzinfo=UTC),
        ),
    ]

    holdings = calculate_holdings(transactions)
    xlu = next(holding for holding in holdings if holding.symbol == "XLU.US")

    assert xlu.quantity == Decimal("12")
    assert xlu.total_cost_usd == Decimal("517.02")
    assert xlu.avg_buy_price_usd == Decimal("43.085")


def test_xtb_split_transactions_use_id_tiebreaker_for_same_timestamp_rows():
    buy = DummyTransaction(
        "xtb",
        "buy",
        "XLU.US",
        "equity",
        "6",
        "86.17",
        datetime(2025, 9, 25, tzinfo=UTC),
    )
    split = DummyTransaction(
        "xtb",
        "split",
        "XLU.US",
        "equity",
        "2",
        None,
        datetime(2025, 9, 25, tzinfo=UTC),
    )
    buy.id = 1
    split.id = 2

    holdings = calculate_holdings([split, buy])
    xlu = next(holding for holding in holdings if holding.symbol == "XLU.US")

    assert xlu.quantity == Decimal("12")
    assert xlu.total_cost_usd == Decimal("517.02")


@pytest.mark.asyncio
async def test_deterministic_price_enrichment_computes_valuation_fields():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "BTC",
            "crypto",
            "1.0",
            "50000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "buy",
            "BTC",
            "crypto",
            "1.0",
            "70000",
            datetime(2026, 2, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "xtb",
            "buy",
            "SPY",
            "equity",
            "2",
            "500",
            datetime(2026, 1, 15, tzinfo=UTC),
        ),
    ]

    holdings = calculate_holdings(transactions)
    priced_holdings = await enrich_with_prices(
        holdings,
        {"BTC": 65000.0, "SPY": 550.0},
    )

    btc = next(holding for holding in priced_holdings if holding.symbol == "BTC")
    spy = next(holding for holding in priced_holdings if holding.symbol == "SPY")

    assert btc.current_price_usd == Decimal("65000.0")
    assert btc.current_value_usd == Decimal("130000.00")
    assert btc.unrealized_pnl_usd == Decimal("10000.00")
    assert btc.unrealized_pnl_pct == Decimal("8.333333333333333333333333333")

    assert spy.current_price_usd == Decimal("550.0")
    assert spy.current_value_usd == Decimal("1100.0")
    assert spy.unrealized_pnl_usd == Decimal("100.0")
    assert spy.unrealized_pnl_pct == Decimal("10.0")


def test_benchmark_ratios_use_spy_btc_and_xau_proxies():
    ratios = calculate_benchmark_ratios({"SPY": 500.0, "BTC": 62500.0, "XAU": 2500.0})

    assert ratios["spx_in_btc"] == Decimal("0.008")
    assert ratios["spx_in_gold"] == Decimal("0.2")


def test_binance_latest_snapshot_is_definitive_and_ld_assets_merge():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "BTC",
            "crypto",
            "0.5",
            "40000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "xtb",
            "buy",
            "BTC",
            "crypto",
            "0.1",
            "60000",
            datetime(2026, 1, 15, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "balance_snapshot_spot",
            "BTC",
            "crypto",
            "1.0",
            None,
            datetime(2026, 2, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "balance_snapshot_earn",
            "LDBTC",
            "crypto",
            "0.25",
            None,
            datetime(2026, 2, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "balance_snapshot_spot",
            "BTC",
            "crypto",
            "2.0",
            None,
            datetime(2026, 3, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "balance_snapshot_earn",
            "LDBTC",
            "crypto",
            "0.5",
            None,
            datetime(2026, 3, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "staking_position",
            "ETH",
            "crypto",
            "1.25",
            None,
            datetime(2026, 3, 1, tzinfo=UTC),
        ),
    ]

    holdings = calculate_holdings(transactions)

    btc = next(holding for holding in holdings if holding.symbol == "BTC")
    eth = next(holding for holding in holdings if holding.symbol == "ETH")

    assert btc.quantity == Decimal("2.6")
    assert btc.total_cost_usd == Decimal("6000")
    assert eth.quantity == Decimal("1.25")


def test_binance_staking_subscribe_moves_cost_basis_without_double_counting_holdings():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "ETH",
            "crypto",
            "1.0",
            "2000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "staking_subscribe",
            "WBETH",
            "crypto",
            "0.95",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]
    transactions[1].raw_data = {"stake_asset": "ETH", "stake_amount": "1.0"}

    holdings = calculate_holdings(transactions)

    assert {holding.symbol for holding in holdings} == {"WBETH"}
    wbeth = holdings[0]
    assert wbeth.quantity == Decimal("0.95")
    assert wbeth.total_cost_usd == Decimal("2000")


def test_binance_staking_subscribe_accepts_export_amounts_with_thousands_separators():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "FET",
            "crypto",
            "3024.12030413",
            "0.50",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "earn_subscribe",
            "FET",
            "crypto",
            "3024.12030413",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]
    transactions[1].raw_data = {
        "stake_asset": "FET",
        "stake_amount": "3,024.12030413",
    }

    holdings = calculate_holdings(transactions)

    assert len(holdings) == 1
    assert holdings[0].symbol == "FET"
    assert holdings[0].total_cost_usd == Decimal("1512.0601520650")


def test_binance_staking_redeem_moves_cost_basis_back_to_redeemed_asset():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "ETH",
            "crypto",
            "1.0",
            "2000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "staking_subscribe",
            "WBETH",
            "crypto",
            "0.95",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "staking_redeem",
            "ETH",
            "crypto",
            "1.0",
            None,
            datetime(2026, 1, 3, tzinfo=UTC),
        ),
    ]
    transactions[1].raw_data = {"stake_asset": "ETH", "stake_amount": "1.0"}
    transactions[2].raw_data = {"redeem_asset": "WBETH", "redeem_amount": "0.95"}

    holdings = calculate_holdings(transactions)

    assert {holding.symbol for holding in holdings} == {"ETH"}
    eth = holdings[0]
    assert eth.quantity == Decimal("1.0")
    assert eth.total_cost_usd == Decimal("2000")


def test_binance_eth_staking_wrap_parser_metadata_supports_basis_transfer_from_beth():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "BETH",
            "crypto",
            "1.0",
            "2000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "staking_subscribe",
            "WBETH",
            "crypto",
            "0.95",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]
    transactions[1].raw_data = {
        "source_type": "eth_staking_wrap",
        "stake_asset": "BETH",
        "stake_amount": "1.0",
        "wrapped_beth_amount": "1.0",
        "ratio": "1:0.95",
    }

    holdings = calculate_holdings(transactions)

    assert {holding.symbol for holding in holdings} == {"WBETH"}
    wbeth = holdings[0]
    assert wbeth.quantity == Decimal("0.95")
    assert wbeth.total_cost_usd == Decimal("2000")


def test_binance_non_stable_convert_moves_cost_basis_between_assets():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "ETH",
            "crypto",
            "1.0",
            "2000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "convert_sell",
            "ETH",
            "crypto",
            "1.0",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "convert_buy",
            "BNB",
            "crypto",
            "10.0",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]
    transactions[1].raw_data = {
        "convert_to_asset": "BNB",
        "convert_to_quantity": "10.0",
    }
    transactions[2].raw_data = {
        "convert_from_asset": "ETH",
        "convert_from_quantity": "1.0",
    }

    holdings = calculate_holdings(transactions)

    assert {holding.symbol for holding in holdings} == {"BNB"}
    bnb = holdings[0]
    assert bnb.quantity == Decimal("10.0")
    assert bnb.total_cost_usd == Decimal("2000")


def test_external_crypto_withdrawal_reduces_holdings_by_principal_and_same_asset_fee():
    transactions = [
        DummyTransaction(
            "binance",
            "buy",
            "BTC",
            "crypto",
            "0.01",
            "60000",
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "binance",
            "external_withdrawal",
            "BTC",
            "crypto",
            "0.005",
            None,
            datetime(2026, 1, 2, tzinfo=UTC),
        ),
    ]
    transactions[1].fee = Decimal("0.0001")
    transactions[1].fee_currency = "BTC"

    holdings = calculate_holdings(transactions)

    btc = next(holding for holding in holdings if holding.symbol == "BTC")
    assert btc.quantity == Decimal("0.0049")
    assert btc.total_cost_usd == Decimal("294")


def test_calculate_holdings_excludes_cash_like_assets():
    transactions = [
        DummyTransaction(
            "binance",
            "balance_snapshot_spot",
            "USDT",
            "stablecoin",
            "1200",
            None,
            datetime(2026, 3, 1, tzinfo=UTC),
        ),
        DummyTransaction(
            "xtb",
            "deposit",
            "USD",
            "fiat",
            "500",
            None,
            datetime(2026, 3, 2, tzinfo=UTC),
        ),
        DummyTransaction(
            "xtb",
            "buy",
            "AAPL",
            "equity",
            "2",
            "180",
            datetime(2026, 3, 3, tzinfo=UTC),
        ),
    ]

    holdings = calculate_holdings(transactions)

    assert [holding.symbol for holding in holdings] == ["AAPL"]
