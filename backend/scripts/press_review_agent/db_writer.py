"""Database writer for press review → pl_fundamental_article + aud_llm_call + pl_article_segment."""

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import sentry_sdk
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AudLlmCall
from app.models.pipeline import PlArticleSegment, PlFundamentalArticle
from scripts.press_review_agent.config import (
    AUTHOR_LABELS,
    MODEL_IDS,
    PRODUCTION_PROVIDER,
    THEMES,
    Provider,
)

log = logging.getLogger(__name__)

# Neutral fallback used when the LLM omits a theme. Guarantees 4 gauges
# render every day; presence is surfaced to Sentry as a warning so we
# can detect prompt drift without breaking the daily run.
NEUTRAL_FALLBACK_RATIONALE = "Aucune couverture significative dans les sources du jour."
NEUTRAL_FALLBACK_SCORE = 0.0
NEUTRAL_FALLBACK_CONFIDENCE = 0.1


class DbWriterError(Exception):
    pass


class DuplicateArticleError(DbWriterError):
    """Raised when an article already exists for this date + provider."""

    pass


def write_article(
    session: Session,
    provider: Provider,
    parsed: dict[str, str],
    article_date: date | None = None,
    dry_run: bool = False,
    source_count: int | None = None,
    total_sources: int | None = None,
) -> uuid.UUID | None:
    """Insert a press review article into pl_fundamental_article.

    Raises DuplicateArticleError if a row already exists for (date, llm_provider).
    Returns the article UUID, or None if dry_run.
    """
    row_date = article_date or date.today()

    if dry_run:
        log.info(
            "[DRY RUN] [%s] Would insert article: date=%s, summary=%d chars",
            provider.value,
            row_date,
            len(parsed.get("resume", "")),
        )
        return None

    existing = session.execute(
        select(PlFundamentalArticle.id).where(
            PlFundamentalArticle.date == row_date,
            PlFundamentalArticle.llm_provider == provider.value,
        )
    ).scalar_one_or_none()

    if existing:
        raise DuplicateArticleError(
            f"Article already exists for date={row_date}, "
            f"provider={provider.value} (id={existing}). "
            f"Pipeline may have run twice today."
        )

    article = PlFundamentalArticle(
        date=row_date,
        category="macro",
        source=AUTHOR_LABELS[provider],
        summary=parsed["resume"],
        keywords=parsed.get("mots_cle"),
        impact_synthesis=parsed.get("impact_synthetiques"),
        llm_provider=provider.value,
        is_active=(provider == PRODUCTION_PROVIDER),
        source_count=source_count,
        total_sources=total_sources,
    )
    session.add(article)
    session.flush()
    log.info(
        "[%s] Inserted article id=%s for date=%s",
        provider.value,
        article.id,
        row_date,
    )
    return article.id


def _fill_missing_themes(
    theme_sentiments: dict[str, Any],
    provider: Provider,
    article_date: date,
) -> tuple[dict[str, Any], list[str]]:
    """Return a copy of `theme_sentiments` with all 4 themes guaranteed.

    Missing themes are filled with a neutral fallback row and reported to
    Sentry as a warning. Never mutates the input dict.
    """
    missing = [t for t in THEMES if t not in theme_sentiments]
    if not missing:
        return dict(theme_sentiments), []

    log.warning(
        "[%s] LLM omitted %d theme(s): %s — filling with neutral fallback",
        provider.value,
        len(missing),
        missing,
    )
    sentry_sdk.capture_message(
        f"press_review_partial_themes: {provider.value} omitted {missing}",
        level="warning",
    )
    sentry_sdk.set_context(
        "press_review_partial_themes",
        {
            "provider": provider.value,
            "article_date": article_date.isoformat(),
            "missing_themes": missing,
            "present_themes": sorted(theme_sentiments.keys()),
        },
    )

    filled = dict(theme_sentiments)
    for theme in missing:
        filled[theme] = {
            "score": NEUTRAL_FALLBACK_SCORE,
            "confidence": NEUTRAL_FALLBACK_CONFIDENCE,
            "rationale": NEUTRAL_FALLBACK_RATIONALE,
        }
    return filled, missing


def write_theme_sentiments(
    session: Session,
    article_id: uuid.UUID,
    article_date: date,
    theme_sentiments: dict[str, Any],
    provider: Provider,
    dry_run: bool = False,
) -> int:
    """Insert per-theme sentiment scores into pl_article_segment.

    If the LLM omitted any of the 4 themes (production / chocolat /
    transformation / economie), they are filled with a neutral fallback
    row and a Sentry warning is emitted. Guarantees 4 rows per day so
    the dashboard always renders 4 sentiment gauges.

    Returns the number of segments written (always len(THEMES) on success).
    """
    filled, _missing = _fill_missing_themes(theme_sentiments, provider, article_date)

    if dry_run:
        log.info(
            "[DRY RUN] [%s] Would insert %d theme sentiments",
            provider.value,
            len(filled),
        )
        return 0

    count = 0
    for theme, data in filled.items():
        score = float(data["score"])
        if score > 0.1:
            sentiment_label = "bullish"
        elif score < -0.1:
            sentiment_label = "bearish"
        else:
            sentiment_label = "neutral"

        segment = PlArticleSegment(
            article_id=article_id,
            article_date=article_date,
            zone="all",
            theme=theme,
            facts=data.get("rationale"),
            sentiment=sentiment_label,
            sentiment_score=Decimal(str(round(score, 2))),
            confidence=Decimal(str(round(float(data.get("confidence", 0.5)), 2))),
            llm_provider=provider.value,
            llm_model=MODEL_IDS[provider],
            extraction_version="inline_v1",
        )
        session.add(segment)
        count += 1

    session.flush()
    log.info(
        "[%s] Inserted %d theme sentiments for date=%s",
        provider.value,
        count,
        article_date,
    )
    return count


def write_llm_call(
    session: Session,
    provider: Provider,
    usage: dict | None,
    latency_ms: float,
    pipeline_run_id: uuid.UUID | None = None,
    dry_run: bool = False,
) -> None:
    """Insert an LLM call audit record into aud_llm_call."""
    if dry_run:
        log.info(
            "[DRY RUN] [%s] Would log LLM call: %s, %.0fms",
            provider.value,
            usage,
            latency_ms,
        )
        return

    usage = usage or {}
    call = AudLlmCall(
        pipeline_run_id=pipeline_run_id,
        provider=provider.value,
        model=MODEL_IDS[provider],
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=int(latency_ms),
    )
    session.add(call)
    session.flush()
    log.info("[%s] Logged LLM call: %s", provider.value, usage)
