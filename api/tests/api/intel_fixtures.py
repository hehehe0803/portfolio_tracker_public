from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import app.db.session as db_session
import app.main as main_module
import pytest
import pytest_asyncio
from app.api import deps
from app.db.base import Base
from app.db.models import Asset, User
from app.db.safety import (
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    assert_safe_destructive_database_url,
    pick_safe_test_database_url,
)
from app.main import create_application
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = pick_safe_test_database_url(
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    default_url=DEFAULT_LOCAL_PYTEST_DATABASE_URL,
)


@pytest_asyncio.fixture
async def intel_session_factory():
    assert_safe_destructive_database_url(
        TEST_DATABASE_URL,
        context="api/tests/api/intel_fixtures.py",
    )
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as session:
        session.add(User(id=1, username="intel-tester", password_hash="test"))
        await session.commit()
    try:
        yield session_factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def app(intel_session_factory, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    async def readiness_probe() -> None:
        return None

    engine = intel_session_factory.kw["bind"]
    monkeypatch.setattr(db_session, "async_session_factory", intel_session_factory)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(main_module, "async_session_factory", intel_session_factory)
    monkeypatch.setattr(main_module, "engine", engine)
    application = create_application(run_startup_db_init=False, run_startup_repairs=False, run_scheduler=False, readiness_check=readiness_probe)

    async def _override_user():
        return SimpleNamespace(id=1, username="intel-tester", telegram_chat_id=None, totp_enabled=False)

    application.dependency_overrides[deps.get_current_user] = _override_user
    return application


@pytest_asyncio.fixture
async def seeded_asset(intel_session_factory) -> AsyncIterator[Asset]:
    async with intel_session_factory() as session:
        asset = Asset(symbol="AAPL", asset_type="equity")
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
        yield asset
