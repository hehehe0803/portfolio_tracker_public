from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import pytest
import pytest_asyncio
from app.config import settings
from app.db.base import Base
from app.db.models import ImportArtifact, Transaction
from app.db.safety import (
    DEFAULT_TEST_DATABASE_SERVER_URL,
    assert_safe_destructive_database_url,
    pick_safe_test_database_server_url,
    quote_postgresql_identifier,
)
from app.services.binance_ingest import confirm_binance_import, parse_binance_file
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def _resolve_database_url():
    return make_url(
        pick_safe_test_database_server_url(
            settings.DATABASE_URL,
            default_url=DEFAULT_TEST_DATABASE_SERVER_URL,
        )
    )


def _assert_safe_test_database_url(database_url: str, context: str) -> None:
    assert_safe_destructive_database_url(database_url, context=context)


async def _create_temporary_database() -> str:
    base_url = _resolve_database_url()
    if base_url.get_backend_name() != "postgresql":
        pytest.skip("binance import flow tests require PostgreSQL")

    database_name = f"portfolio_tracker_binance_test_{uuid4().hex}"
    temp_database_url = base_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    _assert_safe_test_database_url(
        temp_database_url,
        context="tests/binance/test_binance_import_flow.py:create",
    )
    quoted_database_name = quote_postgresql_identifier(database_name)

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
        pytest.skip(f"unable to create disposable postgres database: {exc}")

    await admin_engine.dispose()
    return base_url.set(database=database_name).render_as_string(hide_password=False)


async def _drop_temporary_database(database_url: str) -> None:
    temp_url = make_url(database_url)
    _assert_safe_test_database_url(
        database_url,
        context="tests/binance/test_binance_import_flow.py:drop",
    )
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


def _build_binance_export_zip() -> bytes:
    members = {
        "Binance-Spot-Trade-History-202604201027(UTC+7).csv": (
            "Time,Pair,Side,Price,Executed,Amount,Fee\n"
            "25-10-11 01:01:13,BTCUSDT,BUY,60000,0.01000000BTC,600.00000000USDT,0.00001000BTC\n"
        ),
        "Binance-Deposit-History-202604201017(UTC+7).csv": (
            "Time,Coin,Network,Amount,Address,TXID,Status\n"
            "25-10-10 15:28:51,USDT,BSC,1000.0,0xabc,tx-1,Completed\n"
        ),
        "Binance-Transaction-History-202604201017(UTC+7).csv": (
            "User ID,Time,Account,Operation,Coin,Change,Remark\n"
            "1,25-10-10 13:00:00,Funding,P2P Trading,USDT,1000.00,P2P - order-1\n"
            "1,25-10-10 13:05:00,Funding,Transfer Between Main and Funding Wallet,USDT,-600.00,\n"
            "1,25-10-10 13:05:00,Spot,Transfer Between Main and Funding Wallet,USDT,600.00,\n"
        ),
    }
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buff.getvalue()


@pytest.mark.asyncio
async def test_parse_and_confirm_binance_import_is_idempotent(test_session_factory):
    file_bytes = _build_binance_export_zip()

    async with test_session_factory() as session:
        artifact = await parse_binance_file(file_bytes, "binance-export.zip", session)
        assert artifact.status == "reviewed"
        assert artifact.parsed_count == 5
        assert artifact.duplicate_count == 0
        assert artifact.parse_preview["total_parsed"] == 5
        assert artifact.parse_preview["summary"]["by_type"]["spot_trade_buy"] == 1

        result = await confirm_binance_import(artifact.id, session)
        assert result == {
            "committed": 5,
            "duplicates_skipped": 0,
            "artifact_id": artifact.id,
        }

    async with test_session_factory() as session:
        txs = (
            (
                await session.execute(
                    select(Transaction).order_by(Transaction.timestamp, Transaction.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(txs) == 5
        assert {tx.tx_type for tx in txs} == {
            "deposit",
            "external_deposit",
            "spot_trade_buy",
            "transfer_in",
            "transfer_out",
        }
        buy_tx = next(tx for tx in txs if tx.tx_type == "spot_trade_buy")
        assert buy_tx.asset_symbol == "BTC"
        assert buy_tx.total_usd == 600
        assert buy_tx.import_id is not None
        assert buy_tx.raw_data["source_type"] == "spot_trade"

    async with test_session_factory() as session:
        artifact_2 = await parse_binance_file(file_bytes, "binance-export.zip", session)
        assert artifact_2.status == "reviewed"
        assert artifact_2.parsed_count == 5
        assert artifact_2.duplicate_count == 5

        result_2 = await confirm_binance_import(artifact_2.id, session)
        assert result_2 == {
            "committed": 0,
            "duplicates_skipped": 5,
            "artifact_id": artifact_2.id,
        }

        artifacts = (
            (await session.execute(select(ImportArtifact).order_by(ImportArtifact.id)))
            .scalars()
            .all()
        )
        assert [artifact.committed_count for artifact in artifacts] == [5, 0]
