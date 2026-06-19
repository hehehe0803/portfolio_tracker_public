# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.import_review import (
    ImportReviewRow,
    assess_import_rows,
    build_daily_import_briefing,
    find_transfer_link_candidates,
)


def _row(
    *,
    institution: str = "binance",
    tx_type: str = "spot_trade",
    asset_symbol: str = "ASTER",
    quantity: Decimal = Decimal("10"),
    timestamp: datetime | None = None,
    fingerprint: str | None = "row-fp",
    schema_certainty: str = "high",
    raw_data: dict | None = None,
) -> ImportReviewRow:
    return ImportReviewRow(
        institution=institution,
        tx_type=tx_type,
        asset_symbol=asset_symbol,
        quantity=quantity,
        timestamp=timestamp or datetime(2025, 10, 10, 12, tzinfo=UTC),
        fingerprint=fingerprint,
        schema_certainty=schema_certainty,
        raw_data=raw_data or {},
    )


def test_assess_import_rows_assigns_confidence_and_review_actions_from_row_risks():
    rows = [
        _row(asset_symbol="ASTER", fingerprint="stable-fp"),
        _row(asset_symbol="UNKNOWNCOIN", fingerprint="unknown-fp"),
        _row(asset_symbol="USDT", fingerprint="duplicate-fp"),
        _row(asset_symbol="BTC", fingerprint=None),
        _row(asset_symbol="ETH", fingerprint="delta-fp", raw_data={"delta_usd": "125"}),
        _row(
            asset_symbol="HYPE",
            fingerprint="ambiguous-transfer-fp",
            raw_data={"transfer_link_ambiguous": True},
        ),
    ]

    assessments = assess_import_rows(
        rows,
        known_symbols={"ASTER", "USDT", "BTC", "ETH", "HYPE"},
        existing_fingerprints={"duplicate-fp"},
        material_delta_usd=Decimal("100"),
    )

    by_fp = {assessment.row.fingerprint: assessment for assessment in assessments}
    assert by_fp["stable-fp"].confidence == "high"
    assert by_fp["stable-fp"].review_actions == ["approve_import"]

    assert by_fp["unknown-fp"].confidence == "low"
    assert "map_symbol" in by_fp["unknown-fp"].review_actions

    assert by_fp["duplicate-fp"].confidence == "low"
    assert by_fp["duplicate-fp"].review_actions == ["reject_import"]

    missing_fingerprint = assessments[3]
    assert missing_fingerprint.confidence == "medium"
    assert "refresh_source" in missing_fingerprint.review_actions

    assert by_fp["delta-fp"].confidence == "medium"
    assert "investigate_delta" in by_fp["delta-fp"].review_actions

    assert by_fp["ambiguous-transfer-fp"].confidence == "low"
    assert "confirm_transfer_link" in by_fp["ambiguous-transfer-fp"].review_actions


def test_find_transfer_link_candidates_marks_exact_and_ambiguous_cross_venue_matches():
    base_time = datetime(2025, 10, 10, 12, tzinfo=UTC)
    withdrawal = _row(
        institution="binance",
        tx_type="withdrawal",
        asset_symbol="ASTER",
        quantity=Decimal("-100.0000"),
        timestamp=base_time,
        fingerprint="binance-withdrawal",
        raw_data={"source_endpoint": "withdraw_history"},
    )
    exact_deposit = _row(
        institution="aster",
        tx_type="aster_transfer_candidate",
        asset_symbol="ASTER",
        quantity=Decimal("100.05"),
        timestamp=base_time + timedelta(hours=4),
        fingerprint="aster-deposit",
        raw_data={"source_type": "aster_csv", "custody_movement_candidate": True},
    )
    late_deposit = _row(
        institution="hyperliquid",
        tx_type="hyperliquid_transfer_candidate",
        asset_symbol="ASTER",
        quantity=Decimal("100"),
        timestamp=base_time + timedelta(days=4),
        fingerprint="late-hyperliquid-deposit",
    )

    candidates = find_transfer_link_candidates(
        [withdrawal],
        [exact_deposit, late_deposit],
        amount_tolerance_pct=Decimal("0.001"),
        time_window=timedelta(days=2),
    )

    assert len(candidates) == 1
    assert candidates[0].withdrawal_fingerprint == "binance-withdrawal"
    assert candidates[0].deposit_fingerprints == ["aster-deposit"]
    assert candidates[0].confidence == "high"
    assert candidates[0].review_action == "confirm_transfer_link"
    assert candidates[0].auto_commit is False

    second_deposit = _row(
        institution="hyperliquid",
        tx_type="hyperliquid_transfer_candidate",
        asset_symbol="ASTER",
        quantity=Decimal("99.98"),
        timestamp=base_time + timedelta(hours=5),
        fingerprint="hyperliquid-deposit",
    )
    ambiguous = find_transfer_link_candidates(
        [withdrawal],
        [exact_deposit, second_deposit],
        amount_tolerance_pct=Decimal("0.001"),
        time_window=timedelta(days=2),
    )

    assert ambiguous[0].confidence == "low"
    assert ambiguous[0].ambiguous is True
    assert ambiguous[0].deposit_fingerprints == ["aster-deposit", "hyperliquid-deposit"]


def test_build_daily_import_briefing_returns_counts_actions_and_ambiguous_transfers():
    rows = [
        _row(fingerprint="safe"),
        _row(
            fingerprint="needs-link",
            raw_data={"transfer_link_ambiguous": True},
        ),
    ]
    assessments = assess_import_rows(
        rows,
        known_symbols={"ASTER"},
        existing_fingerprints=set(),
    )
    transfer = find_transfer_link_candidates(
        [
            _row(
                tx_type="withdrawal",
                quantity=Decimal("-5"),
                fingerprint="withdrawal",
            )
        ],
        [
            _row(
                institution="aster",
                tx_type="aster_transfer_candidate",
                quantity=Decimal("5"),
                fingerprint="deposit-a",
            ),
            _row(
                institution="hyperliquid",
                tx_type="hyperliquid_transfer_candidate",
                quantity=Decimal("5"),
                fingerprint="deposit-b",
            ),
        ],
    )

    briefing = build_daily_import_briefing(assessments, transfer)

    assert briefing["source"] == "import_review"
    assert briefing["social_or_news_intelligence"] is False
    assert briefing["confidence_counts"] == {"high": 1, "medium": 0, "low": 1}
    assert briefing["review_action_counts"]["approve_import"] == 1
    assert briefing["review_action_counts"]["confirm_transfer_link"] == 2
    assert briefing["ambiguous_transfer_count"] == 1
    assert briefing["ambiguous_transfers"][0]["withdrawal_fingerprint"] == "withdrawal"
