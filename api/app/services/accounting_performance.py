from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from app.services.accounting_history import ConfidenceState, HistoricalValueResult

_CONFIDENCE_RANK: dict[str, int] = {
    "trusted": 0,
    "warning": 1,
    "provisional": 2,
    "review_required": 3,
    "blocked": 4,
}

_VISIBLE_CONFIDENCE_STATES = {"trusted", "warning"}
_DEFAULT_PERIOD_DAYS = (7, 30, 90)
_EXACT_ANCHOR_REASON = "exact_anchor"


@dataclass(frozen=True)
class RollingPerformancePeriod:
    label: str
    days: int
    start_at: datetime
    end_at: datetime
    starting_value_usd: Decimal | None
    ending_value_usd: Decimal | None
    deposits_usd: Decimal
    withdrawals_usd: Decimal
    investment_gain_usd: Decimal | None
    confidence_state: ConfidenceState
    reason_codes: tuple[str, ...]
    start_boundary_confidence_state: ConfidenceState
    end_boundary_confidence_state: ConfidenceState
    period_performance_visible: bool


@dataclass(frozen=True)
class RollingPerformanceSummary:
    as_of: datetime
    default_period_label: str
    periods: tuple[RollingPerformancePeriod, ...]

    @property
    def default_period(self) -> RollingPerformancePeriod | None:
        for period in self.periods:
            if period.label == self.default_period_label:
                return period
        return None


@dataclass(frozen=True)
class _BoundaryImpact:
    value_usd: Decimal | None
    confidence_state: ConfidenceState
    effective_confidence_state: ConfidenceState
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class _PeriodCashflows:
    deposits_usd: Decimal
    withdrawals_usd: Decimal
    confidence_states: tuple[ConfidenceState, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class _IssueImpact:
    confidence_state: ConfidenceState
    reason_code: str


def calculate_rolling_performance(
    *,
    as_of: datetime,
    boundary_values: Sequence[HistoricalValueResult],
    cashflows: Sequence[Any],
    issues: Sequence[Any] | None = None,
    periods_days: Sequence[int] = _DEFAULT_PERIOD_DAYS,
    default_period_days: int = 30,
) -> RollingPerformanceSummary:
    boundaries = _boundary_lookup(boundary_values)
    periods = tuple(
        _calculate_period(
            as_of=as_of,
            days=days,
            boundaries=boundaries,
            cashflows=cashflows,
            issues=issues or (),
        )
        for days in periods_days
    )
    return RollingPerformanceSummary(
        as_of=as_of,
        default_period_label=_period_label(default_period_days),
        periods=periods,
    )


def _calculate_period(
    *,
    as_of: datetime,
    days: int,
    boundaries: dict[datetime, HistoricalValueResult],
    cashflows: Sequence[Any],
    issues: Sequence[Any],
) -> RollingPerformancePeriod:
    start_at = as_of - timedelta(days=days)
    start_boundary = _boundary_impact(
        boundary=boundaries.get(start_at),
        prefix="start_boundary",
    )
    end_boundary = _boundary_impact(
        boundary=boundaries.get(as_of),
        prefix="end_boundary",
    )
    period_cashflows = _period_cashflows(
        start_at=start_at,
        end_at=as_of,
        cashflows=cashflows,
    )
    issue_impacts = _period_issue_impacts(
        start_at=start_at,
        end_at=as_of,
        issues=issues,
    )

    confidence_state = _max_confidence_state(
        (
            start_boundary.effective_confidence_state,
            end_boundary.effective_confidence_state,
            *period_cashflows.confidence_states,
            *(impact.confidence_state for impact in issue_impacts),
        )
    )
    reason_codes = _dedupe_reason_codes(
        (
            *start_boundary.reason_codes,
            *end_boundary.reason_codes,
            *period_cashflows.reason_codes,
            *(impact.reason_code for impact in issue_impacts),
        )
    )
    investment_gain = _investment_gain_or_none(
        start_value=start_boundary.value_usd,
        end_value=end_boundary.value_usd,
        deposits=period_cashflows.deposits_usd,
        withdrawals=period_cashflows.withdrawals_usd,
        confidence_state=confidence_state,
    )

    return RollingPerformancePeriod(
        label=_period_label(days),
        days=days,
        start_at=start_at,
        end_at=as_of,
        starting_value_usd=start_boundary.value_usd,
        ending_value_usd=end_boundary.value_usd,
        deposits_usd=period_cashflows.deposits_usd,
        withdrawals_usd=period_cashflows.withdrawals_usd,
        investment_gain_usd=investment_gain,
        confidence_state=confidence_state,
        reason_codes=reason_codes,
        start_boundary_confidence_state=start_boundary.confidence_state,
        end_boundary_confidence_state=end_boundary.confidence_state,
        period_performance_visible=(
            investment_gain is not None
            and confidence_state in _VISIBLE_CONFIDENCE_STATES
        ),
    )


def _boundary_lookup(
    boundary_values: Sequence[HistoricalValueResult],
) -> dict[datetime, HistoricalValueResult]:
    return {boundary.as_of: boundary for boundary in boundary_values}


def _boundary_impact(
    *,
    boundary: HistoricalValueResult | None,
    prefix: str,
) -> _BoundaryImpact:
    if boundary is None:
        return _BoundaryImpact(
            value_usd=None,
            confidence_state="provisional",
            effective_confidence_state="provisional",
            reason_codes=(f"{prefix}_missing_anchor",),
        )

    confidence_state = boundary.confidence_state
    effective_confidence_state = _effective_boundary_confidence(boundary)
    reason_codes: tuple[str, ...] = ()
    if effective_confidence_state != "trusted" or boundary.value_usd is None:
        reason_codes = tuple(
            f"{prefix}_{reason_code}"
            for reason_code in boundary.reason_codes
            if reason_code != _EXACT_ANCHOR_REASON
        )
        if not reason_codes:
            reason_codes = (f"{prefix}_confidence_{confidence_state}",)

    return _BoundaryImpact(
        value_usd=boundary.value_usd,
        confidence_state=confidence_state,
        effective_confidence_state=effective_confidence_state,
        reason_codes=reason_codes,
    )


def _effective_boundary_confidence(
    boundary: HistoricalValueResult,
) -> ConfidenceState:
    if boundary.value_usd is not None:
        return boundary.confidence_state
    if "missing_anchor" in boundary.reason_codes:
        return "provisional"
    return _max_confidence_state(("provisional", boundary.confidence_state))


def _period_cashflows(
    *,
    start_at: datetime,
    end_at: datetime,
    cashflows: Sequence[Any],
) -> _PeriodCashflows:
    deposits = Decimal("0")
    withdrawals = Decimal("0")
    confidence_states: list[ConfidenceState] = []
    reason_codes: list[str] = []

    for cashflow in cashflows:
        if _attr(cashflow, "status", "active") != "active":
            continue
        occurred_at = _attr(cashflow, "occurred_at", None)
        if not _is_inside_period(occurred_at, start_at=start_at, end_at=end_at):
            continue

        cashflow_type = str(_attr(cashflow, "cashflow_type", "")).lower()
        amount = _decimal_or_none(_attr(cashflow, "capital_effect_usd", None))
        if amount is None:
            amount = _decimal_or_none(_attr(cashflow, "amount_usd", None))

        confidence_state = _coerce_confidence_state(
            str(_attr(cashflow, "confidence_state", "trusted"))
        )
        if confidence_state != "trusted":
            confidence_states.append(confidence_state)
            reason_codes.append(
                str(
                    _attr(
                        cashflow,
                        "reason_code",
                        f"cashflow_confidence_{confidence_state}",
                    )
                )
            )

        if cashflow_type == "external_deposit":
            if amount is None:
                confidence_states.append("blocked")
                reason_codes.append("missing_cashflow_amount")
                continue
            deposits += abs(amount)
        elif cashflow_type == "external_withdrawal":
            if amount is None:
                confidence_states.append("blocked")
                reason_codes.append("missing_cashflow_amount")
                continue
            withdrawals += abs(amount)

    return _PeriodCashflows(
        deposits_usd=deposits,
        withdrawals_usd=withdrawals,
        confidence_states=tuple(confidence_states),
        reason_codes=_dedupe_reason_codes(reason_codes),
    )


def _period_issue_impacts(
    *,
    start_at: datetime,
    end_at: datetime,
    issues: Sequence[Any],
) -> tuple[_IssueImpact, ...]:
    impacts: list[_IssueImpact] = []
    for issue in issues:
        if _attr(issue, "status", "open") != "open":
            continue
        scopes = tuple(
            str(scope) for scope in (_attr(issue, "affected_metric_scopes", ()) or ())
        )
        if "period_performance" not in scopes:
            continue
        occurred_at = _attr(issue, "occurred_at", None)
        if occurred_at is not None and not _is_inside_period(
            occurred_at,
            start_at=start_at,
            end_at=end_at,
        ):
            continue
        impacts.append(
            _IssueImpact(
                confidence_state=_issue_confidence_state(issue),
                reason_code=str(
                    _attr(issue, "reason_code", "unresolved_accounting_issue")
                ),
            )
        )
    return tuple(impacts)


def _issue_confidence_state(issue: Any) -> ConfidenceState:
    for attr_name in ("severity", "confidence_state"):
        state = _attr(issue, attr_name, None)
        if state is not None:
            return _coerce_confidence_state(str(state))
    return "blocked"


def _investment_gain_or_none(
    *,
    start_value: Decimal | None,
    end_value: Decimal | None,
    deposits: Decimal,
    withdrawals: Decimal,
    confidence_state: ConfidenceState,
) -> Decimal | None:
    if start_value is None or end_value is None:
        return None
    if confidence_state in {"review_required", "blocked"}:
        return None
    return end_value - start_value - deposits + withdrawals


def _is_inside_period(
    occurred_at: Any,
    *,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    return isinstance(occurred_at, datetime) and start_at < occurred_at <= end_at


def _period_label(days: int) -> str:
    return f"{days}D"


def _max_confidence_state(states: Iterable[ConfidenceState]) -> ConfidenceState:
    max_state: ConfidenceState = "trusted"
    for state in states:
        if _CONFIDENCE_RANK[state] > _CONFIDENCE_RANK[max_state]:
            max_state = state
    return max_state


def _coerce_confidence_state(state: str) -> ConfidenceState:
    if state in _CONFIDENCE_RANK:
        return cast(ConfidenceState, state)
    return "blocked"


def _dedupe_reason_codes(reason_codes: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reason_codes))


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _attr(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)
