from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.services.analytics import (
    calculate_holdings,
    latest_binance_snapshot_aggregation,
)


class DummyTransaction:
    def __init__(
        self,
        *,
        institution: str = "binance",
        tx_type: str,
        asset_symbol: str,
        quantity: str,
        timestamp: datetime,
        asset_type: str = "crypto",
        raw_data: dict | None = None,
        price_usd: str | None = None,
        total_usd: str | None = None,
    ) -> None:
        self.institution = institution
        self.tx_type = tx_type
        self.asset_symbol = asset_symbol
        self.asset_type = asset_type
        self.quantity = Decimal(quantity)
        self.timestamp = timestamp
        self.raw_data = raw_data or {}
        self.price_usd = Decimal(price_usd) if price_usd is not None else None
        self.total_usd = Decimal(total_usd) if total_usd is not None else None
        self.fee = Decimal("0")
        self.fee_currency = "USD"


def test_latest_binance_snapshot_excludes_ld_receipts_when_earn_position_exists():
    captured_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    rows = [
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="ASTER",
            quantity="4699.13892928",
            timestamp=captured_at,
            raw_data={"account_type": "earn"},
        ),
        DummyTransaction(
            tx_type="balance_snapshot_spot",
            asset_symbol="LDASTER",
            quantity="4694.11319142",
            timestamp=captured_at,
            raw_data={"account_type": "spot"},
        ),
    ]

    snapshot = latest_binance_snapshot_aggregation(rows)

    assert snapshot.quantities == {"ASTER": Decimal("4699.13892928")}
    aster_sources = snapshot.source_drilldown["ASTER"]
    assert [source["source"] for source in aster_sources] == [
        "earn_position",
        "ld_receipt_token",
    ]
    assert [source["included"] for source in aster_sources] == [True, False]
    assert aster_sources[1]["reason"] == (
        "ld_receipt_token_excluded_corresponding_position_present"
    )


def test_calculate_holdings_keeps_wbeth_eth_staking_separate_excludes_ld():
    captured_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    rows = [
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="WBETH",
            quantity="1.25",
            timestamp=captured_at,
            raw_data={"account_type": "earn"},
        ),
        DummyTransaction(
            tx_type="balance_snapshot_spot",
            asset_symbol="LDWBETH",
            quantity="1.25",
            timestamp=captured_at,
            raw_data={"account_type": "spot"},
        ),
        DummyTransaction(
            tx_type="staking_position",
            asset_symbol="ETH",
            quantity="0.75",
            timestamp=captured_at,
            raw_data={"position_id": "eth_staking"},
        ),
        DummyTransaction(
            tx_type="balance_snapshot_spot",
            asset_symbol="LDETH",
            quantity="0.75",
            timestamp=captured_at,
            raw_data={"account_type": "spot"},
        ),
    ]

    holdings = {holding.symbol: holding for holding in calculate_holdings(rows)}

    assert holdings["WBETH"].quantity == Decimal("1.25")
    assert holdings["ETH"].quantity == Decimal("0.75")
    assert {
        source["asset_symbol"]: source["included"]
        for source in holdings["WBETH"].source_drilldown
    } == {
        "WBETH": True,
        "LDWBETH": False,
    }
    assert {
        source["asset_symbol"]: source["included"]
        for source in holdings["ETH"].source_drilldown
    } == {
        "ETH": True,
        "LDETH": False,
    }


def test_ld_receipt_remains_counted_when_corresponding_position_is_absent():
    captured_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    rows = [
        DummyTransaction(
            tx_type="balance_snapshot_spot",
            asset_symbol="LDBTC",
            quantity="0.05",
            timestamp=captured_at,
            raw_data={"account_type": "spot"},
        ),
    ]

    holdings = calculate_holdings(rows)

    assert len(holdings) == 1
    assert holdings[0].symbol == "BTC"
    assert holdings[0].quantity == Decimal("0.05")
    assert holdings[0].source_drilldown[0]["reason"] == (
        "ld_receipt_token_included_no_corresponding_position"
    )


def test_live_binance_snapshot_excludes_eth_staking_when_earn_eth_is_current():
    captured_at = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    rows = [
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="ETH",
            quantity="0.73696728",
            timestamp=captured_at,
            raw_data={"account_type": "earn"},
        ),
        DummyTransaction(
            tx_type="staking_position",
            asset_symbol="ETH",
            quantity="1.74215224",
            timestamp=captured_at,
            raw_data={"position_id": "eth_staking"},
        ),
    ]

    snapshot = latest_binance_snapshot_aggregation(rows)

    assert snapshot.quantities == {"ETH": Decimal("0.73696728")}
    eth_sources = snapshot.source_drilldown["ETH"]
    assert [(source["source"], source["included"]) for source in eth_sources] == [
        ("earn_position", True),
        ("staking_position", False),
    ]
    assert eth_sources[1]["reason"] == (
        "staking_position_excluded_corresponding_earn_position_present"
    )


def test_live_binance_mock_current_value_matches_broker_visible_exposure():
    captured_at = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
    rows = [
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="WBETH",
            quantity="1.59",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="ASTER",
            quantity="4699",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="ETH",
            quantity="0.73696728",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="staking_position",
            asset_symbol="ETH",
            quantity="1.74215224",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="balance_snapshot_spot",
            asset_symbol="BTC",
            quantity="0.01894",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="BNSOL",
            quantity="8.08",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="balance_snapshot_earn",
            asset_symbol="FET",
            quantity="3024.12030413",
            timestamp=captured_at,
        ),
        DummyTransaction(
            tx_type="balance_snapshot_spot",
            asset_symbol="BNB",
            quantity="0.085",
            timestamp=captured_at,
        ),
    ]
    prices = {
        "WBETH": Decimal("2578.616352201257861635220126"),
        "ASTER": Decimal("0.6597148329431793998723132581"),
        "ETH": Decimal("2306.689961870765305704922859"),
        "BTC": Decimal("79197.46568109820485744456177"),
        "BNSOL": Decimal("93.81188118811881188118811881"),
        "FET": Decimal("0.2048860256348757833433815894"),
        "BNB": Decimal("623.5294117647058823529411765"),
    }

    holdings = calculate_holdings(rows)
    value = sum(holding.quantity * prices[holding.symbol] for holding in holdings)

    assert {holding.symbol: holding.quantity for holding in holdings}["FET"] == Decimal(
        "3024.12030413"
    )
    assert Decimal("11800") <= value <= Decimal("12000")
    assert value < Decimal("15200")
