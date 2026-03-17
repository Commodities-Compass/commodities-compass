"""Database writer for meteo agent → pl_weather_observation + aud_llm_call."""

import logging
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.audit import AudLlmCall
from app.models.pipeline import PlWeatherObservation
from scripts.meteo_agent.config import MODEL_ID

log = logging.getLogger(__name__)


class DbWriterError(Exception):
    pass


def write_observation(
    session: Session,
    parsed: dict[str, str],
    observation_date: date | None = None,
    dry_run: bool = False,
) -> uuid.UUID | None:
    """Insert weather observation into pl_weather_observation.

    Returns the observation UUID, or None if dry_run.
    """
    row_date = observation_date or date.today()

    if dry_run:
        log.info(
            "[DRY RUN] Would insert weather observation: date=%s, texte=%d chars",
            row_date,
            len(parsed.get("texte", "")),
        )
        return None

    obs = PlWeatherObservation(
        date=row_date,
        observation=parsed["texte"],
        summary=parsed["resume"],
        keywords=parsed.get("mots_cle"),
        impact_assessment=parsed.get("impact_synthetiques"),
    )
    session.add(obs)
    session.flush()
    log.info("Inserted weather observation id=%s for date=%s", obs.id, row_date)
    return obs.id


def write_llm_call(
    session: Session,
    usage: dict | None,
    latency_ms: float,
    pipeline_run_id: uuid.UUID | None = None,
    dry_run: bool = False,
) -> None:
    """Insert LLM call audit record for meteo agent."""
    if dry_run:
        log.info("[DRY RUN] Would log LLM call: %s, %.0fms", usage, latency_ms)
        return

    usage = usage or {}
    call = AudLlmCall(
        pipeline_run_id=pipeline_run_id,
        provider="openai",
        model=MODEL_ID,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        latency_ms=int(latency_ms),
    )
    session.add(call)
    session.flush()
    log.info("Logged LLM call: %s", usage)
