from __future__ import annotations

import os
from uuid import uuid4

import app.db.session as db_session
import app.main as main_module
import pytest
import pytest_asyncio
from app.db.base import Base
from app.db.models import User
from app.db.safety import (
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    pick_safe_test_database_url,
)
from app.main import create_application
from app.services.auth import hash_password
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
)
TEST_DATABASE_URL = pick_safe_test_database_url(
    TEST_DATABASE_URL,
    default_url=DEFAULT_LOCAL_PYTEST_DATABASE_URL,
)


@pytest_asyncio.fixture
async def test_session_factory():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield session_factory
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


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
        username = f"auth-test-{uuid4().hex}"
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


async def test_login_returns_tokens_and_me_uses_access_token(
    async_client,
    create_user,
    password: str,
    auth_header,
):
    user = await create_user()

    login_response = await async_client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": password},
    )

    assert login_response.status_code == 200
    tokens = login_response.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"
    assert tokens["totp_required"] is False

    me_response = await async_client.get(
        "/v1/auth/me",
        headers=auth_header(tokens["access_token"]),
    )

    assert me_response.status_code == 200
    assert me_response.json() == {
        "id": user.id,
        "username": user.username,
        "totp_enabled": False,
        "telegram_configured": False,
    }


async def test_refresh_rotates_refresh_token_and_rejects_reuse(
    async_client,
    create_user,
    password: str,
):
    user = await create_user()

    login_response = await async_client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": password},
    )
    refresh_token = login_response.json()["refresh_token"]

    refresh_response = await async_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 200
    rotated_refresh_token = refresh_response.json()["refresh_token"]
    assert rotated_refresh_token
    assert rotated_refresh_token != refresh_token

    reuse_response = await async_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert reuse_response.status_code == 401


async def test_logout_revokes_session_and_refresh_token(
    async_client,
    create_user,
    password: str,
    auth_header,
):
    user = await create_user()

    login_response = await async_client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": password},
    )
    tokens = login_response.json()

    logout_response = await async_client.post(
        "/v1/auth/logout",
        headers=auth_header(tokens["access_token"]),
    )

    assert logout_response.status_code == 200
    assert logout_response.json() == {"message": "Logged out"}

    refresh_response = await async_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert refresh_response.status_code == 401


async def test_me_rejects_access_token_for_revoked_session(
    async_client,
    create_user,
    password: str,
    auth_header,
):
    user = await create_user()

    login_response = await async_client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": password},
    )
    access_token = login_response.json()["access_token"]

    logout_response = await async_client.post(
        "/v1/auth/logout",
        headers=auth_header(access_token),
    )
    assert logout_response.status_code == 200

    me_response = await async_client.get(
        "/v1/auth/me",
        headers=auth_header(access_token),
    )

    assert me_response.status_code == 401


async def test_auth_refresh_route_emits_operation_telemetry(
    async_client,
    app,
    create_user,
    password: str,
):
    user = await create_user()

    login_response = await async_client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": password},
    )
    refresh_token = login_response.json()["refresh_token"]

    refresh_response = await async_client.post(
        "/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 200
    telemetry_events = app.state.telemetry.snapshot()
    assert any(
        event["event_type"] == "operation"
        and event["name"] == "auth.refresh"
        and event["outcome"] == "success"
        and event["user_id"] == user.id
        for event in telemetry_events
    )
    assert any(
        event["event_type"] == "request"
        and event["route"] == "/v1/auth/refresh"
        and event["status_code"] == 200
        and event["sensitive"] is True
        for event in telemetry_events
    )


async def test_auth_login_rate_limit_returns_429_with_deterministic_headers(
    async_client,
    app,
    create_user,
    password: str,
):
    user = await create_user()
    fake_now = {"value": 0.0}
    app.state.rate_limiter._clock = lambda: fake_now["value"]

    responses = []
    for _ in range(6):
        responses.append(
            await async_client.post(
                "/v1/auth/login",
                json={"username": user.username, "password": password},
            )
        )

    assert [response.status_code for response in responses[:5]] == [
        200,
        200,
        200,
        200,
        200,
    ]
    assert responses[5].status_code == 429
    assert responses[5].json() == {"detail": "Rate limit exceeded"}
    assert responses[5].headers["Retry-After"] == "60"
    assert responses[5].headers["X-RateLimit-Limit"] == "5"
    assert responses[5].headers["X-RateLimit-Remaining"] == "0"
    assert responses[5].headers["X-RateLimit-Rule"] == "auth"

    telemetry_events = app.state.telemetry.snapshot()
    assert any(
        event["event_type"] == "request"
        and event["route"] == "/v1/auth/login"
        and event["status_code"] == 429
        and event["rate_limited"] is True
        and event["rule_name"] == "auth"
        for event in telemetry_events
    )


async def test_auth_refresh_rate_limit_returns_429_with_deterministic_headers(
    async_client,
    app,
    create_user,
    password: str,
):
    user = await create_user()
    fake_now = {"value": 0.0}
    app.state.rate_limiter._clock = lambda: fake_now["value"]

    login_response = await async_client.post(
        "/v1/auth/login",
        json={"username": user.username, "password": password},
    )
    refresh_token = login_response.json()["refresh_token"]

    responses = []
    for _ in range(6):
        responses.append(
            await async_client.post(
                "/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )
        )
        if responses[-1].status_code == 200:
            refresh_token = responses[-1].json()["refresh_token"]

    assert [response.status_code for response in responses[:5]] == [
        200,
        200,
        200,
        200,
        200,
    ]
    assert responses[5].status_code == 429
    assert responses[5].json() == {"detail": "Rate limit exceeded"}
    assert responses[5].headers["Retry-After"] == "60"
    assert responses[5].headers["X-RateLimit-Limit"] == "5"
    assert responses[5].headers["X-RateLimit-Remaining"] == "0"
    assert responses[5].headers["X-RateLimit-Rule"] == "auth"

    telemetry_events = app.state.telemetry.snapshot()
    assert any(
        event["event_type"] == "request"
        and event["route"] == "/v1/auth/refresh"
        and event["status_code"] == 429
        and event["rate_limited"] is True
        and event["rule_name"] == "auth"
        for event in telemetry_events
    )
