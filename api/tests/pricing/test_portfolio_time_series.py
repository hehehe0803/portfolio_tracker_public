# ruff: noqa: S101
from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import app.config as app_config
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app.config import settings
from app.db.models import Asset, BenchmarkQuote, PositionSnapshot
from app.db.safety import (
    DEFAULT_TEST_DATABASE_SERVER_URL,
    build_temporary_test_database_url,
    pick_safe_test_database_server_url,
    quote_postgresql_identifier,
)
from app.services.portfolio_state import (
    BENCHMARK_AGGREGATE_VIEWS,
    PORTFOLIO_AGGREGATE_VIEWS,
    BenchmarkAggregatePoint,
    PortfolioAggregatePoint,
    list_benchmark_quote_aggregates,
    list_portfolio_value_aggregates,
    refresh_time_series_aggregates,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason=(
        "GitHub Actions Timescale background workers can hang continuous aggregate "
        "integration cleanup; local make ci covers this file."
    ),
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "api" / "Alembic.ini"


def _resolve_database_url():
    return make_url(
        pick_safe_test_database_server_url(
            os.environ.get("TEST_DATABASE_BASE_URL")
            or os.environ.get("TEST_DATABASE_URL")
            or os.environ.get("DATABASE_URL")
            or settings.DATABASE_URL,
            default_url=DEFAULT_TEST_DATABASE_SERVER_URL,
        )
    )


def _run_alembic_upgrade(database_url: str) -> None:
    previous_database_url = os.environ.get("DATABASE_URL")
    previous_skip_policies = os.environ.get("PORTFOLIO_TEST_SKIP_TIMESCALE_POLICIES")
    previous_settings = app_config.settings
    os.environ["DATABASE_URL"] = database_url
    os.environ["PORTFOLIO_TEST_SKIP_TIMESCALE_POLICIES"] = "1"
    app_config.get_settings.cache_clear()
    app_config.settings = app_config.get_settings()
    try:
        command.upgrade(Config(str(ALEMBIC_INI)), "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        if previous_skip_policies is None:
            os.environ.pop("PORTFOLIO_TEST_SKIP_TIMESCALE_POLICIES", None)
        else:
            os.environ["PORTFOLIO_TEST_SKIP_TIMESCALE_POLICIES"] = (
                previous_skip_policies
            )
        app_config.get_settings.cache_clear()
        app_config.settings = previous_settings


async def _create_temporary_database() -> str:
    base_url = _resolve_database_url()
    if base_url.get_backend_name() != "postgresql":
        pytest.skip("portfolio time-series tests require a PostgreSQL DATABASE_URL")

    database_url = build_temporary_test_database_url(
        base_url,
        name_prefix="pt_timeseries",
        context="api/tests/pricing/test_portfolio_time_series.py",
    )
    temp_url = make_url(database_url)
    quoted_database_name = quote_postgresql_identifier(temp_url.database or "")
    admin_url = base_url.set(database="postgres").render_as_string(hide_password=False)
    admin_engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f"CREATE DATABASE {quoted_database_name}"))
    except Exception as exc:
        await admin_engine.dispose()
        pytest.skip(f"unable to create a disposable postgres database: {exc}")

    await admin_engine.dispose()
    return database_url


async def _drop_temporary_database(database_url: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return

    temp_url = make_url(database_url)
    quoted_database_name = quote_postgresql_identifier(temp_url.database or "")
    admin_url = temp_url.set(database="postgres").render_as_string(hide_password=False)
    admin_engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text("SET statement_timeout = '30s'"))
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": temp_url.database},
            )
            await conn.execute(
                text(f"DROP DATABASE IF EXISTS {quoted_database_name} WITH (FORCE)")
            )
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def migrated_session_factory():
    database_url = await _create_temporary_database()
    try:
        await asyncio.to_thread(_run_alembic_upgrade, database_url)

        engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            yield session_factory
        finally:
            await engine.dispose()
    finally:
        await _drop_temporary_database(database_url)


async def test_portfolio_hourly_aggregates_return_latest_bucket_totals(
    migrated_session_factory,
):
    first_capture = datetime(2026, 4, 15, 10, 5, tzinfo=UTC)
    second_capture = datetime(2026, 4, 15, 10, 40, tzinfo=UTC)
    third_capture = datetime(2026, 4, 15, 11, 15, tzinfo=UTC)

    async with migrated_session_factory() as session:
        btc = Asset(symbol="BTC", asset_type="crypto")
        aapl = Asset(symbol="AAPL", asset_type="equity")
        session.add_all([btc, aapl])
        await session.flush()

        session.add_all(
            [
                PositionSnapshot(
                    asset_id=btc.id,
                    captured_at=first_capture,
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("80"),
                    total_cost_usd=Decimal("80"),
                    current_price_usd=Decimal("100"),
                    current_value_usd=Decimal("100"),
                    unrealized_pnl_usd=Decimal("20"),
                    unrealized_pnl_pct=Decimal("25"),
                ),
                PositionSnapshot(
                    asset_id=aapl.id,
                    captured_at=first_capture,
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("40"),
                    total_cost_usd=Decimal("40"),
                    current_price_usd=Decimal("50"),
                    current_value_usd=Decimal("50"),
                    unrealized_pnl_usd=Decimal("10"),
                    unrealized_pnl_pct=Decimal("25"),
                ),
                PositionSnapshot(
                    asset_id=btc.id,
                    captured_at=second_capture,
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("80"),
                    total_cost_usd=Decimal("80"),
                    current_price_usd=Decimal("120"),
                    current_value_usd=Decimal("120"),
                    unrealized_pnl_usd=Decimal("40"),
                    unrealized_pnl_pct=Decimal("50"),
                ),
                PositionSnapshot(
                    asset_id=aapl.id,
                    captured_at=second_capture,
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("40"),
                    total_cost_usd=Decimal("40"),
                    current_price_usd=Decimal("55"),
                    current_value_usd=Decimal("55"),
                    unrealized_pnl_usd=Decimal("15"),
                    unrealized_pnl_pct=Decimal("37.5"),
                ),
                PositionSnapshot(
                    asset_id=btc.id,
                    captured_at=third_capture,
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("80"),
                    total_cost_usd=Decimal("80"),
                    current_price_usd=Decimal("130"),
                    current_value_usd=Decimal("130"),
                    unrealized_pnl_usd=Decimal("50"),
                    unrealized_pnl_pct=Decimal("62.5"),
                ),
                PositionSnapshot(
                    asset_id=aapl.id,
                    captured_at=third_capture,
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("40"),
                    total_cost_usd=Decimal("40"),
                    current_price_usd=Decimal("60"),
                    current_value_usd=Decimal("60"),
                    unrealized_pnl_usd=Decimal("20"),
                    unrealized_pnl_pct=Decimal("50"),
                ),
            ]
        )
        await session.commit()

        await refresh_time_series_aggregates(
            session,
            start_at=first_capture,
            end_at=third_capture + timedelta(hours=1),
        )
        await session.execute(
            text(
                "ALTER MATERIALIZED VIEW portfolio_snapshots_hourly "
                "SET (timescaledb.materialized_only = true)"
            )
        )
        points = await list_portfolio_value_aggregates(session, resolution="hourly")

    assert points == [
        PortfolioAggregatePoint(
            bucket_start=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
            total_value_usd=Decimal("175.000000"),
            total_cost_usd=Decimal("120.000000"),
            total_pnl_usd=Decimal("55.000000"),
        ),
        PortfolioAggregatePoint(
            bucket_start=datetime(2026, 4, 15, 11, 0, tzinfo=UTC),
            total_value_usd=Decimal("190.000000"),
            total_cost_usd=Decimal("120.000000"),
            total_pnl_usd=Decimal("70.000000"),
        ),
    ]


async def test_benchmark_daily_aggregates_return_latest_symbol_prices(
    migrated_session_factory,
):
    first_capture = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)
    second_capture = datetime(2026, 4, 15, 16, 0, tzinfo=UTC)
    third_capture = datetime(2026, 4, 16, 9, 0, tzinfo=UTC)

    async with migrated_session_factory() as session:
        session.add_all(
            [
                BenchmarkQuote(
                    symbol="BTC",
                    captured_at=first_capture,
                    price_usd=Decimal("70000"),
                ),
                BenchmarkQuote(
                    symbol="SPY",
                    captured_at=first_capture,
                    price_usd=Decimal("500"),
                ),
                BenchmarkQuote(
                    symbol="BTC",
                    captured_at=second_capture,
                    price_usd=Decimal("71000"),
                ),
                BenchmarkQuote(
                    symbol="SPY",
                    captured_at=second_capture,
                    price_usd=Decimal("505"),
                ),
                BenchmarkQuote(
                    symbol="BTC",
                    captured_at=third_capture,
                    price_usd=Decimal("72000"),
                ),
                BenchmarkQuote(
                    symbol="SPY",
                    captured_at=third_capture,
                    price_usd=Decimal("510"),
                ),
            ]
        )
        await session.commit()

        await refresh_time_series_aggregates(
            session,
            start_at=first_capture,
            end_at=third_capture + timedelta(days=1),
        )
        await session.execute(
            text(
                "ALTER MATERIALIZED VIEW benchmark_quotes_daily "
                "SET (timescaledb.materialized_only = true)"
            )
        )
        points = await list_benchmark_quote_aggregates(session, resolution="daily")

    assert points == [
        BenchmarkAggregatePoint(
            bucket_start=datetime(2026, 4, 15, 0, 0, tzinfo=UTC),
            symbol="BTC",
            price_usd=Decimal("71000.000000"),
        ),
        BenchmarkAggregatePoint(
            bucket_start=datetime(2026, 4, 15, 0, 0, tzinfo=UTC),
            symbol="SPY",
            price_usd=Decimal("505.000000"),
        ),
        BenchmarkAggregatePoint(
            bucket_start=datetime(2026, 4, 16, 0, 0, tzinfo=UTC),
            symbol="BTC",
            price_usd=Decimal("72000.000000"),
        ),
        BenchmarkAggregatePoint(
            bucket_start=datetime(2026, 4, 16, 0, 0, tzinfo=UTC),
            symbol="SPY",
            price_usd=Decimal("510.000000"),
        ),
    ]


async def test_refresh_time_series_aggregates_populates_materialized_data_for_each_view(
    migrated_session_factory,
):
    captured_at = datetime(2026, 4, 15, 10, 5, tzinfo=UTC)
    end_at = captured_at + timedelta(days=31)
    aggregate_views = [
        *PORTFOLIO_AGGREGATE_VIEWS.values(),
        *BENCHMARK_AGGREGATE_VIEWS.values(),
    ]
    aggregate_resolutions = list(PORTFOLIO_AGGREGATE_VIEWS)

    async with migrated_session_factory() as session:
        asset = Asset(symbol="BTC", asset_type="crypto")
        session.add(asset)
        await session.flush()
        session.add(
            PositionSnapshot(
                asset_id=asset.id,
                captured_at=captured_at,
                quantity=Decimal("1"),
                avg_buy_price_usd=Decimal("80"),
                total_cost_usd=Decimal("80"),
                current_price_usd=Decimal("100"),
                current_value_usd=Decimal("100"),
                unrealized_pnl_usd=Decimal("20"),
                unrealized_pnl_pct=Decimal("25"),
            )
        )
        session.add(
            BenchmarkQuote(
                symbol="BTC",
                captured_at=captured_at,
                price_usd=Decimal("70000"),
            )
        )
        await session.commit()

        for view_name in aggregate_views:
            await session.execute(
                text(
                    f"ALTER MATERIALIZED VIEW {view_name} "
                    "SET (timescaledb.materialized_only = true)"
                )
            )

        for resolution in aggregate_resolutions:
            assert (
                await list_portfolio_value_aggregates(session, resolution=resolution)
                == []
            )
            assert (
                await list_benchmark_quote_aggregates(session, resolution=resolution)
                == []
            )

        for resolution in aggregate_resolutions:
            await refresh_time_series_aggregates(
                session,
                start_at=captured_at,
                end_at=end_at,
                resolutions=(resolution,),
            )

            assert (
                len(
                    await list_portfolio_value_aggregates(
                        session, resolution=resolution
                    )
                )
                == 1
            )
            assert (
                len(
                    await list_benchmark_quote_aggregates(
                        session, resolution=resolution
                    )
                )
                == 1
            )
