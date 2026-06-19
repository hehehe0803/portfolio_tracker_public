import asyncio

import app.db  # noqa: F401
from app.db.base import Base
from app.db.models import User
from app.db.safety import (
    DEFAULT_LOCAL_SMOKE_DATABASE_URL,
    pick_safe_test_database_url,
)
from app.db.session import async_session_factory, engine
from app.services.auth import hash_password


def _guard_database() -> None:
    safe_database_url = pick_safe_test_database_url(
        str(engine.url),
        default_url=DEFAULT_LOCAL_SMOKE_DATABASE_URL,
    )
    if safe_database_url != str(engine.url):
        raise ValueError(
            "frontend/e2e/seed-auth-smoke-backend.py must run against the configured "
            f"smoke database, got '{engine.url}'"
        )


async def main() -> None:
    _guard_database()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        session.add(
            User(
                username="admin",
                password_hash=hash_password("secret"),
                totp_enabled=False,
            )
        )
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
