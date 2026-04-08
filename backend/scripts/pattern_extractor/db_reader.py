"""Read articles from pl_fundamental_article for extraction."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline import PlArticleSegment, PlFundamentalArticle

logger = logging.getLogger(__name__)


def read_all_articles(
    session: Session,
    *,
    limit: int | None = None,
) -> list[PlFundamentalArticle]:
    """Read all articles ordered by date descending."""
    stmt = (
        select(PlFundamentalArticle)
        .where(PlFundamentalArticle.summary.isnot(None))
        .order_by(PlFundamentalArticle.date.asc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def read_unprocessed_articles(
    session: Session,
    extraction_version: str,
    *,
    limit: int | None = None,
) -> list[PlFundamentalArticle]:
    """Read articles that don't yet have segments for this extraction_version."""
    processed_ids = (
        select(PlArticleSegment.article_id)
        .where(PlArticleSegment.extraction_version == extraction_version)
        .distinct()
    )
    stmt = (
        select(PlFundamentalArticle)
        .where(
            PlFundamentalArticle.summary.isnot(None),
            PlFundamentalArticle.id.notin_(processed_ids),
        )
        .order_by(PlFundamentalArticle.date.asc())
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


def read_latest_article(
    session: Session,
) -> PlFundamentalArticle | None:
    """Read the most recent active article."""
    stmt = (
        select(PlFundamentalArticle)
        .where(
            PlFundamentalArticle.is_active.is_(True),
            PlFundamentalArticle.summary.isnot(None),
        )
        .order_by(PlFundamentalArticle.date.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()
