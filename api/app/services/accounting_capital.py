from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

CONFIDENCE_ORDER = {
    "trusted": 0,
    "warning": 1,
    "provisional": 2,
    "review_required": 3,
    "blocked": 4,
}

SENSITIVE_BLOCKING_SCOPES = {
    "current_value",
    "current_portfolio_value",
    "cash_reserve",
    "broker_cash",
    "stablecoin_reserve",
    "position_existence",
    "historical_coverage",
    "lifetime_pnl",
    "period_performance",
    "asset_level_lifetime_contribution",
    "asset_level_lifetime_pnl",
    "asset_lifetime_pnl",
}

DERIVED_STAT_SCOPES = {
    "current_value",
    "current_portfolio_value",
    "net_capital",
    "lifetime_pnl",
    "period_performance",
}

CASHFLOW_METRIC_SCOPES = ("net_capital", "lifetime_pnl", "period_performance")


@dataclass
class CapitalCashflow:
    classification_key: str
    cashflow_type: str
    capital_effect_usd: Decimal | None
    occurred_at: datetime
    confidence_state: str = "trusted"
    status: str = "active"
    materiality_usd: Decimal | None = None
    review_task_id: str | None = None


@dataclass
class CapitalCurrentValue:
    value_usd: Decimal | None
    as_of: datetime
    holdings_reconciled: bool
    broker_cash_reconciled: bool
    stablecoin_reserve_reconciled: bool
    position_existence_reconciled: bool
    confidence_state: str = "trusted"
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapitalIssue:
    reason_code: str
    amount_usd: Decimal | None
    affected_metric_scopes: tuple[str, ...] = ()
    severity: str | None = None
    review_task_id: str | None = None
    status: str = "open"


@dataclass(frozen=True)
class CapitalTruthSummary:
    gross_deposits_usd: Decimal
    gross_withdrawals_usd: Decimal
    net_capital_at_work_usd: Decimal
    current_portfolio_value_usd: Decimal | None
    lifetime_pnl_usd: Decimal | None
    return_pct: Decimal | None
    first_activity_date: datetime | None
    elapsed_months: Decimal | None
    avg_gross_deposit_per_month_usd: Decimal | None
    avg_gross_withdrawal_per_month_usd: Decimal | None
    avg_net_capital_added_per_month_usd: Decimal | None
    confidence_state: str
    reason_codes: tuple[str, ...]
    top_review_task_id: str | None = None
    blocked_metric_scopes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _ConfidenceImpact:
    state: str
    reason_code: str
    review_task_id: str | None = None
    blocked_scopes: tuple[str, ...] = ()


def calculate_capital_truth(
    *,
    current_value: CapitalCurrentValue | Any,
    cashflows: Sequence[CapitalCashflow | Any],
    transfer_links: Sequence[Any] | None = None,
    import_approvals: Sequence[Any] | None = None,
    cost_basis_decisions: Sequence[Any] | None = None,
    issues: Sequence[CapitalIssue | Any] | None = None,
    activity_dates: Sequence[datetime] | None = None,
) -> CapitalTruthSummary:
    active_cashflows = [
        cashflow
        for cashflow in cashflows
        if _attr(cashflow, "status", "active") == "active"
    ]
    gross_deposits = Decimal("0")
    gross_withdrawals = Decimal("0")
    impacts: list[_ConfidenceImpact] = []
    raw_current_value = _current_value_amount(current_value)

    for cashflow in active_cashflows:
        cashflow_type = str(_attr(cashflow, "cashflow_type", "")).lower()
        capital_effect = _decimal_or_none(_attr(cashflow, "capital_effect_usd", None))
        amount = capital_effect
        if amount is None:
            amount = _decimal_or_none(_attr(cashflow, "amount_usd", None))
        if cashflow_type == "external_deposit" and amount is not None:
            gross_deposits += abs(amount)
        elif cashflow_type == "external_withdrawal" and amount is not None:
            gross_withdrawals += abs(amount)
        else:
            continue

        cashflow_confidence = str(_attr(cashflow, "confidence_state", "trusted"))
        if cashflow_confidence != "trusted":
            threshold_state = _threshold_state(
                _cashflow_materiality(cashflow, amount),
                raw_current_value,
            )
            state = _max_confidence([cashflow_confidence, threshold_state])
            impacts.append(
                _ConfidenceImpact(
                    state=state,
                    reason_code=str(
                        _attr(
                            cashflow,
                            "reason_code",
                            f"cashflow_confidence_{cashflow_confidence}",
                        )
                    ),
                    review_task_id=_attr(cashflow, "review_task_id", None),
                    blocked_scopes=CASHFLOW_METRIC_SCOPES
                    if state == "blocked"
                    else (),
                )
            )

    net_capital = gross_deposits - gross_withdrawals
    portfolio_value = _trusted_current_value_or_none(current_value, impacts)
    threshold_value = portfolio_value or raw_current_value

    impacts.extend(
        _decision_impacts(
            transfer_links or (),
            default_reason_prefix="transfer_link",
            portfolio_value=threshold_value,
        )
    )
    impacts.extend(
        _decision_impacts(
            import_approvals or (),
            default_reason_prefix="import_approval",
            portfolio_value=threshold_value,
        )
    )
    impacts.extend(
        _decision_impacts(
            cost_basis_decisions or (),
            default_reason_prefix="cost_basis_decision",
            portfolio_value=threshold_value,
        )
    )

    issue_impacts = [
        _impact_for_issue(issue, threshold_value)
        for issue in (issues or [])
        if _attr(issue, "status", "open") == "open"
    ]
    impacts.extend(issue_impacts)

    first_activity = _first_activity_date(active_cashflows, activity_dates)
    elapsed_months = _elapsed_months(
        first_activity, _attr(current_value, "as_of", None)
    )
    if first_activity is None:
        impacts.append(
            _ConfidenceImpact(
                state="provisional",
                reason_code="missing_first_activity_date",
            )
        )

    confidence_state = _max_confidence(impact.state for impact in impacts)
    blocked_scopes = _blocked_scopes(impacts)
    derived_stats_allowed = not set(blocked_scopes).intersection(DERIVED_STAT_SCOPES)
    current_value_allowed = portfolio_value is not None

    lifetime_pnl = None
    return_pct = None
    if current_value_allowed and derived_stats_allowed:
        lifetime_pnl = portfolio_value - net_capital
        if net_capital != Decimal("0"):
            return_pct = lifetime_pnl / net_capital * Decimal("100")

    monthly_averages = _monthly_averages(
        elapsed_months=elapsed_months,
        gross_deposits=gross_deposits,
        gross_withdrawals=gross_withdrawals,
        net_capital=net_capital,
    )

    return CapitalTruthSummary(
        gross_deposits_usd=gross_deposits,
        gross_withdrawals_usd=gross_withdrawals,
        net_capital_at_work_usd=net_capital,
        current_portfolio_value_usd=portfolio_value,
        lifetime_pnl_usd=lifetime_pnl,
        return_pct=return_pct,
        first_activity_date=first_activity,
        elapsed_months=elapsed_months,
        avg_gross_deposit_per_month_usd=monthly_averages[0],
        avg_gross_withdrawal_per_month_usd=monthly_averages[1],
        avg_net_capital_added_per_month_usd=monthly_averages[2],
        confidence_state=confidence_state,
        reason_codes=_reason_codes(impacts),
        top_review_task_id=_top_review_task_id(impacts),
        blocked_metric_scopes=blocked_scopes,
    )


def _trusted_current_value_or_none(
    current_value: CapitalCurrentValue | Any,
    impacts: list[_ConfidenceImpact],
) -> Decimal | None:
    value = _current_value_amount(current_value)
    if value is None:
        impacts.append(
            _ConfidenceImpact(
                state="blocked",
                reason_code="missing_current_value",
                blocked_scopes=("current_value", "lifetime_pnl"),
            )
        )
        return None

    coverage_reasons = {
        "holdings_reconciled": ("holdings_unresolved", ("current_value",)),
        "broker_cash_reconciled": (
            "broker_cash_unresolved",
            ("current_value", "broker_cash", "cash_reserve", "lifetime_pnl"),
        ),
        "stablecoin_reserve_reconciled": (
            "stablecoin_reserve_unresolved",
            ("current_value", "stablecoin_reserve", "cash_reserve", "lifetime_pnl"),
        ),
        "position_existence_reconciled": (
            "position_existence_unresolved",
            ("current_value", "position_existence", "lifetime_pnl"),
        ),
    }
    unresolved = [
        coverage
        for attr_name, coverage in coverage_reasons.items()
        if not bool(_attr(current_value, attr_name, False))
    ]
    for reason, scopes in unresolved:
        impacts.append(
            _ConfidenceImpact(
                state="blocked",
                reason_code=reason,
                blocked_scopes=(*scopes, "period_performance"),
            )
        )
    confidence_state = str(_attr(current_value, "confidence_state", "trusted"))
    if confidence_state != "trusted":
        impacts.append(
            _ConfidenceImpact(
                state=confidence_state,
                reason_code=f"current_value_confidence_{confidence_state}",
                blocked_scopes=("current_value", "lifetime_pnl")
                if confidence_state in {"review_required", "blocked"}
                else (),
            )
        )
    for reason in _attr(current_value, "reason_codes", ()) or ():
        impacts.append(
            _ConfidenceImpact(
                state=confidence_state,
                reason_code=str(reason),
                blocked_scopes=("current_value", "lifetime_pnl")
                if confidence_state in {"review_required", "blocked"}
                else (),
            )
        )
    if unresolved or confidence_state in {"review_required", "blocked"}:
        return None
    return value


def _impact_for_issue(
    issue: CapitalIssue | Any,
    portfolio_value: Decimal | None,
) -> _ConfidenceImpact:
    scopes = tuple(
        str(scope) for scope in (_attr(issue, "affected_metric_scopes", ()) or ())
    )
    explicit_severity = _attr(issue, "severity", None)
    threshold_state = _threshold_state(
        _decimal_or_none(_attr(issue, "amount_usd", None)), portfolio_value
    )
    state = _max_confidence(
        state
        for state in (
            str(explicit_severity) if explicit_severity else None,
            threshold_state,
        )
        if state is not None
    )
    if set(scopes).intersection(SENSITIVE_BLOCKING_SCOPES):
        state = _max_confidence([state, "blocked"])
    blocked_scopes = scopes if state == "blocked" else ()
    return _ConfidenceImpact(
        state=state,
        reason_code=str(_attr(issue, "reason_code", "unresolved_accounting_issue")),
        review_task_id=_attr(issue, "review_task_id", None),
        blocked_scopes=blocked_scopes,
    )


def _decision_impacts(
    records: Sequence[Any],
    *,
    default_reason_prefix: str,
    portfolio_value: Decimal | None,
) -> list[_ConfidenceImpact]:
    impacts: list[_ConfidenceImpact] = []
    for record in records:
        if _attr(record, "status", "active") != "active":
            continue
        confidence_state = str(_attr(record, "confidence_state", "trusted"))
        if confidence_state == "trusted":
            continue
        scopes = _record_scopes(record)
        threshold_state = _threshold_state(_record_materiality(record), portfolio_value)
        state = _max_confidence([confidence_state, threshold_state])
        if set(scopes).intersection(SENSITIVE_BLOCKING_SCOPES):
            state = _max_confidence([state, "blocked"])
        impacts.append(
            _ConfidenceImpact(
                state=state,
                reason_code=str(
                    _attr(
                        record,
                        "reason_code",
                        f"{default_reason_prefix}_confidence_{confidence_state}",
                    )
                ),
                review_task_id=_attr(record, "review_task_id", None),
                blocked_scopes=scopes
                if state == "blocked"
                else (),
            )
        )
    return impacts


def _cashflow_materiality(
    cashflow: CapitalCashflow | Any,
    amount: Decimal | None,
) -> Decimal | None:
    materiality = _decimal_or_none(_attr(cashflow, "materiality_usd", None))
    if materiality is not None:
        return abs(materiality)
    return abs(amount) if amount is not None else None


def _record_scopes(record: Any) -> tuple[str, ...]:
    scopes = _attr(record, "affected_metric_scopes", None)
    if scopes is None:
        scopes = _attr(record, "approved_scope", None)
    return tuple(str(scope) for scope in (scopes or ()))


def _record_materiality(record: Any) -> Decimal | None:
    for attr_name in ("materiality_usd", "amount_usd", "cost_basis_usd"):
        value = _decimal_or_none(_attr(record, attr_name, None))
        if value is not None:
            return abs(value)
    return None


def _threshold_state(
    amount_usd: Decimal | None,
    portfolio_value: Decimal | None,
) -> str:
    if amount_usd is None:
        return "trusted"
    amount = abs(amount_usd)
    if portfolio_value is None:
        return "provisional" if amount > Decimal("0") else "trusted"
    warning_absolute = Decimal("10")
    warning_relative = portfolio_value * Decimal("0.0001")
    provisional_threshold = max(Decimal("100"), portfolio_value * Decimal("0.01"))
    blocked_threshold = portfolio_value * Decimal("0.05")
    if amount > blocked_threshold:
        return "blocked"
    if amount > provisional_threshold:
        return "provisional"
    if amount > warning_absolute or amount > warning_relative:
        return "warning"
    return "trusted"


def _first_activity_date(
    cashflows: Sequence[CapitalCashflow | Any],
    activity_dates: Sequence[datetime] | None,
) -> datetime | None:
    dates = list(activity_dates or [])
    dates.extend(
        occurred_at
        for cashflow in cashflows
        if (occurred_at := _attr(cashflow, "occurred_at", None)) is not None
    )
    if not dates:
        return None
    return min(dates)


def _elapsed_months(
    first_activity: datetime | None, as_of: datetime | None
) -> Decimal | None:
    if first_activity is None or as_of is None or as_of <= first_activity:
        return None
    whole_months = (
        (as_of.year - first_activity.year) * 12 + as_of.month - first_activity.month
    )
    if as_of.day < first_activity.day:
        whole_months -= 1
    if whole_months <= 0:
        elapsed_days = Decimal((as_of - first_activity).days)
        return elapsed_days / Decimal("30") if elapsed_days > 0 else None
    return Decimal(whole_months)


def _monthly_averages(
    *,
    elapsed_months: Decimal | None,
    gross_deposits: Decimal,
    gross_withdrawals: Decimal,
    net_capital: Decimal,
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if elapsed_months is None or elapsed_months <= Decimal("0"):
        return None, None, None
    return (
        gross_deposits / elapsed_months,
        gross_withdrawals / elapsed_months,
        net_capital / elapsed_months,
    )


def _max_confidence(states: Iterable[str]) -> str:
    max_state = "trusted"
    for state in states:
        if CONFIDENCE_ORDER[state] > CONFIDENCE_ORDER[max_state]:
            max_state = state
    return max_state


def _reason_codes(impacts: Sequence[_ConfidenceImpact]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(impact.reason_code for impact in impacts))


def _blocked_scopes(impacts: Sequence[_ConfidenceImpact]) -> tuple[str, ...]:
    scopes: list[str] = []
    for impact in impacts:
        scopes.extend(impact.blocked_scopes)
    return tuple(dict.fromkeys(scopes))


def _top_review_task_id(impacts: Sequence[_ConfidenceImpact]) -> str | None:
    ranked = sorted(
        (
            impact
            for impact in impacts
            if impact.review_task_id is not None
            and impact.state in {"review_required", "blocked"}
        ),
        key=lambda impact: CONFIDENCE_ORDER[impact.state],
        reverse=True,
    )
    if not ranked:
        return None
    return ranked[0].review_task_id


def _current_value_amount(current_value: CapitalCurrentValue | Any) -> Decimal | None:
    return _decimal_or_none(_attr(current_value, "value_usd", None))


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
