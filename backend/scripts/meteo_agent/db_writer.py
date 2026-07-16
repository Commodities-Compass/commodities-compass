"""Database writer for meteo agent → pl_weather_observation + aud_llm_call."""

import logging
import uuid
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.audit import AudLlmCall
from app.models.pipeline import PlWeatherObservation
from scripts.meteo_agent.config import MODEL_ID

log = logging.getLogger(__name__)


class DbWriterError(Exception):
    pass


class DuplicateObservationError(DbWriterError):
    """Raised when a weather observation already exists for this date."""

    pass


def write_observation(
    session: Session,
    parsed: dict[str, str],
    observation_date: date | None = None,
    language: str = "fr",
    dry_run: bool = False,
    force: bool = False,
) -> uuid.UUID | None:
    """Insert (or overwrite when ``force=True``) a weather observation.

    The row is keyed on ``(date, language)`` (US-0 widened the unique
    constraint), so the FR and EN bulletins for a session coexist as two
    independent rows. Each ``language`` is written natively — the EN run is a
    fresh English analysis, not a translation of the FR row.

    Behavior on duplicate (a row already exists for ``(date, language)``):
      * ``force=False`` (default) — raise ``DuplicateObservationError``
        (fail-loud). Detects a runaway double-fire of the cron, which is
        the original intent of the guard.
      * ``force=True`` — UPDATE the existing row in place and return its id.

    The ``--force`` flag plumbing exists for legitimate operator reruns
    (cleanup, manual recovery after a cron failure). Without ``--force``
    the duplicate guard stays armed.

    Returns the observation UUID, or None if dry_run.
    """
    row_date = observation_date or date.today()

    if dry_run:
        log.info(
            "[DRY RUN] Would insert weather observation: date=%s language=%s, texte=%d chars",
            row_date,
            language,
            len(parsed.get("texte", "")),
        )
        return None

    existing = session.execute(
        select(PlWeatherObservation.id).where(
            PlWeatherObservation.date == row_date,
            PlWeatherObservation.language == language,
        )
    ).scalar_one_or_none()

    if existing:
        if not force:
            raise DuplicateObservationError(
                f"Weather observation already exists for date={row_date} "
                f"language={language} (id={existing}). Pipeline may have run "
                f"twice today. Re-run with --force to overwrite explicitly."
            )
        log.warning(
            "Weather observation exists for date=%s language=%s — overwriting "
            "via --force (id=%s)",
            row_date,
            language,
            existing,
        )
        session.execute(
            update(PlWeatherObservation)
            .where(PlWeatherObservation.id == existing)
            .values(
                language=language,
                observation=parsed["texte"],
                summary=parsed["resume"],
                keywords=parsed.get("mots_cle"),
                impact_assessment=parsed.get("impact_synthetiques"),
                diagnostics=parsed.get("diagnostics"),
            )
        )
        session.flush()
        return existing

    obs = PlWeatherObservation(
        date=row_date,
        language=language,
        observation=parsed["texte"],
        summary=parsed["resume"],
        keywords=parsed.get("mots_cle"),
        impact_assessment=parsed.get("impact_synthetiques"),
        diagnostics=parsed.get("diagnostics"),
    )
    session.add(obs)
    session.flush()
    log.info(
        "Inserted weather observation id=%s for date=%s language=%s",
        obs.id,
        row_date,
        language,
    )
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
