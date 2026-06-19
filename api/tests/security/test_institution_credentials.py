from __future__ import annotations

import io
import os
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import app.config as app_config
import app.db.session as db_session
import app.main as main_module
import pytest
import pytest_asyncio
from fakeredis import FakeStrictRedis
from app.db.base import Base
from app.db.models import (
    ActivityLog,
    Asset,
    ImportArtifact,
    Institution,
    PendingOrder,
    Transaction,
    User,
)
from app.db.safety import (
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    pick_safe_test_database_url,
)
from app.main import create_application
from app.services.auth import hash_password
from app.services.binance_ingest import confirm_binance_import, parse_binance_file
from app.services.binance_client import BinanceError
from app.services.binance_sync import _normalize_simple_earn_history, sync_binance
from app.services.credentials import (
    CredentialCipher,
    CredentialConfigError,
    InvalidCredentialError,
)
from fastapi import FastAPI
from sqlalchemy import select
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
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )

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
        username = f"security-test-{uuid4().hex}"
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
def login(async_client, create_user, password: str):
    async def _login() -> tuple[User, str]:
        user = await create_user()
        response = await async_client.post(
            "/v1/auth/login",
            json={"username": user.username, "password": password},
        )
        assert response.status_code == 200
        return user, response.json()["access_token"]

    return _login


async def test_credential_cipher_round_trip_requires_matching_key() -> None:
    plaintext = "binance-secret-value"
    encrypted = CredentialCipher("security-test-master-key").encrypt(plaintext)

    assert encrypted != plaintext
    assert CredentialCipher("security-test-master-key").decrypt(encrypted) == plaintext

    with pytest.raises(InvalidCredentialError):
        CredentialCipher("wrong-master-key").decrypt(encrypted)


async def test_set_binance_keys_encrypts_at_rest_and_writes_audit_log(
    async_client,
    app,
    auth_header,
    login,
    test_session_factory,
) -> None:
    user, access_token = await login()

    response = await async_client.post(
        "/v1/settings/binance-keys",
        json={"api_key": "plain-key", "api_secret": "plain-secret"},
        headers=auth_header(access_token),
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Binance keys updated"
    assert response.json()["rotated"] is False

    async with test_session_factory() as session:
        institution = (
            await session.execute(
                select(Institution).where(Institution.name == "binance")
            )
        ).scalar_one()
        activity_log = (
            await session.execute(
                select(ActivityLog).where(ActivityLog.user_id == user.id)
            )
        ).scalar_one()

    assert institution.api_key_encrypted != "plain-key"
    assert institution.api_secret_encrypted != "plain-secret"
    assert "plain-key" not in institution.api_key_encrypted
    assert "plain-secret" not in institution.api_secret_encrypted
    assert institution.credential_rotation_count == 0
    assert institution.get_api_credentials()["api_key"] == "plain-key"
    assert institution.get_api_credentials()["api_secret"] == "plain-secret"
    assert activity_log.source == "settings.binance_credentials"
    assert activity_log.status == "updated"
    telemetry_events = app.state.telemetry.snapshot()
    assert any(
        event["event_type"] == "operation"
        and event["name"] == "settings.binance_credentials.update"
        and event["outcome"] == "success"
        and event["user_id"] == user.id
        for event in telemetry_events
    )
    assert any(
        event["event_type"] == "request"
        and event["route"] == "/v1/settings/binance-keys"
        and event["status_code"] == 200
        and event["sensitive"] is True
        for event in telemetry_events
    )


async def test_rotate_binance_keys_initializes_rotation_count_for_first_time_use(
    async_client,
    auth_header,
    login,
    test_session_factory,
) -> None:
    _, access_token = await login()

    rotate_response = await async_client.post(
        "/v1/settings/binance-keys/rotate",
        json={
            "api_key": "first-rotation-key",
            "api_secret": "first-rotation-secret",
            "reason": "initial-setup",
        },
        headers=auth_header(access_token),
    )

    assert rotate_response.status_code == 200
    assert rotate_response.json()["message"] == "Binance keys rotated"
    assert rotate_response.json()["rotated"] is True
    assert rotate_response.json()["rotation_count"] == 1

    async with test_session_factory() as session:
        institution = (
            await session.execute(
                select(Institution).where(Institution.name == "binance")
            )
        ).scalar_one()

    assert institution.credential_rotation_count == 1
    assert institution.get_api_credentials() == {
        "api_key": "first-rotation-key",
        "api_secret": "first-rotation-secret",
    }


async def test_rotate_binance_keys_reencrypts_credentials_and_sync_uses_new_values(
    async_client,
    auth_header,
    login,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory,
) -> None:
    _, access_token = await login()

    initial_response = await async_client.post(
        "/v1/settings/binance-keys",
        json={"api_key": "initial-key", "api_secret": "initial-secret"},
        headers=auth_header(access_token),
    )
    assert initial_response.status_code == 200

    async with test_session_factory() as session:
        institution_before = (
            await session.execute(
                select(Institution).where(Institution.name == "binance")
            )
        ).scalar_one()
        encrypted_before = institution_before.api_secret_encrypted
        updated_at_before = institution_before.credentials_updated_at

    rotate_response = await async_client.post(
        "/v1/settings/binance-keys/rotate",
        json={
            "api_key": "rotated-key",
            "api_secret": "rotated-secret",
            "reason": "scheduled-quarterly-rotation",
        },
        headers=auth_header(access_token),
    )

    assert rotate_response.status_code == 200
    assert rotate_response.json()["message"] == "Binance keys rotated"
    assert rotate_response.json()["rotated"] is True

    captured: dict[str, str | None] = {}

    class FakeClient:
        def __init__(self, api_key: str | None, api_secret: str | None):
            self.api_key = api_key
            self.api_secret = api_secret

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_account_summary(self):
            return SimpleNamespace(
                spot_balances=[],
                funding_balances=[],
                earn_balances=[],
                staking_positions=[],
            )

    def fake_create_binance_client(
        *, api_key: str | None, api_secret: str | None, testnet: bool = False
    ):
        captured["api_key"] = api_key
        captured["api_secret"] = api_secret
        return FakeClient(api_key=api_key, api_secret=api_secret)

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        fake_create_binance_client,
    )

    async with test_session_factory() as session:
        institution_after = (
            await session.execute(
                select(Institution).where(Institution.name == "binance")
            )
        ).scalar_one()

        assert institution_after.api_secret_encrypted != encrypted_before
        assert institution_after.credentials_updated_at > updated_at_before
        assert institution_after.credential_rotation_count == 1
        assert institution_after.get_api_credentials()["api_key"] == "rotated-key"
        assert institution_after.get_api_credentials()["api_secret"] == "rotated-secret"

        result = await sync_binance(session)

    assert result["synced"] == 0
    assert result["degraded"] is True
    assert result["warnings"] == [
        "export baseline required before Binance API delta sync can extend history"
    ]
    assert captured == {
        "api_key": "rotated-key",
        "api_secret": "rotated-secret",
    }


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/settings/binance-keys",
            {"api_key": "***", "api_secret": "plain-secret"},
        ),
        (
            "/v1/settings/binance-keys/rotate",
            {
                "api_key": "***",
                "api_secret": "rotated-secret",
                "reason": "manual-rotation",
            },
        ),
    ],
)
async def test_binance_key_endpoints_return_controlled_error_when_master_key_missing(
    async_client,
    auth_header,
    login,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, str],
) -> None:
    _, access_token = await login()
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "",
        raising=False,
    )

    response = await async_client.post(
        path,
        json=payload,
        headers=auth_header(access_token),
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Institution credential encryption is not configured"
    }


async def test_binance_sync_returns_controlled_error_when_stored_credentials_cannot_be_decrypted(
    async_client,
    auth_header,
    login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, access_token = await login()

    store_response = await async_client.post(
        "/v1/settings/binance-keys",
        json={"api_key": "***", "api_secret": "plain-secret"},
        headers=auth_header(access_token),
    )
    assert store_response.status_code == 200

    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "wrong-master-key",
        raising=False,
    )

    response = await async_client.post(
        "/v1/sync/binance",
        headers=auth_header(access_token),
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Stored Binance credentials could not be decrypted"
    }


async def test_sync_binance_requires_master_key_before_bootstrapping_from_env(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "BINANCE_API_KEY",
        "env-plaintext-key",
        raising=False,
    )
    monkeypatch.setattr(
        app_config.settings,
        "BINANCE_API_SECRET",
        "env-plaintext-secret",
        raising=False,
    )
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "",
        raising=False,
    )

    async with test_session_factory() as session:
        with pytest.raises(CredentialConfigError):
            await sync_binance(session)


async def test_sync_binance_requires_both_encrypted_key_and_secret(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "BINANCE_API_KEY",
        "",
        raising=False,
    )
    monkeypatch.setattr(
        app_config.settings,
        "BINANCE_API_SECRET",
        "env-secret-should-not-be-used",
        raising=False,
    )
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "db-only-key"
                ),
                api_secret_encrypted=None,
            )
        )
        await session.commit()

        result = await sync_binance(session)

    assert result == {
        "error": "Binance encrypted API credentials not configured",
        "synced": 0,
    }


@pytest.mark.parametrize(
    "path",
    ["/v1/settings/binance-keys", "/v1/settings/binance-keys/rotate"],
)
async def test_binance_key_endpoints_reject_empty_credentials(
    async_client,
    auth_header,
    login,
    path: str,
) -> None:
    _, access_token = await login()

    payload: dict[str, str] = {"api_key": "", "api_secret": ""}
    if path.endswith("/rotate"):
        payload["reason"] = "empty-test"

    response = await async_client.post(
        path,
        json=payload,
        headers=auth_header(access_token),
    )

    assert response.status_code == 422


async def test_sync_binance_bootstraps_encrypted_credentials_from_env_once(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )
    monkeypatch.setattr(
        app_config.settings,
        "BINANCE_API_KEY",
        "env-bootstrap-key",
        raising=False,
    )
    monkeypatch.setattr(
        app_config.settings,
        "BINANCE_API_SECRET",
        "env-bootstrap-secret",
        raising=False,
    )

    captured: dict[str, str | None] = {}

    class FakeClient:
        def __init__(self, api_key: str | None, api_secret: str | None):
            self.api_key = api_key
            self.api_secret = api_secret

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_account_summary(self):
            return SimpleNamespace(
                spot_balances=[],
                funding_balances=[],
                earn_balances=[],
                staking_positions=[],
            )

    def fake_create_binance_client(
        *, api_key: str | None, api_secret: str | None, testnet: bool = False
    ):
        captured["api_key"] = api_key
        captured["api_secret"] = api_secret
        return FakeClient(api_key=api_key, api_secret=api_secret)

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        fake_create_binance_client,
    )

    async with test_session_factory() as session:
        result = await sync_binance(session)
        institution = (
            await session.execute(
                select(Institution).where(Institution.name == "binance")
            )
        ).scalar_one()

    assert result["synced"] == 0
    assert result["degraded"] is True
    assert result["warnings"] == [
        "export baseline required before Binance API delta sync can extend history"
    ]
    assert captured == {
        "api_key": "env-bootstrap-key",
        "api_secret": "env-bootstrap-secret",
    }
    assert institution.api_key_encrypted is not None
    assert institution.api_secret_encrypted is not None
    assert institution.get_api_credentials() == {
        "api_key": "env-bootstrap-key",
        "api_secret": "env-bootstrap-secret",
    }


def _build_api_overlap_export_zip() -> bytes:
    members = {
        "Binance-Deposit-History-202604201017(UTC+7).csv": (
            "Time,Coin,Network,Amount,Address,TXID,Status\n"
            "26-04-20 09:00:00,USDT,BSC,50.0,0xdeposit,dep-1,Completed\n"
        ),
        "Binance-Convert-Order-History-202604201027(UTC+7).csv": (
            "Time,Wallet,Pair,Type,Sell,Buy,Price,Inverse Price,Date Updated,Status\n"
            "26-04-20 10:00:00,Spot,ETHBNB,Market,1.00000000ETH,10.00000000BNB,,,,Success\n"
        ),
        "Binance-Transaction-History-202604201017(UTC+7).csv": (
            "User ID,Time,Account,Operation,Coin,Change,Remark\n"
            "1,26-04-20 11:00:00,Funding,P2P Trading,USDT,100.00,P2P - order-1\n"
        ),
    }
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buff.getvalue()


def _build_locked_overlap_export_zip() -> bytes:
    members = {
        "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv": (
            "Time,Coin,Interest,Lock Period,APR,Type\n"
            "2024-05-20 00:00:00,GLMR,0.03117278,30 Days,,Locked Rewards\n"
        ),
        "Binance-SimpleEarn—Locked-History-202604201021(UTC+7).csv": (
            "Redemption Date,Coin,Redemption Amount,Redeem to,Est. Arrival Time,Status\n"
            "25-01-04 07:23:45,ADA,0.88750574,SPOT Wallet,25-01-04 07:23:45,Success\n"
        ),
    }
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buff.getvalue()


def _build_duplicate_locked_reward_export_zip() -> bytes:
    members = {
        "Binance-SimpleEarn—Locked-History-202604201020(UTC+7).csv": (
            "Time,Coin,Interest,Lock Period,APR,Type\n"
            "2024-05-20 00:00:00,GLMR,0.03117278,30 Days,,Locked Rewards\n"
            "2024-05-20 08:00:00,GLMR,0.03117278,30 Days,,Locked Rewards\n"
        )
    }
    buff = io.BytesIO()
    with zipfile.ZipFile(buff, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in members.items():
            zf.writestr(name, body)
    return buff.getvalue()


async def test_sync_binance_ingests_api_deltas_and_dedupes_against_export_baseline(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            frozen = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
            return frozen if tz is None else frozen.astimezone(tz)

    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )
    monkeypatch.setattr(app_config.settings, "BINANCE_API_KEY", "", raising=False)
    monkeypatch.setattr(app_config.settings, "BINANCE_API_SECRET", "", raising=False)

    export_bytes = _build_api_overlap_export_zip()
    captured_windows: dict[str, tuple[datetime | None, datetime | None]] = {}

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_account_summary(self):
            return SimpleNamespace(
                spot_balances=[],
                funding_balances=[],
                earn_balances=[],
                staking_positions=[],
            )

        def get_deposit_history(self, start_time=None, end_time=None, **kwargs):
            captured_windows.setdefault("deposit", (start_time, end_time))
            rows = [
                {
                    "insertTime": int(
                        datetime(2026, 4, 19, 12, 0, tzinfo=UTC).timestamp() * 1000
                    ),
                    "coin": "USDT",
                    "amount": "75.0",
                    "network": "BSC",
                    "address": "0xlate-deposit",
                    "txId": "dep-late",
                    "status": 1,
                },
                {
                    "insertTime": int(
                        datetime(2026, 4, 20, 2, 0, tzinfo=UTC).timestamp() * 1000
                    ),
                    "coin": "USDT",
                    "amount": "50.0",
                    "network": "BSC",
                    "address": "0xdeposit",
                    "txId": "dep-1",
                    "status": 1,
                },
            ]
            if start_time is None:
                return rows
            return [
                row
                for row in rows
                if datetime.fromtimestamp(row["insertTime"] / 1000, tz=UTC)
                >= start_time
            ]

        def get_withdraw_history(self, start_time=None, end_time=None, **kwargs):
            captured_windows.setdefault("withdraw", (start_time, end_time))
            return [
                {
                    "applyTime": "2026-04-20 11:30:00",
                    "completeTime": "2026-04-20 11:35:00",
                    "coin": "USDT",
                    "amount": "25",
                    "transactionFee": "0.1",
                    "network": "BSC",
                    "address": "0xwithdraw",
                    "txId": "wd-1",
                    "status": 6,
                }
            ]

        def get_convert_trade_history(
            self, start_time=None, end_time=None, limit=100, **kwargs
        ):
            captured_windows.setdefault("convert", (start_time, end_time))
            return {
                "list": [
                    {
                        "orderId": "conv-1",
                        "createTime": int(
                            datetime(2026, 4, 20, 3, 0, tzinfo=UTC).timestamp() * 1000
                        ),
                        "fromAsset": "ETH",
                        "fromAmount": "1.00000000",
                        "toAsset": "BNB",
                        "toAmount": "10.00000000",
                        "status": "SUCCESS",
                    },
                    {
                        "orderId": "conv-2",
                        "createTime": int(
                            datetime(2026, 4, 20, 4, 0, tzinfo=UTC).timestamp() * 1000
                        ),
                        "fromAsset": "USDT",
                        "fromAmount": "200.00",
                        "toAsset": "BTC",
                        "toAmount": "0.00200000",
                        "status": "SUCCESS",
                    },
                ]
            }

        def get_flexible_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1, **kwargs
        ):
            captured_windows.setdefault("flex_sub", (start_time, end_time))
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2026, 4, 20, 5, 0, tzinfo=UTC).timestamp() * 1000
                        ),
                        "asset": "USDT",
                        "amount": "12.5",
                        "productName": "USDT Flexible",
                        "type": "NORMAL",
                        "sourceAccount": "SPOT",
                        "status": "SUCCESS",
                        "purchaseId": "flex-sub-1",
                    }
                ]
            }

        def get_flexible_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1, **kwargs
        ):
            captured_windows.setdefault("flex_red", (start_time, end_time))
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2026, 4, 20, 6, 0, tzinfo=UTC).timestamp() * 1000
                        ),
                        "asset": "USDT",
                        "amount": "3.5",
                        "productName": "USDT Flexible",
                        "redeemType": "FAST",
                        "destAccount": "SPOT",
                        "status": "SUCCESS",
                        "redeemId": "flex-red-1",
                    }
                ]
            }

        def get_flexible_rewards_history(
            self,
            rewards_type="BONUS",
            start_time=None,
            end_time=None,
            limit=100,
            **kwargs,
        ):
            captured_windows.setdefault(f"flex_reward_{rewards_type}", (start_time, end_time))
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2026, 4, 20, 7, 0, tzinfo=UTC).timestamp() * 1000
                        ),
                        "asset": "USDT",
                        "rewards": "0.25",
                        "type": rewards_type,
                        "productName": "USDT Flexible",
                        "positionId": "flex-pos-1",
                    }
                ]
            }

        def get_locked_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1, **kwargs
        ):
            captured_windows.setdefault("locked_sub", (start_time, end_time))
            return {"rows": []}

        def get_locked_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1, **kwargs
        ):
            captured_windows.setdefault("locked_red", (start_time, end_time))
            return {"rows": []}

        def get_locked_rewards_history(
            self, start_time=None, end_time=None, limit=100, current=1, **kwargs
        ):
            captured_windows.setdefault("locked_reward", (start_time, end_time))
            return {"rows": []}

        def get_c2c_trade_history(
            self,
            start_time=None,
            end_time=None,
            limit=100,
            trade_type=None,
            page=1,
            **kwargs,
        ):
            captured_windows.setdefault(f"c2c_{trade_type}", (start_time, end_time))
            if trade_type == "BUY":
                return {
                    "data": [
                        {
                            "orderNumber": "order-1",
                            "createTime": int(
                                datetime(2026, 4, 20, 4, 0, tzinfo=UTC).timestamp()
                                * 1000
                            ),
                            "tradeType": "BUY",
                            "asset": "USDT",
                            "amount": "100.00",
                            "totalPrice": "100.00",
                            "fiat": "USD",
                            "status": "COMPLETED",
                        }
                    ]
                }
            return {"data": []}

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr("app.services.binance_sync.datetime", FrozenDatetime)

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "***"
                ),
                api_secret_encrypted=CredentialCipher(
                    "security-test-master-key"
                ).encrypt("sync-secret"),
            )
        )
        await session.commit()

        artifact = await parse_binance_file(
            export_bytes, "binance-api-baseline.zip", session
        )
        await confirm_binance_import(artifact.id, session)
        result = await sync_binance(session)

        txs = (
            (
                await session.execute(
                    select(Transaction)
                    .where(Transaction.institution == "binance")
                    .order_by(Transaction.timestamp)
                )
            )
            .scalars()
            .all()
        )

    assert result["synced"] == 8
    assert result["skipped"] == 4
    assert result["delta_synced"] == 8
    assert result["delta_skipped"] == 4
    assert result["snapshot_synced"] == 0
    assert result["degraded"] is False
    assert result["warnings"] == []
    assert result["api_since"] == "2026-04-19T02:00:00+00:00"

    ledger_txs = [
        tx
        for tx in txs
        if not tx.tx_type.startswith("balance_snapshot_")
        and tx.tx_type != "staking_position"
    ]
    assert len(ledger_txs) == 12
    assert {tx.tx_type for tx in ledger_txs} == {
        "deposit",
        "convert_sell",
        "convert_buy",
        "external_deposit",
        "withdrawal",
        "earn_subscribe",
        "earn_redeem",
        "earn_reward",
    }

    late_deposit = next(
        tx
        for tx in ledger_txs
        if tx.tx_type == "deposit" and tx.raw_data.get("source_id") == "dep-late"
    )
    assert late_deposit.quantity == Decimal("75")
    assert late_deposit.raw_data["source_endpoint"] == "deposit_history"

    withdrawal = next(tx for tx in ledger_txs if tx.tx_type == "withdrawal")
    assert withdrawal.fee == Decimal("0.1")
    assert withdrawal.raw_data["source_endpoint"] == "withdraw_history"
    assert withdrawal.raw_data["source_id"] == "wd-1"

    reward = next(
        tx
        for tx in ledger_txs
        if tx.tx_type == "earn_reward"
        and tx.raw_data["source_endpoint"] == "simple_earn_flexible_rewards"
        and tx.raw_data["reward_type"] == "BONUS"
    )
    assert reward.quantity == Decimal("0.25")
    assert reward.raw_data["reward_type"] == "BONUS"

    c2c_rows = [tx for tx in ledger_txs if tx.tx_type == "external_deposit"]
    assert len(c2c_rows) == 1
    c2c = c2c_rows[0]
    assert c2c.raw_data["source_type"] == "transaction_history"
    assert c2c.raw_data["remark"] == "P2P - order-1"

    api_start = datetime(2026, 4, 19, 2, 0, tzinfo=UTC)
    assert captured_windows["deposit"][0] == api_start
    assert captured_windows["convert"][0] == datetime(2026, 4, 19, 3, 0, tzinfo=UTC)
    assert captured_windows["c2c_BUY"][0] == datetime(2026, 4, 19, 4, 0, tzinfo=UTC)
    for key, window in captured_windows.items():
        if key not in {"deposit", "convert", "c2c_BUY"}:
            assert window[0] in {api_start, None}, key
        assert window[1] is not None, key


async def test_sync_binance_source_specific_overlap_suppresses_locked_export_matches(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )
    monkeypatch.setattr(app_config.settings, "BINANCE_API_KEY", "", raising=False)
    monkeypatch.setattr(app_config.settings, "BINANCE_API_SECRET", "", raising=False)

    export_bytes = _build_locked_overlap_export_zip()

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_deposit_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_withdraw_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_convert_trade_history(self, start_time=None, end_time=None, **kwargs):
            return {"list": []}

        def get_flexible_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_rewards_history(
            self, rewards_type="BONUS", start_time=None, end_time=None, limit=100
        ):
            return {"rows": []}

        def get_locked_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2025, 1, 4, 0, 23, 45, tzinfo=UTC).timestamp()
                            * 1000
                        ),
                        "asset": "ADA",
                        "amount": "0.88750574",
                        "lockPeriod": 120,
                        "type": "NEW_TRANSFERRED",
                        "status": "PAID",
                    }
                ]
            }

        def get_locked_rewards_history(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2024, 5, 20, 0, 22, 55, tzinfo=UTC).timestamp()
                            * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    }
                ]
            }

        def get_c2c_trade_history(
            self,
            start_time=None,
            end_time=None,
            limit=100,
            trade_type=None,
            page=1,
            **kwargs,
        ):
            return {"data": []}

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "***"
                ),
                api_secret_encrypted=CredentialCipher(
                    "security-test-master-key"
                ).encrypt("sync-secret"),
            )
        )
        await session.commit()

        artifact = await parse_binance_file(
            export_bytes, "binance-locked-baseline.zip", session
        )
        await confirm_binance_import(artifact.id, session)
        result = await sync_binance(session)

        ledger_txs = (
            (
                await session.execute(
                    select(Transaction)
                    .where(Transaction.institution == "binance")
                    .order_by(Transaction.timestamp)
                )
            )
            .scalars()
            .all()
        )

    assert result["synced"] == 0
    assert result["delta_synced"] == 0
    assert result["delta_skipped"] == 2
    assert result["warnings"] == []
    assert len([tx for tx in ledger_txs if tx.import_id is None]) == 0


async def test_sync_binance_exact_duplicate_consumes_overlap_capacity(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )
    monkeypatch.setattr(app_config.settings, "BINANCE_API_KEY", "", raising=False)
    monkeypatch.setattr(app_config.settings, "BINANCE_API_SECRET", "", raising=False)

    export_bytes = _build_duplicate_locked_reward_export_zip()

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_deposit_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_withdraw_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_convert_trade_history(self, start_time=None, end_time=None, **kwargs):
            return {"list": []}

        def get_flexible_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_rewards_history(
            self, rewards_type="BONUS", start_time=None, end_time=None, limit=100
        ):
            return {"rows": []}

        def get_locked_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_rewards_history(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2024, 5, 19, 17, 0, tzinfo=UTC).timestamp() * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    },
                    {
                        "time": int(
                            datetime(2024, 5, 19, 17, 22, 55, tzinfo=UTC).timestamp()
                            * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    },
                    {
                        "time": int(
                            datetime(2024, 5, 19, 18, 30, tzinfo=UTC).timestamp() * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    },
                ]
            }

        def get_c2c_trade_history(
            self,
            start_time=None,
            end_time=None,
            limit=100,
            trade_type=None,
            page=1,
            **kwargs,
        ):
            return {"data": []}

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "***"
                ),
                api_secret_encrypted=CredentialCipher(
                    "security-test-master-key"
                ).encrypt("sync-secret"),
            )
        )
        await session.commit()

        artifact = await parse_binance_file(
            export_bytes, "binance-duplicate-locked-rewards.zip", session
        )
        await confirm_binance_import(artifact.id, session)
        result = await sync_binance(session)

    assert result["delta_synced"] == 1
    assert result["delta_skipped"] == 2
    assert result["synced"] == 1


async def test_sync_binance_api_exact_duplicate_does_not_consume_export_overlap_capacity(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )
    monkeypatch.setattr(app_config.settings, "BINANCE_API_KEY", "", raising=False)
    monkeypatch.setattr(app_config.settings, "BINANCE_API_SECRET", "", raising=False)

    export_bytes = _build_locked_overlap_export_zip()

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_deposit_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_withdraw_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_convert_trade_history(self, start_time=None, end_time=None, **kwargs):
            return {"list": []}

        def get_flexible_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_rewards_history(
            self, rewards_type="BONUS", start_time=None, end_time=None, limit=100
        ):
            return {"rows": []}

        def get_locked_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_rewards_history(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2024, 5, 20, 0, 22, 55, tzinfo=UTC).timestamp()
                            * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    },
                    {
                        "time": int(
                            datetime(2024, 5, 20, 0, 30, tzinfo=UTC).timestamp() * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    },
                ]
            }

        def get_c2c_trade_history(
            self,
            start_time=None,
            end_time=None,
            limit=100,
            trade_type=None,
            page=1,
            **kwargs,
        ):
            return {"data": []}

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    exact_reward = _normalize_simple_earn_history(
        {
            "rows": [
                {
                    "time": int(
                        datetime(2024, 5, 20, 0, 22, 55, tzinfo=UTC).timestamp() * 1000
                    ),
                    "asset": "GLMR",
                    "amount": "0.03117278",
                    "lockPeriod": 30,
                    "type": "LOCKED_REWARD",
                }
            ]
        },
        kind="locked_reward",
    )[0]

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "***"
                ),
                api_secret_encrypted=CredentialCipher(
                    "security-test-master-key"
                ).encrypt("sync-secret"),
            )
        )
        await session.commit()

        artifact = await parse_binance_file(
            export_bytes, "binance-locked-baseline.zip", session
        )
        await confirm_binance_import(artifact.id, session)

        session.add(
            Transaction(
                institution="binance",
                tx_type="earn_reward",
                asset_symbol="GLMR",
                asset_type="crypto",
                quantity=Decimal("0.03117278"),
                price_usd=None,
                total_usd=None,
                fee=Decimal("0"),
                fee_currency="GLMR",
                timestamp=exact_reward.timestamp,
                fingerprint=exact_reward.fingerprint,
                raw_data=exact_reward.raw_data,
                import_id=None,
            )
        )
        await session.commit()

        result = await sync_binance(session)

    assert result["delta_synced"] == 0
    assert result["delta_skipped"] == 2
    assert result["synced"] == 0


async def test_sync_binance_does_not_seed_source_specific_overlap_from_prior_api_rows(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )
    monkeypatch.setattr(app_config.settings, "BINANCE_API_KEY", "", raising=False)
    monkeypatch.setattr(app_config.settings, "BINANCE_API_SECRET", "", raising=False)

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_deposit_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_withdraw_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_convert_trade_history(self, start_time=None, end_time=None, **kwargs):
            return {"list": []}

        def get_flexible_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_flexible_rewards_history(
            self, rewards_type="BONUS", start_time=None, end_time=None, limit=100
        ):
            return {"rows": []}

        def get_locked_subscription_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_redemption_records(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {"rows": []}

        def get_locked_rewards_history(
            self, start_time=None, end_time=None, limit=100, current=1
        ):
            return {
                "rows": [
                    {
                        "time": int(
                            datetime(2024, 5, 20, 0, 22, 55, tzinfo=UTC).timestamp()
                            * 1000
                        ),
                        "asset": "GLMR",
                        "amount": "0.03117278",
                        "lockPeriod": 30,
                        "type": "LOCKED_REWARD",
                    }
                ]
            }

        def get_c2c_trade_history(
            self,
            start_time=None,
            end_time=None,
            limit=100,
            trade_type=None,
            page=1,
            **kwargs,
        ):
            return {"data": []}

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "***"
                ),
                api_secret_encrypted=CredentialCipher(
                    "security-test-master-key"
                ).encrypt("sync-secret"),
            )
        )
        session.add(
            ActivityLog(
                source="imports.binance_baseline",
                status="confirmed",
                message="Confirmed Binance export baseline import.",
            )
        )
        session.add(
            Transaction(
                institution="binance",
                tx_type="earn_reward",
                asset_symbol="GLMR",
                asset_type="crypto",
                quantity=Decimal("0.03117278"),
                price_usd=None,
                total_usd=None,
                fee=Decimal("0"),
                fee_currency="GLMR",
                timestamp=datetime(2024, 5, 19, 17, 0, tzinfo=UTC),
                fingerprint="prior-api-row",
                raw_data={
                    "source_type": "simple_earn_locked_reward",
                    "lock_period": 30,
                },
                import_id=None,
            )
        )
        await session.commit()

        result = await sync_binance(session)
        ledger_txs = (
            (
                await session.execute(
                    select(Transaction)
                    .where(Transaction.institution == "binance")
                    .order_by(Transaction.timestamp)
                )
            )
            .scalars()
            .all()
        )

    assert result["synced"] == 1
    assert result["delta_synced"] == 1
    assert result["delta_skipped"] == 0
    assert len([tx for tx in ledger_txs if tx.import_id is None]) == 2


async def test_sync_status_surfaces_latest_degraded_binance_sync_warning(
    async_client,
    auth_header,
    login,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, access_token = await login()

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_account_summary(self):
            return SimpleNamespace(
                spot_balances=[],
                funding_balances=[],
                earn_balances=[],
                staking_positions=[],
            )

        def get_deposit_history(self, start_time=None, end_time=None, **kwargs):
            return []

        def get_withdraw_history(self, start_time=None, end_time=None, **kwargs):
            raise BinanceError("withdraw disabled")

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    async with test_session_factory() as session:
        session.add(
            Institution(
                name="binance",
                api_key_encrypted=CredentialCipher("security-test-master-key").encrypt(
                    "***"
                ),
                api_secret_encrypted=CredentialCipher(
                    "security-test-master-key"
                ).encrypt("sync-secret"),
            )
        )
        session.add(
            ImportArtifact(
                institution="binance",
                filename="baseline.zip",
                file_type="zip",
                file_data=b"baseline",
                status="committed",
                committed_count=1,
            )
        )
        session.add(
            ActivityLog(
                source="imports.binance_baseline",
                status="confirmed",
                message="Confirmed Binance export baseline import.",
            )
        )
        await session.commit()
        result = await sync_binance(session)

    assert result["degraded"] is True
    assert result["warnings"] == ["withdraw_history: withdraw disabled"]

    status_response = await async_client.get(
        "/v1/sync/status",
        headers=auth_header(access_token),
    )
    assert status_response.status_code == 200
    payload = status_response.json()
    binance = next(item for item in payload if item["name"] == "binance")
    assert binance["degraded"] is True
    assert "withdraw_history: withdraw disabled" in binance["warning"]


async def test_sensitive_sync_route_rate_limits_and_emits_telemetry(
    async_client,
    app,
    auth_header,
    login,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, access_token = await login()
    fake_now = {"value": 0.0}
    app.state.rate_limiter._clock = lambda: fake_now["value"]

    async def fake_sync_binance(_db):
        return {"synced": 1, "degraded": False, "warnings": []}

    monkeypatch.setattr("app.services.scheduler_jobs.sync_binance", fake_sync_binance)

    responses = []
    for _ in range(4):
        responses.append(
            await async_client.post(
                "/v1/sync/binance",
                headers=auth_header(access_token),
            )
        )

    assert [response.status_code for response in responses[:3]] == [200, 200, 200]
    assert responses[3].status_code == 429
    assert responses[3].json() == {"detail": "Rate limit exceeded"}
    assert responses[3].headers["Retry-After"] == "60"
    assert responses[3].headers["X-RateLimit-Limit"] == "3"
    assert responses[3].headers["X-RateLimit-Remaining"] == "0"
    assert responses[3].headers["X-RateLimit-Rule"] == "sensitive"

    telemetry_events = app.state.telemetry.snapshot()
    assert any(
        event["event_type"] == "operation"
        and event["name"] == "sync.binance"
        and event["outcome"] == "success"
        and event["user_id"] == user.id
        for event in telemetry_events
    )
    assert any(
        event["event_type"] == "request"
        and event["route"] == "/v1/sync/binance"
        and event["status_code"] == 429
        and event["rate_limited"] is True
        and event["rule_name"] == "sensitive"
        for event in telemetry_events
    )


@pytest.mark.parametrize(
    ("path", "payload", "operation_name"),
    [
        (
            "/v1/portfolio/state/refresh",
            {"captured_at": "2026-04-21T11:00:00Z"},
            "portfolio.state_refresh",
        ),
        (
            "/v1/settings/binance-keys",
            {"api_key": "plain-key", "api_secret": "plain-secret"},
            "settings.binance_credentials.update",
        ),
        (
            "/v1/settings/binance-keys/rotate",
            {
                "api_key": "rotated-key",
                "api_secret": "rotated-secret",
                "reason": "rate-limit-test",
            },
            "settings.binance_credentials.rotate",
        ),
    ],
)
async def test_sensitive_routes_rate_limit_with_deterministic_headers(
    async_client,
    app,
    auth_header,
    login,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, str],
    operation_name: str,
) -> None:
    user, access_token = await login()
    fake_now = {"value": 0.0}
    app.state.rate_limiter._clock = lambda: fake_now["value"]

    if path == "/v1/portfolio/state/refresh":
        async def fake_repair_xtb_split_transactions(_db):
            return 0

        async def fake_refresh_portfolio_state(_db, captured_at):
            return SimpleNamespace(
                captured_at=captured_at,
                asset_count=1,
                snapshot_count=1,
                benchmark_count=1,
            )

        async def fake_refresh_time_series_aggregates(_db, start_at, end_at):
            return None

        monkeypatch.setattr(
            "app.services.scheduler_jobs.repair_xtb_split_transactions",
            fake_repair_xtb_split_transactions,
        )
        monkeypatch.setattr(
            "app.services.scheduler_jobs.refresh_portfolio_state",
            fake_refresh_portfolio_state,
        )
        monkeypatch.setattr(
            "app.services.scheduler_jobs.refresh_time_series_aggregates",
            fake_refresh_time_series_aggregates,
        )
        monkeypatch.setattr(
            "app.services.scheduler_jobs.get_redis_connection",
            lambda: FakeStrictRedis(),
        )

    responses = []
    for _ in range(4):
        responses.append(
            await async_client.post(path, json=payload, headers=auth_header(access_token))
        )

    assert [response.status_code for response in responses[:3]] == [200, 200, 200]
    assert responses[3].status_code == 429
    assert responses[3].json() == {"detail": "Rate limit exceeded"}
    assert responses[3].headers["Retry-After"] == "60"
    assert responses[3].headers["X-RateLimit-Limit"] == "3"
    assert responses[3].headers["X-RateLimit-Remaining"] == "0"
    assert responses[3].headers["X-RateLimit-Rule"] == "sensitive"

    telemetry_events = app.state.telemetry.snapshot()
    assert any(
        event["event_type"] == "operation"
        and event["name"] == operation_name
        and event["outcome"] == "success"
        and event["user_id"] == user.id
        for event in telemetry_events
    )
    assert any(
        event["event_type"] == "request"
        and event["route"] == path
        and event["status_code"] == 429
        and event["rate_limited"] is True
        and event["rule_name"] == "sensitive"
        for event in telemetry_events
    )


async def test_sync_binance_upserts_pending_orders_and_closes_stale_ones(
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_config.settings,
        "INSTITUTION_CREDENTIALS_MASTER_KEY",
        "security-test-master-key",
        raising=False,
    )

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_open_orders(self):
            return [
                SimpleNamespace(
                    order_id="1001",
                    symbol="BTC",
                    market_symbol="BTCUSDT",
                    order_type="limit",
                    status="new",
                    side="buy",
                    quantity=0.25,
                    limit_price=64000.0,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 20, 8, 30, tzinfo=UTC),
                ),
                SimpleNamespace(
                    order_id="1002",
                    symbol="ETH",
                    market_symbol="ETHUSDT",
                    order_type="stop_loss_limit",
                    status="pending_new",
                    side="sell",
                    quantity=1.5,
                    limit_price=3000.0,
                    stop_price=2950.0,
                    placed_at=datetime(2026, 4, 20, 9, 45, tzinfo=UTC),
                ),
                SimpleNamespace(
                    order_id="1003",
                    symbol="SOL",
                    market_symbol="SOLEUR",
                    order_type="limit",
                    status="new",
                    side="buy",
                    quantity=12.5,
                    limit_price=145.4,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 20, 10, 15, tzinfo=UTC),
                ),
                SimpleNamespace(
                    order_id="skip-me",
                    symbol="",
                    market_symbol="UNKNWNPAIR",
                    order_type="limit",
                    status="new",
                    side="buy",
                    quantity=3.0,
                    limit_price=1.0,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 20, 10, 30, tzinfo=UTC),
                ),
            ]

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    async with test_session_factory() as session:
        institution = Institution(name="binance")
        institution.set_api_credentials("***", "sync-secret", rotated=False)
        btc_asset = Asset(symbol="BTC", asset_type="crypto")
        session.add_all([institution, btc_asset])
        await session.flush()
        session.add_all(
            [
                PendingOrder(
                    asset_id=btc_asset.id,
                    institution="binance",
                    symbol="BTC",
                    external_order_id="stale-1",
                    order_type="limit",
                    status="open",
                    side="buy",
                    quantity=Decimal("0.1"),
                    limit_price=Decimal("50000"),
                    stop_price=None,
                    placed_at=datetime(2026, 4, 19, 8, 0, tzinfo=UTC),
                ),
                PendingOrder(
                    asset_id=btc_asset.id,
                    institution="xtb",
                    symbol="BTC",
                    external_order_id="xtb-1",
                    order_type="stop",
                    status="pending",
                    side="sell",
                    quantity=Decimal("0.2"),
                    limit_price=None,
                    stop_price=Decimal("45000"),
                    placed_at=None,
                ),
            ]
        )
        await session.commit()

        result = await sync_binance(session)
        orders = (
            (
                await session.execute(
                    select(PendingOrder).order_by(
                        PendingOrder.institution.asc(),
                        PendingOrder.external_order_id.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    assert result["degraded"] is True
    assert result["warnings"] == [
        "export baseline required before Binance API delta sync can extend history"
    ]
    assert [
        (order.institution, order.external_order_id, order.symbol, order.status)
        for order in orders
    ] == [
        ("binance", "1001", "BTC", "open"),
        ("binance", "1002", "ETH", "pending"),
        ("binance", "1003", "SOL", "open"),
        ("binance", "stale-1", "BTC", "closed"),
        ("xtb", "xtb-1", "BTC", "pending"),
    ]
    btc_order = next(order for order in orders if order.external_order_id == "1001")
    eth_order = next(order for order in orders if order.external_order_id == "1002")
    sol_order = next(order for order in orders if order.external_order_id == "1003")
    assert btc_order.limit_price == Decimal("64000.0")
    assert btc_order.stop_price is None
    assert eth_order.limit_price == Decimal("3000.0")
    assert eth_order.stop_price == Decimal("2950.0")
    assert sol_order.symbol == "SOL"
    assert sol_order.limit_price == Decimal("145.4")


async def test_pending_orders_endpoint_returns_synced_binance_orders_deterministically(
    async_client,
    auth_header,
    login,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, access_token = await login()

    class FakeClient:
        api_key = "***"
        api_secret = "sync-secret"

        def get_spot_balances(self):
            return []

        def get_funding_balances(self, *, suppress_errors: bool = True):
            return []

        def get_flexible_products(self, *, suppress_errors: bool = True):
            return []

        def get_staking_positions(self, *, suppress_errors: bool = True):
            return []

        def get_open_orders(self):
            return [
                SimpleNamespace(
                    order_id="1001",
                    symbol="BTC",
                    market_symbol="BTCUSDT",
                    order_type="limit",
                    status="new",
                    side="buy",
                    quantity=0.25,
                    limit_price=64000.0,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 20, 8, 30, tzinfo=UTC),
                ),
                SimpleNamespace(
                    order_id="1002",
                    symbol="ETH",
                    market_symbol="ETHUSDT",
                    order_type="stop_loss_limit",
                    status="pending_new",
                    side="sell",
                    quantity=1.5,
                    limit_price=3000.0,
                    stop_price=2950.0,
                    placed_at=datetime(2026, 4, 20, 9, 45, tzinfo=UTC),
                ),
                SimpleNamespace(
                    order_id="1003",
                    symbol="SOL",
                    market_symbol="SOLEUR",
                    order_type="limit",
                    status="new",
                    side="buy",
                    quantity=12.5,
                    limit_price=145.4,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 20, 10, 15, tzinfo=UTC),
                ),
                SimpleNamespace(
                    order_id="skip-me",
                    symbol="",
                    market_symbol="UNKNWNPAIR",
                    order_type="limit",
                    status="new",
                    side="buy",
                    quantity=3.0,
                    limit_price=1.0,
                    stop_price=None,
                    placed_at=datetime(2026, 4, 20, 10, 30, tzinfo=UTC),
                ),
            ]

    monkeypatch.setattr(
        "app.services.binance_sync.create_binance_client",
        lambda **kwargs: FakeClient(),
    )

    async with test_session_factory() as session:
        institution = Institution(name="binance")
        institution.set_api_credentials("***", "sync-secret", rotated=False)
        btc_asset = Asset(symbol="BTC", asset_type="crypto")
        session.add_all([institution, btc_asset])
        await session.flush()
        session.add(
            PendingOrder(
                asset_id=btc_asset.id,
                institution="binance",
                symbol="BTC",
                external_order_id="stale-1",
                order_type="limit",
                status="open",
                side="buy",
                quantity=Decimal("0.1"),
                limit_price=Decimal("50000"),
                stop_price=None,
                placed_at=datetime(2026, 4, 19, 8, 0, tzinfo=UTC),
            )
        )
        await session.commit()

    sync_response = await async_client.post(
        "/v1/sync/binance",
        headers=auth_header(access_token),
    )
    pending_orders_response = await async_client.get(
        "/v1/portfolio/pending-orders",
        headers=auth_header(access_token),
    )

    assert sync_response.status_code == 200
    assert pending_orders_response.status_code == 200
    assert pending_orders_response.json() == [
        {
            "institution": "binance",
            "symbol": "BTC",
            "external_order_id": "1001",
            "order_type": "limit",
            "status": "open",
            "side": "buy",
            "quantity": 0.25,
            "limit_price": 64000.0,
            "stop_price": None,
            "placed_at": "2026-04-20T08:30:00+00:00",
        },
        {
            "institution": "binance",
            "symbol": "ETH",
            "external_order_id": "1002",
            "order_type": "stop_loss_limit",
            "status": "pending",
            "side": "sell",
            "quantity": 1.5,
            "limit_price": 3000.0,
            "stop_price": 2950.0,
            "placed_at": "2026-04-20T09:45:00+00:00",
        },
        {
            "institution": "binance",
            "symbol": "SOL",
            "external_order_id": "1003",
            "order_type": "limit",
            "status": "open",
            "side": "buy",
            "quantity": 12.5,
            "limit_price": 145.4,
            "stop_price": None,
            "placed_at": "2026-04-20T10:15:00+00:00",
        },
    ]
