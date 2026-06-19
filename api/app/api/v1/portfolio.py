"""
Portfolio endpoints: summary, holdings list, transaction history.
"""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from redis import RedisError
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DBSession
from app.db.models import (
    Asset,
    BenchmarkQuote,
    PendingOrder,
    PositionSnapshot,
    Transaction,
)
from app.services import analytics, pricing, scheduler_jobs
from app.services.portfolio_state import (
    EMPTY_PORTFOLIO_BENCHMARK_SYMBOL,
    EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


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
