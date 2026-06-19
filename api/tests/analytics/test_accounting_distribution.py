# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.services.accounting_distribution import (
    DistributionCurrentValue,
    DistributionHolding,
    calculate_asset_type_distribution,
)

AS_OF = datetime(2026, 6, 19, tzinfo=UTC)


def _trusted_current_value(value_usd: str = "1960") -> DistributionCurrentValue:
    return DistributionCurrentValue(
        value_usd=Decimal(value_usd),
        as_of=AS_OF,
        holdings_reconciled=True,
        broker_cash_reconciled=True,
        stablecoin_reserve_reconciled=True,
        position_existence_reconciled=True,
    )


def test_stablecoins_are_cash_reserve_and_excluded_from_crypto_distribution() -> None:
    summary = calculate_asset_type_distribution(
        current_value=_trusted_current_value(),
        holdings=[
            DistributionHolding(
                symbol="BTC",
                asset_type="crypto",
                current_value_usd=Decimal("1000"),
            ),
            DistributionHolding(
                symbol="USDT",
                asset_type="crypto",
                current_value_usd=Decimal("200"),
            ),
            DistributionHolding(
                symbol="USDC",
                asset_type="stablecoin",
                current_value_usd=Decimal("50"),
            ),
            DistributionHolding(
                symbol="USD",
                asset_type="cash",
                current_value_usd=Decimal("100"),
                cash_reserve_kind="broker_cash",
            ),
            DistributionHolding(
                symbol="USD",
                asset_type="cash",
                current_value_usd=Decimal("25"),
                cash_reserve_kind="other_tracked_cash",
            ),
            DistributionHolding(
                symbol="VOO",
                asset_type="etf",
                current_value_usd=Decimal("500"),
            ),
            DistributionHolding(
                symbol="XAU",
                asset_type="commodity",
                current_value_usd=Decimal("75"),
            ),
            DistributionHolding(
                symbol="WATCH",
                asset_type="collectible",
                current_value_usd=Decimal("10"),
            ),
        ],
    )

    buckets = {bucket.asset_type: bucket for bucket in summary.asset_type_buckets}

    assert buckets["crypto"].value_usd == Decimal("1000")
    assert buckets["cash"].value_usd == Decimal("375")
    assert buckets["stocks_etfs"].value_usd == Decimal("500")
    assert buckets["commodities"].value_usd == Decimal("75")
    assert buckets["other"].value_usd == Decimal("10")
    assert summary.cash_reserve.stablecoin_usd == Decimal("250")
    assert summary.cash_reserve.broker_cash_usd == Decimal("100")
    assert summary.cash_reserve.other_tracked_cash_usd == Decimal("25")
    assert summary.cash_reserve.total_usd == Decimal("375")
    assert buckets["crypto"].percentage == (
        Decimal("1000") / Decimal("1960") * Decimal("100")
    )
    assert summary.confidence_state == "trusted"
    assert summary.reason_codes == ()


def test_distribution_mismatch_prevents_trusted_percentages() -> None:
    summary = calculate_asset_type_distribution(
        current_value=_trusted_current_value("1000"),
        holdings=[
            DistributionHolding(
                symbol="BTC",
                asset_type="crypto",
                current_value_usd=Decimal("980"),
            )
        ],
    )

    assert summary.total_allocated_usd == Decimal("980")
    assert summary.current_value_usd == Decimal("1000")
    assert summary.reconciliation_delta_usd == Decimal("-20")
    assert summary.reconciliation_tolerance_usd == Decimal("0.1000")
    assert summary.percentages_visible is False
    assert summary.confidence_state == "provisional"
    assert "distribution_total_mismatch" in summary.reason_codes
    assert summary.asset_type_buckets[0].percentage is None
    assert summary.asset_type_buckets[0].percentage_state == "suppressed"


def test_weak_current_value_suppresses_percentages_but_keeps_dollar_values() -> None:
    current_value = _trusted_current_value("1000")
    current_value.confidence_state = "provisional"
    current_value.reason_codes = ("current_value_from_daily_pdf",)

    summary = calculate_asset_type_distribution(
        current_value=current_value,
        holdings=[
            DistributionHolding(
                symbol="BTC",
                asset_type="crypto",
                current_value_usd=Decimal("800"),
            ),
            DistributionHolding(
                symbol="USDT",
                asset_type="crypto",
                current_value_usd=Decimal("200"),
            ),
        ],
    )

    buckets = {bucket.asset_type: bucket for bucket in summary.asset_type_buckets}

    assert buckets["crypto"].value_usd == Decimal("800")
    assert buckets["cash"].value_usd == Decimal("200")
    assert summary.cash_reserve.stablecoin_usd == Decimal("200")
    assert summary.percentages_visible is False
    assert summary.confidence_state == "provisional"
    assert "current_value_confidence_provisional" in summary.reason_codes
    assert "current_value_from_daily_pdf" in summary.reason_codes
    assert all(bucket.percentage is None for bucket in summary.asset_type_buckets)


def test_cash_reserve_confidence_is_scoped_to_cash_outputs() -> None:
    current_value = _trusted_current_value("1000")
    current_value.stablecoin_reserve_reconciled = False

    summary = calculate_asset_type_distribution(
        current_value=current_value,
        holdings=[
            DistributionHolding(
                symbol="ETH",
                asset_type="crypto",
                current_value_usd=Decimal("800"),
            ),
            DistributionHolding(
                symbol="USDC",
                asset_type="crypto",
                current_value_usd=Decimal("200"),
            ),
        ],
    )

    buckets = {bucket.asset_type: bucket for bucket in summary.asset_type_buckets}

    assert buckets["crypto"].value_usd == Decimal("800")
    assert buckets["crypto"].confidence_state == "trusted"
    assert buckets["cash"].value_usd == Decimal("200")
    assert buckets["cash"].confidence_state == "blocked"
    assert summary.cash_reserve.confidence_state == "blocked"
    assert summary.cash_reserve.reason_codes == ("stablecoin_reserve_unresolved",)
    assert summary.percentages_visible is False
    assert summary.confidence_state == "blocked"
    assert "stablecoin_reserve_unresolved" in summary.reason_codes
