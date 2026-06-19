from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from app.services.pricing import HistoricalPriceResult, get_historical_price_usd

ConfidenceState = Literal[
    "trusted",
    "warning",
    "provisional",
    "review_required",
    "blocked",
]
HistoricalValueSource = Literal["exact_anchor", "reconstructed", "unavailable"]
HistoryReasonCode = Literal[
    "exact_anchor",
    "reconstructed_value",
    "missing_anchor",
    "missing_historical_price",
    "missing_source_coverage",
    "missing_cashflow_classification",
    "missing_accounting_decision",
    "missing_anchor_component_value",
    "anchor_conflict",
    "current_value_trusted_history_untrusted",
]

HistoricalPriceLookup = Callable[
    [str, datetime],
    Awaitable[HistoricalPriceResult],
]

_CONFIDENCE_RANK: dict[ConfidenceState, int] = {
    "trusted": 0,
    "warning": 1,
    "provisional": 2,
    "review_required": 3,
    "blocked": 4,
}


@dataclass(frozen=True)
class HistoricalValueAnchor:
    captured_at: datetime
    value_usd: Decimal | None
    source: str
    confidence_state: ConfidenceState = "trusted"
    reason_codes: tuple[HistoryReasonCode, ...] = ()


@dataclass(frozen=True)
class HistoricalPosition:
    symbol: str
    quantity: Decimal
    source: str


@dataclass(frozen=True)
class SourceCoverageWindow:
    source: str
    start_at: datetime
    end_at: datetime | None
    confidence_state: ConfidenceState = "trusted"


@dataclass(frozen=True)
class HistoricalValueResult:
    as_of: datetime
    value_usd: Decimal | None
    source: HistoricalValueSource
    confidence_state: ConfidenceState
    reason_codes: tuple[HistoryReasonCode, ...]
    sensitive_metrics_visible: bool


@dataclass(frozen=True)
class HistoryMetricVisibility:
    confidence_state: ConfidenceState
    reason_codes: tuple[HistoryReasonCode, ...]
    lifetime_pnl_visible: bool
    period_performance_visible: bool


def _dedupe_reason_codes(
    reason_codes: Sequence[HistoryReasonCode],
) -> tuple[HistoryReasonCode, ...]:
    return tuple(dict.fromkeys(reason_codes))


def _max_confidence_state(states: Sequence[ConfidenceState]) -> ConfidenceState:
    if not states:
        return "trusted"
    return max(states, key=lambda state: _CONFIDENCE_RANK[state])


def _price_reason_code(reason_code: str | None) -> HistoryReasonCode:
    if reason_code == "missing_historical_price":
        return "missing_historical_price"
    return "missing_historical_price"


def _sensitive_metrics_visible(confidence_state: ConfidenceState) -> bool:
    return confidence_state in {"trusted", "warning"}


def _exact_anchors_for_date(
    *,
    as_of: datetime,
    anchors: Sequence[HistoricalValueAnchor],
) -> list[HistoricalValueAnchor]:
    same_day_anchors = [
        anchor
        for anchor in anchors
        if anchor.captured_at.date() == as_of.date() and anchor.captured_at <= as_of
    ]
    if not same_day_anchors:
        return []
    selected_timestamp = max(anchor.captured_at for anchor in same_day_anchors)
    return [
        anchor
        for anchor in same_day_anchors
        if anchor.captured_at == selected_timestamp
    ]


def _coverage_for_position(
    *,
    as_of: datetime,
    position: HistoricalPosition,
    source_coverage: Sequence[SourceCoverageWindow],
) -> SourceCoverageWindow | None:
    for coverage in source_coverage:
        if coverage.source != position.source:
            continue
        if coverage.start_at <= as_of and (
            coverage.end_at is None or as_of <= coverage.end_at
        ):
            return coverage
    return None


async def _reconstruct_value(
    *,
    as_of: datetime,
    positions: Sequence[HistoricalPosition],
    source_coverage: Sequence[SourceCoverageWindow],
    price_lookup: HistoricalPriceLookup,
    transaction_ledger_complete: bool,
    cashflow_classifications_complete: bool,
    accounting_decisions_complete: bool,
) -> HistoricalValueResult:
    reason_codes: list[HistoryReasonCode] = []
    blocking_reason_codes: list[HistoryReasonCode] = []
    confidence_states: list[ConfidenceState] = []
    reconstructed_value = Decimal("0")

    if not positions:
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=None,
            source="unavailable",
            confidence_state="blocked",
            reason_codes=("missing_anchor",),
            sensitive_metrics_visible=False,
        )

    if not transaction_ledger_complete:
        blocking_reason_codes.append("missing_source_coverage")
        confidence_states.append("blocked")
    if not cashflow_classifications_complete:
        blocking_reason_codes.append("missing_cashflow_classification")
        confidence_states.append("blocked")
    if not accounting_decisions_complete:
        blocking_reason_codes.append("missing_accounting_decision")
        confidence_states.append("blocked")

    for position in positions:
        coverage = _coverage_for_position(
            as_of=as_of,
            position=position,
            source_coverage=source_coverage,
        )
        if coverage is None:
            blocking_reason_codes.append("missing_source_coverage")
            confidence_states.append("blocked")
            continue
        confidence_states.append(coverage.confidence_state)
        if coverage.confidence_state != "trusted":
            reason_codes.append("missing_source_coverage")

        price_result = await price_lookup(position.symbol, as_of)
        if price_result.price_usd is None:
            blocking_reason_codes.append(_price_reason_code(price_result.reason_code))
            confidence_states.append("blocked")
            continue
        reconstructed_value += position.quantity * price_result.price_usd

    if blocking_reason_codes:
        confidence_state = _max_confidence_state(confidence_states)
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=None,
            source="unavailable",
            confidence_state=confidence_state,
            reason_codes=_dedupe_reason_codes(
                [*reason_codes, *blocking_reason_codes]
            ),
            sensitive_metrics_visible=False,
        )

    return HistoricalValueResult(
        as_of=as_of,
        value_usd=reconstructed_value,
        source="reconstructed",
        confidence_state=_max_confidence_state(confidence_states),
        reason_codes=_dedupe_reason_codes(["reconstructed_value", *reason_codes]),
        sensitive_metrics_visible=_sensitive_metrics_visible(
            _max_confidence_state(confidence_states)
        ),
    )


async def resolve_historical_value(
    *,
    as_of: datetime,
    exact_anchors: Sequence[HistoricalValueAnchor],
    positions: Sequence[HistoricalPosition],
    source_coverage: Sequence[SourceCoverageWindow],
    price_lookup: HistoricalPriceLookup = get_historical_price_usd,
    transaction_ledger_complete: bool = True,
    cashflow_classifications_complete: bool = True,
    accounting_decisions_complete: bool = True,
) -> HistoricalValueResult:
    exact_anchors_on_date = _exact_anchors_for_date(
        as_of=as_of,
        anchors=exact_anchors,
    )
    exact_anchor_values = {
        anchor.value_usd
        for anchor in exact_anchors_on_date
        if anchor.value_usd is not None
    }
    if len(exact_anchor_values) > 1:
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=None,
            source="unavailable",
            confidence_state="blocked",
            reason_codes=("anchor_conflict",),
            sensitive_metrics_visible=False,
        )
    if exact_anchors_on_date:
        confidence_state = _max_confidence_state(
            [anchor.confidence_state for anchor in exact_anchors_on_date]
        )
        reason_codes = _dedupe_reason_codes(
            [
                reason_code
                for anchor in exact_anchors_on_date
                for reason_code in (anchor.reason_codes or ("exact_anchor",))
            ]
        )
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=exact_anchors_on_date[0].value_usd,
            source="exact_anchor",
            confidence_state=confidence_state,
            reason_codes=reason_codes,
            sensitive_metrics_visible=_sensitive_metrics_visible(confidence_state),
        )

    return await _reconstruct_value(
        as_of=as_of,
        positions=positions,
        source_coverage=source_coverage,
        price_lookup=price_lookup,
        transaction_ledger_complete=transaction_ledger_complete,
        cashflow_classifications_complete=cashflow_classifications_complete,
        accounting_decisions_complete=accounting_decisions_complete,
    )


def evaluate_history_metric_visibility(
    *,
    current_value_confidence_state: ConfidenceState,
    history_confidence_state: ConfidenceState,
    history_reason_codes: Sequence[HistoryReasonCode],
) -> HistoryMetricVisibility:
    reason_codes = list(history_reason_codes)
    if (
        current_value_confidence_state == "trusted"
        and history_confidence_state != "trusted"
    ):
        reason_codes.insert(0, "current_value_trusted_history_untrusted")

    confidence_state = _max_confidence_state(
        [current_value_confidence_state, history_confidence_state]
    )
    visible = _sensitive_metrics_visible(confidence_state)
    return HistoryMetricVisibility(
        confidence_state=confidence_state,
        reason_codes=_dedupe_reason_codes(reason_codes),
        lifetime_pnl_visible=visible,
        period_performance_visible=visible,
    )
