# ruff: noqa: S101

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.accounting_capital import CapitalCashflow, CapitalIssue
from app.services.accounting_history import (
    ConfidenceState,
    HistoricalValueResult,
    HistoryReasonCode,
)
from app.services.accounting_performance import calculate_rolling_performance

AS_OF = datetime(2026, 6, 19, tzinfo=UTC)


@dataclass(frozen=True)
class PeriodIssue:
    reason_code: str
    affected_metric_scopes: tuple[str, ...]
    occurred_at: datetime
    severity: str = "blocked"
    status: str = "open"


def _boundary(
    *,
    as_of: datetime,
    value_usd: str | None,
    confidence_state: ConfidenceState = "trusted",
    reason_codes: tuple[HistoryReasonCode, ...] = ("exact_anchor",),
) -> HistoricalValueResult:
    return HistoricalValueResult(
        as_of=as_of,
        value_usd=Decimal(value_usd) if value_usd is not None else None,
        source="exact_anchor" if value_usd is not None else "unavailable",
        confidence_state=confidence_state,
        reason_codes=reason_codes,
        sensitive_metrics_visible=confidence_state in {"trusted", "warning"},
    )


def _period(summary, label: str):
    return next(period for period in summary.periods if period.label == label)


def test_missing_start_boundary_marks_period_provisional_without_gain() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(
                as_of=AS_OF - timedelta(days=30),
                value_usd=None,
                confidence_state="blocked",
                reason_codes=("missing_anchor",),
            ),
        ],
        cashflows=[],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.starting_value_usd is None
    assert period.ending_value_usd == Decimal("1100")
    assert period.investment_gain_usd is None
    assert period.confidence_state == "provisional"
    assert period.period_performance_visible is False
    assert "start_boundary_missing_anchor" in period.reason_codes


def test_low_confidence_end_boundary_degrades_period_confidence() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(
                as_of=AS_OF,
                value_usd="1100",
                confidence_state="provisional",
                reason_codes=("reconstructed_value", "missing_source_coverage"),
            ),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.investment_gain_usd == Decimal("100")
    assert period.confidence_state == "provisional"
    assert period.period_performance_visible is False
    assert "end_boundary_reconstructed_value" in period.reason_codes
    assert "end_boundary_missing_source_coverage" in period.reason_codes


def test_unresolved_cashflow_inside_period_blocks_trusted_performance() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[
            CapitalCashflow(
                classification_key="unknown-1",
                cashflow_type="unknown",
                capital_effect_usd=Decimal("75"),
                occurred_at=AS_OF - timedelta(days=8),
                confidence_state="blocked",
                status="active",
            )
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.investment_gain_usd is None
    assert period.confidence_state == "blocked"
    assert period.period_performance_visible is False
    assert "cashflow_confidence_blocked" in period.reason_codes


def test_material_low_confidence_cashflow_inside_period_blocks_performance() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[
            CapitalCashflow(
                classification_key="material-warning",
                cashflow_type="external_deposit",
                capital_effect_usd=Decimal("50"),
                occurred_at=AS_OF - timedelta(days=8),
                confidence_state="warning",
                status="active",
                materiality_usd=Decimal("75"),
            )
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.investment_gain_usd is None
    assert period.confidence_state == "blocked"
    assert period.period_performance_visible is False
    assert "cashflow_confidence_warning" in period.reason_codes


def test_accounting_issue_inside_period_blocks_period_performance_scope() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[],
        issues=[
            PeriodIssue(
                reason_code="unknown_outgoing_transfer",
                affected_metric_scopes=("period_performance",),
                occurred_at=AS_OF - timedelta(days=2),
            ),
            CapitalIssue(
                reason_code="old_lifetime_issue",
                amount_usd=Decimal("50"),
                affected_metric_scopes=("lifetime_pnl",),
            ),
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.investment_gain_usd is None
    assert period.confidence_state == "blocked"
    assert period.period_performance_visible is False
    assert period.reason_codes == ("unknown_outgoing_transfer",)


def test_period_performance_issue_blocks_even_with_warning_severity() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[],
        issues=[
            PeriodIssue(
                reason_code="warning_period_issue",
                affected_metric_scopes=("period_performance",),
                occurred_at=AS_OF - timedelta(days=2),
                severity="warning",
            )
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.investment_gain_usd is None
    assert period.confidence_state == "blocked"
    assert period.period_performance_visible is False
    assert period.reason_codes == ("warning_period_issue",)
