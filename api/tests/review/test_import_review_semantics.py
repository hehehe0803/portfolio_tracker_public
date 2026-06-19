# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.import_review import (
    ImportReviewRow,
    ReviewAction,
    ReviewConfidence,
    build_daily_import_briefing,
    classify_import_row,
    find_transfer_link_candidates,
)


def _row(
    *,
    institution: str = "binance",
    tx_type: str = "deposit",
    asset_symbol: str = "USDT",
    quantity: Decimal = Decimal("100"),
    total_usd: Decimal | None = Decimal("100"),
    timestamp: datetime = datetime(2026, 5, 26, 8, 0, tzinfo=UTC),
    fingerprint: str = "fp-1",
    external_id: str | None = "external-1",
    duplicate: bool = False,
    raw_data: dict | None = None,
) -> ImportReviewRow:
    return ImportReviewRow(
        institution=institution,
        tx_type=tx_type,
        asset_symbol=asset_symbol,
        asset_type="stablecoin",
        quantity=quantity,
        total_usd=total_usd,
        timestamp=timestamp,
        fingerprint=fingerprint,
        external_id=external_id,
        duplicate=duplicate,
        raw_data=raw_data or {"schema": "known"},
    )


def test_classify_import_row_marks_certain_identifier_backed_rows_high_confidence():
    review = classify_import_row(_row())

    assert review.confidence is ReviewConfidence.HIGH
    assert review.actions == (ReviewAction.APPROVE_IMPORT,)
    assert review.reasons == ("known_schema", "stable_symbol", "identifier_backed")


def test_classify_import_row_requires_review_for_unknown_duplicate_missing_value():
    review = classify_import_row(
        _row(
            asset_symbol="MYSTERY",
            total_usd=None,
            external_id=None,
            duplicate=True,
            raw_data={"schema": "unknown"},
        )
    )

    assert review.confidence is ReviewConfidence.LOW
    assert ReviewAction.REJECT_IMPORT in review.actions
    assert ReviewAction.MAP_SYMBOL in review.actions
    assert ReviewAction.INVESTIGATE_DELTA in review.actions
    assert review.reasons == (
        "unknown_schema",
        "unknown_symbol",
        "missing_identifier",
        "duplicate",
        "missing_material_value",
    )


def test_find_transfer_link_candidates_links_single_withdrawal_to_crypto_csv_deposit():
    withdrawal = _row(
        institution="binance",
        tx_type="withdrawal",
        asset_symbol="USDT",
        quantity=Decimal("-100"),
        fingerprint="binance-out",
        timestamp=datetime(2026, 5, 26, 8, 0, tzinfo=UTC),
    )
    deposit = _row(
        institution="aster",
        tx_type="aster_transfer_candidate",
        asset_symbol="USDT",
        quantity=Decimal("99.98"),
        fingerprint="aster-in",
        timestamp=datetime(2026, 5, 26, 8, 45, tzinfo=UTC),
        external_id=None,
        raw_data={"source_type": "aster_csv", "custody_movement_candidate": True},
    )

    candidates = find_transfer_link_candidates(
        [withdrawal, deposit],
        amount_tolerance=Decimal("0.001"),
        time_window=timedelta(hours=2),
    )

    assert len(candidates) == 1
    assert candidates[0].confidence is ReviewConfidence.MEDIUM
    assert candidates[0].actions == (ReviewAction.CONFIRM_TRANSFER_LINK,)
    assert candidates[0].withdrawal_fingerprint == "binance-out"
    assert candidates[0].deposit_fingerprints == ("aster-in",)
    assert candidates[0].amount_delta == Decimal("0.02")


def test_find_transfer_link_candidates_flags_ambiguous_matches_for_review():
    withdrawal = _row(
        institution="binance",
        tx_type="withdrawal",
        quantity=Decimal("-100"),
        fingerprint="binance-out",
    )
    first_deposit = _row(
        institution="aster",
        tx_type="aster_transfer_candidate",
        quantity=Decimal("100"),
        fingerprint="aster-in",
        external_id=None,
        raw_data={"source_type": "aster_csv", "custody_movement_candidate": True},
    )
    second_deposit = _row(
        institution="hyperliquid",
        tx_type="hyperliquid_transfer_candidate",
        quantity=Decimal("99.99"),
        fingerprint="hyperliquid-in",
        external_id=None,
        raw_data={"source_type": "hyperliquid_csv", "custody_movement_candidate": True},
    )

    candidates = find_transfer_link_candidates(
        [withdrawal, first_deposit, second_deposit],
        amount_tolerance=Decimal("0.001"),
        time_window=timedelta(hours=2),
    )

    assert len(candidates) == 1
    assert candidates[0].confidence is ReviewConfidence.LOW
    assert ReviewAction.CONFIRM_TRANSFER_LINK in candidates[0].actions
    assert ReviewAction.INVESTIGATE_DELTA in candidates[0].actions
    assert candidates[0].deposit_fingerprints == ("aster-in", "hyperliquid-in")


def test_build_daily_import_briefing_summarizes_review_debt_without_mutating_rows():
    high = classify_import_row(_row(fingerprint="high"))
    low = classify_import_row(
        _row(
            asset_symbol="MYSTERY",
            total_usd=None,
            external_id=None,
            duplicate=True,
            fingerprint="low",
            raw_data={"schema": "unknown"},
        )
    )
    transfer = find_transfer_link_candidates(
        [
            _row(tx_type="withdrawal", quantity=Decimal("-100"), fingerprint="out"),
            _row(
                institution="aster",
                tx_type="aster_transfer_candidate",
                quantity=Decimal("100"),
                fingerprint="in",
                external_id=None,
                raw_data={
                    "source_type": "aster_csv",
                    "custody_movement_candidate": True,
                },
            ),
        ]
    )[0]

    briefing = build_daily_import_briefing([high, low], [transfer])

    assert briefing["confidence_counts"] == {"high": 1, "medium": 0, "low": 1}
    assert briefing["review_action_counts"]["approve_import"] == 1
    assert briefing["review_action_counts"]["reject_import"] == 1
    assert briefing["review_action_counts"]["confirm_transfer_link"] == 1
    assert briefing["ambiguous_transfer_candidate_count"] == 0
    assert briefing["items"][0]["fingerprint"] == "high"
