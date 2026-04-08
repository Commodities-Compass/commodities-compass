"""Write extracted segments to pl_article_segment + audit to aud_llm_call."""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.audit import AudLlmCall
from app.models.pipeline import PlArticleSegment
from scripts.pattern_extractor.config import EXTRACTION_VERSION, MODEL_ID
from scripts.pattern_extractor.output_parser import (
    ExtractionOutput,
    serialize_causal_chains,
    serialize_entities,
)

logger = logging.getLogger(__name__)


def write_segments(
    session: Session,
    article_id: uuid.UUID,
    article_date: date,
    extraction: ExtractionOutput,
    *,
    extraction_version: str = EXTRACTION_VERSION,
    dry_run: bool = False,
) -> int:
    """Write extracted segments to pl_article_segment.

    Returns the number of segments written.
    """
    if dry_run:
        logger.info(
            "[DRY RUN] Would write %d segments for article %s (%s)",
            len(extraction.segments),
            article_id,
            article_date,
        )
        for seg in extraction.segments:
            logger.info(
                "  [DRY RUN] zone=%s theme=%s sentiment=%s confidence=%.2f facts=%s...",
                seg.zone,
                seg.theme,
                seg.sentiment,
                seg.confidence,
                seg.facts[:80],
            )
        return len(extraction.segments)

    count = 0
    for seg in extraction.segments:
        row = PlArticleSegment(
            article_id=article_id,
            article_date=article_date,
            zone=seg.zone,
            theme=seg.theme,
            facts=seg.facts,
            causal_chains=serialize_causal_chains(seg.causal_chains),
            sentiment=seg.sentiment,
            sentiment_score=Decimal(str(round(seg.sentiment_score, 2))),
            entities=serialize_entities(seg.entities),
            confidence=Decimal(str(round(seg.confidence, 2))),
            llm_provider="openai",
            llm_model=MODEL_ID,
            extraction_version=extraction_version,
        )
        session.add(row)
        count += 1

    session.flush()
    logger.info(
        "Wrote %d segments for article %s (%s)",
        count,
        article_id,
        article_date,
    )
    return count


def write_llm_call(
    session: Session,
    usage: dict[str, int],
    latency_ms: int,
    *,
    dry_run: bool = False,
) -> None:
    """Insert LLM call audit record."""
    if dry_run:
        logger.info("[DRY RUN] Would log LLM call: %s, %dms", usage, latency_ms)
        return

    call = AudLlmCall(
        provider="openai",
        model=MODEL_ID,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=latency_ms,
    )
    session.add(call)
    session.flush()
    logger.info("Logged LLM call: %s", usage)
