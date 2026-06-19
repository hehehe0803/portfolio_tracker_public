from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.services.accounting_history import (
    HistoricalPosition,
    HistoricalValueAnchor,
    HistoryMetricVisibility,
    SourceCoverageWindow,
    evaluate_history_metric_visibility,
    resolve_historical_value,
)
from app.services.pricing import HistoricalPriceResult


async def _missing_price(
    symbol: str,
    as_of: datetime,
) -> HistoricalPriceResult:
    return HistoricalPriceResult(
        symbol=symbol,
        as_of=as_of,
        price_usd=None,
        reason_code="missing_historical_price",
    )


async def _trusted_price(
    symbol: str,
    as_of: datetime,
) -> HistoricalPriceResult:
    return HistoricalPriceResult(
        symbol=symbol,
        as_of=as_of,
        price_usd=Decimal("2500"),
        reason_code=None,
    )


@pytest.mark.asyncio
async def test_reconstruction_blocks_when_historical_price_is_missing():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[],
        positions=[
            HistoricalPosition(
                symbol="ETH",
                quantity=Decimal("2"),
                source="binance",
            )
        ],
        source_coverage=[
            SourceCoverageWindow(
                source="binance",
                start_at=datetime(2026, 1, 1, tzinfo=UTC),
                end_at=datetime(2026, 12, 31, tzinfo=UTC),
                confidence_state="trusted",
            )
        ],
        price_lookup=_missing_price,
    )

    assert result.value_usd is None
    assert result.source == "unavailable"
    assert result.confidence_state == "blocked"
    assert result.reason_codes == ("missing_historical_price",)
    assert result.sensitive_metrics_visible is False


@pytest.mark.asyncio
async def test_reconstruction_blocks_when_source_coverage_is_missing():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[],
        positions=[
            HistoricalPosition(
                symbol="ETH",
                quantity=Decimal("2"),
                source="binance",
            )
        ],
        source_coverage=[],
        price_lookup=_trusted_price,
    )

    assert result.value_usd is None
    assert result.source == "unavailable"
    assert result.confidence_state == "blocked"
    assert result.reason_codes == ("missing_source_coverage",)


@pytest.mark.asyncio
async def test_conflicting_exact_anchors_block_history_value():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[
            HistoricalValueAnchor(
                captured_at=as_of,
                value_usd=Decimal("1000"),
                source="position_snapshot",
            ),
            HistoricalValueAnchor(
                captured_at=as_of,
                value_usd=Decimal("1001"),
                source="broker_statement",
            ),
        ],
        positions=[],
        source_coverage=[],
        price_lookup=_trusted_price,
    )

    assert result.value_usd is None
    assert result.source == "unavailable"
    assert result.confidence_state == "blocked"
    assert result.reason_codes == ("anchor_conflict",)


def test_trusted_current_value_does_not_make_lifetime_history_trusted():
    visibility = evaluate_history_metric_visibility(
        current_value_confidence_state="trusted",
        history_confidence_state="blocked",
        history_reason_codes=("missing_historical_price",),
    )

    assert visibility == HistoryMetricVisibility(
        confidence_state="blocked",
        reason_codes=(
            "current_value_trusted_history_untrusted",
            "missing_historical_price",
        ),
        lifetime_pnl_visible=False,
        period_performance_visible=False,
    )
