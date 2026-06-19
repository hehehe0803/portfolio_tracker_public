from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.services.xtb_ingest import (
    _normalize_xtb_timestamp,
    _normalized_fingerprint,
    _parse_share_count_from_description,
    _parse_split_ratio,
    _split_dedupe_key,
    _split_fingerprint,
    _xtb_tx_to_db,
    dedupe_xtb_transactions,
    summarize_xtb_transactions,
)
from app.services.xtb_parser import TransactionType, XTBTransaction


def _build_xtb_transaction(
    *,
    amount: str,
    description: str,
    symbol: str = "ACHR.US",
    tx_type: TransactionType = TransactionType.OPEN_POSITION,
) -> XTBTransaction:
    return XTBTransaction(
        id="1",
        date=datetime(2026, 3, 1, 12, 0, 0),
        tx_type=tx_type,
        amount=Decimal(amount),
        currency="USD",
        symbol=symbol,
        description=description,
    )


def test_parse_share_count_from_symbol_description():
    assert _parse_share_count_from_description("OPEN BUY 8.0000 ACHR.US") == Decimal(
        "8.0000"
    )


def test_parse_share_count_from_at_price_description_uses_trade_quantity():
    assert _parse_share_count_from_description("OPEN BUY 0.3507/11.3507 @ 17.62") == (
        Decimal("0.3507")
    )


def test_xtb_ingest_maps_quantity_and_price_from_description():
    xtx = _build_xtb_transaction(
        amount="-74.40",
        description="OPEN BUY 8.0000 ACHR.US",
    )

    db_tx = _xtb_tx_to_db(xtx, import_id=99)

    assert db_tx.quantity == Decimal("8.0000")
    assert db_tx.price_usd == Decimal("9.3")
    assert db_tx.total_usd == Decimal("-74.40")


def test_xtb_ingest_maps_fractional_share_quantity_and_price_from_description():
    xtx = _build_xtb_transaction(
        amount="-51.201138",
        description="OPEN BUY 0.2383 @ 214.86",
        symbol="MU.US",
    )

    db_tx = _xtb_tx_to_db(xtx, import_id=99)

    assert db_tx.quantity == Decimal("0.2383")
    assert db_tx.price_usd == Decimal("214.86")
    assert db_tx.asset_symbol == "MU.US"


def test_xtb_ingest_maps_dividend_cashflows_to_usd_cash_asset():
    xtx = _build_xtb_transaction(
        amount="2.43",
        description="NVO.US USD 1.2174/ SHR from 2026-04-08",
        symbol="NVO.US",
        tx_type=TransactionType.DIVIDEND,
    )

    db_tx = _xtb_tx_to_db(xtx, import_id=99)

    assert db_tx.asset_symbol == "USD"
    assert db_tx.asset_type == "crypto"
    assert db_tx.quantity == Decimal("2.43")
    assert db_tx.price_usd is None


def test_parse_split_ratio_from_description():
    assert _parse_split_ratio("XLU.US split 2 for 1") == Decimal("2")


def test_normalize_xtb_timestamp_adds_utc_to_naive_datetimes():
    normalized = _normalize_xtb_timestamp(datetime(2025, 9, 25, 15, 30, 1))

    assert normalized.tzinfo == UTC
    assert normalized.isoformat() == "2025-09-25T15:30:01+00:00"


def test_split_fingerprint_is_stable_for_naive_and_utc_timestamps():
    naive = _split_fingerprint(
        timestamp=datetime(2025, 9, 25, 15, 30, 1),
        symbol="XLU.US",
        description="XLU.US split 2 for 1",
    )
    aware = _split_fingerprint(
        timestamp=datetime(2025, 9, 25, 15, 30, 1, tzinfo=UTC),
        symbol="XLU.US",
        description="XLU.US split 2 for 1",
    )

    assert naive == aware


def test_split_dedupe_key_includes_event_time():
    first = _split_dedupe_key(
        timestamp=datetime(2025, 9, 25, 15, 30, 1),
        symbol="XLU.US",
        description="XLU.US split 2 for 1",
    )
    second = _split_dedupe_key(
        timestamp=datetime(2026, 9, 25, 15, 30, 1),
        symbol="XLU.US",
        description="XLU.US split 2 for 1",
    )

    assert first != second


def test_xtb_ingest_maps_split_rows_to_split_transactions():
    xtx = _build_xtb_transaction(
        amount="-517.08",
        description="XLU.US split 2 for 1",
        symbol="XLU.US",
    )

    db_tx = _xtb_tx_to_db(xtx, import_id=99)

    assert db_tx.tx_type == "split"
    assert db_tx.asset_symbol == "XLU.US"
    assert db_tx.quantity == Decimal("2")
    assert db_tx.price_usd is None
    assert db_tx.total_usd is None


def test_xtb_ingest_rejects_unsupported_split_descriptions_during_dedupe():
    xtx = _build_xtb_transaction(
        amount="-517.08",
        description="XLU.US split soon",
        symbol="XLU.US",
    )

    with pytest.raises(ValueError, match="Unsupported XTB split description"):
        dedupe_xtb_transactions([xtx], existing_fingerprints=set())


def test_xtb_summary_treats_split_rows_as_non_cash_events():
    transactions = [
        _build_xtb_transaction(
            amount="-517.08",
            description="XLU.US split 2 for 1",
            symbol="XLU.US",
        ),
        _build_xtb_transaction(
            amount="-74.40",
            description="OPEN BUY 8.0000 ACHR.US",
        ),
    ]

    summary = summarize_xtb_transactions(transactions)

    assert summary["gross_amount"] == Decimal("74.40")
    assert summary["by_type"]["split"] == Decimal("-517.08")
    assert summary["by_type"]["buy"] == Decimal("-74.40")


def test_xtb_summary_classifies_split_like_corrections_as_corrections():
    transactions = [
        _build_xtb_transaction(
            amount="100",
            description="corr XLU.US split 2 for 1",
            symbol="XLU.US",
        )
    ]

    summary = summarize_xtb_transactions(transactions)

    assert summary["gross_amount"] == Decimal("100")
    assert summary["by_type"]["correction"] == Decimal("100")


def test_xtb_dedupe_uses_normalized_split_fingerprint():
    split_tx = _build_xtb_transaction(
        amount="-517.08",
        description="XLU.US split 2 for 1",
        symbol="XLU.US",
    )

    deduped = dedupe_xtb_transactions(
        [split_tx], existing_fingerprints={_normalized_fingerprint(split_tx)}
    )

    assert deduped == []


def test_xtb_dedupe_skips_split_rows_when_matching_legacy_split_key_exists():
    split_tx = _build_xtb_transaction(
        amount="-517.08",
        description="XLU.US split 2 for 1",
        symbol="XLU.US",
    )

    deduped = dedupe_xtb_transactions(
        [split_tx],
        existing_fingerprints=set(),
        existing_split_keys={
            _split_dedupe_key(
                timestamp=split_tx.date,
                symbol="XLU.US",
                description="XLU.US split 2 for 1",
            )
        },
    )

    assert deduped == []


def test_xtb_dedupe_drops_duplicate_split_rows_within_same_batch():
    first_split = _build_xtb_transaction(
        amount="-517.08",
        description="XLU.US split 2 for 1",
        symbol="XLU.US",
    )
    duplicate_split = _build_xtb_transaction(
        amount="-517.08",
        description="XLU.US split 2 for 1",
        symbol="XLU.US",
    )

    deduped = dedupe_xtb_transactions(
        [first_split, duplicate_split],
        existing_fingerprints=set(),
        existing_split_keys=set(),
    )

    assert deduped == [first_split]


def test_xtb_dedupe_skips_correction_rows_before_validating_split_format():
    correction_tx = _build_xtb_transaction(
        amount="0",
        description="corr XLU.US split soon",
        symbol="XLU.US",
    )

    deduped = dedupe_xtb_transactions([correction_tx], existing_fingerprints=set())

    assert deduped == []
