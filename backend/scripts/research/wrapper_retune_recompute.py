"""RESEARCH (non-production) — full in-process recompute of the C5 ensemble on CORRECTED
indicators, pinned to v1.0.0, + dump the soft-gate cache for the wrapper re-tune sweep.

Why: the macroeco fan-out bug corrupted pl_derived_indicators for ~3 months; the local
recompute that followed timed out and left stragglers (verify probe: 2026-02-01 stale).
This script re-runs decide() over ALL ensemble dates in ascending order — writing the
corrected soft-gate + wrapper + published rows back so each date's trailing window reads
corrected priors — and simultaneously caches the wrapper-INDEPENDENT soft-gate outputs
(+ today's 14 specialist votes) so the sweep can re-evaluate thousands of wrapper configs
in-memory with zero recompute.

Artifacts written to the scratchpad:
  - softgate_cache.parquet : 1 row/date — soft_gate_decision, net_score, macro/priors,
                             winter/spring signed, running_acc_5d/realized_return_5d (ref).
  - votes_long.parquet     : date × specialist_name × pred (today's votes).
  - chained.parquet        : full v_contract_data_chained (date, contract_id, h/l/close)
                             for returns / ATR-regime / forward-return computations.

Run: DATABASE_SYNC_URL=... PYTHONPATH=. poetry run python scripts/research/wrapper_retune_recompute.py [--no-write]
"""

from __future__ import annotations

import argparse
import dataclasses
import uuid

import pandas as pd
from ensemble.artifact_io import DBArtifactLoader
from ensemble.data_loader_protocol import DecideRequest
from ensemble.ensemble_pipeline import EnsemblePipeline
from ensemble.orchestrator.soft_gate import SoftGateOrchestrator
from sqlalchemy import text

from scripts.db import get_session
from scripts.ensemble_compute.cluster_mapping_loader import (
    REGIME_MONITOR_ATR_PCTL_KEY,
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
from scripts.ensemble_compute.db_writer import write_decision
from scripts.front_month import front_month_for_date

ALGO_NAME = "ensemble_v1_softgate_wrapper"
ALGO_VERSION = "1.0.0"
MARKET_LOOKBACK_DAYS = 600
_REGIME_ATR_WINDOW = 252
SCRATCH = "/private/tmp/claude-501/-Users-hediblagui-Developer-work-commodities-compass/7899f171-a6c8-4f83-b792-ca6cafc37aa6/scratchpad"


class _Adapter:
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


# --- verbatim copies from scripts/ensemble_compute/main.py (avoid importing the module,
#     which runs bootstrap_scraper/@monitor side effects at import time) ---
def _regime_monitor_fires(market, threshold, wrapped_decision) -> bool:
    if threshold is None or wrapped_decision == "MONITOR":
        return False
    m = market.dropna(subset=["atr_14d", "close"])
    if len(m) < 60:
        return False
    atr_pct = (m["atr_14d"].astype(float) / m["close"].astype(float)).to_numpy()
    window = atr_pct[-_REGIME_ATR_WINDOW:]
    pctl = float((window <= atr_pct[-1]).mean())
    return pctl > float(threshold)


_MACRO_HALF_LIFE_BREAKS = (0.30, 0.60)


def _macro_half_life_days(surprise: float) -> int:
    s = abs(float(surprise))
    if s < _MACRO_HALF_LIFE_BREAKS[0]:
        return 1
    if s < _MACRO_HALF_LIFE_BREAKS[1]:
        return 3
    return 7


def _build_diagnostics(decision, wrapper, macro) -> dict:
    sg = decision.soft_gate_decision
    return {
        "weights_sum": getattr(sg, "weights_sum", None),
        "n_committed_specialists": getattr(sg, "n_committed_specialists", None),
        "wrapper_active": decision.wrapped_decision != sg.decision,
        "fired_trend": bool(getattr(wrapper, "last_fired_trend", False)),
        "fired_three_way": bool(getattr(wrapper, "last_fired_three_way", False)),
        "macro_half_life_days": _macro_half_life_days(getattr(macro, "surprise", 0.0)),
    }


def _resolve_v100(session) -> uuid.UUID:
    row = session.execute(
        text("SELECT id FROM pl_algorithm_version WHERE name = :n AND version = :v"),
        {"n": ALGO_NAME, "v": ALGO_VERSION},
    ).fetchone()
    if row is None:
        raise RuntimeError(f"{ALGO_NAME} v{ALGO_VERSION} missing")
    return row[0]


def _training_month(session, vid) -> str:
    row = session.execute(
        text(
            "SELECT MAX(training_month) FROM pl_model_artifact "
            "WHERE algorithm_version_id = :aid AND artifact_kind = 'specialist_model' "
            "AND training_month IS NOT NULL"
        ),
        {"aid": vid},
    ).fetchone()
    return str(row[0])


def _assemble(session, vid):
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
    regime_threshold = load_optional_config_float(
        session, vid, REGIME_MONITOR_ATR_PCTL_KEY
    )
    return pipeline, regime_threshold


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true", help="cache only, no DB writes")
    ap.add_argument(
        "--limit", type=int, default=None, help="process only first N dates (smoke)"
    )
    args = ap.parse_args()

    with get_session() as session:
        vid = _resolve_v100(session)
        dates = [
            r[0]
            for r in session.execute(
                text(
                    "SELECT date FROM pl_orchestrator_decision "
                    "WHERE algorithm_version_id = :v ORDER BY date"
                ),
                {"v": vid},
            ).fetchall()
        ]
        if args.limit:
            dates = dates[: args.limit]
        print(
            f"pinned v{ALGO_VERSION} id={vid} — recomputing {len(dates)} dates "
            f"(write={'NO' if args.no_write else 'YES'})"
        )
        pipeline, regime_threshold = _assemble(session, vid)
        print(f"regime_threshold(atr-pctl)={regime_threshold}")

        cache_rows = []
        votes_rows = []
        dist = {"sg": {}, "wrapped": {}, "published": {}}
        for i, d in enumerate(dates):
            contract_id = front_month_for_date(session, d)
            market = load_market_history(
                session,
                end_date=d,
                contract_id=contract_id,
                lookback_days=MARKET_LOOKBACK_DAYS,
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
            dec = pipeline.decide(req)
            regime_fired = _regime_monitor_fires(
                market, regime_threshold, dec.wrapped_decision
            )
            published = "MONITOR" if regime_fired else dec.wrapped_decision

            sg = dec.soft_gate_decision
            ctx = sg.context
            cache_rows.append(
                {
                    "date": pd.Timestamp(d),
                    "contract_id": str(contract_id),
                    "soft_gate_decision": sg.decision,
                    "net_score": float(getattr(sg, "net_score", float("nan"))),
                    "macro_direction": int(getattr(ctx, "macro_direction", 0) or 0),
                    "macro_surprise": float(getattr(ctx, "macro_surprise", 0.0) or 0.0),
                    "prior_open": float(getattr(ctx, "prior_open", float("nan"))),
                    "prior_hedge": float(getattr(ctx, "prior_hedge", float("nan"))),
                    "prior_monitor": float(getattr(ctx, "prior_monitor", float("nan"))),
                    "anomaly_score_z": float(
                        getattr(ctx, "anomaly_score_z", float("nan"))
                    ),
                    "winter_vote_signed": int(dec.winter_vote_signed),
                    "spring_vote_signed": int(dec.spring_vote_signed),
                    "running_acc_5d_ref": float(dec.running_acc_5d)
                    if dec.running_acc_5d == dec.running_acc_5d
                    else float("nan"),
                    "realized_return_5d_ref": float(dec.realized_return_5d)
                    if dec.realized_return_5d == dec.realized_return_5d
                    else float("nan"),
                    "regime_fired_ref": bool(regime_fired),
                }
            )
            for name, pred in dec.per_specialist_votes.items():
                votes_rows.append(
                    {"date": pd.Timestamp(d), "specialist_name": name, "pred": pred}
                )

            for k, v in (
                ("sg", sg.decision),
                ("wrapped", dec.wrapped_decision),
                ("published", published),
            ):
                dist[k][v] = dist[k].get(v, 0) + 1

            if not args.no_write:
                diagnostics = _build_diagnostics(dec, pipeline.wrapper, macro)
                diagnostics["regime_monitor_fired"] = regime_fired
                write_decision(
                    session,
                    data_date=d,
                    contract_id=contract_id,
                    algorithm_version_id=vid,
                    decision=dec,
                    diagnostics=diagnostics,
                    final_decision=published,
                )
                session.commit()
            if (i + 1) % 20 == 0:
                print(f"  ... {i + 1}/{len(dates)}")

        # chained series for the sweep (returns / atr / forward)
        chained = pd.read_sql(
            text(
                "SELECT date, contract_id, high, low, close FROM v_contract_data_chained ORDER BY date"
            ),
            session.connection(),
        )

    cache = pd.DataFrame(cache_rows)
    votes = pd.DataFrame(votes_rows)
    cache.to_parquet(f"{SCRATCH}/softgate_cache.parquet")
    votes.to_parquet(f"{SCRATCH}/votes_long.parquet")
    chained.to_parquet(f"{SCRATCH}/chained.parquet")

    print("\n=== CORRECTED baseline distributions (this recompute) ===")
    for k in ("sg", "wrapped", "published"):
        ordered = sorted(dist[k].items(), key=lambda x: -x[1])
        print(f"  {k:<10} " + "  ".join(f"{dec}={n}" for dec, n in ordered))
    print(
        f"\ncache rows: {len(cache)}  votes rows: {len(votes)}  chained rows: {len(chained)}"
    )
    print(
        f"saved -> {SCRATCH}/softgate_cache.parquet, votes_long.parquet, chained.parquet"
    )


if __name__ == "__main__":
    main()
