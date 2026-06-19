from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import app.db.session as db_session
import app.main as main_module
import app.services.portfolio_state as portfolio_state_module
import app.services.scheduler_jobs as scheduler_jobs_module
import pytest
import pytest_asyncio
from fakeredis import FakeStrictRedis
from app.config import settings
from app.db.base import Base
from app.db.models import ActivityLog, Asset, PendingOrder, Transaction, User
from app.db.safety import (
    DEFAULT_TEST_DATABASE_SERVER_URL,
    build_temporary_test_database_url,
    pick_safe_test_database_server_url,
    quote_postgresql_identifier,
)
from app.main import create_application
from app.services.analytics import HoldingStats
from app.services.auth import hash_password
from app.services.portfolio_state import refresh_portfolio_state
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


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
        pytest.skip("portfolio state API tests require a PostgreSQL DATABASE_URL")

    database_url = build_temporary_test_database_url(
        base_url,
        name_prefix="portfolio_state_api",
        context="api/tests/api/test_portfolio_state_api.py",
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


@pytest.fixture
def app(test_session_factory, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def readiness_probe() -> None:
        return None

    engine = test_session_factory.kw["bind"]
    monkeypatch.setattr(db_session, "async_session_factory", test_session_factory)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(main_module, "async_session_factory", test_session_factory)
    monkeypatch.setattr(main_module, "engine", engine)

    return create_application(
        run_startup_db_init=False,
        run_startup_repairs=False,
        run_scheduler=False,
        readiness_check=readiness_probe,
    )


@pytest.fixture
def password() -> str:
    return "correct-horse-battery-staple"


@pytest.fixture
def auth_header():
    def _auth_header(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _auth_header


@pytest.fixture
def create_user(password: str, test_session_factory):
    async def _create_user() -> User:
        username = f"portfolio-api-{uuid4().hex}"
        async with test_session_factory() as session:
            user = User(
                username=username,
                password_hash=hash_password(password),
                totp_enabled=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _create_user


@pytest.fixture
def login(create_user, password: str, auth_header):
    async def _login(async_client):
        user = await create_user()
        response = await async_client.post(
            "/v1/auth/login",
            json={"username": user.username, "password": password},
        )
        assert response.status_code == 200
        access_token = response.json()["access_token"]
        return user, auth_header(access_token)

    return _login


@pytest.fixture
def seed_portfolio_state(test_session_factory):
    async def _seed() -> datetime:
        captured_at = datetime(2026, 4, 15, 11, 30, tzinfo=UTC)

        async with test_session_factory() as session:
            await refresh_portfolio_state(
                session,
                captured_at=captured_at,
                holdings=[
                    HoldingStats(
                        symbol="BTC",
                        asset_type="crypto",
                        quantity=Decimal("1.5"),
                        avg_buy_price_usd=Decimal("50000"),
                        total_cost_usd=Decimal("75000"),
                        institution="binance",
                    ),
                    HoldingStats(
                        symbol="AAPL",
                        asset_type="equity",
                        quantity=Decimal("10"),
                        avg_buy_price_usd=Decimal("180"),
                        total_cost_usd=Decimal("1800"),
                        institution="ibkr",
                    ),
                ],
                prices={
                    "BTC": 70000.0,
                    "AAPL": 210.0,
                    "SPY": 505.25,
                    "XAU": 2400.5,
                },
            )

            btc_asset = (
                await session.execute(select(Asset).where(Asset.symbol == "BTC"))
            ).scalar_one()
            session.add(
                PendingOrder(
                    asset_id=btc_asset.id,
                    institution="binance",
                    symbol="BTC",
                    external_order_id="ord-002",
                    order_type="limit",
                    status="open",
                    side="buy",
                    quantity=Decimal("0.2500000000"),
                    limit_price=Decimal("64000.000000"),
                    stop_price=None,
                    placed_at=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
                )
            )
            session.add(
                PendingOrder(
                    asset_id=btc_asset.id,
                    institution="xtb",
                    symbol="BTC",
                    external_order_id="ord-001",
                    order_type="stop",
                    status="pending",
                    side="sell",
                    quantity=Decimal("0.1000000000"),
                    limit_price=None,
                    stop_price=Decimal("61000.000000"),
                    placed_at=None,
                )
            )
            session.add(
                PendingOrder(
                    asset_id=btc_asset.id,
                    institution="binance",
                    symbol="BTC",
                    external_order_id="ord-999",
                    order_type="market",
                    status="filled",
                    side="sell",
                    quantity=Decimal("0.5000000000"),
                    limit_price=None,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
                )
            )
            await session.commit()

        return captured_at

    return _seed


async def test_portfolio_state_endpoints_expose_persisted_foundation_data(
    async_client,
    login,
    seed_portfolio_state,
):
    _, headers = await login(async_client)
    captured_at = await seed_portfolio_state()

    assets_response = await async_client.get("/v1/portfolio/assets", headers=headers)
    latest_snapshots_response = await async_client.get(
        "/v1/portfolio/snapshots/latest",
        headers=headers,
    )
    latest_benchmarks_response = await async_client.get(
        "/v1/portfolio/benchmarks/latest",
        headers=headers,
    )
    pending_orders_response = await async_client.get(
        "/v1/portfolio/pending-orders",
        headers=headers,
    )

    assert assets_response.status_code == 200
    assert assets_response.json() == [
        {
            "symbol": "AAPL",
            "asset_type": "equity",
            "last_price_usd": 210.0,
            "last_seen_at": captured_at.isoformat(),
        },
        {
            "symbol": "BTC",
            "asset_type": "crypto",
            "last_price_usd": 70000.0,
            "last_seen_at": captured_at.isoformat(),
        },
    ]

    assert latest_snapshots_response.status_code == 200
    assert latest_snapshots_response.json() == {
        "captured_at": captured_at.isoformat(),
        "snapshots": [
            {
                "symbol": "AAPL",
                "asset_type": "equity",
                "quantity": 10.0,
                "avg_buy_price_usd": 180.0,
                "total_cost_usd": 1800.0,
                "current_price_usd": 210.0,
                "current_value_usd": 2100.0,
                "unrealized_pnl_usd": 300.0,
                "unrealized_pnl_pct": pytest.approx(16.6666666667),
                "freshness": {
                    "source": "persisted_position_snapshot",
                    "as_of": captured_at.isoformat(),
                    "stale": False,
                    "degraded": False,
                    "fallback": False,
                    "warnings": [],
                },
            },
            {
                "symbol": "BTC",
                "asset_type": "crypto",
                "quantity": 1.5,
                "avg_buy_price_usd": 50000.0,
                "total_cost_usd": 75000.0,
                "current_price_usd": 70000.0,
                "current_value_usd": 105000.0,
                "unrealized_pnl_usd": 30000.0,
                "unrealized_pnl_pct": 40.0,
                "freshness": {
                    "source": "persisted_position_snapshot",
                    "as_of": captured_at.isoformat(),
                    "stale": False,
                    "degraded": False,
                    "fallback": False,
                    "warnings": [],
                },
            },
        ],
        "freshness": {
            "source": "persisted_position_snapshot",
            "as_of": captured_at.isoformat(),
            "stale": False,
            "degraded": False,
            "fallback": False,
            "warnings": [],
        },
    }

    assert latest_benchmarks_response.status_code == 200
    assert latest_benchmarks_response.json() == {
        "captured_at": captured_at.isoformat(),
        "quotes": [
            {
                "symbol": "BTC",
                "price_usd": 70000.0,
                "freshness": {
                    "source": "persisted_benchmark_quote",
                    "as_of": captured_at.isoformat(),
                    "stale": False,
                    "degraded": False,
                    "fallback": False,
                    "warnings": [],
                },
            },
            {
                "symbol": "SPY",
                "price_usd": 505.25,
                "freshness": {
                    "source": "persisted_benchmark_quote",
                    "as_of": captured_at.isoformat(),
                    "stale": False,
                    "degraded": False,
                    "fallback": False,
                    "warnings": [],
                },
            },
            {
                "symbol": "XAU",
                "price_usd": 2400.5,
                "freshness": {
                    "source": "persisted_benchmark_quote",
                    "as_of": captured_at.isoformat(),
                    "stale": False,
                    "degraded": False,
                    "fallback": False,
                    "warnings": [],
                },
            },
        ],
        "freshness": {
            "source": "persisted_benchmark_quote",
            "as_of": captured_at.isoformat(),
            "stale": False,
            "degraded": False,
            "fallback": False,
            "warnings": [],
        },
    }

    assert pending_orders_response.status_code == 200
    assert pending_orders_response.json() == [
        {
            "institution": "binance",
            "symbol": "BTC",
            "external_order_id": "ord-002",
            "order_type": "limit",
            "status": "open",
            "side": "buy",
            "quantity": 0.25,
            "limit_price": 64000.0,
            "stop_price": None,
            "placed_at": "2026-04-15T10:00:00+00:00",
        },
        {
            "institution": "xtb",
            "symbol": "BTC",
            "external_order_id": "ord-001",
            "order_type": "stop",
            "status": "pending",
            "side": "sell",
            "quantity": 0.1,
            "limit_price": None,
            "stop_price": 61000.0,
            "placed_at": None,
        },
    ]


async def test_refresh_endpoint_allows_explicit_capture_time_and_empty_pending_orders(
    async_client,
    login,
    monkeypatch: pytest.MonkeyPatch,
):
    _, headers = await login(async_client)
    captured_at = "2026-04-15T12:00:00+00:00"

    async def fake_get_holdings(_session):
        return []

    async def fake_get_prices_bulk(_symbols):
        return {}

    monkeypatch.setattr(
        portfolio_state_module.analytics, "get_holdings", fake_get_holdings
    )
    monkeypatch.setattr(
        portfolio_state_module.pricing,
        "get_prices_bulk",
        fake_get_prices_bulk,
    )
    monkeypatch.setattr(
        scheduler_jobs_module,
        "get_redis_connection",
        lambda: FakeStrictRedis(),
    )

    refresh_response = await async_client.post(
        "/v1/portfolio/state/refresh",
        headers=headers,
        json={"captured_at": captured_at},
    )
    pending_orders_response = await async_client.get(
        "/v1/portfolio/pending-orders",
        headers=headers,
    )
    latest_snapshots_response = await async_client.get(
        "/v1/portfolio/snapshots/latest",
        headers=headers,
    )
    latest_benchmarks_response = await async_client.get(
        "/v1/portfolio/benchmarks/latest",
        headers=headers,
    )

    assert refresh_response.status_code == 200
    assert refresh_response.json() == {
        "captured_at": captured_at,
        "asset_count": 0,
        "snapshot_count": 0,
        "benchmark_count": 0,
    }

    assert pending_orders_response.status_code == 200
    assert pending_orders_response.json() == []

    assert latest_snapshots_response.status_code == 200
    assert latest_snapshots_response.json() == {
        "captured_at": captured_at,
        "snapshots": [],
        "freshness": {
            "source": "persisted_position_snapshot",
            "as_of": captured_at,
            "stale": False,
            "degraded": False,
            "fallback": False,
            "warnings": ["latest snapshot has no current position rows"],
        },
    }

    assert latest_benchmarks_response.status_code == 200
    assert latest_benchmarks_response.json() == {
        "captured_at": captured_at,
        "quotes": [],
        "freshness": {
            "source": "persisted_benchmark_quote",
            "as_of": captured_at,
            "stale": False,
            "degraded": False,
            "fallback": False,
            "warnings": ["latest benchmark capture has no quote rows"],
        },
    }


async def test_refresh_endpoint_empty_refresh_supersedes_older_latest_state(
    async_client,
    login,
    seed_portfolio_state,
    monkeypatch: pytest.MonkeyPatch,
):
    _, headers = await login(async_client)
    await seed_portfolio_state()
    captured_at = "2026-04-15T12:00:00+00:00"

    async def fake_get_holdings(_session):
        return []

    async def fake_get_prices_bulk(_symbols):
        return {}

    monkeypatch.setattr(
        portfolio_state_module.analytics, "get_holdings", fake_get_holdings
    )
    monkeypatch.setattr(
        portfolio_state_module.pricing,
        "get_prices_bulk",
        fake_get_prices_bulk,
    )
    monkeypatch.setattr(
        scheduler_jobs_module,
        "get_redis_connection",
        lambda: FakeStrictRedis(),
    )

    refresh_response = await async_client.post(
        "/v1/portfolio/state/refresh",
        headers=headers,
        json={"captured_at": captured_at},
    )
    latest_snapshots_response = await async_client.get(
        "/v1/portfolio/snapshots/latest",
        headers=headers,
    )
    latest_benchmarks_response = await async_client.get(
        "/v1/portfolio/benchmarks/latest",
        headers=headers,
    )

    assert refresh_response.status_code == 200
    assert refresh_response.json() == {
        "captured_at": captured_at,
        "asset_count": 0,
        "snapshot_count": 0,
        "benchmark_count": 0,
    }

    assert latest_snapshots_response.status_code == 200
    assert latest_snapshots_response.json() == {
        "captured_at": captured_at,
        "snapshots": [],
        "freshness": {
            "source": "persisted_position_snapshot",
            "as_of": captured_at,
            "stale": False,
            "degraded": False,
            "fallback": False,
            "warnings": ["latest snapshot has no current position rows"],
        },
    }

    assert latest_benchmarks_response.status_code == 200
    assert latest_benchmarks_response.json() == {
        "captured_at": captured_at,
        "quotes": [],
        "freshness": {
            "source": "persisted_benchmark_quote",
            "as_of": captured_at,
            "stale": False,
            "degraded": False,
            "fallback": False,
            "warnings": ["latest benchmark capture has no quote rows"],
        },
    }


async def test_refresh_endpoint_rejects_duplicate_symbols_from_holdings_pipeline(
    async_client,
    login,
    monkeypatch: pytest.MonkeyPatch,
):
    _, headers = await login(async_client)

    async def fake_get_holdings(_session):
        return [
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
                avg_buy_price_usd=Decimal("60000"),
                total_cost_usd=Decimal("120000"),
                institution="xtb",
            ),
        ]

    monkeypatch.setattr(
        portfolio_state_module.analytics, "get_holdings", fake_get_holdings
    )

    response = await async_client.post(
        "/v1/portfolio/state/refresh",
        headers=headers,
        json={"captured_at": datetime(2026, 4, 16, 12, 0, tzinfo=UTC).isoformat()},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Duplicate holding symbols are not allowed: BTC"
    }


async def test_transactions_endpoint_uses_stable_timestamp_and_id_ordering(
    async_client,
    login,
    test_session_factory,
):
    _, headers = await login(async_client)

    async with test_session_factory() as session:
        session.add_all(
            [
                Transaction(
                    institution="xtb",
                    tx_type="buy",
                    asset_symbol="AAA",
                    asset_type="equity",
                    quantity=Decimal("1"),
                    price_usd=Decimal("10"),
                    total_usd=Decimal("10"),
                    fee=Decimal("0"),
                    fee_currency="USD",
                    timestamp=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
                    fingerprint="stable-order-1",
                    raw_data={},
                ),
                Transaction(
                    institution="xtb",
                    tx_type="buy",
                    asset_symbol="BBB",
                    asset_type="equity",
                    quantity=Decimal("1"),
                    price_usd=Decimal("10"),
                    total_usd=Decimal("10"),
                    fee=Decimal("0"),
                    fee_currency="USD",
                    timestamp=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
                    fingerprint="stable-order-2",
                    raw_data={},
                ),
            ]
        )
        await session.commit()

        inserted = (
            (
                await session.execute(
                    select(Transaction)
                    .where(
                        Transaction.fingerprint.in_(
                            ["stable-order-1", "stable-order-2"]
                        )
                    )
                    .order_by(Transaction.id.asc())
                )
            )
            .scalars()
            .all()
        )

    response = await async_client.get(
        "/v1/portfolio/transactions?limit=2&offset=0",
        headers=headers,
    )

    assert response.status_code == 200
    assert [tx["id"] for tx in response.json()] == [inserted[1].id, inserted[0].id]


@pytest.mark.asyncio
async def test_sync_freshness_includes_owned_polling_status(
    async_client, login, test_session_factory
):
    _, headers = await login(async_client)
    captured_at = datetime.now(UTC)
    async with test_session_factory() as session:
        session.add(
            ActivityLog(
                source="owned_polling.refresh",
                status="success",
                message=f"captured_at={captured_at.isoformat()}",
                created_at=captured_at,
            )
        )
        await session.commit()

    response = await async_client.get("/v1/sync/freshness", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert "owned_polling" in payload
    owned = payload["owned_polling"]
    assert owned["last_success_at"] == captured_at.isoformat()
    assert owned["stale"] is False
    assert owned["next_run_at"] is not None
