from __future__ import annotations

import pytest
from app.db.safety import (
    DEFAULT_LOCAL_PYTEST_DATABASE_URL,
    DEFAULT_LOCAL_SMOKE_DATABASE_URL,
    DEFAULT_TEST_DATABASE_SERVER_URL,
    assert_safe_database_server_url,
    assert_safe_destructive_database_url,
    build_temporary_test_database_url,
    pick_safe_test_database_server_url,
    pick_safe_test_database_url,
    quote_postgresql_identifier,
)


@pytest.mark.parametrize(
    ("database_url", "context"),
    [
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_dev",
            "auth test fixture",
        ),
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/postgres",
            "frontend smoke seed",
        ),
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_prod",
            "manual script",
        ),
        (
            "postgresql+asyncpg://portfolio:portfolio@db.internal:5432/portfolio_restore_test",
            "restore drill",
        ),
        (
            "sqlite:///tmp/portfolio_restore_test.db",
            "restore drill",
        ),
    ],
)
def test_assert_safe_destructive_database_url_rejects_non_test_databases(
    database_url: str,
    context: str,
) -> None:
    with pytest.raises(ValueError, match="Refusing destructive database operation"):
        assert_safe_destructive_database_url(database_url, context=context)


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_frontend_auth_smoke",
        "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_api_test",
        "postgresql+asyncpg://portfolio:portfolio@127.0.0.1:5433/test_portfolio_tracker",
    ],
)
def test_assert_safe_destructive_database_url_allows_explicit_test_or_smoke_databases(
    database_url: str,
) -> None:
    assert_safe_destructive_database_url(database_url, context="test fixture")


@pytest.mark.parametrize(
    "database_url",
    [
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/"
            'portfolio_backend_test";DROP DATABASE portfolio_dev;--'
        ),
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/"
            "portfolio_smoke\nDROP DATABASE portfolio_dev"
        ),
    ],
)
def test_assert_safe_destructive_database_url_rejects_malicious_database_identifiers(
    database_url: str,
) -> None:
    with pytest.raises(ValueError, match="invalid PostgreSQL identifier"):
        assert_safe_destructive_database_url(database_url, context="malicious fixture")


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://portfolio:portfolio@localhost:5433/postgres",
        "postgresql+asyncpg://portfolio:portfolio@127.0.0.1:5433/portfolio_backend_test",
    ],
)
def test_assert_safe_database_server_url_allows_local_postgres_server_urls(
    database_url: str,
) -> None:
    assert_safe_database_server_url(database_url, context="test database provisioning")


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://portfolio:portfolio@db.internal:5432/postgres",
        "postgresql+asyncpg://portfolio:portfolio@localhost:5433/template1",
        "sqlite+aiosqlite:///tmp/test.db",
    ],
)
def test_assert_safe_database_server_url_rejects_remote_template_or_non_postgres_urls(
    database_url: str,
) -> None:
    with pytest.raises(ValueError, match="Refusing test database provisioning"):
        assert_safe_database_server_url(
            database_url,
            context="test database provisioning",
        )


def test_build_temporary_test_database_url_creates_explicit_test_database_name() -> (
    None
):
    database_url = build_temporary_test_database_url(
        DEFAULT_TEST_DATABASE_SERVER_URL,
        name_prefix="portfolio_state_api",
        context="api/tests/api/test_portfolio_state_api.py",
        suffix="fixedsuffix",
    )

    assert database_url == (
        "postgresql+asyncpg://portfolio:portfolio@localhost:5433/"
        "portfolio_state_api_test_fixedsuffix"
    )


def test_quote_postgresql_identifier_wraps_valid_names() -> None:
    assert (
        quote_postgresql_identifier("portfolio_backend_test")
        == '"portfolio_backend_test"'
    )


def test_pick_safe_test_database_url_rejects_unsafe_explicit_database() -> None:
    with pytest.raises(ValueError, match="Refusing destructive database operation"):
        pick_safe_test_database_url(
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_dev",
            default_url=DEFAULT_LOCAL_PYTEST_DATABASE_URL,
        )


@pytest.mark.parametrize(
    ("database_url", "default_url"),
    [
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_backend_test",
            DEFAULT_LOCAL_PYTEST_DATABASE_URL,
        ),
        (
            "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_frontend_auth_smoke",
            DEFAULT_LOCAL_SMOKE_DATABASE_URL,
        ),
    ],
)
def test_pick_safe_test_database_url_keeps_safe_explicit_test_or_smoke_databases(
    database_url: str,
    default_url: str,
) -> None:
    assert (
        pick_safe_test_database_url(database_url, default_url=default_url)
        == database_url
    )


def test_pick_safe_test_database_server_url_falls_back_to_local_postgres_server() -> (
    None
):
    assert pick_safe_test_database_server_url(None) == DEFAULT_TEST_DATABASE_SERVER_URL


def test_pick_safe_test_database_server_url_rejects_unsafe_explicit_server() -> None:
    with pytest.raises(ValueError, match="Refusing test database provisioning"):
        pick_safe_test_database_server_url(
            "postgresql+asyncpg://portfolio:portfolio@db.internal:5432/postgres"
        )
