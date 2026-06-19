"""
Database Session Management.

Provides async SQLAlchemy engine and session factory for database operations.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


# Create async engine with connection pooling
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL statements in debug mode
    pool_pre_ping=True,  # Validate connections before use
    pool_size=10,  # Number of connections to keep in pool
    max_overflow=20,  # Additional connections beyond pool_size
    pool_timeout=30,  # Seconds to wait for available connection
    pool_recycle=1800,  # Recycle connections after 30 minutes
)

# Create async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    autocommit=False,  # Explicit commits required
    autoflush=False,  # Don't autoflush after query
)


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for obtaining async database sessions.
    
    Provides a session with automatic cleanup on exit.
    Use this as a dependency in FastAPI routes.
    
    Yields:
        AsyncSession configured with async engine.
    
    Example:
        @app.get("/users")
        async def get_users(session: AsyncSession = Depends(get_async_session)):
            results = await session.execute(select(User))
            return results.scalars().all()
    """
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database session injection."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_health() -> None:
    """Verify that the configured database can execute a simple query."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
