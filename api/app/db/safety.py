from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy.engine import URL, make_url

_ALLOWED_DATABASE_MARKERS = ("test", "smoke")
_ALLOWED_HOSTS = {None, "", "localhost", "127.0.0.1"}
_FORBIDDEN_DATABASE_NAMES = {
    "portfolio_dev",
    "portfolio_prod",
    "portfolio_production",
    "postgres",
    "template0",
    "template1",
}
_FORBIDDEN_ADMIN_DATABASE_NAMES = {"template0", "template1"}
_POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

DEFAULT_TEST_DATABASE_SERVER_URL = (
    "postgresql+asyncpg://portfolio:portfolio@localhost:5433/postgres"
)
DEFAULT_LOCAL_PYTEST_DATABASE_URL = (
    "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_backend_test"
)
DEFAULT_LOCAL_SMOKE_DATABASE_URL = "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_frontend_auth_smoke"


def _coerce_url(database_url: str | URL) -> URL:
    return database_url if isinstance(database_url, URL) else make_url(database_url)


def _is_local_host(hostname: str | None) -> bool:
    return hostname in _ALLOWED_HOSTS


def _validate_postgresql_identifier(identifier: str, *, context: str) -> None:
    if _POSTGRES_IDENTIFIER_RE.fullmatch(identifier):
        return

    raise ValueError(
        f"Refusing {context}: '{identifier or '<unknown>'}' is not a valid "
        "PostgreSQL identifier"
    )


def quote_postgresql_identifier(identifier: str) -> str:
    _validate_postgresql_identifier(
        identifier, context="database operation: invalid PostgreSQL identifier"
    )
    return f'"{identifier}"'


def assert_safe_destructive_database_url(
    database_url: str | URL,
    *,
    context: str,
) -> None:
    """Reject destructive test helpers pointed at non-test databases.

    Intended for flows that run drop_all/create_all or similar schema-destructive
    setup. The guard is intentionally conservative: only localhost databases
    whose names clearly contain "test" or "smoke" are allowed.
    """

    url = _coerce_url(database_url)
    database_name = (url.database or "").strip()
    hostname = url.host
    normalized_name = database_name.lower()

    if url.get_backend_name() != "postgresql":
        raise ValueError(
            "Refusing destructive database operation for "
            f"{context}: backend '{url.get_backend_name()}' is not PostgreSQL"
        )

    _validate_postgresql_identifier(
        database_name,
        context=f"{context}: invalid PostgreSQL identifier",
    )

    has_allowed_marker = any(
        marker in normalized_name for marker in _ALLOWED_DATABASE_MARKERS
    )
    is_forbidden_name = normalized_name in _FORBIDDEN_DATABASE_NAMES
    is_local_host = _is_local_host(hostname)

    if has_allowed_marker and is_local_host and not is_forbidden_name:
        return

    raise ValueError(
        "Refusing destructive database operation for "
        f"{context}: database '{database_name or '<unknown>'}' on host "
        f"'{hostname or '<default>'}' is not an explicitly safe local test database"
    )


def assert_safe_database_server_url(database_url: str | URL, *, context: str) -> None:
    """Allow provisioning only against a local PostgreSQL server URL.

    This guard is for create/drop database flows that must connect to an admin
    database such as `postgres`. It intentionally rejects remote hosts,
    non-PostgreSQL backends, and template databases.
    """

    url = _coerce_url(database_url)
    database_name = (url.database or "").strip()
    normalized_name = database_name.lower()

    if (
        url.get_backend_name() == "postgresql"
        and _is_local_host(url.host)
        and normalized_name not in _FORBIDDEN_ADMIN_DATABASE_NAMES
    ):
        return

    raise ValueError(
        "Refusing test database provisioning for "
        f"{context}: database '{database_name or '<unknown>'}' on host "
        "'"
        f"{url.host or '<default>'}"
        "' is not an explicitly safe local PostgreSQL server URL"
    )


def pick_safe_test_database_url(
    database_url: str | None, *, default_url: str = DEFAULT_LOCAL_PYTEST_DATABASE_URL
) -> str:
    if database_url:
        assert_safe_destructive_database_url(
            database_url, context="pick_safe_test_database_url"
        )
        return database_url

    assert_safe_destructive_database_url(
        default_url, context="pick_safe_test_database_url:default"
    )
    return default_url


def pick_safe_test_database_server_url(
    database_url: str | None, *, default_url: str = DEFAULT_TEST_DATABASE_SERVER_URL
) -> str:
    if database_url:
        assert_safe_database_server_url(
            database_url, context="pick_safe_test_database_server_url"
        )
        return database_url

    assert_safe_database_server_url(
        default_url, context="pick_safe_test_database_server_url:default"
    )
    return default_url


def build_temporary_test_database_url(
    database_server_url: str | URL,
    *,
    name_prefix: str,
    context: str,
    suffix: str | None = None,
) -> str:
    server_url = _coerce_url(database_server_url)
    assert_safe_database_server_url(server_url, context=context)

    normalized_prefix = "_".join(
        part for part in name_prefix.lower().split("_") if part
    )
    database_name = f"{normalized_prefix}_test_{suffix or uuid4().hex}"
    database_url = server_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    assert_safe_destructive_database_url(database_url, context=context)
    return database_url
