"""Tests for ``scripts.ensemble_compute.db_loader.load_macro_signal``.

Covers:
- Empty window → neutral MacroSignal (fail-soft, no crash).
- Bullish/bearish window → matching direction.
- High-confidence-only filtering (MacroEventLayer drops conf < 0.70 internally).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models.pipeline import PlArticleSegment, PlFundamentalArticle
from scripts.ensemble_compute.db_loader import EnsembleLoaderError, load_macro_signal


def _seed_article(session: Session, *, on_date: date) -> uuid.UUID:
    """Create a PlFundamentalArticle row so segments have a FK target."""
    article = PlFundamentalArticle(
        date=on_date,
        category="macro",
        source="test",
        summary="test article",
        llm_provider="openai",
        is_active=True,
    )
    session.add(article)
    session.flush()
    return article.id


def _seed_segment(
    session: Session,
    *,
    article_id: uuid.UUID,
    on_date: date,
    sentiment_score: float,
    confidence: float,
    theme: str = "production",
) -> None:
    segment = PlArticleSegment(
        article_id=article_id,
        article_date=on_date,
        zone="all",
        theme=theme,
        sentiment="neutral",
        sentiment_score=Decimal(str(sentiment_score)),
        confidence=Decimal(str(confidence)),
        llm_provider="openai",
        llm_model="o4-mini",
        extraction_version="v1",
    )
    session.add(segment)


@pytest.mark.unit
def test_load_macro_signal_empty_window_raises(
    sync_db_session: Session,
) -> None:
    """No segments in [today-90d, today] → fail-loud (press-review failed upstream)."""
    today = date(2026, 5, 15)
    with pytest.raises(EnsembleLoaderError, match="pl_article_segment empty"):
        load_macro_signal(sync_db_session, today=today)


@pytest.mark.unit
def test_load_macro_signal_bearish_window(sync_db_session: Session) -> None:
    """Window dominated by strongly negative high-confidence segments → direction=-1."""
    today = date(2026, 5, 15)
    # Seed 40 prior days of mild bearish baseline + today with strong bearish signal.
    for i in range(40, 0, -1):
        d = today - timedelta(days=i)
        aid = _seed_article(sync_db_session, on_date=d)
        _seed_segment(
            sync_db_session,
            article_id=aid,
            on_date=d,
            sentiment_score=-0.20,
            confidence=0.80,
        )
    aid_today = _seed_article(sync_db_session, on_date=today)
    _seed_segment(
        sync_db_session,
        article_id=aid_today,
        on_date=today,
        sentiment_score=-0.85,
        confidence=0.90,
    )
    sync_db_session.flush()

    signal = load_macro_signal(sync_db_session, today=today)
    assert signal.direction == -1
    assert 0.0 < signal.confidence <= 1.0


@pytest.mark.unit
def test_load_macro_signal_bullish_window(sync_db_session: Session) -> None:
    """Window dominated by strongly positive high-confidence segments → direction=+1."""
    today = date(2026, 5, 15)
    for i in range(40, 0, -1):
        d = today - timedelta(days=i)
        aid = _seed_article(sync_db_session, on_date=d)
        _seed_segment(
            sync_db_session,
            article_id=aid,
            on_date=d,
            sentiment_score=0.20,
            confidence=0.80,
        )
    aid_today = _seed_article(sync_db_session, on_date=today)
    _seed_segment(
        sync_db_session,
        article_id=aid_today,
        on_date=today,
        sentiment_score=0.85,
        confidence=0.90,
    )
    sync_db_session.flush()

    signal = load_macro_signal(sync_db_session, today=today)
    assert signal.direction == 1
    assert 0.0 < signal.confidence <= 1.0


@pytest.mark.unit
def test_load_macro_signal_low_confidence_only_returns_neutral(
    sync_db_session: Session,
) -> None:
    """Segments below confidence=0.70 are dropped by MacroEventLayer → neutral signal."""
    today = date(2026, 5, 15)
    for i in range(40, 0, -1):
        d = today - timedelta(days=i)
        aid = _seed_article(sync_db_session, on_date=d)
        _seed_segment(
            sync_db_session,
            article_id=aid,
            on_date=d,
            sentiment_score=-0.85,
            confidence=0.50,  # below MacroEventLayer's 0.70 threshold
        )
    sync_db_session.flush()

    signal = load_macro_signal(sync_db_session, today=today)
    assert signal.direction == 0
    assert signal.confidence == 0.0
