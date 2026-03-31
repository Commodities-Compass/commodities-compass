"""Shared pytest fixtures for backend tests.

Uses local PostgreSQL (docker-compose, port 5433) for all tests.
Run `pnpm db:up` before running tests.
"""

import os

# Set test environment variables BEFORE importing app modules.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5433/commodities_compass_test",
)
os.environ.setdefault(
    "DATABASE_SYNC_URL",
    "postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass_test",
)
os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")
os.environ.setdefault("AUTH0_API_AUDIENCE", "https://test-api")
os.environ.setdefault("AUTH0_ISSUER", "https://test.auth0.com/")
os.environ.setdefault("SPREADSHEET_ID", "test-spreadsheet-id")
os.environ.setdefault("GOOGLE_DRIVE_AUDIO_FOLDER_ID", "test-folder-id")

from collections.abc import AsyncGenerator, Generator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
TEST_SYNC_DATABASE_URL = os.environ["DATABASE_SYNC_URL"]

# Sync engine — used for table setup/teardown and sync tests.
test_sync_engine = create_engine(TEST_SYNC_DATABASE_URL, echo=False)
TestSyncSessionLocal = sessionmaker(test_sync_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Create all tables before tests, drop after."""
    Base.metadata.drop_all(test_sync_engine)
    Base.metadata.create_all(test_sync_engine)
    yield
    Base.metadata.drop_all(test_sync_engine)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async session that rolls back after each test.

    Creates a fresh async engine per test to avoid event loop binding issues.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_size=1)
    async with engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        yield session
        await session.close()
        await trans.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client with overridden DB dependency."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def sync_db_session() -> Generator[Session, None, None]:
    """Provide a sync transactional session that rolls back after each test."""
    conn = test_sync_engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def mock_user() -> dict:
    """Return a mock authenticated user payload."""
    return {
        "sub": "auth0|test-user-id",
        "email": "test@example.com",
        "name": "Test User",
        "permissions": [],
    }
