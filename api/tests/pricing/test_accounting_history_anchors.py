# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.services.accounting_history import (
    HistoricalPosition,
    HistoricalValueAnchor,
    SourceCoverageWindow,
    resolve_historical_value,
)
from app.services.portfolio_state import build_portfolio_value_anchor
from app.services.pricing import HistoricalPriceResult, get_historical_price_usd


async def _historical_price(
    symbol: str,
    as_of: datetime,
) -> HistoricalPriceResult:
    return HistoricalPriceResult(
        symbol=symbol,
        as_of=as_of,
        price_usd=Decimal("120000"),
        reason_code=None,
    )


@pytest.mark.asyncio
async def test_exact_snapshot_anchor_beats_reconstruction_on_same_date():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[
            HistoricalValueAnchor(
                captured_at=as_of,
                value_usd=Decimal("1000"),
                source="position_snapshot",
            )
        ],
        positions=[
            HistoricalPosition(
                symbol="BTC",
                quantity=Decimal("1"),
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
        price_lookup=_historical_price,
    )

    assert result.value_usd == Decimal("1000")
    assert result.source == "exact_anchor"
    assert result.confidence_state == "trusted"
    assert result.reason_codes == ("exact_anchor",)


@pytest.mark.asyncio
async def test_latest_same_day_anchor_before_boundary_beats_reconstruction():
    as_of = datetime(2026, 5, 1, 18, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[
            HistoricalValueAnchor(
                captured_at=datetime(2026, 5, 1, 9, tzinfo=UTC),
                value_usd=Decimal("1000"),
                source="position_snapshot",
            ),
            HistoricalValueAnchor(
                captured_at=datetime(2026, 5, 1, 17, tzinfo=UTC),
                value_usd=Decimal("1100"),
                source="position_snapshot",
            ),
        ],
        positions=[
            HistoricalPosition(
                symbol="BTC",
                quantity=Decimal("1"),
                source="binance",
            )
        ],
        source_coverage=[],
        price_lookup=_historical_price,
        transaction_ledger_complete=True,
    )

    assert result.value_usd == Decimal("1100")
    assert result.source == "exact_anchor"
    assert result.confidence_state == "trusted"
    assert result.reason_codes == ("exact_anchor",)


@pytest.mark.asyncio
async def test_exact_anchor_preserves_blocking_reason_codes():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[
            HistoricalValueAnchor(
                captured_at=as_of,
                value_usd=None,
                source="position_snapshot",
                confidence_state="blocked",
                reason_codes=("missing_anchor_component_value",),
            )
        ],
        positions=[
            HistoricalPosition(
                symbol="BTC",
                quantity=Decimal("1"),
                source="binance",
            )
        ],
        source_coverage=[],
        price_lookup=_historical_price,
    )

    assert result.value_usd is None
    assert result.source == "exact_anchor"
    assert result.confidence_state == "blocked"
    assert result.reason_codes == ("missing_anchor_component_value",)
    assert result.sensitive_metrics_visible is False


@pytest.mark.asyncio
async def test_mixed_missing_and_present_anchor_values_conflict_deterministically():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    result = await resolve_historical_value(
        as_of=as_of,
        exact_anchors=[
            HistoricalValueAnchor(
                captured_at=as_of,
                value_usd=None,
                source="position_snapshot",
                confidence_state="blocked",
                reason_codes=("missing_anchor_component_value",),
            ),
            HistoricalValueAnchor(
                captured_at=as_of,
                value_usd=Decimal("1000"),
                source="broker_statement",
            ),
        ],
        positions=[
            HistoricalPosition(
                symbol="BTC",
                quantity=Decimal("1"),
                source="binance",
            )
        ],
        source_coverage=[],
        price_lookup=_historical_price,
    )

    assert result.value_usd is None
    assert result.source == "unavailable"
    assert result.confidence_state == "blocked"
    assert result.reason_codes == ("anchor_conflict",)


@pytest.mark.asyncio
async def test_historical_price_lookup_reports_missing_without_live_fallback():
    as_of = datetime(2026, 5, 1, tzinfo=UTC)

    with patch(
        "app.services.pricing._fetch_price",
        new_callable=AsyncMock,
        return_value=99999.0,
    ) as live_fetch:
        result = await get_historical_price_usd("BTC", as_of)

    assert result == HistoricalPriceResult(
        symbol="BTC",
        as_of=as_of,
        price_usd=None,
        reason_code="missing_historical_price",
    )
    live_fetch.assert_not_awaited()


def test_portfolio_snapshot_anchor_flags_missing_component_values():
    anchor = build_portfolio_value_anchor(
        captured_at=datetime(2026, 5, 1, tzinfo=UTC),
        component_values_usd=[Decimal("1000"), None],
        source="position_snapshot",
    )

    assert anchor.value_usd is None
    assert anchor.confidence_state == "blocked"
    assert anchor.reason_codes == ("missing_anchor_component_value",)
