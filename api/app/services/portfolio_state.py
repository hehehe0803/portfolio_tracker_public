# ruff: noqa: S608
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, BenchmarkQuote, PositionSnapshot
from app.services import analytics, pricing
from app.services.analytics import HoldingStats

EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL = "__portfolio_empty__"
EMPTY_PORTFOLIO_BENCHMARK_SYMBOL = "__portfolio_empty__"
TimeSeriesResolution = Literal["hourly", "daily", "weekly", "monthly"]
PORTFOLIO_AGGREGATE_VIEWS: dict[TimeSeriesResolution, str] = {
    "hourly": "portfolio_snapshots_hourly",
    "daily": "portfolio_snapshots_daily",
    "weekly": "portfolio_snapshots_weekly",
    "monthly": "portfolio_snapshots_monthly",
}
BENCHMARK_AGGREGATE_VIEWS: dict[TimeSeriesResolution, str] = {
    "hourly": "benchmark_quotes_hourly",
    "daily": "benchmark_quotes_daily",
    "weekly": "benchmark_quotes_weekly",
    "monthly": "benchmark_quotes_monthly",
}
AGGREGATE_REFRESH_PADDING: dict[TimeSeriesResolution, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=32),
}


@dataclass
class PortfolioAggregatePoint:
    bucket_start: datetime
    total_value_usd: Decimal
    total_cost_usd: Decimal
    total_pnl_usd: Decimal


@dataclass
class BenchmarkAggregatePoint:
    bucket_start: datetime
    symbol: str
    price_usd: Decimal


@dataclass(frozen=True)
class PortfolioValueAnchor:
    captured_at: datetime
    value_usd: Decimal | None
    source: str
    confidence_state: str
    reason_codes: tuple[str, ...]
    component_count: int


@dataclass
class PortfolioStateRefreshResult:
    captured_at: datetime
    asset_count: int
    snapshot_count: int
    benchmark_count: int


def _to_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _canonicalize_holdings(holdings: list[HoldingStats]) -> list[HoldingStats]:
    seen_symbols: set[str] = set()
    duplicate_symbols: set[str] = set()
    for holding in holdings:
        if holding.symbol in seen_symbols:
            duplicate_symbols.add(holding.symbol)
        seen_symbols.add(holding.symbol)

    if duplicate_symbols:
        duplicates = ", ".join(sorted(duplicate_symbols))
        raise ValueError(f"Duplicate holding symbols are not allowed: {duplicates}")

    return holdings


def build_portfolio_value_anchor(
    *,
    captured_at: datetime,
    component_values_usd: list[Decimal | None],
    source: str = "position_snapshot",
) -> PortfolioValueAnchor:
    if any(value is None for value in component_values_usd):
        return PortfolioValueAnchor(
            captured_at=captured_at,
            value_usd=None,
            source=source,
            confidence_state="blocked",
            reason_codes=("missing_anchor_component_value",),
            component_count=len(component_values_usd),
        )

    present_component_values = [
        value for value in component_values_usd if value is not None
    ]
    return PortfolioValueAnchor(
        captured_at=captured_at,
        value_usd=sum(present_component_values, Decimal("0")),
        source=source,
        confidence_state="trusted",
        reason_codes=("exact_anchor",),
        component_count=len(component_values_usd),
    )


async def list_portfolio_value_anchors(
    session: AsyncSession,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[PortfolioValueAnchor]:
    filters = [Asset.symbol != EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL]
    if start_at is not None:
        filters.append(PositionSnapshot.captured_at >= start_at)
    if end_at is not None:
        filters.append(PositionSnapshot.captured_at <= end_at)

    rows = (
        await session.execute(
            select(
                PositionSnapshot.captured_at,
                PositionSnapshot.current_value_usd,
            )
            .join(Asset, Asset.id == PositionSnapshot.asset_id)
            .where(*filters)
            .order_by(PositionSnapshot.captured_at.asc(), Asset.symbol.asc())
        )
    ).all()

    values_by_timestamp: dict[datetime, list[Decimal | None]] = {}
    for captured_at, current_value_usd in rows:
        values_by_timestamp.setdefault(captured_at, []).append(current_value_usd)

    return [
        build_portfolio_value_anchor(
            captured_at=captured_at,
            component_values_usd=component_values_usd,
        )
        for captured_at, component_values_usd in values_by_timestamp.items()
    ]


def _aggregate_view_name(
    *,
    resolution: TimeSeriesResolution,
    aggregate_views: dict[TimeSeriesResolution, str],
) -> str:
    try:
        return aggregate_views[resolution]
    except KeyError as exc:
        supported = ", ".join(sorted(aggregate_views))
        raise ValueError(
            "Unsupported time-series resolution "
            f"'{resolution}'. Expected one of: {supported}"
        ) from exc


async def refresh_time_series_aggregates(
    session: AsyncSession,
    *,
    start_at: datetime,
    end_at: datetime,
    resolutions: tuple[TimeSeriesResolution, ...] = (
        "hourly",
        "daily",
        "weekly",
        "monthly",
    ),
) -> None:
    if start_at >= end_at:
        return

    bind = session.bind
    if bind is None:
        raise RuntimeError("refresh_time_series_aggregates requires a bound session")

    async with bind.connect() as connection:
        autocommit_connection = await connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        for resolution in resolutions:
            refresh_padding = AGGREGATE_REFRESH_PADDING[resolution]
            refresh_start_at = start_at - refresh_padding
            refresh_end_at = end_at + refresh_padding
            portfolio_view = _aggregate_view_name(
                resolution=resolution,
                aggregate_views=PORTFOLIO_AGGREGATE_VIEWS,
            )
            benchmark_view = _aggregate_view_name(
                resolution=resolution,
                aggregate_views=BENCHMARK_AGGREGATE_VIEWS,
            )
            for view_name in (portfolio_view, benchmark_view):
                existing_view = await autocommit_connection.scalar(
                    text("SELECT to_regclass(:view_name)"),
                    {"view_name": view_name},
                )
                if existing_view is None:
                    continue
                await autocommit_connection.execute(
                    text(
                        "CALL refresh_continuous_aggregate("
                        "cast(:view_name as regclass), "
                        "cast(:start_at as timestamptz), "
                        "cast(:end_at as timestamptz))"
                    ),
                    {
                        "view_name": view_name,
                        "start_at": refresh_start_at,
                        "end_at": refresh_end_at,
                    },
                )


async def list_portfolio_value_aggregates(
    session: AsyncSession,
    *,
    resolution: TimeSeriesResolution,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[PortfolioAggregatePoint]:
    view_name = _aggregate_view_name(
        resolution=resolution,
        aggregate_views=PORTFOLIO_AGGREGATE_VIEWS,
    )
    filters = ["asset.symbol != :empty_symbol"]
    params: dict[str, object] = {"empty_symbol": EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL}
    if start_at is not None:
        filters.append("aggregate.bucket_start >= :start_at")
        params["start_at"] = start_at
    if end_at is not None:
        filters.append("aggregate.bucket_start < :end_at")
        params["end_at"] = end_at

    result = await session.execute(
        text(  # noqa: S608
            f"""
            SELECT
                aggregate.bucket_start,
                SUM(aggregate.current_value_usd) AS total_value_usd,
                SUM(aggregate.total_cost_usd) AS total_cost_usd,
                SUM(aggregate.current_value_usd)
                    - SUM(aggregate.total_cost_usd) AS total_pnl_usd
            FROM {view_name} AS aggregate
            JOIN assets AS asset ON asset.id = aggregate.asset_id
            WHERE {" AND ".join(filters)}
            GROUP BY aggregate.bucket_start
            ORDER BY aggregate.bucket_start ASC
            """
        ),
        params,
    )
    return [
        PortfolioAggregatePoint(
            bucket_start=row.bucket_start,
            total_value_usd=row.total_value_usd,
            total_cost_usd=row.total_cost_usd,
            total_pnl_usd=row.total_pnl_usd,
        )
        for row in result
    ]


async def list_benchmark_quote_aggregates(
    session: AsyncSession,
    *,
    resolution: TimeSeriesResolution,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[BenchmarkAggregatePoint]:
    view_name = _aggregate_view_name(
        resolution=resolution,
        aggregate_views=BENCHMARK_AGGREGATE_VIEWS,
    )
    filters = ["aggregate.symbol != :empty_symbol"]
    params: dict[str, object] = {"empty_symbol": EMPTY_PORTFOLIO_BENCHMARK_SYMBOL}
    if start_at is not None:
        filters.append("aggregate.bucket_start >= :start_at")
        params["start_at"] = start_at
    if end_at is not None:
        filters.append("aggregate.bucket_start < :end_at")
        params["end_at"] = end_at

    result = await session.execute(
        text(  # noqa: S608
            f"""
            SELECT aggregate.bucket_start, aggregate.symbol, aggregate.price_usd
            FROM {view_name} AS aggregate
            WHERE {" AND ".join(filters)}
            ORDER BY aggregate.bucket_start ASC, aggregate.symbol ASC
            """
        ),
        params,
    )
    return [
        BenchmarkAggregatePoint(
            bucket_start=row.bucket_start,
            symbol=row.symbol,
            price_usd=row.price_usd,
        )
        for row in result
    ]


async def _reconcile_asset_metadata(
    session: AsyncSession,
    *,
    asset_ids: set[int],
) -> None:
    if not asset_ids:
        return

    snapshot_rows = (
        await session.execute(
            select(
                PositionSnapshot.asset_id,
                PositionSnapshot.captured_at,
                PositionSnapshot.current_price_usd,
            )
            .where(PositionSnapshot.asset_id.in_(asset_ids))
            .order_by(
                PositionSnapshot.asset_id.asc(),
                PositionSnapshot.captured_at.desc(),
                PositionSnapshot.id.desc(),
            )
        )
    ).all()

    latest_snapshot_by_asset_id: dict[int, tuple[datetime, Decimal | None]] = {}
    for asset_id, snapshot_captured_at, current_price_usd in snapshot_rows:
        latest_snapshot_by_asset_id.setdefault(
            asset_id, (snapshot_captured_at, current_price_usd)
        )

    assets = (
        (await session.execute(select(Asset).where(Asset.id.in_(asset_ids))))
        .scalars()
        .all()
    )
    for asset in assets:
        latest_snapshot = latest_snapshot_by_asset_id.get(asset.id)
        if latest_snapshot is None:
            asset.last_seen_at = None
            asset.last_price_usd = None
            continue

        asset.last_seen_at, asset.last_price_usd = latest_snapshot


async def _upsert_empty_snapshot_marker(
    session: AsyncSession,
    *,
    captured_at: datetime,
) -> int:
    asset_insert = pg_insert(Asset).values(
        {
            "symbol": EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL,
            "asset_type": "system",
            "last_price_usd": None,
            "last_seen_at": None,
        }
    )
    asset_upsert = asset_insert.on_conflict_do_update(
        constraint="uq_assets_symbol",
        set_={
            "asset_type": asset_insert.excluded.asset_type,
            "last_price_usd": asset_insert.excluded.last_price_usd,
            "last_seen_at": asset_insert.excluded.last_seen_at,
        },
    )
    await session.execute(asset_upsert)

    marker_asset = (
        await session.execute(
            select(Asset).where(Asset.symbol == EMPTY_PORTFOLIO_SNAPSHOT_SYMBOL)
        )
    ).scalar_one()

    snapshot_insert = pg_insert(PositionSnapshot).values(
        {
            "asset_id": marker_asset.id,
            "captured_at": captured_at,
            "quantity": Decimal("0"),
            "avg_buy_price_usd": None,
            "total_cost_usd": Decimal("0"),
            "current_price_usd": None,
            "current_value_usd": None,
            "unrealized_pnl_usd": None,
            "unrealized_pnl_pct": None,
        }
    )
    snapshot_upsert = snapshot_insert.on_conflict_do_update(
        constraint="uq_position_snapshots_asset_id_captured_at",
        set_={
            "quantity": snapshot_insert.excluded.quantity,
            "avg_buy_price_usd": snapshot_insert.excluded.avg_buy_price_usd,
            "total_cost_usd": snapshot_insert.excluded.total_cost_usd,
            "current_price_usd": snapshot_insert.excluded.current_price_usd,
            "current_value_usd": snapshot_insert.excluded.current_value_usd,
            "unrealized_pnl_usd": snapshot_insert.excluded.unrealized_pnl_usd,
            "unrealized_pnl_pct": snapshot_insert.excluded.unrealized_pnl_pct,
        },
    )
    await session.execute(snapshot_upsert)

    return marker_asset.id


async def refresh_portfolio_state(
    session: AsyncSession,
    *,
    captured_at: datetime,
    holdings: list[HoldingStats] | None = None,
    prices: dict[str, float | None] | None = None,
) -> PortfolioStateRefreshResult:
    if holdings is None:
        holdings = await analytics.get_holdings(session)

    affected_asset_ids = set(
        (
            await session.execute(
                select(PositionSnapshot.asset_id).where(
                    PositionSnapshot.captured_at == captured_at
                )
            )
        )
        .scalars()
        .all()
    )
    holdings = _canonicalize_holdings(holdings)

    if prices is None:
        prices = await pricing.get_prices_bulk(
            analytics.portfolio_price_symbols(holdings)
        )

    holdings = await analytics.enrich_with_prices(holdings, prices)
    assets_by_symbol: dict[str, Asset] = {}
    held_symbols = [holding.symbol for holding in holdings]

    if holdings:
        asset_values = [
            {
                "symbol": holding.symbol,
                "asset_type": holding.asset_type,
                "last_price_usd": holding.current_price_usd,
                "last_seen_at": captured_at,
            }
            for holding in holdings
        ]
        asset_insert = pg_insert(Asset).values(asset_values)
        asset_upsert = asset_insert.on_conflict_do_update(
            constraint="uq_assets_symbol",
            set_={
                "asset_type": asset_insert.excluded.asset_type,
                "last_price_usd": asset_insert.excluded.last_price_usd,
                "last_seen_at": asset_insert.excluded.last_seen_at,
            },
        )
        await session.execute(asset_upsert)

        asset_rows = (
            (await session.execute(select(Asset).where(Asset.symbol.in_(held_symbols))))
            .scalars()
            .all()
        )
        assets_by_symbol = {asset.symbol: asset for asset in asset_rows}
        affected_asset_ids.update(asset.id for asset in asset_rows)

        snapshot_values = [
            {
                "asset_id": assets_by_symbol[holding.symbol].id,
                "captured_at": captured_at,
                "quantity": holding.quantity,
                "avg_buy_price_usd": holding.avg_buy_price_usd,
                "total_cost_usd": holding.total_cost_usd,
                "current_price_usd": holding.current_price_usd,
                "current_value_usd": holding.current_value_usd,
                "unrealized_pnl_usd": holding.unrealized_pnl_usd,
                "unrealized_pnl_pct": holding.unrealized_pnl_pct,
            }
            for holding in holdings
        ]
        snapshot_insert = pg_insert(PositionSnapshot).values(snapshot_values)
        snapshot_upsert = snapshot_insert.on_conflict_do_update(
            constraint="uq_position_snapshots_asset_id_captured_at",
            set_={
                "quantity": snapshot_insert.excluded.quantity,
                "avg_buy_price_usd": snapshot_insert.excluded.avg_buy_price_usd,
                "total_cost_usd": snapshot_insert.excluded.total_cost_usd,
                "current_price_usd": snapshot_insert.excluded.current_price_usd,
                "current_value_usd": snapshot_insert.excluded.current_value_usd,
                "unrealized_pnl_usd": snapshot_insert.excluded.unrealized_pnl_usd,
                "unrealized_pnl_pct": snapshot_insert.excluded.unrealized_pnl_pct,
            },
        )
        await session.execute(snapshot_upsert)

        await session.execute(
            delete(PositionSnapshot).where(
                PositionSnapshot.captured_at == captured_at,
                PositionSnapshot.asset_id.not_in(
                    [assets_by_symbol[symbol].id for symbol in held_symbols]
                ),
            )
        )
    else:
        await session.execute(
            delete(PositionSnapshot).where(PositionSnapshot.captured_at == captured_at)
        )
        marker_asset_id = await _upsert_empty_snapshot_marker(
            session,
            captured_at=captured_at,
        )
        await session.execute(
            delete(PositionSnapshot).where(
                PositionSnapshot.captured_at == captured_at,
                PositionSnapshot.asset_id != marker_asset_id,
            )
        )
        affected_asset_ids.discard(marker_asset_id)

    await _reconcile_asset_metadata(session, asset_ids=affected_asset_ids)

    benchmark_values = [
        {
            "symbol": symbol,
            "captured_at": captured_at,
            "price_usd": price_usd,
        }
        for symbol in analytics.BENCHMARK_PROXY_SYMBOLS
        if (price_usd := _to_decimal(prices.get(symbol))) is not None
    ]

    if benchmark_values:
        benchmark_insert = pg_insert(BenchmarkQuote).values(benchmark_values)
        benchmark_upsert = benchmark_insert.on_conflict_do_update(
            constraint="uq_benchmark_quotes_symbol_captured_at",
            set_={"price_usd": benchmark_insert.excluded.price_usd},
        )
        await session.execute(benchmark_upsert)
        await session.execute(
            delete(BenchmarkQuote).where(
                BenchmarkQuote.captured_at == captured_at,
                BenchmarkQuote.symbol.not_in(
                    [row["symbol"] for row in benchmark_values]
                ),
            )
        )
    else:
        benchmark_insert = pg_insert(BenchmarkQuote).values(
            {
                "symbol": EMPTY_PORTFOLIO_BENCHMARK_SYMBOL,
                "captured_at": captured_at,
                "price_usd": Decimal("0"),
            }
        )
        benchmark_upsert = benchmark_insert.on_conflict_do_update(
            constraint="uq_benchmark_quotes_symbol_captured_at",
            set_={"price_usd": benchmark_insert.excluded.price_usd},
        )
        await session.execute(benchmark_upsert)
        await session.execute(
            delete(BenchmarkQuote).where(
                BenchmarkQuote.captured_at == captured_at,
                BenchmarkQuote.symbol != EMPTY_PORTFOLIO_BENCHMARK_SYMBOL,
            )
        )

    return PortfolioStateRefreshResult(
        captured_at=captured_at,
        asset_count=len(holdings),
        snapshot_count=len(holdings),
        benchmark_count=len(benchmark_values),
    )
