"""RESEARCH (non-production) — verify stored soft-gate outputs are on CORRECTED indicators.

Context: the macroeco fan-out bug (PR #74) corrupted pl_derived_indicators for ~3 months.
The ensemble reads those indicators as passthrough features, so every stored
pl_orchestrator_decision written by the daily cron over that window used CORRUPT inputs.
Before we re-tune the wrapper on the stored soft-gate outputs, we must confirm those
outputs reflect the corrected indicators (i.e. the local recompute actually refreshed them).

Method: pin v1.0.0 explicitly (local DB has two same-named version rows), assemble the
pipeline exactly like scripts/ensemble_compute/main.py, re-run decide() on a spread of
sample dates reading the (now corrected) v_contract_data_chained × pl_derived_indicators,
and diff the freshly-computed soft_gate_decision + net_score against the stored row.

  all OK   -> stored soft-gate == corrected recompute -> safe to build the cache from the DB.
  any DIFF -> stored soft-gate is stale/corrupt        -> must full-recompute before tuning.

Run: DATABASE_SYNC_URL=... PYTHONPATH=. poetry run python scripts/research/wrapper_retune_verify.py
"""

from __future__ import annotations

import dataclasses
import math
import uuid

import pandas as pd
from ensemble.artifact_io import DBArtifactLoader
from ensemble.data_loader_protocol import DecideRequest
from ensemble.ensemble_pipeline import EnsemblePipeline
from ensemble.orchestrator.soft_gate import SoftGateOrchestrator
from sqlalchemy import text

from scripts.db import get_session
from scripts.ensemble_compute.cluster_mapping_loader import (
    SOFTGATE_ALPHA_MACRO_CAP_KEY,
    load_cluster_mapping,
    load_compass_wrapper_threshold,
    load_optional_config_float,
    load_wrapper_config,
)
from scripts.ensemble_compute.compass_wrapper import CompassTransitionWrapper
from scripts.ensemble_compute.db_loader import (
    load_macro_signal,
    load_market_history,
    load_recent_orchestrator_decisions,
    load_recent_specialist_votes,
)
from scripts.front_month import front_month_for_date

ALGO_NAME = "ensemble_v1_softgate_wrapper"
ALGO_VERSION = "1.0.0"  # pin: local DB has 1.0.0 (live) + 1.0.1 (shadow, same name)
MARKET_LOOKBACK_DAYS = 600
N_SAMPLE = 10


class _Adapter:
    """SQLAlchemy-2 text() wrapper so R&D's DBArtifactLoader works (mirror of main.py)."""

    def __init__(self, session) -> None:
        self._session = session

    def execute(self, sql, params=None):
        if isinstance(sql, str):
            sql = text(sql)
        return (
            self._session.execute(sql)
            if params is None
            else self._session.execute(sql, params)
        )

    def __getattr__(self, name):
        return getattr(self._session, name)


def _resolve_v100(session) -> uuid.UUID:
    row = session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :n AND version = :v"),
        {"n": ALGO_NAME, "v": ALGO_VERSION},
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"{ALGO_NAME} v{ALGO_VERSION} missing from pl_algorithm_version"
        )
    return row[0]


def _training_month(session, vid: uuid.UUID) -> str:
    row = session.execute(
        text(
            "SELECT MAX(training_month) FROM pl_model_artifact "
            "WHERE algorithm_version_id = :aid AND artifact_kind = 'specialist_model' "
            "AND training_month IS NOT NULL"
        ),
        {"aid": vid},
    ).fetchone()
    if row is None or row[0] is None:
        raise RuntimeError("no specialist_model artifacts for v1.0.0")
    return str(row[0])


def _assemble_pipeline(session, vid: uuid.UUID) -> EnsemblePipeline:
    """Assemble the v1.0.0 pipeline exactly as main.py (cluster mapping, compass wrapper,
    alpha_macro cap). The wrapper config is irrelevant for the soft-gate outputs we diff,
    but we set it up faithfully so the object is identical to prod."""
    cluster_mapping = load_cluster_mapping(session, vid)
    tm = _training_month(session, vid)
    loader = DBArtifactLoader(_Adapter(session), str(vid))
    pipeline = EnsemblePipeline.from_loader(
        loader, training_month=tm, cluster_mapping=cluster_mapping
    )
    compass_threshold = load_compass_wrapper_threshold(session, vid)
    wrapper_config = load_wrapper_config(session, vid)
    pipeline.wrapper = CompassTransitionWrapper(
        config=wrapper_config,
        cluster_mapping=pipeline.wrapper.cluster_mapping,
        dispersion_with_acc_threshold=compass_threshold,
    )
    alpha_cap = load_optional_config_float(session, vid, SOFTGATE_ALPHA_MACRO_CAP_KEY)
    if alpha_cap is not None and pipeline.soft_gate.config.alpha_macro > alpha_cap:
        pipeline.soft_gate = SoftGateOrchestrator(
            config=dataclasses.replace(
                pipeline.soft_gate.config, alpha_macro=alpha_cap
            ),
            base_accuracy=pipeline.soft_gate.base_accuracy,
        )
    return pipeline


def _decide(session, pipeline, vid, d):
    contract_id = front_month_for_date(session, d)
    market = load_market_history(
        session, end_date=d, contract_id=contract_id, lookback_days=MARKET_LOOKBACK_DAYS
    )
    rd = load_recent_orchestrator_decisions(
        session, end_date=d, contract_id=contract_id, algorithm_version_id=vid
    )
    rv = load_recent_specialist_votes(
        session, end_date=d, contract_id=contract_id, algorithm_version_id=vid
    )
    macro = load_macro_signal(session, today=d)
    req = DecideRequest(
        today=pd.Timestamp(d),
        contract_id=str(contract_id),
        market_history=market,
        recent_decisions=rd,
        recent_votes=rv,
        macro=macro,
    )
    return pipeline.decide(req)


def main() -> None:
    with get_session() as session:
        vid = _resolve_v100(session)
        all_dates = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT date FROM pl_orchestrator_decision "
                    "WHERE algorithm_version_id = :v ORDER BY date"
                ),
                {"v": vid},
            ).fetchall()
        ]
        step = max(1, len(all_dates) // N_SAMPLE)
        sample = all_dates[::step][:N_SAMPLE]
        print(
            f"pinned v{ALGO_VERSION} id={vid}  ({len(all_dates)} dates, sampling {len(sample)})"
        )
        pipeline = _assemble_pipeline(session, vid)
        print(
            f"{'date':<12}{'sg_new':>8}{'sg_db':>8}{'ns_new':>10}{'ns_db':>10}"
            f"{'wrap_new':>10}{'wrap_db':>10}{'':>3}"
        )
        n_sg_match = 0
        n_wrap_match = 0
        for d in sample:
            dec = _decide(session, pipeline, vid, d)
            row = session.execute(
                text(
                    "SELECT soft_gate_decision, net_score, decision_wrapped "
                    "FROM pl_orchestrator_decision "
                    "WHERE algorithm_version_id = :v AND date = :d"
                ),
                {"v": vid, "d": d},
            ).fetchone()
            sg_new = dec.soft_gate_decision.decision
            ns_new = float(getattr(dec.soft_gate_decision, "net_score", float("nan")))
            wrap_new = dec.wrapped_decision
            sg_db, ns_db_raw, wrap_db = row[0], row[1], row[2]
            ns_db = float(ns_db_raw) if ns_db_raw is not None else float("nan")
            sg_ok = sg_new == sg_db and (
                (math.isnan(ns_new) and math.isnan(ns_db)) or abs(ns_new - ns_db) < 1e-3
            )
            wrap_ok = wrap_new == wrap_db
            n_sg_match += int(sg_ok)
            n_wrap_match += int(wrap_ok)
            flag = "OK" if sg_ok else "SG!"
            if sg_ok and not wrap_ok:
                flag = "wrap!"
            print(
                f"{str(d):<12}{sg_new:>8}{sg_db:>8}{ns_new:>10.4f}{ns_db:>10.4f}"
                f"{wrap_new:>10}{wrap_db:>10}{flag:>5}"
            )
        print(
            f"\nsoft-gate match {n_sg_match}/{len(sample)}  |  wrapped match {n_wrap_match}/{len(sample)}"
        )
        if n_sg_match == len(sample):
            print(
                "=> stored soft-gate == corrected recompute. Safe to build cache from DB."
            )
        else:
            print(
                "=> stored soft-gate DIFFERS from corrected recompute => STALE. Full recompute required."
            )


if __name__ == "__main__":
    main()
