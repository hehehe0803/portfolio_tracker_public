"""
Portfolio endpoints: summary, holdings list, transaction history.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from redis import RedisError
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.db.models import (
    AccountingCostBasisDecision,
    AccountingExternalCashflowClassification,
    AccountingImportApproval,
    AccountingReconciliationTask,
    AccountingTransferLink,
    Asset,
    BenchmarkQuote,
    PendingOrder,
    PositionSnapshot,
    Transaction,
)
from app.services import accounting_review, analytics, pricing, scheduler_jobs
from app.services.accounting_capital import (
    CapitalCurrentValue,
    calculate_capital_truth,
)
from app.services.accounting_distribution import (
    DistributionCurrentValue,
    DistributionHolding,
    calculate_asset_type_distribution,
)
from app.services.accounting_history import ConfidenceState, HistoricalValueResult
from app.services.accounting_holding_drivers import (
    HoldingDriver,
    HoldingDriverInput,
    calculate_holding_drivers,
)
from app.services.accounting_performance import calculate_rolling_performance
from app.services.portfolio_state import (
    EMPTY_PORTFOLIO_BENCHMARK_SYMBOL,
    EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
)
from shared.python.contracts import (
    AccountingReviewTask,
    AssetCurrentPosition,
    AssetDetailContract,
    AssetDriverExplanation,
    AssetLifetimeContribution,
    AssetRecentMovement,
    CashReserveContract,
    DashboardContract,
    DashboardLifetimeSummary,
    DashboardRollingPeriod,
    DistributionBucketContract,
    HoldingDriverContract,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_DASHBOARD_PERIOD_DAYS = 30
_STABLECOIN_SYMBOLS = {"USDT", "USDC", "BUSD", "FDUSD", "DAI"}
_FIAT_CASH_SYMBOLS = {"USD", "EUR", "GBP", "CHF", "JPY"}
_CONFIDENCE_RANK: dict[ConfidenceState, int] = {
    "trusted": 0,
    "warning": 1,
    "provisional": 2,
    "review_required": 3,
    "blocked": 4,
}
_SENSITIVE_ASSET_LIFETIME_SCOPES = {
    "asset_level_lifetime_contribution",
    "asset_level_lifetime_pnl",
    "asset_lifetime_pnl",
    "cost_basis",
    "lifetime_pnl",
    "period_performance",
    "unrealized_pnl",
}
_SENSITIVE_ASSET_POSITION_PNL_SCOPES = {
    "cost_basis",
    "current_position_pnl",
    "position_pnl",
    "unrealized_pnl",
}
_SENSITIVE_ASSET_COST_BASIS_SCOPES = {"cost_basis"}
_HOLDING_DRIVER_BLOCKING_SCOPES = {
    "cost_basis",
    "current_value",
    "period_performance",
    "position_existence",
    "unrealized_pnl",
}
_CURRENT_VALUE_SCOPES = {"current_value", "current_portfolio_value"}
_SEVERE_REVIEW_STATES = {"review_required", "blocked"}


class PortfolioStateRefreshRequest(BaseModel):
    captured_at: datetime | None = None


def _jsonify_decimal_payload(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _jsonify_decimal_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonify_decimal_payload(item) for item in value]
    return value


def _freshness_metadata(
    *,
    source: str,
    as_of: datetime | str | None,
    stale: bool = False,
    degraded: bool = False,
    fallback: bool = False,
    warnings: list[str] | None = None,
) -> dict:
    if isinstance(as_of, datetime):
        as_of_value = as_of.isoformat()
    else:
        as_of_value = as_of
    return {
        "source": source,
        "as_of": as_of_value,
        "stale": stale,
        "degraded": degraded,
        "fallback": fallback,
        "warnings": warnings or [],
    }


def _current_value_freshness(
    *,
    symbol: str,
    price_present: bool,
    as_of: datetime,
) -> dict:
    if price_present:
        return _freshness_metadata(source="live_price_provider", as_of=as_of)
    warning = f"{symbol} has no current price metadata"
    return _freshness_metadata(
        source="missing_price",
        as_of=as_of,
        stale=True,
        degraded=True,
        warnings=[warning],
    )


async def _latest_snapshot_current_value_usd(db: DBSession) -> Decimal | None:
    captured_at = await db.scalar(select(func.max(PositionSnapshot.captured_at)))
    if captured_at is None:
        return None
    total = await db.scalar(
        select(func.sum(PositionSnapshot.current_value_usd))
        .join(Asset, Asset.id == PositionSnapshot.asset_id)
        .where(
            PositionSnapshot.captured_at == captured_at,
            PositionSnapshot.current_value_usd.is_not(None),
            Asset.symbol != EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
        )
    )
    return total if total is not None else Decimal("0")


async def _compose_dashboard_contract(db: DBSession) -> DashboardContract:
    latest_captured_at, latest_rows = await _latest_position_snapshot_state(db)
    as_of = latest_captured_at or _snapshot_as_of(latest_rows)
    current_value_usd = _sum_current_value_usd(
        latest_rows,
        empty_value_when_captured=latest_captured_at is not None,
    )
    task_rows = await _open_accounting_task_rows(db)
    review_queue = await accounting_review.list_open_accounting_review_tasks(db)
    issues = _issue_records(task_rows)
    cashflows = await _active_accounting_rows(
        db, AccountingExternalCashflowClassification
    )

    capital_current_value = _capital_current_value(
        current_value_usd=current_value_usd,
        as_of=as_of,
        open_tasks=task_rows,
    )
    capital_summary = calculate_capital_truth(
        current_value=capital_current_value,
        cashflows=cashflows,
        transfer_links=await _active_accounting_rows(db, AccountingTransferLink),
        import_approvals=await _active_accounting_rows(db, AccountingImportApproval),
        cost_basis_decisions=await _active_accounting_rows(
            db, AccountingCostBasisDecision
        ),
        issues=issues,
        activity_dates=[cashflow.occurred_at for cashflow in cashflows],
    )

    distribution_summary = calculate_asset_type_distribution(
        current_value=_distribution_current_value(
            current_value_usd=current_value_usd,
            as_of=as_of,
            open_tasks=task_rows,
        ),
        holdings=_distribution_holdings(latest_rows),
    )

    performance = calculate_rolling_performance(
        as_of=as_of,
        boundary_values=[
            await _historical_boundary(
                db,
                as_of - timedelta(days=_DASHBOARD_PERIOD_DAYS),
            ),
            await _historical_boundary(db, as_of),
        ],
        cashflows=cashflows,
        issues=issues,
        periods_days=(_DASHBOARD_PERIOD_DAYS,),
        default_period_days=_DASHBOARD_PERIOD_DAYS,
    )
    driver_summary = calculate_holding_drivers(
        as_of=as_of,
        holdings=await _holding_driver_inputs(
            db,
            latest_rows,
            as_of=as_of,
            cashflows=cashflows,
            open_tasks=task_rows,
        ),
        periods_days=(_DASHBOARD_PERIOD_DAYS,),
        default_period_days=_DASHBOARD_PERIOD_DAYS,
        max_drivers_per_period=5,
    )
    driver_period = driver_summary.default_period
    rolling_30d = _rolling_period_contract(performance.default_period, as_of=as_of)
    lifetime = DashboardLifetimeSummary(
        gross_contributions_usd=capital_summary.gross_deposits_usd,
        gross_withdrawals_usd=capital_summary.gross_withdrawals_usd,
        net_capital_at_work_usd=capital_summary.net_capital_at_work_usd,
        lifetime_pnl_usd=capital_summary.lifetime_pnl_usd,
        return_pct=capital_summary.return_pct,
        confidence_state=capital_summary.confidence_state,
        reason_codes=list(capital_summary.reason_codes),
        visible=capital_summary.lifetime_pnl_usd is not None,
    )
    confidence_state = _max_confidence_state(
        [
            capital_summary.confidence_state,
            distribution_summary.confidence_state,
            rolling_30d.confidence_state,
            driver_period.confidence_state if driver_period else "trusted",
        ]
    )
    reason_codes = _dedupe(
        [
            *capital_summary.reason_codes,
            *distribution_summary.reason_codes,
            *rolling_30d.reason_codes,
            *(driver_period.reason_codes if driver_period else ()),
        ]
    )
    return DashboardContract(
        as_of=as_of,
        current_total_value_usd=capital_summary.current_portfolio_value_usd,
        rolling_30d=rolling_30d,
        lifetime=lifetime,
        confidence_state=confidence_state,
        reason_codes=reason_codes,
        blocked_metric_scopes=list(capital_summary.blocked_metric_scopes),
        asset_type_distribution=[
            DistributionBucketContract(
                asset_type=bucket.asset_type,
                value_usd=bucket.value_usd,
                percentage=bucket.percentage,
                percentage_state=bucket.percentage_state,
                confidence_state=bucket.confidence_state,
                reason_codes=list(bucket.reason_codes),
            )
            for bucket in distribution_summary.asset_type_buckets
        ],
        cash_reserve=CashReserveContract(
            stablecoin_usd=distribution_summary.cash_reserve.stablecoin_usd,
            broker_cash_usd=distribution_summary.cash_reserve.broker_cash_usd,
            other_tracked_cash_usd=(
                distribution_summary.cash_reserve.other_tracked_cash_usd
            ),
            total_usd=distribution_summary.cash_reserve.total_usd,
            confidence_state=distribution_summary.cash_reserve.confidence_state,
            reason_codes=list(distribution_summary.cash_reserve.reason_codes),
        ),
        holding_drivers=[
            _holding_driver_contract(driver)
            for driver in (driver_period.drivers if driver_period else ())
        ],
        top_reconciliation_action=_top_reconciliation_action(
            review_queue.tasks,
            preferred_task_id=capital_summary.top_review_task_id,
        ),
    )


async def _compose_asset_detail_contract(
    db: DBSession,
    symbol: str,
) -> AssetDetailContract:
    normalized_symbol = symbol.upper()
    latest_row = await _latest_position_snapshot_row(db, normalized_symbol)
    if latest_row is None:
        raise HTTPException(status_code=404, detail="asset position not found")

    snapshot, asset = latest_row
    latest_rows = await _latest_position_snapshot_rows(db)
    review_queue = await accounting_review.list_open_accounting_review_tasks(db)
    trust_blockers = [
        task
        for task in review_queue.tasks
        if task.status == "open" and task.asset_symbol.upper() == normalized_symbol
    ]
    driver = await _asset_holding_driver(
        db,
        normalized_symbol,
        as_of=snapshot.captured_at,
    )
    return AssetDetailContract(
        symbol=asset.symbol,
        asset_type=asset.asset_type,
        as_of=snapshot.captured_at,
        current_position=_asset_current_position(
            snapshot,
            trust_blockers=trust_blockers,
        ),
        capital_allocated_usd=_asset_capital_allocated_usd(
            snapshot,
            trust_blockers=trust_blockers,
        ),
        lifetime=await _asset_lifetime_contribution(
            db,
            symbol=normalized_symbol,
            latest_rows=latest_rows,
            trust_blockers=trust_blockers,
        ),
        recent_movement=_asset_recent_movement(driver),
        driver_explanation=_asset_driver_explanation(driver),
        trust_blockers=trust_blockers,
    )


async def _latest_position_snapshot_rows(db: DBSession) -> list[tuple[Any, Any]]:
    _captured_at, rows = await _latest_position_snapshot_state(db)
    return rows


async def _latest_position_snapshot_state(
    db: DBSession,
) -> tuple[datetime | None, list[tuple[Any, Any]]]:
    captured_at = await db.scalar(select(func.max(PositionSnapshot.captured_at)))
    if captured_at is None:
        return None, []
    return captured_at, await _position_snapshot_rows_at(db, captured_at)


async def _latest_position_snapshot_row(
    db: DBSession,
    symbol: str,
) -> tuple[Any, Any] | None:
    captured_at = await db.scalar(select(func.max(PositionSnapshot.captured_at)))
    if captured_at is None:
        return None
    row = await db.execute(
        select(PositionSnapshot, Asset)
        .join(Asset, Asset.id == PositionSnapshot.asset_id)
        .where(
            PositionSnapshot.captured_at == captured_at,
            Asset.symbol == symbol,
            Asset.symbol != EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
        )
    )
    return row.first()


async def _position_snapshot_rows_at(
    db: DBSession,
    captured_at: datetime,
) -> list[tuple[Any, Any]]:
    rows = await db.execute(
        select(PositionSnapshot, Asset)
        .join(Asset, Asset.id == PositionSnapshot.asset_id)
        .where(
            PositionSnapshot.captured_at == captured_at,
            Asset.symbol != EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
        )
        .order_by(Asset.symbol.asc())
    )
    return list(rows.all())


async def _position_snapshot_rows_at_or_before(
    db: DBSession,
    captured_at: datetime,
) -> tuple[datetime | None, list[tuple[Any, Any]]]:
    anchor_at = await db.scalar(
        select(func.max(PositionSnapshot.captured_at)).where(
            PositionSnapshot.captured_at <= captured_at
        )
    )
    if anchor_at is None:
        return None, []
    return anchor_at, await _position_snapshot_rows_at(db, anchor_at)


async def _active_accounting_rows(db: DBSession, model: Any) -> list[Any]:
    rows = await db.execute(select(model).where(model.status == "active"))
    return list(rows.scalars().all())


async def _open_accounting_task_rows(
    db: DBSession,
) -> list[AccountingReconciliationTask]:
    rows = await db.execute(
        select(AccountingReconciliationTask)
        .where(AccountingReconciliationTask.status == "open")
        .order_by(
            AccountingReconciliationTask.occurred_at.asc(),
            AccountingReconciliationTask.id.asc(),
        )
    )
    return list(rows.scalars().all())


async def _transaction_rows(db: DBSession) -> list[Transaction]:
    rows = await db.execute(select(Transaction).order_by(Transaction.timestamp.asc()))
    return list(rows.scalars().all())


def _snapshot_as_of(rows: Sequence[tuple[Any, Any]]) -> datetime:
    if rows:
        return rows[0][0].captured_at
    return datetime.now(UTC)


def _sum_current_value_usd(
    rows: Sequence[tuple[Any, Any]],
    *,
    empty_value_when_captured: bool = False,
) -> Decimal | None:
    if not rows:
        return Decimal("0") if empty_value_when_captured else None
    values = [snapshot.current_value_usd for snapshot, _asset in rows]
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal("0"))


def _capital_current_value(
    *,
    current_value_usd: Decimal | None,
    as_of: datetime,
    open_tasks: Sequence[AccountingReconciliationTask],
) -> CapitalCurrentValue:
    flags = _reconciliation_flags(open_tasks)
    return CapitalCurrentValue(
        value_usd=current_value_usd,
        as_of=as_of,
        holdings_reconciled=flags["holdings_reconciled"],
        broker_cash_reconciled=flags["broker_cash_reconciled"],
        stablecoin_reserve_reconciled=flags["stablecoin_reserve_reconciled"],
        position_existence_reconciled=flags["position_existence_reconciled"],
    )


def _distribution_current_value(
    *,
    current_value_usd: Decimal | None,
    as_of: datetime,
    open_tasks: Sequence[AccountingReconciliationTask],
) -> DistributionCurrentValue:
    flags = _reconciliation_flags(open_tasks)
    return DistributionCurrentValue(
        value_usd=current_value_usd,
        as_of=as_of,
        holdings_reconciled=flags["holdings_reconciled"],
        broker_cash_reconciled=flags["broker_cash_reconciled"],
        stablecoin_reserve_reconciled=flags["stablecoin_reserve_reconciled"],
        position_existence_reconciled=flags["position_existence_reconciled"],
    )


def _reconciliation_flags(
    open_tasks: Sequence[AccountingReconciliationTask],
) -> dict[str, bool]:
    severe_scopes = {
        scope
        for task in open_tasks
        if task.severity in _SEVERE_REVIEW_STATES
        for scope in (task.affected_metric_scopes or [])
    }
    return {
        "holdings_reconciled": not severe_scopes.intersection(
            {*_CURRENT_VALUE_SCOPES, "holdings"}
        ),
        "broker_cash_reconciled": "broker_cash" not in severe_scopes,
        "stablecoin_reserve_reconciled": "stablecoin_reserve" not in severe_scopes,
        "position_existence_reconciled": "position_existence" not in severe_scopes,
    }


def _issue_records(
    tasks: Sequence[AccountingReconciliationTask],
) -> list[dict[str, Any]]:
    return [
        {
            "reason_code": _task_reason_code(task),
            "amount_usd": task.amount_usd,
            "affected_metric_scopes": tuple(task.affected_metric_scopes or ()),
            "severity": task.severity,
            "review_task_id": task.task_id,
            "status": task.status,
            "occurred_at": task.occurred_at,
        }
        for task in tasks
    ]


def _task_reason_code(task: AccountingReconciliationTask | AccountingReviewTask) -> str:
    evidence = task.evidence or {}
    reasons = evidence.get("reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])
    return task.task_type


def _distribution_holdings(
    rows: Sequence[tuple[Any, Any]],
) -> list[DistributionHolding]:
    return [
        DistributionHolding(
            symbol=asset.symbol,
            asset_type=asset.asset_type,
            current_value_usd=snapshot.current_value_usd,
            cash_reserve_kind=_cash_reserve_kind(asset),
            institution=None,
        )
        for snapshot, asset in rows
    ]


def _cash_reserve_kind(asset: Asset) -> str | None:
    symbol = asset.symbol.upper()
    asset_type = asset.asset_type.lower()
    if symbol in _STABLECOIN_SYMBOLS or asset_type == "stablecoin":
        return "stablecoin"
    if symbol in _FIAT_CASH_SYMBOLS and asset_type in {"cash", "fiat", "currency"}:
        return "broker_cash"
    if asset_type in {"cash", "fiat", "currency"}:
        return "other_tracked_cash"
    return None


async def _historical_boundary(
    db: DBSession,
    as_of: datetime,
) -> HistoricalValueResult:
    captured_at, rows = await _position_snapshot_rows_at_or_before(db, as_of)
    value_usd = _sum_current_value_usd(
        rows,
        empty_value_when_captured=captured_at is not None,
    )
    if captured_at is None:
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=None,
            source="unavailable",
            confidence_state="provisional",
            reason_codes=("missing_anchor",),
            sensitive_metrics_visible=False,
        )
    if value_usd is None:
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=None,
            source="exact_anchor",
            confidence_state="blocked",
            reason_codes=("missing_anchor_component_value",),
            sensitive_metrics_visible=False,
        )
    if not _same_instant(captured_at, as_of):
        return HistoricalValueResult(
            as_of=as_of,
            value_usd=None,
            source="stale_anchor",
            confidence_state="provisional",
            reason_codes=("stale_anchor",),
            sensitive_metrics_visible=False,
        )
    return HistoricalValueResult(
        as_of=as_of,
        value_usd=value_usd,
        source="exact_anchor",
        confidence_state="trusted",
        reason_codes=("exact_anchor",),
        sensitive_metrics_visible=True,
    )


async def _holding_driver_inputs(
    db: DBSession,
    latest_rows: Sequence[tuple[Any, Any]],
    *,
    as_of: datetime,
    cashflows: Sequence[Any] | None = None,
    open_tasks: Sequence[Any] | None = None,
) -> list[HoldingDriverInput]:
    _start_captured_at, start_rows = await _position_snapshot_rows_at_or_before(
        db, as_of - timedelta(days=_DASHBOARD_PERIOD_DAYS)
    )
    period_start = as_of - timedelta(days=_DASHBOARD_PERIOD_DAYS)
    start_by_symbol = (
        {asset.symbol: snapshot for snapshot, asset in start_rows}
        if _start_captured_at is not None
        and _same_instant(_start_captured_at, period_start)
        else {}
    )
    active_cashflows = (
        list(cashflows)
        if cashflows is not None
        else await _active_accounting_rows(db, AccountingExternalCashflowClassification)
    )
    task_rows = (
        list(open_tasks)
        if open_tasks is not None
        else await _open_accounting_task_rows(db)
    )
    return [
        HoldingDriverInput(
            symbol=asset.symbol,
            period_days=_DASHBOARD_PERIOD_DAYS,
            starting_value_usd=(
                start_by_symbol[asset.symbol].current_value_usd
                if asset.symbol in start_by_symbol
                else None
            ),
            ending_value_usd=snapshot.current_value_usd,
            deposits_usd=_symbol_period_cashflow_usd(
                asset.symbol,
                active_cashflows,
                start_at=period_start,
                end_at=as_of,
                cashflow_type="external_deposit",
            ),
            withdrawals_usd=_symbol_period_cashflow_usd(
                asset.symbol,
                active_cashflows,
                start_at=period_start,
                end_at=as_of,
                cashflow_type="external_withdrawal",
            ),
            confidence_state=_asset_driver_confidence_state(asset.symbol, task_rows),
            reason_codes=_asset_driver_reason_codes(asset.symbol, task_rows),
        )
        for snapshot, asset in latest_rows
    ]


async def _asset_holding_driver(
    db: DBSession,
    symbol: str,
    *,
    as_of: datetime,
) -> HoldingDriver | None:
    latest_rows = await _latest_position_snapshot_rows(db)
    summary = calculate_holding_drivers(
        as_of=as_of,
        holdings=await _holding_driver_inputs(db, latest_rows, as_of=as_of),
        periods_days=(_DASHBOARD_PERIOD_DAYS,),
        default_period_days=_DASHBOARD_PERIOD_DAYS,
    )
    period = summary.default_period
    if period is None:
        return None
    for driver in period.drivers:
        if driver.symbol == symbol:
            return driver
    return None


def _symbol_period_cashflow_usd(
    symbol: str,
    cashflows: Sequence[Any],
    *,
    start_at: datetime,
    end_at: datetime,
    cashflow_type: str,
) -> Decimal:
    normalized_symbol = symbol.upper()
    total = Decimal("0")
    for cashflow in cashflows:
        if getattr(cashflow, "status", "active") != "active":
            continue
        if str(getattr(cashflow, "asset_symbol", "")).upper() != normalized_symbol:
            continue
        if str(getattr(cashflow, "cashflow_type", "")).lower() != cashflow_type:
            continue
        occurred_at = getattr(cashflow, "occurred_at", None)
        if (
            not isinstance(occurred_at, datetime)
            or not start_at < occurred_at <= end_at
        ):
            continue
        amount = _cashflow_amount_usd(cashflow)
        if amount is not None:
            total += abs(amount)
    return total


def _cashflow_amount_usd(cashflow: Any) -> Decimal | None:
    for attr_name in ("capital_effect_usd", "amount_usd"):
        value = _decimal_or_none(getattr(cashflow, attr_name, None))
        if value is not None:
            return value
    return None


def _asset_driver_confidence_state(
    symbol: str, tasks: Sequence[Any]
) -> ConfidenceState:
    matching_tasks = _asset_driver_blocking_tasks(symbol, tasks)
    if not matching_tasks:
        return "trusted"
    return _max_confidence_state(task.severity for task in matching_tasks)


def _asset_driver_reason_codes(symbol: str, tasks: Sequence[Any]) -> tuple[str, ...]:
    return tuple(
        _task_reason_code(task) for task in _asset_driver_blocking_tasks(symbol, tasks)
    )


def _asset_driver_blocking_tasks(symbol: str, tasks: Sequence[Any]) -> list[Any]:
    normalized_symbol = symbol.upper()
    return [
        task
        for task in tasks
        if getattr(task, "status", "open") == "open"
        and str(getattr(task, "asset_symbol", "")).upper() == normalized_symbol
        and getattr(task, "severity", None) in _SEVERE_REVIEW_STATES
        and set(getattr(task, "affected_metric_scopes", None) or ()).intersection(
            _HOLDING_DRIVER_BLOCKING_SCOPES
        )
    ]


def _rolling_period_contract(
    period: Any,
    *,
    as_of: datetime,
) -> DashboardRollingPeriod:
    if period is None:
        return DashboardRollingPeriod(
            label=f"{_DASHBOARD_PERIOD_DAYS}D",
            days=_DASHBOARD_PERIOD_DAYS,
            start_at=as_of - timedelta(days=_DASHBOARD_PERIOD_DAYS),
            end_at=as_of,
            starting_value_usd=None,
            ending_value_usd=None,
            external_contributions_usd=Decimal("0"),
            external_withdrawals_usd=Decimal("0"),
            investment_gain_usd=None,
            confidence_state="provisional",
            reason_codes=["missing_period_data"],
            visible=False,
        )
    return DashboardRollingPeriod(
        label=period.label,
        days=period.days,
        start_at=period.start_at,
        end_at=period.end_at,
        starting_value_usd=period.starting_value_usd,
        ending_value_usd=period.ending_value_usd,
        external_contributions_usd=period.deposits_usd,
        external_withdrawals_usd=period.withdrawals_usd,
        investment_gain_usd=period.investment_gain_usd,
        confidence_state=period.confidence_state,
        reason_codes=list(period.reason_codes),
        visible=period.period_performance_visible,
    )


def _holding_driver_contract(driver: HoldingDriver) -> HoldingDriverContract:
    return HoldingDriverContract(
        symbol=driver.symbol,
        movement_usd=driver.movement_usd,
        share_of_known_movement_pct=driver.share_of_known_movement_pct,
        direction=driver.direction,
        confidence_state=driver.confidence_state,
        reason_codes=list(driver.reason_codes),
        value_state=driver.value_state,
    )


def _top_reconciliation_action(
    tasks: Sequence[AccountingReviewTask],
    *,
    preferred_task_id: str | None,
) -> AccountingReviewTask | None:
    by_id = {task.task_id: task for task in tasks}
    if preferred_task_id and preferred_task_id in by_id:
        return by_id[preferred_task_id]
    for task in tasks:
        if task.severity == "blocked":
            return task
    for task in tasks:
        if task.severity == "review_required":
            return task
    return tasks[0] if tasks else None


def _asset_current_position(
    snapshot: PositionSnapshot,
    *,
    trust_blockers: Sequence[AccountingReviewTask],
) -> AssetCurrentPosition:
    reason_codes: list[str] = []
    confidence_state: ConfidenceState = "trusted"
    if snapshot.current_value_usd is None:
        reason_codes.append("missing_current_value")
        confidence_state = "blocked"
    pnl_blocking_reasons = _asset_blocking_reasons(
        trust_blockers,
        _SENSITIVE_ASSET_POSITION_PNL_SCOPES,
    )
    cost_basis_blocking_reasons = _asset_blocking_reasons(
        trust_blockers,
        _SENSITIVE_ASSET_COST_BASIS_SCOPES,
    )
    if pnl_blocking_reasons:
        reason_codes.extend(pnl_blocking_reasons)
        confidence_state = _max_confidence_state([confidence_state, "blocked"])
    elif cost_basis_blocking_reasons:
        reason_codes.extend(cost_basis_blocking_reasons)
        confidence_state = _max_confidence_state([confidence_state, "blocked"])
    return AssetCurrentPosition(
        quantity=snapshot.quantity,
        current_price_usd=snapshot.current_price_usd,
        current_value_usd=snapshot.current_value_usd,
        average_cost_usd=(
            None if cost_basis_blocking_reasons else snapshot.avg_buy_price_usd
        ),
        current_position_pnl_usd=(
            None if pnl_blocking_reasons else snapshot.unrealized_pnl_usd
        ),
        current_position_pnl_pct=(
            None if pnl_blocking_reasons else snapshot.unrealized_pnl_pct
        ),
        confidence_state=confidence_state,
        reason_codes=_dedupe(reason_codes),
    )


def _asset_capital_allocated_usd(
    snapshot: PositionSnapshot,
    *,
    trust_blockers: Sequence[AccountingReviewTask],
) -> Decimal | None:
    if _asset_blocking_reasons(trust_blockers, _SENSITIVE_ASSET_COST_BASIS_SCOPES):
        return None
    return snapshot.total_cost_usd


async def _asset_lifetime_contribution(
    db: DBSession,
    *,
    symbol: str,
    latest_rows: Sequence[tuple[Any, Any]],
    trust_blockers: Sequence[AccountingReviewTask],
) -> AssetLifetimeContribution:
    blocking_reasons = _asset_lifetime_blocking_reasons(trust_blockers)
    if blocking_reasons:
        return AssetLifetimeContribution(
            contribution_basis_usd=None,
            contribution_pnl_usd=None,
            confidence_state="blocked",
            reason_codes=blocking_reasons,
            visible=False,
        )
    missing_current_value_reasons = _asset_missing_current_value_reasons(
        symbol,
        latest_rows,
    )
    if missing_current_value_reasons:
        return AssetLifetimeContribution(
            contribution_basis_usd=None,
            contribution_pnl_usd=None,
            confidence_state="blocked",
            reason_codes=missing_current_value_reasons,
            visible=False,
        )

    contribution_row = await _asset_contribution_row(
        db,
        symbol=symbol,
        latest_rows=latest_rows,
    )
    if contribution_row is None:
        return AssetLifetimeContribution(
            contribution_basis_usd=None,
            contribution_pnl_usd=None,
            confidence_state="provisional",
            reason_codes=["missing_asset_lifetime_contribution_data"],
            visible=False,
        )
    return AssetLifetimeContribution(
        contribution_basis_usd=_decimal_or_none(contribution_row.get("total_cost_usd")),
        contribution_pnl_usd=_decimal_or_none(
            contribution_row.get("net_lifetime_pnl_usd")
        ),
        confidence_state="trusted",
        reason_codes=[],
        visible=True,
    )


def _asset_lifetime_blocking_reasons(
    trust_blockers: Sequence[AccountingReviewTask],
) -> list[str]:
    return _asset_blocking_reasons(
        trust_blockers,
        _SENSITIVE_ASSET_LIFETIME_SCOPES,
    )


def _asset_missing_current_value_reasons(
    symbol: str,
    latest_rows: Sequence[tuple[Any, Any]],
) -> list[str]:
    normalized_symbol = symbol.upper()
    for snapshot, asset in latest_rows:
        if asset.symbol.upper() != normalized_symbol:
            continue
        if snapshot.current_value_usd is None:
            return ["missing_current_value"]
        if snapshot.current_price_usd is None:
            return ["missing_current_price"]
        return []
    return ["missing_asset_current_value"]


def _asset_blocking_reasons(
    trust_blockers: Sequence[AccountingReviewTask],
    blocking_scopes: set[str],
) -> list[str]:
    reasons: list[str] = []
    for task in trust_blockers:
        scopes = set(task.affected_metric_scopes or [])
        if task.severity in _SEVERE_REVIEW_STATES and scopes.intersection(
            blocking_scopes
        ):
            reasons.append(_task_reason_code(task))
    return _dedupe(reasons)


async def _asset_contribution_row(
    db: DBSession,
    *,
    symbol: str,
    latest_rows: Sequence[tuple[Any, Any]],
) -> dict[str, object] | None:
    summary = await analytics.calculate_asset_contribution_summary(
        await _transaction_rows(db),
        _latest_price_map(latest_rows),
        sort_by="symbol",
        order="asc",
    )
    asset_rows = summary.get("assets", [])
    if not isinstance(asset_rows, list):
        return None
    for row in asset_rows:
        if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol:
            return row
    return None


def _latest_price_map(rows: Sequence[tuple[Any, Any]]) -> dict[str, Decimal]:
    return {
        asset.symbol: snapshot.current_price_usd
        for snapshot, asset in rows
        if snapshot.current_price_usd is not None
    }


def _asset_recent_movement(driver: HoldingDriver | None) -> AssetRecentMovement | None:
    if driver is None:
        return None
    return AssetRecentMovement(
        period_label=f"{_DASHBOARD_PERIOD_DAYS}D",
        movement_usd=driver.movement_usd,
        direction=driver.direction,
        confidence_state=driver.confidence_state,
        reason_codes=list(driver.reason_codes),
        value_state=driver.value_state,
    )


def _asset_driver_explanation(
    driver: HoldingDriver | None,
) -> AssetDriverExplanation | None:
    if driver is None:
        return None
    return AssetDriverExplanation(
        symbol=driver.symbol,
        period_label=f"{_DASHBOARD_PERIOD_DAYS}D",
        movement_usd=driver.movement_usd,
        share_of_known_movement_pct=driver.share_of_known_movement_pct,
        direction=driver.direction,
        explanation=_driver_explanation_text(driver),
        confidence_state=driver.confidence_state,
        reason_codes=list(driver.reason_codes),
    )


def _driver_explanation_text(driver: HoldingDriver) -> str:
    if driver.value_state == "hidden" or driver.movement_usd is None:
        return f"{driver.symbol} movement is hidden until confidence improves."
    if driver.direction == "positive":
        verb = "gained"
    elif driver.direction == "negative":
        verb = "lost"
    elif driver.direction == "flat":
        verb = "was flat"
    else:
        verb = "has unknown movement"
    return (
        f"{driver.symbol} {verb} over {_DASHBOARD_PERIOD_DAYS}D after external flows."
    )


def _max_confidence_state(states: Iterable[str]) -> ConfidenceState:
    max_state: ConfidenceState = "trusted"
    for state in states:
        normalized: ConfidenceState = (
            cast(ConfidenceState, state) if state in _CONFIDENCE_RANK else "blocked"
        )
        if _CONFIDENCE_RANK[normalized] > _CONFIDENCE_RANK[max_state]:
            max_state = normalized
    return max_state


def _same_instant(left: datetime, right: datetime) -> bool:
    return left == right


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@router.get("/dashboard", response_model=DashboardContract)
async def portfolio_dashboard(user: CurrentUser, db: DBSession):
    """Confidence-aware dashboard contract for the first portfolio screen."""
    return await _compose_dashboard_contract(db)


@router.get("/assets/{symbol}/detail", response_model=AssetDetailContract)
async def portfolio_asset_detail(symbol: str, user: CurrentUser, db: DBSession):
    """Confidence-aware asset detail contract with explicit P&L scopes."""
    return await _compose_asset_detail_contract(db, symbol)


@router.get("/summary")
async def portfolio_summary(user: CurrentUser, db: DBSession):
    """Aggregated portfolio totals + per-asset breakdown with live prices."""
    holdings = await analytics.get_holdings(db)
    symbols = list(dict.fromkeys([h.symbol for h in holdings] + ["SPY", "BTC", "XAU"]))
    prices = await pricing.get_prices_bulk(symbols)
    holdings = await analytics.enrich_with_prices(holdings, prices)
    benchmark_ratios = analytics.calculate_benchmark_ratios(prices)
    benchmark_spx_in_btc = benchmark_ratios["spx_in_btc"]
    benchmark_spx_in_gold = benchmark_ratios["spx_in_gold"]

    total_value = sum((h.current_value_usd or Decimal("0")) for h in holdings)
    total_cost = sum(h.total_cost_usd for h in holdings)
    total_pnl = total_value - total_cost
    freshness_as_of = datetime.now(UTC)
    holding_freshness = {
        h.symbol: _current_value_freshness(
            symbol=h.symbol,
            price_present=h.current_price_usd is not None
            and h.current_value_usd is not None,
            as_of=freshness_as_of,
        )
        for h in holdings
    }
    freshness_warnings = [
        warning
        for freshness in holding_freshness.values()
        for warning in freshness["warnings"]
    ]
    current_snapshot_freshness = _freshness_metadata(
        source="live_price_provider"
        if not freshness_warnings
        else "mixed_price_metadata",
        as_of=freshness_as_of,
        degraded=bool(freshness_warnings),
        stale=bool(freshness_warnings),
        warnings=freshness_warnings,
    )

    # Asset type breakdown
    by_type: dict[str, Decimal] = {}
    for h in holdings:
        at = h.asset_type
        by_type[at] = by_type.get(at, Decimal("0")) + (
            h.current_value_usd or Decimal("0")
        )

    return {
        "total_value_usd": float(total_value),
        "total_cost_usd": float(total_cost),
        "total_pnl_usd": float(total_pnl),
        "total_pnl_pct": float(total_pnl / total_cost * 100) if total_cost > 0 else 0,
        "holding_count": len(holdings),
        "by_asset_type": {k: float(v) for k, v in by_type.items()},
        "benchmarks": {
            "spx_in_btc": (
                float(benchmark_spx_in_btc)
                if benchmark_spx_in_btc is not None
                else None
            ),
            "spx_in_gold": (
                float(benchmark_spx_in_gold)
                if benchmark_spx_in_gold is not None
                else None
            ),
        },
        "freshness": {
            "current_snapshot": current_snapshot_freshness,
            "api_delta": _freshness_metadata(
                source="sync_status_activity", as_of=None, warnings=[]
            ),
            "export_baseline": _freshness_metadata(
                source="import_artifacts", as_of=None, warnings=[]
            ),
            "warnings": freshness_warnings,
        },
        "holdings": [
            {
                "symbol": h.symbol,
                "asset_type": h.asset_type,
                "institution": h.institution,
                "quantity": float(h.quantity),
                "avg_buy_price_usd": float(h.avg_buy_price_usd)
                if h.avg_buy_price_usd
                else None,
                "current_price_usd": float(h.current_price_usd)
                if h.current_price_usd
                else None,
                "current_value_usd": float(h.current_value_usd)
                if h.current_value_usd
                else None,
                "total_cost_usd": float(h.total_cost_usd),
                "unrealized_pnl_usd": float(h.unrealized_pnl_usd)
                if h.unrealized_pnl_usd
                else None,
                "unrealized_pnl_pct": float(h.unrealized_pnl_pct)
                if h.unrealized_pnl_pct
                else None,
                "source_drilldown": _jsonify_decimal_payload(h.source_drilldown or []),
                "freshness": holding_freshness[h.symbol],
            }
            for h in holdings
        ],
    }


@router.get("/capital-truth")
async def portfolio_capital_truth(user: CurrentUser, db: DBSession):
    """Lifetime accounting truth: money in/out vs current snapshot value."""
    transactions = await analytics.fetch_transactions(db)
    snapshot_current_value = await _latest_snapshot_current_value_usd(db)
    if snapshot_current_value is not None:
        summary = await analytics.calculate_capital_truth_summary(
            transactions,
            current_value_usd=snapshot_current_value,
            current_value_source="latest_position_snapshot",
        )
    else:
        symbols = sorted(
            {
                symbol.upper()
                for tx in transactions
                for symbol in (tx.asset_symbol, getattr(tx, "fee_currency", None))
                if symbol
            }
        )
        prices = await pricing.get_prices_bulk(symbols)
        summary = await analytics.calculate_capital_truth_summary(
            transactions,
            current_prices=prices,
            current_value_source="transaction_lot_valuation",
        )
    return _jsonify_decimal_payload(summary)


@router.get("/performance-summary")
async def portfolio_performance_summary(user: CurrentUser, db: DBSession):
    """
    Performance-oriented summary with external cashflows,
    PnL, bridge transfers, and XIRR.
    """
    transactions = await analytics.fetch_transactions(db)
    symbols = sorted(
        {
            symbol.upper()
            for tx in transactions
            for symbol in (tx.asset_symbol, getattr(tx, "fee_currency", None))
            if symbol
        }
    )
    prices = await pricing.get_prices_bulk(symbols)
    summary = await analytics.calculate_performance_summary(transactions, prices)
    return _jsonify_decimal_payload(summary)


@router.get("/asset-contributions")
async def portfolio_asset_contributions(
    user: CurrentUser,
    db: DBSession,
    sort_by: str = Query("net_lifetime_pnl_usd"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """Asset-level winners/losers lifetime contribution metrics."""
    transactions = await analytics.fetch_transactions(db)
    symbols = sorted(
        {
            symbol.upper()
            for tx in transactions
            for symbol in (tx.asset_symbol, getattr(tx, "fee_currency", None))
            if symbol
        }
    )
    prices = await pricing.get_prices_bulk(symbols)
    summary = await analytics.calculate_asset_contribution_summary(
        transactions,
        prices,
        sort_by=sort_by,
        order=order,
    )
    return _jsonify_decimal_payload(summary)


@router.get("/transactions")
async def list_transactions(
    user: CurrentUser,
    db: DBSession,
    institution: str | None = Query(None),
    asset: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    q = (
        select(Transaction)
        .order_by(Transaction.timestamp.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if institution:
        q = q.where(Transaction.institution == institution)
    if asset:
        q = q.where(Transaction.asset_symbol == asset.upper())

    result = await db.execute(q)
    txs = result.scalars().all()

    return [
        {
            "id": tx.id,
            "institution": tx.institution,
            "type": tx.tx_type,
            "asset": tx.asset_symbol,
            "asset_type": tx.asset_type,
            "quantity": float(tx.quantity),
            "price_usd": float(tx.price_usd) if tx.price_usd else None,
            "total_usd": float(tx.total_usd) if tx.total_usd else None,
            "fee": float(tx.fee),
            "fee_currency": tx.fee_currency,
            "timestamp": tx.timestamp.isoformat(),
            "raw_data": tx.raw_data,
        }
        for tx in txs
    ]


@router.post("/state/refresh")
async def portfolio_state_refresh(
    user: CurrentUser,
    request: Request,
    db: DBSession,
    payload: PortfolioStateRefreshRequest | None = None,
):
    captured_at = (
        payload.captured_at if payload and payload.captured_at else datetime.now(UTC)
    )
    user_id = user.id
    try:
        redis_connection = scheduler_jobs.get_redis_connection()
        redis_connection.ping()
        result = await scheduler_jobs.execute_owned_refresh(
            db,
            redis_connection=redis_connection,
            captured_at=captured_at,
            route="/v1/portfolio/state/refresh",
            user_id=user_id,
        )
    except RedisError as exc:
        request.app.state.telemetry.record_operation(
            name="portfolio.state_refresh",
            outcome="failed",
            route="/v1/portfolio/state/refresh",
            user_id=user_id,
            detail="refresh_lock_unavailable",
        )
        raise HTTPException(
            status_code=503,
            detail="Portfolio refresh lock is unavailable; check Redis",
        ) from exc
    except ValueError as exc:
        request.app.state.telemetry.record_operation(
            name="portfolio.state_refresh",
            outcome="rejected",
            route="/v1/portfolio/state/refresh",
            user_id=user_id,
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request.app.state.telemetry.record_operation(
        name="portfolio.state_refresh",
        outcome=result["status"],
        route="/v1/portfolio/state/refresh",
        user_id=user_id,
    )
    if result["status"] == "skipped":
        return result
    return {
        "captured_at": result["captured_at"],
        "asset_count": result["asset_count"],
        "snapshot_count": result["snapshot_count"],
        "benchmark_count": result["benchmark_count"],
    }


@router.get("/assets")
async def portfolio_assets(user: CurrentUser, db: DBSession):
    assets = (
        (
            await db.execute(
                select(Asset)
                .where(Asset.last_seen_at.is_not(None))
                .order_by(Asset.symbol.asc())
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "symbol": asset.symbol,
            "asset_type": asset.asset_type,
            "last_price_usd": float(asset.last_price_usd)
            if asset.last_price_usd is not None
            else None,
            "last_seen_at": asset.last_seen_at.isoformat()
            if asset.last_seen_at is not None
            else None,
        }
        for asset in assets
    ]


@router.get("/snapshots/latest")
async def portfolio_latest_snapshots(user: CurrentUser, db: DBSession):
    captured_at = await db.scalar(select(func.max(PositionSnapshot.captured_at)))
    if captured_at is None:
        return {"captured_at": None, "snapshots": []}

    rows = (
        await db.execute(
            select(PositionSnapshot, Asset)
            .join(Asset, Asset.id == PositionSnapshot.asset_id)
            .where(
                PositionSnapshot.captured_at == captured_at,
                Asset.symbol != EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
            )
            .order_by(Asset.symbol.asc())
        )
    ).all()
    return {
        "captured_at": captured_at.isoformat(),
        "snapshots": [
            {
                "symbol": asset.symbol,
                "asset_type": asset.asset_type,
                "quantity": float(snapshot.quantity),
                "avg_buy_price_usd": (
                    float(snapshot.avg_buy_price_usd)
                    if snapshot.avg_buy_price_usd is not None
                    else None
                ),
                "total_cost_usd": float(snapshot.total_cost_usd),
                "current_price_usd": (
                    float(snapshot.current_price_usd)
                    if snapshot.current_price_usd is not None
                    else None
                ),
                "current_value_usd": (
                    float(snapshot.current_value_usd)
                    if snapshot.current_value_usd is not None
                    else None
                ),
                "unrealized_pnl_usd": (
                    float(snapshot.unrealized_pnl_usd)
                    if snapshot.unrealized_pnl_usd is not None
                    else None
                ),
                "unrealized_pnl_pct": (
                    float(snapshot.unrealized_pnl_pct)
                    if snapshot.unrealized_pnl_pct is not None
                    else None
                ),
                "freshness": _freshness_metadata(
                    source="persisted_position_snapshot",
                    as_of=snapshot.captured_at,
                    degraded=snapshot.current_value_usd is None,
                    stale=False,
                    warnings=(
                        [f"{asset.symbol} snapshot has no current value"]
                        if snapshot.current_value_usd is None
                        else []
                    ),
                ),
            }
            for snapshot, asset in rows
        ],
        "freshness": _freshness_metadata(
            source="persisted_position_snapshot",
            as_of=captured_at,
            stale=False,
            degraded=False,
            warnings=[] if rows else ["latest snapshot has no current position rows"],
        ),
    }


@router.get("/benchmarks/latest")
async def portfolio_latest_benchmarks(user: CurrentUser, db: DBSession):
    captured_at = await db.scalar(select(func.max(BenchmarkQuote.captured_at)))
    if captured_at is None:
        return {"captured_at": None, "quotes": []}

    quotes = (
        (
            await db.execute(
                select(BenchmarkQuote)
                .where(
                    BenchmarkQuote.captured_at == captured_at,
                    BenchmarkQuote.symbol != EMPTY_PORTFOLIO_BENCHMARK_SYMBOL,
                )
                .order_by(BenchmarkQuote.symbol.asc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "captured_at": captured_at.isoformat(),
        "quotes": [
            {
                "symbol": quote.symbol,
                "price_usd": float(quote.price_usd),
                "freshness": _freshness_metadata(
                    source="persisted_benchmark_quote",
                    as_of=quote.captured_at,
                    stale=False,
                    degraded=False,
                    warnings=[],
                ),
            }
            for quote in quotes
        ],
        "freshness": _freshness_metadata(
            source="persisted_benchmark_quote",
            as_of=captured_at,
            stale=False,
            degraded=False,
            warnings=[] if quotes else ["latest benchmark capture has no quote rows"],
        ),
    }


@router.get("/pending-orders")
async def portfolio_pending_orders(user: CurrentUser, db: DBSession):
    orders = (
        (
            await db.execute(
                select(PendingOrder)
                .where(PendingOrder.status.in_(("open", "pending")))
                .order_by(
                    PendingOrder.institution.asc(),
                    PendingOrder.external_order_id.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "institution": order.institution,
            "symbol": order.symbol,
            "external_order_id": order.external_order_id,
            "order_type": order.order_type,
            "status": order.status,
            "side": order.side,
            "quantity": float(order.quantity),
            "limit_price": float(order.limit_price)
            if order.limit_price is not None
            else None,
            "stop_price": float(order.stop_price)
            if order.stop_price is not None
            else None,
            "placed_at": order.placed_at.isoformat()
            if order.placed_at is not None
            else None,
        }
        for order in orders
    ]
