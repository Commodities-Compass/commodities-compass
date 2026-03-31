"""Database writer for press review → pl_fundamental_article + aud_llm_call."""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AudLlmCall
from app.models.pipeline import PlFundamentalArticle
from scripts.press_review_agent.config import AUTHOR_LABELS, MODEL_IDS, Provider

log = logging.getLogger(__name__)


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
