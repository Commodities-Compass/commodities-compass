"""Shared pytest fixtures for backend tests."""

import os

# Set test environment variables BEFORE importing app modules.
# python-decouple reads env vars at class definition time in config.py,
# so these must be in os.environ before any app import triggers Settings().
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_SYNC_URL", "sqlite:///:memory:")
os.environ.setdefault("AUTH0_DOMAIN", "test.auth0.com")
os.environ.setdefault("AUTH0_CLIENT_ID", "test-client-id")
os.environ.setdefault("AUTH0_API_AUDIENCE", "https://test-api")
os.environ.setdefault("AUTH0_ISSUER", "https://test.auth0.com/")
os.environ.setdefault("SPREADSHEET_ID", "test-spreadsheet-id")
os.environ.setdefault("GOOGLE_DRIVE_AUDIO_FOLDER_ID", "test-folder-id")

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables before tests, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session that rolls back after each test."""
    async with TestSessionLocal() as session:
        async with session.begin():
            yield session
        await session.rollback()


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
def mock_user() -> dict:
    """Return a mock authenticated user payload."""
    return {
        "sub": "auth0|test-user-id",
        "email": "test@example.com",
        "name": "Test User",
        "permissions": [],
    }
