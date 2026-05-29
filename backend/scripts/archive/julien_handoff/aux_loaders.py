"""Auxiliary loaders — tables that don't pivot naturally into the daily-wide CSV.

These produce standalone CSVs alongside the main cocoa_rd_dataset_YYYYMMDD.csv.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import Engine, text


def load_specialist_predictions(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """All 14 specialist votes per day for the window. Long format.

    Includes contract code, algorithm version name, prediction class,
    window_months (12 baseline / 24 GARCH), feature count, and the back-filled
    forward 6d return (NaN until h=6 horizon expires).
    """
    sql = text(
        """
        SELECT
            sp.date,
            c.code AS contract_code,
            av.name AS algorithm_name,
            av.version AS algorithm_version,
            sp.specialist_name,
            sp.window_months,
            sp.pred,
            sp.n_features_used,
            sp.forward_return_6d,
            sp.created_at
        FROM pl_specialist_prediction sp
        JOIN ref_contract c ON c.id = sp.contract_id
        JOIN pl_algorithm_version av ON av.id = sp.algorithm_version_id
        WHERE sp.date BETWEEN :start AND :end
        ORDER BY sp.date, sp.specialist_name
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_orchestrator_decisions(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """C5 soft-gate + wrapper decision audit trail (one row per day)."""
    sql = text(
        """
        SELECT
            od.date,
            c.code AS contract_code,
            av.name AS algorithm_name,
            av.version AS algorithm_version,
            od.soft_gate_decision,
            od.decision_wrapped,
            od.net_score,
            od.weights_sum,
            od.n_committed_specialists,
            od.wrapper_active,
            od.fired_running_acc,
            od.fired_trend,
            od.fired_dispersion,
            od.fired_three_way,
            od.running_acc_5d,
            od.realized_return_5d,
            od.winter_vote_signed,
            od.spring_vote_signed,
            od.macro_direction,
            od.macro_surprise,
            od.macro_half_life_days,
            od.anomaly_score_z,
            od.prior_open,
            od.prior_hedge,
            od.prior_monitor,
            od.created_at
        FROM pl_orchestrator_decision od
        JOIN ref_contract c ON c.id = od.contract_id
        JOIN pl_algorithm_version av ON av.id = od.algorithm_version_id
        WHERE od.date BETWEEN :start AND :end
        ORDER BY od.date, av.version
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_signal_components(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Per-indicator decomposition (raw, normalized, weighted_contribution). Long."""
    sql = text(
        """
        SELECT
            sc.date,
            c.code AS contract_code,
            av.name AS algorithm_name,
            av.version AS algorithm_version,
            sc.indicator_name,
            sc.raw_value,
            sc.normalized_value,
            sc.weighted_contribution,
            sc.created_at
        FROM pl_signal_component sc
        JOIN ref_contract c ON c.id = sc.contract_id
        LEFT JOIN pl_algorithm_version av ON av.id = sc.algorithm_version_id
        WHERE sc.date BETWEEN :start AND :end
        ORDER BY sc.date, av.version NULLS LAST, sc.indicator_name
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_article_segments(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Raw pl_article_segment rows (high-confidence only) for the window.

    Filters confidence >= 0.70 to match the MacroEventLayer threshold so
    Julien sees exactly the segments the C5 ensemble considers. Joined back
    to pl_fundamental_article for title/source/url context.
    """
    sql = text(
        """
        SELECT
            s.article_date,
            a.title,
            a.source,
            a.category,
            a.llm_provider AS article_provider,
            a.is_active AS article_is_active,
            s.zone,
            s.theme,
            s.sentiment,
            s.sentiment_score,
            s.confidence,
            s.facts,
            s.causal_chains,
            s.entities,
            s.llm_provider AS segment_provider,
            s.llm_model,
            s.extraction_version,
            s.created_at
        FROM pl_article_segment s
        JOIN pl_fundamental_article a ON a.id = s.article_id
        WHERE s.article_date BETWEEN :start AND :end
          AND s.confidence >= 0.70
        ORDER BY s.article_date, s.zone, s.theme
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_fundamental_articles(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Active press review articles for the window (one per day, prod provider)."""
    sql = text(
        """
        SELECT
            date,
            category,
            source,
            title,
            summary,
            keywords,
            sentiment,
            impact_synthesis,
            llm_provider,
            is_active,
            source_count,
            total_sources,
            created_at
        FROM pl_fundamental_article
        WHERE date BETWEEN :start AND :end
          AND is_active = TRUE
        ORDER BY date
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_weather_observations(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Daily Compass weather narrative + per-site qualitative diagnostics (JSONB)."""
    sql = text(
        """
        SELECT
            date,
            region,
            observation,
            summary,
            keywords,
            impact_assessment,
            diagnostics,
            created_at
        FROM pl_weather_observation
        WHERE date BETWEEN :start AND :end
        ORDER BY date
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_seasonal_scores(engine: Engine) -> pd.DataFrame:
    """Per-location seasonal scoring (current campaign and prior, all seasons)."""
    sql = text(
        """
        SELECT
            campaign,
            season_name,
            location_name,
            months_covered,
            start_date,
            end_date,
            total_precip_mm,
            total_et0_mm,
            cumulative_balance_mm,
            days_rain,
            days_stress_temp,
            avg_tmax,
            harmattan_days,
            score,
            computed_at
        FROM pl_seasonal_score
        ORDER BY campaign DESC, start_date, location_name
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)


def load_sentiment_features(engine: Engine, start: date, end: date) -> pd.DataFrame:
    """Shadow-mode sentiment features (z-score + delta-3d) per theme.

    Built by the compute-sentiment-features pipeline. Not yet injected into
    the engine composite — Julien gets to see the raw shadow signal.
    """
    sql = text(
        """
        SELECT
            date,
            theme,
            raw_score,
            zscore,
            zscore_delta,
            min_periods_met,
            created_at
        FROM pl_sentiment_feature
        WHERE date BETWEEN :start AND :end
        ORDER BY date, theme
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn, params={"start": start, "end": end})


def load_algorithm_versions(engine: Engine) -> pd.DataFrame:
    """Snapshot of all algorithm versions with their is_active / compute_enabled flags."""
    sql = text(
        """
        SELECT name, version, horizon, is_active, compute_enabled,
               description, created_at
        FROM pl_algorithm_version
        ORDER BY name, version
        """
    )
    with engine.connect() as conn:
        return pd.read_sql(sql, conn)
