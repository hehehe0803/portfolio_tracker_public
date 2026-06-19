"""
One-time setup: create the admin user.
Run: uv run python -m app.setup_user
"""

import asyncio
import sys

from sqlalchemy import select
from app.db.session import async_session_factory
import app.db  # noqa: F401
from app.db.base import Base
from app.db.session import engine
from app.db.models import User
from app.services.auth import hash_password


async def main():
    username = input("Username [admin]: ").strip() or "admin"
    password = input("Password: ").strip()
    if not password:
        print("Password cannot be empty")
        sys.exit(1)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        existing = await session.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none():
            print(f"User '{username}' already exists")
            sys.exit(0)
        user = User(username=username, password_hash=hash_password(password))
        session.add(user)
        await session.commit()
        print(f"User '{username}' created. Run /v1/auth/totp/setup to enable 2FA.")


if __name__ == "__main__":
    asyncio.run(main())
