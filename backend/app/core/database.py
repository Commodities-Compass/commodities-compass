from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Pool config only applies to connection-based drivers (not SQLite StaticPool)
_pool_kwargs = (
    {}
    if "sqlite" in settings.DATABASE_URL
    else {
        "pool_size": 5,
        "max_overflow": 5,
        "pool_timeout": 30,
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }
)

# Async engine for FastAPI
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    **_pool_kwargs,
)

# Sync engine for Alembic migrations
sync_engine = create_engine(
    settings.DATABASE_SYNC_URL,
    echo=settings.DEBUG,
)

# Async session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session. Callers that write must commit explicitly."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
