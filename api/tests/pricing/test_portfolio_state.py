from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.base import Base
from app.db.models import Asset, BenchmarkQuote, PositionSnapshot, Transaction
from app.db.safety import (
    DEFAULT_TEST_DATABASE_SERVER_URL,
    build_temporary_test_database_url,
    pick_safe_test_database_server_url,
    quote_postgresql_identifier,
)
from app.services.analytics import HoldingStats
from app.services.portfolio_state import refresh_portfolio_state


def _resolve_database_url():
    return make_url(
        pick_safe_test_database_server_url(
            os.environ.get("TEST_DATABASE_BASE_URL")
            or os.environ.get("DATABASE_URL")
            or settings.DATABASE_URL,
            default_url=DEFAULT_TEST_DATABASE_SERVER_URL,
        )
    )


async def _create_temporary_database() -> str:
    base_url = _resolve_database_url()
    if base_url.get_backend_name() != "postgresql":
        pytest.skip("portfolio state tests require a PostgreSQL DATABASE_URL")

    database_url = build_temporary_test_database_url(
        base_url,
        name_prefix="portfolio_tracker_pricing",
        context="api/tests/pricing/test_portfolio_state.py",
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
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": temp_url.database},
            )
            await conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_database_name}"))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture
async def test_session_factory():
    database_url = await _create_temporary_database()
    try:
        engine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        try:
            yield session_factory
        finally:
            await engine.dispose()
    finally:
        await _drop_temporary_database(database_url)


async def test_refresh_portfolio_state_persists_assets_snapshots_and_benchmarks(
    test_session_factory,
):
    captured_at = datetime(2026, 4, 15, 8, 0, tzinfo=UTC)
    holdings = [
        HoldingStats(
            symbol="BTC",
            asset_type="crypto",
            quantity=Decimal("1.25"),
            avg_buy_price_usd=Decimal("50000"),
            total_cost_usd=Decimal("62500"),
            institution="binance",
        ),
        HoldingStats(
            symbol="AAPL",
            asset_type="equity",
            quantity=Decimal("2"),
            avg_buy_price_usd=Decimal("180"),
            total_cost_usd=Decimal("360"),
            institution="ibkr",
        ),
    ]
    prices = {
        "BTC": 70000.0,
        "AAPL": 210.5,
        "SPY": 505.25,
        "XAU": 2388.4,
    }

    async with test_session_factory() as session:
        result = await refresh_portfolio_state(
            session,
            captured_at=captured_at,
            holdings=holdings,
            prices=prices,
        )
        await session.commit()

        asset_rows = (
            (await session.execute(select(Asset).order_by(Asset.symbol.asc())))
            .scalars()
            .all()
        )
        snapshot_rows = (
            await session.execute(
                select(PositionSnapshot, Asset.symbol)
                .join(Asset, Asset.id == PositionSnapshot.asset_id)
                .order_by(Asset.symbol.asc())
            )
        ).all()
        benchmark_rows = (
            (
                await session.execute(
                    select(BenchmarkQuote)
                    .where(BenchmarkQuote.captured_at == captured_at)
                    .order_by(BenchmarkQuote.symbol.asc())
                )
            )
            .scalars()
            .all()
        )

    assert result.asset_count == 2
    assert result.snapshot_count == 2
    assert result.benchmark_count == 3

    assert [asset.symbol for asset in asset_rows] == ["AAPL", "BTC"]
    assert asset_rows[0].last_price_usd == Decimal("210.500000")
    assert asset_rows[0].last_seen_at == captured_at
    assert asset_rows[1].last_price_usd == Decimal("70000.000000")
    assert asset_rows[1].last_seen_at == captured_at

    assert len(snapshot_rows) == 2
    snapshot_by_symbol = {symbol: snapshot for snapshot, symbol in snapshot_rows}
    btc_snapshot = snapshot_by_symbol["BTC"]
    aapl_snapshot = snapshot_by_symbol["AAPL"]

    assert btc_snapshot.captured_at == captured_at
    assert btc_snapshot.quantity == Decimal("1.2500000000")
    assert btc_snapshot.avg_buy_price_usd == Decimal("50000.000000")
    assert btc_snapshot.total_cost_usd == Decimal("62500.000000")
    assert btc_snapshot.current_price_usd == Decimal("70000.000000")
    assert btc_snapshot.current_value_usd == Decimal("87500.000000")
    assert btc_snapshot.unrealized_pnl_usd == Decimal("25000.000000")
    assert btc_snapshot.unrealized_pnl_pct == Decimal("40.0000000000")

    assert aapl_snapshot.captured_at == captured_at
    assert aapl_snapshot.quantity == Decimal("2.0000000000")
    assert aapl_snapshot.current_price_usd == Decimal("210.500000")
    assert aapl_snapshot.current_value_usd == Decimal("421.000000")

    assert [(row.symbol, row.price_usd) for row in benchmark_rows] == [
        ("BTC", Decimal("70000.000000")),
        ("SPY", Decimal("505.250000")),
        ("XAU", Decimal("2388.400000")),
    ]


async def test_refresh_portfolio_state_same_timestamp_updates_without_duplicate_rows(
    test_session_factory,
):
    captured_at = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)

    async with test_session_factory() as session:
        first_result = await refresh_portfolio_state(
            session,
            captured_at=captured_at,
            holdings=[
                HoldingStats(
                    symbol="ETH",
                    asset_type="crypto",
                    quantity=Decimal("2"),
                    avg_buy_price_usd=Decimal("2000"),
                    total_cost_usd=Decimal("4000"),
                    institution="binance",
                )
            ],
            prices={
                "ETH": 2500.0,
                "SPY": 500.0,
                "BTC": 65000.0,
                "XAU": 2400.0,
            },
        )
        await session.commit()

        second_result = await refresh_portfolio_state(
            session,
            captured_at=captured_at,
            holdings=[
                HoldingStats(
                    symbol="ETH",
                    asset_type="crypto",
                    quantity=Decimal("3"),
                    avg_buy_price_usd=Decimal("2200"),
                    total_cost_usd=Decimal("6600"),
                    institution="binance",
                )
            ],
            prices={
                "ETH": 2600.0,
                "SPY": 510.0,
                "BTC": 68000.0,
                "XAU": 2450.0,
            },
        )
        await session.commit()

        asset_rows = (await session.execute(select(Asset))).scalars().all()
        snapshot_rows = (
            (await session.execute(select(PositionSnapshot))).scalars().all()
        )
        benchmark_rows = (
            (
                await session.execute(
                    select(BenchmarkQuote)
                    .where(BenchmarkQuote.captured_at == captured_at)
                    .order_by(BenchmarkQuote.symbol.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_result.snapshot_count == 1
    assert second_result.snapshot_count == 1

    assert len(asset_rows) == 1
    assert asset_rows[0].symbol == "ETH"
    assert asset_rows[0].last_price_usd == Decimal("2600.000000")
    assert asset_rows[0].last_seen_at == captured_at

    assert len(snapshot_rows) == 1
    assert snapshot_rows[0].quantity == Decimal("3.0000000000")
    assert snapshot_rows[0].avg_buy_price_usd == Decimal("2200.000000")
    assert snapshot_rows[0].total_cost_usd == Decimal("6600.000000")
    assert snapshot_rows[0].current_price_usd == Decimal("2600.000000")
    assert snapshot_rows[0].current_value_usd == Decimal("7800.000000")
    assert snapshot_rows[0].unrealized_pnl_usd == Decimal("1200.000000")
    assert snapshot_rows[0].unrealized_pnl_pct == Decimal("18.1818181818")

    assert [(row.symbol, row.price_usd) for row in benchmark_rows] == [
        ("BTC", Decimal("68000.000000")),
        ("SPY", Decimal("510.000000")),
        ("XAU", Decimal("2450.000000")),
    ]


async def test_refresh_portfolio_state_same_timestamp_reconciles_removed_snapshots_and_asset_metadata(
    test_session_factory,
):
    earlier_captured_at = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)
    captured_at = datetime(2026, 4, 15, 9, 30, tzinfo=UTC)

    async with test_session_factory() as session:
        await refresh_portfolio_state(
            session,
            captured_at=earlier_captured_at,
            holdings=[
                HoldingStats(
                    symbol="ETH",
                    asset_type="crypto",
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("1900"),
                    total_cost_usd=Decimal("1900"),
                    institution="binance",
                ),
                HoldingStats(
                    symbol="AAPL",
                    asset_type="equity",
                    quantity=Decimal("4"),
                    avg_buy_price_usd=Decimal("145"),
                    total_cost_usd=Decimal("580"),
                    institution="ibkr",
                ),
            ],
            prices={
                "ETH": 2400.0,
                "AAPL": 205.0,
                "SPY": 495.0,
                "BTC": 64000.0,
                "XAU": 2380.0,
            },
        )
        await session.commit()

        await refresh_portfolio_state(
            session,
            captured_at=captured_at,
            holdings=[
                HoldingStats(
                    symbol="ETH",
                    asset_type="crypto",
                    quantity=Decimal("2"),
                    avg_buy_price_usd=Decimal("2000"),
                    total_cost_usd=Decimal("4000"),
                    institution="binance",
                ),
                HoldingStats(
                    symbol="AAPL",
                    asset_type="equity",
                    quantity=Decimal("5"),
                    avg_buy_price_usd=Decimal("150"),
                    total_cost_usd=Decimal("750"),
                    institution="ibkr",
                ),
            ],
            prices={
                "ETH": 2500.0,
                "AAPL": 210.0,
                "SPY": 500.0,
                "BTC": 65000.0,
                "XAU": 2400.0,
            },
        )
        await session.commit()

        await refresh_portfolio_state(
            session,
            captured_at=captured_at,
            holdings=[
                HoldingStats(
                    symbol="ETH",
                    asset_type="crypto",
                    quantity=Decimal("1.5"),
                    avg_buy_price_usd=Decimal("2100"),
                    total_cost_usd=Decimal("3150"),
                    institution="binance",
                )
            ],
            prices={
                "ETH": 2600.0,
                "SPY": 505.0,
                "BTC": 66000.0,
            },
        )
        await session.commit()

        snapshot_rows = (
            await session.execute(
                select(PositionSnapshot, Asset.symbol)
                .join(Asset, Asset.id == PositionSnapshot.asset_id)
                .where(PositionSnapshot.captured_at == captured_at)
                .order_by(Asset.symbol.asc())
            )
        ).all()
        asset_rows = (
            (await session.execute(select(Asset).order_by(Asset.symbol.asc())))
            .scalars()
            .all()
        )
        benchmark_rows = (
            (
                await session.execute(
                    select(BenchmarkQuote)
                    .where(BenchmarkQuote.captured_at == captured_at)
                    .order_by(BenchmarkQuote.symbol.asc())
                )
            )
            .scalars()
            .all()
        )

    assert [(symbol, snapshot.quantity) for snapshot, symbol in snapshot_rows] == [
        ("ETH", Decimal("1.5000000000"))
    ]
    asset_by_symbol = {asset.symbol: asset for asset in asset_rows}
    assert asset_by_symbol["AAPL"].last_seen_at == earlier_captured_at
    assert asset_by_symbol["AAPL"].last_price_usd == Decimal("205.000000")
    assert asset_by_symbol["ETH"].last_seen_at == captured_at
    assert asset_by_symbol["ETH"].last_price_usd == Decimal("2600.000000")
    assert [(row.symbol, row.price_usd) for row in benchmark_rows] == [
        ("BTC", Decimal("66000.000000")),
        ("SPY", Decimal("505.000000")),
    ]


async def test_refresh_portfolio_state_empty_refresh_keeps_latest_timestamp_representable(
    test_session_factory,
):
    earlier_captured_at = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)
    captured_at = datetime(2026, 4, 15, 10, 30, tzinfo=UTC)

    async with test_session_factory() as session:
        await refresh_portfolio_state(
            session,
            captured_at=earlier_captured_at,
            holdings=[
                HoldingStats(
                    symbol="BTC",
                    asset_type="crypto",
                    quantity=Decimal("1"),
                    avg_buy_price_usd=Decimal("50000"),
                    total_cost_usd=Decimal("50000"),
                    institution="binance",
                )
            ],
            prices={
                "BTC": 70000.0,
                "SPY": 500.0,
                "XAU": 2400.0,
            },
        )
        await session.commit()

        result = await refresh_portfolio_state(
            session,
            captured_at=captured_at,
            holdings=[],
            prices={},
        )
        await session.commit()

        latest_snapshot_captured_at = await session.scalar(
            select(func.max(PositionSnapshot.captured_at))
        )
        latest_benchmark_captured_at = await session.scalar(
            select(func.max(BenchmarkQuote.captured_at))
        )

    assert result.asset_count == 0
    assert result.snapshot_count == 0
    assert result.benchmark_count == 0
    assert latest_snapshot_captured_at == captured_at
    assert latest_benchmark_captured_at == captured_at


async def test_refresh_portfolio_state_rejects_duplicate_symbol_input(
    test_session_factory,
):
    captured_at = datetime(2026, 4, 15, 9, 45, tzinfo=UTC)

    async with test_session_factory() as session:
        with pytest.raises(
            ValueError, match="Duplicate holding symbols are not allowed: BTC"
        ):
            await refresh_portfolio_state(
                session,
                captured_at=captured_at,
                holdings=[
                    HoldingStats(
                        symbol="BTC",
                        asset_type="crypto",
                        quantity=Decimal("1"),
                        avg_buy_price_usd=Decimal("50000"),
                        total_cost_usd=Decimal("50000"),
                        institution="binance",
                    ),
                    HoldingStats(
                        symbol="BTC",
                        asset_type="crypto",
                        quantity=Decimal("2"),
                        avg_buy_price_usd=Decimal("55000"),
                        total_cost_usd=Decimal("110000"),
                        institution="binance",
                    ),
                ],
                prices={
                    "BTC": 70000.0,
                    "SPY": 500.0,
                    "XAU": 2400.0,
                },
            )

        asset_rows = (await session.execute(select(Asset))).scalars().all()
        snapshot_rows = (
            (await session.execute(select(PositionSnapshot))).scalars().all()
        )

    assert asset_rows == []
    assert snapshot_rows == []


async def test_refresh_portfolio_state_uses_holdings_and_price_pipeline_when_inputs_omitted(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    captured_at = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)
    requested_symbols: list[str] = []

    async def fake_get_prices_bulk(symbols: list[str]) -> dict[str, float | None]:
        requested_symbols.extend(symbols)
        return {
            "MSFT": 420.0,
            "SPY": 500.0,
            "BTC": 65000.0,
            "XAU": 2400.0,
        }

    monkeypatch.setattr(
        "app.services.portfolio_state.pricing.get_prices_bulk", fake_get_prices_bulk
    )

    async with test_session_factory() as session:
        session.add(
            Transaction(
                institution="ibkr",
                tx_type="buy",
                asset_symbol="MSFT",
                asset_type="equity",
                quantity=Decimal("3"),
                price_usd=Decimal("300"),
                total_usd=Decimal("900"),
                fee=Decimal("0"),
                fee_currency="USD",
                timestamp=datetime(2026, 4, 10, 12, 0, tzinfo=UTC),
                fingerprint="portfolio-state-msft-buy",
                raw_data={},
            )
        )
        await session.commit()

        result = await refresh_portfolio_state(session, captured_at=captured_at)
        await session.commit()

        snapshot_rows = (
            (await session.execute(select(PositionSnapshot))).scalars().all()
        )
        benchmark_rows = (
            (
                await session.execute(
                    select(BenchmarkQuote).order_by(BenchmarkQuote.symbol.asc())
                )
            )
            .scalars()
            .all()
        )

    assert result.asset_count == 1
    assert result.snapshot_count == 1
    assert result.benchmark_count == 3
    assert requested_symbols == ["MSFT", "SPY", "BTC", "XAU"]
    assert len(snapshot_rows) == 1
    assert snapshot_rows[0].current_price_usd == Decimal("420.000000")
    assert [(row.symbol, row.price_usd) for row in benchmark_rows] == [
        ("BTC", Decimal("65000.000000")),
        ("SPY", Decimal("500.000000")),
        ("XAU", Decimal("2400.000000")),
    ]
