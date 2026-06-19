from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://portfolio:portfolio@localhost:5433/portfolio_backend_test"
)


def _ensure_api_path() -> None:
    api_root = Path(__file__).resolve().parents[2] / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))


async def provision_database(database_url: str, *, recreate: bool) -> None:
    _ensure_api_path()
    from app.db.safety import (
        assert_safe_database_server_url,
        assert_safe_destructive_database_url,
        quote_postgresql_identifier,
    )

    assert_safe_destructive_database_url(
        database_url, context="api/scripts/provision_test_database.py"
    )
    target_url = make_url(database_url)
    quoted_database_name = quote_postgresql_identifier(target_url.database or "")
    admin_url = target_url.set(database="postgres").render_as_string(
        hide_password=False
    )
    assert_safe_database_server_url(
        admin_url, context="api/scripts/provision_test_database.py"
    )

    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as conn:
            if recreate:
                await conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": target_url.database},
                )
                await conn.execute(
                    text(f"DROP DATABASE IF EXISTS {quoted_database_name}")
                )
            await conn.execute(text(f"CREATE DATABASE {quoted_database_name}"))
    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Provision a dedicated local PostgreSQL test/smoke database safely."
    )
    parser.add_argument(
        "--database-url",
        default=DEFAULT_DATABASE_URL,
        help="Target test/smoke database URL to create or recreate.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the target database before returning.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(provision_database(args.database_url, recreate=args.recreate))


if __name__ == "__main__":
    main()
