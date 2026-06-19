# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.services.accounting_capital import (
    CapitalCashflow,
    CapitalCurrentValue,
    CapitalIssue,
    calculate_capital_truth,
)

AS_OF = datetime(2026, 4, 1, tzinfo=UTC)


def _cashflow(
    *,
    key: str,
    cashflow_type: str,
    capital_effect_usd: str | None,
    occurred_at: datetime,
    confidence_state: str = "trusted",
    status: str = "active",
    materiality_usd: str | None = None,
    review_task_id: str | None = None,
) -> CapitalCashflow:
    return CapitalCashflow(
        classification_key=key,
        cashflow_type=cashflow_type,
        capital_effect_usd=(
            Decimal(capital_effect_usd) if capital_effect_usd is not None else None
        ),
        occurred_at=occurred_at,
        confidence_state=confidence_state,
        status=status,
        materiality_usd=(
            Decimal(materiality_usd) if materiality_usd is not None else None
        ),
        review_task_id=review_task_id,
    )


def _trusted_current_value(value_usd: str = "1800") -> CapitalCurrentValue:
    return CapitalCurrentValue(
        value_usd=Decimal(value_usd),
        as_of=AS_OF,
        holdings_reconciled=True,
        broker_cash_reconciled=True,
        stablecoin_reserve_reconciled=True,
        position_existence_reconciled=True,
    )


def test_net_capital_lifetime_pnl_and_monthly_averages_use_external_cashflows() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value(),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
            _cashflow(
                key="deposit-2",
                cashflow_type="external_deposit",
                capital_effect_usd="500",
                occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
            ),
            _cashflow(
                key="withdrawal-1",
                cashflow_type="external_withdrawal",
                capital_effect_usd="-200",
                occurred_at=datetime(2026, 3, 1, tzinfo=UTC),
            ),
            _cashflow(
                key="internal-1",
                cashflow_type="not_external_cashflow",
                capital_effect_usd="0",
                occurred_at=datetime(2026, 2, 1, tzinfo=UTC),
            ),
        ],
        activity_dates=[
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 2, 1, tzinfo=UTC),
        ],
    )

    assert summary.gross_deposits_usd == Decimal("1500")
    assert summary.gross_withdrawals_usd == Decimal("200")
    assert summary.net_capital_at_work_usd == Decimal("1300")
    assert summary.current_portfolio_value_usd == Decimal("1800")
    assert summary.lifetime_pnl_usd == Decimal("500")
    assert summary.lifetime_pnl_usd != (
        summary.current_portfolio_value_usd - summary.gross_deposits_usd
    )
    assert summary.first_activity_date == datetime(2026, 1, 1, tzinfo=UTC)
    assert summary.elapsed_months == Decimal("3")
    assert summary.avg_gross_deposit_per_month_usd == Decimal("500")
    assert summary.avg_gross_withdrawal_per_month_usd == Decimal(
        "66.66666666666666666666666667"
    )
    assert summary.avg_net_capital_added_per_month_usd == Decimal(
        "433.3333333333333333333333333"
    )
    assert summary.confidence_state == "trusted"
    assert summary.reason_codes == ()


def test_missing_first_activity_date_hides_monthly_averages() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("0"),
        cashflows=[],
        activity_dates=[],
    )

    assert summary.first_activity_date is None
    assert summary.avg_gross_deposit_per_month_usd is None
    assert summary.avg_gross_withdrawal_per_month_usd is None
    assert summary.avg_net_capital_added_per_month_usd is None
    assert summary.confidence_state == "provisional"
    assert "missing_first_activity_date" in summary.reason_codes
    assert summary.lifetime_pnl_usd == Decimal("0")


def test_blocking_issue_hides_sensitive_stats_but_keeps_context_visible() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value(),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
        issues=[
            CapitalIssue(
                reason_code="unknown_outgoing_transfer",
                amount_usd=Decimal("50"),
                affected_metric_scopes=("lifetime_pnl", "period_performance"),
                severity="blocked",
                review_task_id="task_1",
            )
        ],
    )

    assert summary.gross_deposits_usd == Decimal("1000")
    assert summary.net_capital_at_work_usd == Decimal("1000")
    assert summary.lifetime_pnl_usd is None
    assert summary.return_pct is None
    assert summary.confidence_state == "blocked"
    assert summary.top_review_task_id == "task_1"
    assert "unknown_outgoing_transfer" in summary.reason_codes


def test_transfer_link_confidence_propagates_without_changing_capital() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("1000"),
        cashflows=[
            {
                "classification_key": "deposit-1",
                "cashflow_type": "external_deposit",
                "capital_effect_usd": Decimal("1000"),
                "occurred_at": datetime(2026, 1, 1, tzinfo=UTC),
                "confidence_state": "trusted",
                "status": "active",
            }
        ],
        transfer_links=[
            {
                "link_group_key": "transfer-1",
                "capital_effect_usd": Decimal("0"),
                "confidence_state": "warning",
                "status": "active",
                "review_task_id": "task_transfer_warning",
                "affected_metric_scopes": ("audit_context",),
                "reason_code": "transfer_link_warning",
            }
        ],
    )

    assert summary.gross_deposits_usd == Decimal("1000")
    assert summary.gross_withdrawals_usd == Decimal("0")
    assert summary.net_capital_at_work_usd == Decimal("1000")
    assert summary.confidence_state == "warning"
    assert "transfer_link_warning" in summary.reason_codes


@pytest.mark.parametrize(
    ("issue", "expected_state", "expected_reason"),
    [
        (
            CapitalIssue(
                reason_code="minor_note",
                amount_usd=Decimal("20"),
                affected_metric_scopes=("audit_context",),
            ),
            "warning",
            "minor_note",
        ),
        (
            CapitalIssue(
                reason_code="source_coverage_incomplete",
                amount_usd=Decimal("150"),
                affected_metric_scopes=("audit_context",),
            ),
            "provisional",
            "source_coverage_incomplete",
        ),
        (
            CapitalIssue(
                reason_code="semantic_decision_needed",
                amount_usd=Decimal("25"),
                affected_metric_scopes=("net_capital",),
                severity="review_required",
                review_task_id="task_review",
            ),
            "review_required",
            "semantic_decision_needed",
        ),
        (
            CapitalIssue(
                reason_code="large_unresolved_value",
                amount_usd=Decimal("600"),
                affected_metric_scopes=("audit_context",),
            ),
            "blocked",
            "large_unresolved_value",
        ),
    ],
)
def test_unresolved_issue_materiality_propagates_confidence_and_reason_codes(
    issue: CapitalIssue,
    expected_state: str,
    expected_reason: str,
) -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("10000"),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
        issues=[issue],
    )

    assert summary.confidence_state == expected_state
    assert expected_reason in summary.reason_codes


def test_review_required_audit_context_does_not_hide_lifetime_pnl() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("1500"),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
        issues=[
            CapitalIssue(
                reason_code="audit_context_review",
                amount_usd=Decimal("25"),
                affected_metric_scopes=("audit_context",),
                severity="review_required",
                review_task_id="task_audit",
            )
        ],
    )

    assert summary.confidence_state == "review_required"
    assert summary.lifetime_pnl_usd == Decimal("500")
    assert summary.return_pct == Decimal("50.0")
    assert summary.blocked_metric_scopes == ()
    assert summary.top_review_task_id == "task_audit"


def test_warning_threshold_uses_lower_or_boundary_not_maximum() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("1000000"),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
        issues=[
            CapitalIssue(
                reason_code="small_large_portfolio_issue",
                amount_usd=Decimal("50"),
                affected_metric_scopes=("audit_context",),
            )
        ],
    )

    assert summary.confidence_state == "warning"
    assert "small_large_portfolio_issue" in summary.reason_codes


def test_material_cashflow_confidence_blocks_sensitive_derived_stats() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("10000"),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                confidence_state="warning",
                materiality_usd="600",
                review_task_id="task_cashflow",
            ),
        ],
    )

    assert summary.gross_deposits_usd == Decimal("1000")
    assert summary.confidence_state == "blocked"
    assert summary.lifetime_pnl_usd is None
    assert summary.return_pct is None
    assert "lifetime_pnl" in summary.blocked_metric_scopes
    assert "period_performance" in summary.blocked_metric_scopes


def test_import_approval_scope_blocks_current_value_when_low_confidence() -> None:
    summary = calculate_capital_truth(
        current_value=_trusted_current_value("10000"),
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
        import_approvals=[
            {
                "approval_key": "approval-1",
                "status": "active",
                "confidence_state": "warning",
                "approved_scope": ("current_value", "cash_reserve"),
                "materiality_usd": Decimal("600"),
                "reason_code": "import_approval_cash_gap",
            }
        ],
    )

    assert summary.confidence_state == "blocked"
    assert summary.current_portfolio_value_usd == Decimal("10000")
    assert summary.lifetime_pnl_usd is None
    assert "current_value" in summary.blocked_metric_scopes
    assert "cash_reserve" in summary.blocked_metric_scopes
    assert "import_approval_cash_gap" in summary.reason_codes


@pytest.mark.parametrize(
    ("coverage_kwargs", "reason"),
    [
        ({"broker_cash_reconciled": False}, "broker_cash_unresolved"),
        ({"stablecoin_reserve_reconciled": False}, "stablecoin_reserve_unresolved"),
        ({"position_existence_reconciled": False}, "position_existence_unresolved"),
    ],
)
def test_unresolved_current_value_coverage_blocks_current_value_and_lifetime_pnl(
    coverage_kwargs: dict[str, bool],
    reason: str,
) -> None:
    current_value = _trusted_current_value()
    for key, value in coverage_kwargs.items():
        setattr(current_value, key, value)

    summary = calculate_capital_truth(
        current_value=current_value,
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="1000",
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ],
    )

    assert summary.current_portfolio_value_usd is None
    assert summary.lifetime_pnl_usd is None
    assert summary.return_pct is None
    assert summary.confidence_state == "blocked"
    assert reason in summary.reason_codes
    assert reason.removesuffix("_unresolved") in summary.blocked_metric_scopes
