"""Shared sync DB session factory for scraper scripts.

All scrapers write to GCP Cloud SQL via DATABASE_SYNC_URL env var.
No default fallback — must be explicitly set to prevent accidental local writes.
"""

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


class DbSessionError(Exception):
    pass


def get_sync_engine(url: str | None = None):
    """Create a sync SQLAlchemy engine from DATABASE_SYNC_URL or explicit URL."""
    db_url = url or os.getenv("DATABASE_SYNC_URL")
    if not db_url:
        raise DbSessionError(
            "DATABASE_SYNC_URL env var not set. "
            "Set it to the GCP Cloud SQL connection string."
        )
    return create_engine(db_url, pool_pre_ping=True)


@contextmanager
def get_session(url: str | None = None) -> Generator[Session, None, None]:
    """Yield a sync session that auto-commits on success, rolls back on error."""
    engine = get_sync_engine(url)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
