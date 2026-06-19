# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import Transaction
from app.services.analytics import calculate_holdings
from app.services.crypto_csv_parser import (
    parse_aster_csv,
    parse_hyperliquid_csv,
    parse_hyperliquid_ledger_csv,
)


def _as_transaction(entry) -> Transaction:
    return Transaction(
        institution=entry.institution,
        tx_type=entry.tx_type,
        asset_symbol=entry.asset_symbol,
        asset_type=entry.asset_type,
        quantity=entry.quantity,
        price_usd=entry.price_usd,
        total_usd=entry.total_usd,
        fee=entry.fee,
        fee_currency=entry.fee_currency,
        timestamp=entry.timestamp,
        fingerprint=entry.fingerprint,
        raw_data=entry.raw_data,
    )


def test_parse_aster_csv_groups_same_timestamp_trade_legs_and_keeps_transfers_neutral():
    csv_text = (
        "Time,Type,Amount,Symbol\n"
        "2025-10-10 15:27:07,Transfer,-4694.48000000 ASTER,-\n"
        "2025-10-10 15:24:01,Trade,114.87633040 ASTER,-\n"
        "2025-10-10 15:24:01,Trade,-185.36596000 USDT,-\n"
    )

    entries = parse_aster_csv(csv_text)

    assert [entry.tx_type for entry in entries] == [
        "aster_transfer_candidate",
        "aster_trade",
    ]

    transfer = entries[0]
    assert transfer.institution == "aster"
    assert transfer.asset_symbol == "ASTER"
    assert transfer.quantity == Decimal("-4694.48000000")
    assert transfer.total_usd is None
    assert transfer.timestamp == datetime(2025, 10, 10, 15, 27, 7, tzinfo=UTC)
    assert transfer.raw_data["custody_movement_candidate"] is True

    trade = entries[1]
    assert trade.asset_symbol == "ASTER"
    assert trade.quantity == Decimal("114.87633040")
    assert trade.price_usd == Decimal("1.613613173005742182029171085")
    assert trade.total_usd == Decimal("185.36596000")
    assert trade.raw_data["side"] == "buy"
    assert trade.raw_data["quote_asset"] == "USDT"
    assert trade.raw_data["quote_quantity"] == "185.36596000"
    assert trade.raw_data["grouped_leg_count"] == 2


def test_parse_aster_csv_groups_many_same_timestamp_legs_into_one_net_trade():
    csv_text = (
        "Time,Type,Amount,Symbol\n"
        "2025-09-24 16:42:26,Trade,204.61543050 ASTER,-\n"
        "2025-09-24 16:42:26,Trade,-475.56882000 USDT,-\n"
        "2025-09-24 16:42:26,Trade,68.92445950 ASTER,-\n"
        "2025-09-24 16:42:26,Trade,-160.00643730 USDT,-\n"
    )

    entries = parse_aster_csv(csv_text)

    assert len(entries) == 1
    assert entries[0].tx_type == "aster_trade"
    assert entries[0].asset_symbol == "ASTER"
    assert entries[0].quantity == Decimal("273.53989000")
    assert entries[0].total_usd == Decimal("635.57525730")
    assert entries[0].raw_data["grouped_leg_count"] == 4


def test_parse_hyperliquid_csv_splits_pair_and_preserves_derivative_metadata():
    csv_text = (
        "time,coin,dir,px,sz,ntl,fee,closedPnl\n"
        "9/18/2025 - 14:59:56,ETH/USDC,Sell,4576.6,0.0515,"
        "235.69490000000002,0.16498643,-0.26283641999999996\n"
        "9/18/2025 - 15:00:16,HYPE/USDC,Buy,58.319,4.03,"
        "235.02557000000002,0.00282099,-0.16451731581\n"
    )

    entries = parse_hyperliquid_csv(csv_text)

    assert [entry.tx_type for entry in entries] == [
        "hyperliquid_derivative_fill",
        "hyperliquid_derivative_fill",
    ]
    assert entries[0].institution == "hyperliquid"
    assert entries[0].asset_symbol == "ETH"
    assert entries[0].asset_type == "derivative"
    assert entries[0].quantity == Decimal("0.0515")
    assert entries[0].price_usd == Decimal("4576.6")
    assert entries[0].total_usd == Decimal("235.69490000000002")
    assert entries[0].fee == Decimal("0.16498643")
    assert entries[0].fee_currency == "USDC"
    assert entries[0].timestamp == datetime(2025, 9, 18, 14, 59, 56, tzinfo=UTC)
    assert entries[0].raw_data["side"] == "sell"
    assert entries[0].raw_data["base_asset"] == "ETH"
    assert entries[0].raw_data["quote_asset"] == "USDC"
    assert entries[0].raw_data["signed_base_quantity"] == "-0.0515"
    assert entries[0].raw_data["closed_pnl"] == "-0.26283641999999996"

    assert entries[1].asset_symbol == "HYPE"
    assert entries[1].raw_data["side"] == "buy"
    assert entries[1].raw_data["signed_base_quantity"] == "4.03"


def test_parse_hyperliquid_ledger_csv_normalizes_deposits_and_withdrawals():
    csv_text = (
        "time,type,coin,amount,hash\n"
        "9/18/2025 - 14:53:32,deposit,ETH,0.0019,0xabc\n"
        "2025-09-19T08:01:02Z,withdrawal,USDC,-125.50,0xdef\n"
    )

    entries = parse_hyperliquid_ledger_csv(csv_text)

    assert [entry.tx_type for entry in entries] == [
        "hyperliquid_deposit_candidate",
        "hyperliquid_withdrawal_candidate",
    ]
    assert entries[0].institution == "hyperliquid"
    assert entries[0].asset_symbol == "ETH"
    assert entries[0].asset_type == "crypto"
    assert entries[0].quantity == Decimal("0.0019")
    assert entries[0].total_usd is None
    assert entries[0].timestamp == datetime(2025, 9, 18, 14, 53, 32, tzinfo=UTC)
    assert entries[0].raw_data["custody_movement_candidate"] is True
    assert entries[0].raw_data["external_id"] == "0xabc"

    assert entries[1].asset_symbol == "USDC"
    assert entries[1].asset_type == "stablecoin"
    assert entries[1].quantity == Decimal("-125.50")
    assert entries[1].total_usd == Decimal("-125.50")
    assert entries[1].raw_data["movement"] == "withdrawal"


def test_crypto_csv_derivative_and_custody_rows_do_not_create_spot_holdings():
    aster_entries = parse_aster_csv(
        "Time,Type,Amount,Symbol\n"
        "2025-10-10 15:27:07,Transfer,-4694.48000000 ASTER,-\n"
        "2025-10-10 15:24:01,Trade,114.87633040 ASTER,-\n"
        "2025-10-10 15:24:01,Trade,-185.36596000 USDT,-\n"
    )
    hyperliquid_entries = parse_hyperliquid_csv(
        "time,coin,dir,px,sz,ntl,fee,closedPnl\n"
        "9/18/2025 - 14:59:56,ETH/USDC,Sell,4576.6,0.0515,"
        "235.69490000000002,0.16498643,-0.26283641999999996\n"
    )

    holdings = calculate_holdings(
        [_as_transaction(entry) for entry in [*aster_entries, *hyperliquid_entries]]
    )

    assert holdings == []
