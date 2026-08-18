"""Build ``judge.schema.Brief`` instances from the pipeline's DB rows.

The Compass daily brief text is 100% templated from ``pl_*`` rows (press-review
agent writes SUPPLY/FUNDAMENTALS/MARKET/SENTIMENT sections into
``pl_fundamental_article.summary``; the brief-generator concatenates them under
labels). Judge reads press + weather + technicals directly from the DB rather
than parsing the ``.txt`` on Drive: same content, no Drive dependency, no race
with brief-generation timing, and — importantly — the F-graduation path (brief
downstream of judge) requires DB reads since the brief file won't exist yet
when judge runs.

Section labels inside ``summary`` are the R&D anchor points; we reuse the
vendored parser (``judge.brief_parser._parse_press``) for the split so a prompt
change on the press-review side that alters those labels stays isolated to one
place.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_cls
from typing import Optional

from judge.brief_parser import _parse_press, _parse_weather  # type: ignore
from judge.schema import Brief, Decision, PressRead, WeatherRead  # type: ignore
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Press-review production provider (see scripts/press_review_agent/config.py).
# Judge reads the EN edition (mirrors R&D's fixture) — the language dimension
# was added by PR #66 (feat/i18n English/Ghana edition).
_PRESS_PROVIDER = "openai"
_LANGUAGE = "en"


class BriefDataMissingError(RuntimeError):
    """A required DB row (article / weather) is absent for the target date."""


def _fetch_press(
    session: Session, target_date: date_cls, language: str = _LANGUAGE
) -> tuple[str, str]:
    """Return ``(summary, impact_synthesis)`` for the given date, or raise."""
    row = session.execute(
        text(
            """
            SELECT summary, COALESCE(impact_synthesis, '') AS impact
            FROM pl_fundamental_article
            WHERE date = :d AND llm_provider = :p AND language = :l
            ORDER BY is_active DESC, created_at DESC
            LIMIT 1
            """
        ),
        {"d": target_date, "p": _PRESS_PROVIDER, "l": language},
    ).fetchone()
    if row is None or not row.summary:
        raise BriefDataMissingError(
            f"no {_PRESS_PROVIDER}/{language} press article for {target_date}"
        )
    return str(row.summary), str(row.impact)


def _fetch_weather(
    session: Session, target_date: date_cls, language: str = _LANGUAGE
) -> str:
    """Return the weather impact-assessment text for the given date, or raise.

    The R&D parser (``judge.brief_parser._parse_weather``) matches
    ``Impact:\\s*(\\d+)\\s*/\\s*10`` to extract the numeric market-impact score
    that feeds the deterministic drift signal. Our meteo agent stores the score
    prefix as ``"2/10; Justification: ..."`` (the ``"Impact: "`` prefix is added
    by the brief-generator at render time, not by the agent). Left as-is,
    the parser silently misses → ``weather.impact_10 = None`` on every row →
    ``weather_series`` empty, ``weather_delta`` NULL. The LLM still gets the
    prose via ``weather.summary`` so decisions aren't affected, but the
    pre-computed numeric drift is lost. Prepend the prefix here so the R&D
    parser can match without touching the pack.
    """
    row = session.execute(
        text(
            """
            SELECT COALESCE(impact_assessment, summary, observation, '') AS body
            FROM pl_weather_observation
            WHERE date = :d AND language = :l
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"d": target_date, "l": language},
    ).fetchone()
    if row is None or not row.body:
        raise BriefDataMissingError(
            f"no {language} weather observation for {target_date}"
        )
    body = str(row.body)
    return body if body.lstrip().startswith("Impact:") else f"Impact: {body}"


def _fetch_technicals(
    session: Session, data_date: date_cls
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Return ``(close, volume, rsi)`` from the row-date's OHLCV + indicators.

    Uses the roll-safe front-month chain (v_contract_data_chained) so a roll
    boundary doesn't split the read. Returns ``(None, None, None)`` on miss —
    technicals are context in the prompt, not gating.
    """
    row = session.execute(
        text(
            """
            SELECT c.close, c.volume, d.rsi_14d AS rsi
            FROM v_contract_data_chained c
            LEFT JOIN pl_derived_indicators d
              ON d.date = c.date AND d.contract_id = c.contract_id
            WHERE c.date = :d
            ORDER BY d.created_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"d": data_date},
    ).fetchone()
    if row is None:
        return (None, None, None)
    return (
        float(row.close) if row.close is not None else None,
        float(row.volume) if row.volume is not None else None,
        float(row.rsi) if row.rsi is not None else None,
    )


class PriorBaseCallMissingError(RuntimeError):
    """No served decision for a prior date in the judge's window.

    Fail-loud on purpose. The previous behaviour returned
    ``(MONITOR, 0.0, "")`` when the row was absent, which fed the LLM a
    fabricated "the algorithm was neutral that day" — an invented history is
    worse than no run at all.
    """


def _fetch_algo_base_call(
    session: Session,
    data_date: date_cls,
    algorithm_version_id: uuid.UUID | str,
) -> tuple[Decision, float, str]:
    """Return ``(decision, confidence_0_5, direction_label)`` for a prior brief.

    Populates the prior briefs' base_decision/confidence in the judge's window
    (the prompt shows the base algorithm's call at each historical brief).
    Today's brief is overridden by ``base_override`` in ``run_shadow``, so this
    only concerns the priors.

    Scoped to the algorithm the judge is overlaying — its OWN history, never
    another algorithm's. It used to hardcode the ensemble name, which meant the
    judge reasoned over a predecessor's calls; and resolving "whatever is
    currently served" would reintroduce the same coupling for as long as the
    new algorithm runs in shadow. The adapter row fills exactly these columns,
    so the base algorithm always has its own priors available.

    Raises ``PriorBaseCallMissingError`` when the date has no decision for that
    algorithm: the recovery path is to backfill the adapter rows, never to
    invent a neutral call.
    """
    row = session.execute(
        text(
            """
            SELECT UPPER(i.decision) AS decision,
                   COALESCE(i.confidence, 0) AS confidence,
                   COALESCE(i.direction, '') AS direction
            FROM pl_indicator_daily i
            WHERE i.date = :d
              AND i.algorithm_version_id = :a
              AND i.decision IS NOT NULL
            ORDER BY i.created_at DESC
            LIMIT 1
            """
        ),
        {"d": data_date, "a": str(algorithm_version_id)},
    ).fetchone()
    if row is None:
        raise PriorBaseCallMissingError(
            f"No decision at {data_date} for algorithm {algorithm_version_id} "
            f"in the judge's prior-brief window. Backfill the adapter rows for "
            f"that session — the window must never be padded with a fabricated "
            f"neutral call."
        )
    try:
        decision = Decision(row.decision)
    except ValueError as exc:
        raise PriorBaseCallMissingError(
            f"Unrecognised decision {row.decision!r} at {data_date}"
        ) from exc
    return (decision, float(row.confidence), str(row.direction))


def build_brief_from_db(
    session: Session,
    *,
    data_date: date_cls,
    target_date: date_cls,
    include_algo_base: bool = True,
    algorithm_version_id: uuid.UUID | str | None = None,
) -> Brief:
    """Compose a ``Brief`` from DB rows keyed on ``data_date``.

    ``data_date`` is the row-date convention shared with the rest of Phase B
    (``pl_indicator_daily.date``); ``target_date = next_session(data_date)`` is
    the session the brief decides for. The two coordinates are what the fixture
    briefs distinguish under "Date:" (target) and "Session close:" (row date).

    Set ``include_algo_base=False`` when the caller will override the base call
    (e.g. today's brief in ``run_shadow`` gets its base from regime).
    """
    summary, impact = _fetch_press(session, data_date)
    weather_text = _fetch_weather(session, data_date)
    close, volume, rsi = _fetch_technicals(session, data_date)

    press = _parse_press(summary)
    # ``impact_synthesis`` is a dedicated column (never lives inside the section
    # body), so we prefer it when present rather than the parser's fallback.
    if impact:
        press = PressRead(
            supply=press.supply,
            fundamentals=press.fundamentals,
            market=press.market,
            sentiment=press.sentiment,
            impact_summary=impact,
        )

    weather: WeatherRead = _parse_weather(weather_text)

    if include_algo_base:
        if algorithm_version_id is None:
            raise PriorBaseCallMissingError(
                "include_algo_base=True requires algorithm_version_id — the "
                "judge's window must be scoped to the algorithm it overlays"
            )
        base_dec, base_conf, base_dir = _fetch_algo_base_call(
            session, data_date, algorithm_version_id
        )
    else:
        base_dec, base_conf, base_dir = (Decision.MONITOR, 0.0, "")

    return Brief(
        session_date=str(target_date),
        last_close_date=str(data_date),
        base_decision=base_dec,
        base_confidence=base_conf,
        base_direction_label=base_dir,
        ytd=None,
        press=press,
        weather=weather,
        close=close,
        volume=volume,
        rsi=rsi,
        raw_text="",
    )
