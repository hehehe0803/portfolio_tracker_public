# ruff: noqa: S101

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.accounting_capital import CapitalCashflow
from app.services.accounting_history import (
    ConfidenceState,
    HistoricalValueResult,
    HistoryReasonCode,
)
from app.services.accounting_performance import calculate_rolling_performance

AS_OF = datetime(2026, 6, 19, tzinfo=UTC)


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


def _cashflow(
    *,
    key: str,
    cashflow_type: str,
    capital_effect_usd: str,
    occurred_at: datetime,
    confidence_state: str = "trusted",
    status: str = "active",
    materiality_usd: str | None = None,
) -> CapitalCashflow:
    return CapitalCashflow(
        classification_key=key,
        cashflow_type=cashflow_type,
        capital_effect_usd=Decimal(capital_effect_usd),
        occurred_at=occurred_at,
        confidence_state=confidence_state,
        status=status,
        materiality_usd=(
            Decimal(materiality_usd) if materiality_usd is not None else None
        ),
    )


def _period(summary, label: str):
    return next(period for period in summary.periods if period.label == label)


def test_rolling_periods_are_available_with_30d_default() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(as_of=AS_OF - timedelta(days=7), value_usd="1070"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
            _boundary(as_of=AS_OF - timedelta(days=90), value_usd="800"),
        ],
        cashflows=[],
    )

    assert summary.default_period_label == "30D"
    assert [period.label for period in summary.periods] == ["7D", "30D", "90D"]
    assert _period(summary, "7D").investment_gain_usd == Decimal("30")
    assert _period(summary, "30D").investment_gain_usd == Decimal("100")
    assert _period(summary, "90D").investment_gain_usd == Decimal("300")


def test_deposit_inside_period_is_not_counted_as_investment_gain() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1500"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[
            _cashflow(
                key="deposit-1",
                cashflow_type="external_deposit",
                capital_effect_usd="400",
                occurred_at=AS_OF - timedelta(days=10),
            )
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.starting_value_usd == Decimal("1000")
    assert period.ending_value_usd == Decimal("1500")
    assert period.deposits_usd == Decimal("400")
    assert period.withdrawals_usd == Decimal("0")
    assert period.investment_gain_usd == Decimal("100")
    assert period.confidence_state == "trusted"
    assert period.reason_codes == ()


def test_withdrawal_inside_period_is_not_counted_as_investment_loss() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="900"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[
            _cashflow(
                key="withdrawal-1",
                cashflow_type="external_withdrawal",
                capital_effect_usd="-250",
                occurred_at=AS_OF - timedelta(days=12),
            )
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.deposits_usd == Decimal("0")
    assert period.withdrawals_usd == Decimal("250")
    assert period.investment_gain_usd == Decimal("150")
    assert period.confidence_state == "trusted"


def test_cashflows_outside_period_do_not_affect_period_gain() -> None:
    summary = calculate_rolling_performance(
        as_of=AS_OF,
        boundary_values=[
            _boundary(as_of=AS_OF, value_usd="1100"),
            _boundary(as_of=AS_OF - timedelta(days=30), value_usd="1000"),
        ],
        cashflows=[
            _cashflow(
                key="old-deposit",
                cashflow_type="external_deposit",
                capital_effect_usd="800",
                occurred_at=AS_OF - timedelta(days=31),
            ),
            _cashflow(
                key="future-withdrawal",
                cashflow_type="external_withdrawal",
                capital_effect_usd="-50",
                occurred_at=AS_OF + timedelta(days=1),
            ),
        ],
        periods_days=(30,),
    )

    period = _period(summary, "30D")

    assert period.deposits_usd == Decimal("0")
    assert period.withdrawals_usd == Decimal("0")
    assert period.investment_gain_usd == Decimal("100")
