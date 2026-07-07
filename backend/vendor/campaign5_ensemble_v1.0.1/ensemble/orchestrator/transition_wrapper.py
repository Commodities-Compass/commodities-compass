"""TransitionProtectionWrapper — Campaign 5 Step 1.

Post-processing layer around Phase 4's soft-gate orchestrator. For each day,
inspect 4 cheap "likely-wrong" detectors over signals ALREADY in the orchestrator
context. If any active detector fires AND the underlying decision is a commit
(OPEN/HEDGE), force MONITOR. Otherwise pass through the soft-gate's decision.

Detectors (each tunable on/off + threshold via Optuna):

    (a) Running-accuracy gate:
            running_acc_5d = orchestrator's committed-day accuracy over the
            previous 5 trading days. If running_acc_5d < τ_run AND we have
            at least min_running_n committed days in that window → fire.
            (NB: this is a CAUSAL diagnostic — uses only data from days strictly
            BEFORE today. No look-ahead.)

    (b) Trend-consensus conflict:
            realized_return_5d = product-1 of daily returns over the prior 5
            trading days. If sign(realized_return_5d) is OPPOSITE the orchestrator's
            net_score AND abs(realized_return_5d) > τ_trend → fire.

    (c) Specialist-cluster dispersion (duality-split):
            winter_votes_signed = (winter OPEN votes) - (winter HEDGE votes)
            spring_votes_signed = (spring OPEN votes) - (spring HEDGE votes)
            If sign(winter_votes_signed) != sign(spring_votes_signed) AND
            BOTH have at least min_cluster_n committed votes → fire.

    (d) Macro+prior+net_score 3-way disagreement:
            Define the sign-vote of each:
              macro_sgn = sign(macro_direction)
              prior_sgn = +1 if prior_open is strongest, -1 if prior_hedge, 0 if prior_monitor
              gate_sgn  = sign(net_score)
            Count nonzero agreements among the 3 signed values. If at most 1 of
            the 3 agrees with the majority direction → fire (signals overall
            disagreement; specialist gate may be confident-but-isolated).

Decision composition: if any ACTIVE detector fires, return MONITOR; otherwise
return the underlying soft-gate decision unchanged. The decision is fully
deterministic given the inputs.

This wrapper does NOT retrain anything. It is a pure POST-PROCESSING step,
applied to the existing Phase 4 per-day decision table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

Decision = Literal["OPEN", "HEDGE", "MONITOR"]

# Default cluster mapping (used only as a fallback in tests). Production callers
# MUST pass an explicit `cluster_mapping` loaded from `pl_algorithm_config` rows
# (`cluster_<specialist_name>` keys). Hardcoded constants here are the same 14
# specialists from Campaign 5 Step 1 — kept as a reference for testing only.
# Per CAMPAIGN_5_PROD_DEPLOYMENT.md §11 rule #5 compliance.
DEFAULT_CLUSTER_MAPPING: dict[str, str] = {
    # Winter
    "exp_optim_002": "winter",
    "exp_optim_005": "winter",
    "exp_optim_006": "winter",
    "exp_optim_011": "winter",
    "xpol_W_TB_garch": "winter",
    "xpol_W_TB_macro": "winter",
    # Spring
    "exp_optim_017_bear_4": "spring",
    "exp_optim_017_bear_8": "spring",
    "exp_optim_017_bull_4": "spring",
    "exp_optim_017_bull_5": "spring",
    "exp_optim_017_bull_7": "spring",
    "exp_optim_017_bull_8": "spring",
    "xpol_S_bull_garch_fx": "spring",
    "xpol_S_bear_garch_macro": "spring",
}


@dataclass(frozen=True)
class WrapperConfig:
    """Detector switches and thresholds. Each detector toggled on/off independently."""

    # (a) Running-accuracy gate
    use_running_acc: bool = True
    tau_run: float = 0.40
    running_window: int = 5
    min_running_n: int = 3

    # (b) Trend-consensus conflict
    use_trend_conflict: bool = True
    tau_trend: float = 0.02     # 2% absolute realized return over 5 days
    trend_window: int = 5

    # (c) Cluster dispersion (Winter vs Spring duality split)
    use_cluster_dispersion: bool = True
    min_cluster_n: int = 2

    # (d) Macro+prior+net_score disagreement
    use_three_way_disagreement: bool = True


@dataclass(frozen=True)
class WrapperDayDiagnostic:
    date: pd.Timestamp
    fired_running_acc: bool
    fired_trend: bool
    fired_dispersion: bool
    fired_three_way: bool
    any_fired: bool
    running_acc_5d: float
    realized_return_5d: float
    winter_vote_signed: int
    spring_vote_signed: int
    final_decision: Decision
    original_decision: Decision


class TransitionProtectionWrapper:
    """Apply post-processing detectors to a frozen orchestrator decision table.

    Public API:
        wrap = TransitionProtectionWrapper(config)
        wrapped, diagnostics = wrap.apply(decisions_df, votes_long_df, returns_series)

    Inputs:
        decisions_df: DataFrame with columns at least
            ['date','decision','net_score','macro_direction','prior_open',
             'prior_hedge','prior_monitor','committed','correct']
            (typically the Phase 4 decisions_per_day.csv).
        votes_long_df: DataFrame with ['date','pred','specialist_name'] —
            used for the cluster-dispersion detector.
        returns_series: pd.Series indexed by date with the daily close-to-close
            return. Used for the trend-conflict detector.

    Outputs:
        wrapped_df: same as decisions_df but with the wrapped decision in
            'decision_wrapped', plus diagnostic boolean columns per detector.
        diagnostics_df: detailed per-day diagnostic table.
    """

    def __init__(
        self,
        config: WrapperConfig | None = None,
        cluster_mapping: dict[str, str] | None = None,
    ) -> None:
        """Construct the wrapper.

        Args:
            config: WrapperConfig (detector switches + thresholds). Defaults to all-on.
            cluster_mapping: dict from specialist_name -> 'winter' | 'spring'. In production
                this is loaded from `pl_algorithm_config` rows (`cluster_<name>` keys) per
                rule #5 (config-as-data). Falls back to `DEFAULT_CLUSTER_MAPPING` (the R&D
                Campaign 5 Step 1 pool) only when not provided — convenient for tests but
                NOT recommended in production.
        """
        self.config: WrapperConfig = config or WrapperConfig()
        self.cluster_mapping: dict[str, str] = dict(cluster_mapping or DEFAULT_CLUSTER_MAPPING)
        self._winter_set: frozenset[str] = frozenset(
            name for name, cluster in self.cluster_mapping.items() if cluster == "winter"
        )
        self._spring_set: frozenset[str] = frozenset(
            name for name, cluster in self.cluster_mapping.items() if cluster == "spring"
        )

    # ---------- detector helpers ----------
    def _running_acc(
        self,
        decisions_df: pd.DataFrame,
        idx: int,
    ) -> tuple[float, int]:
        """Causal running accuracy over the prior `running_window` rows."""
        cfg = self.config
        if idx == 0:
            return float("nan"), 0
        start = max(0, idx - cfg.running_window)
        prior = decisions_df.iloc[start:idx]
        cmt = prior[prior["committed"].astype(bool)]
        n = int(len(cmt))
        if n < cfg.min_running_n:
            return float("nan"), n
        acc = float(cmt["correct"].astype(bool).mean())
        return acc, n

    def _realized_return_5d(
        self,
        returns_by_date: dict[pd.Timestamp, float],
        date: pd.Timestamp,
        sorted_dates: list[pd.Timestamp],
    ) -> float:
        """Causal cumulative return over prior `trend_window` trading days."""
        cfg = self.config
        try:
            j = sorted_dates.index(date)
        except ValueError:
            return float("nan")
        if j == 0:
            return float("nan")
        start = max(0, j - cfg.trend_window)
        prior_dates = sorted_dates[start:j]
        cum = 1.0
        for d in prior_dates:
            r = returns_by_date.get(d, float("nan"))
            if not np.isfinite(r):
                continue
            cum *= (1.0 + r)
        return float(cum - 1.0)

    def _cluster_votes(
        self,
        votes_by_date: pd.DataFrame,
        date: pd.Timestamp,
    ) -> tuple[int, int, int, int]:
        """Returns (winter_n_committed, winter_signed_sum, spring_n_committed, spring_signed_sum).

        Signed sum: +1 per OPEN vote, -1 per HEDGE, 0 per MONITOR.
        """
        day = votes_by_date[votes_by_date["date"] == date]
        winter = day[day["specialist_name"].isin(self._winter_set)]
        spring = day[day["specialist_name"].isin(self._spring_set)]
        def _signed(s: pd.Series) -> int:
            return int((s == "OPEN").sum() - (s == "HEDGE").sum())
        def _committed(s: pd.Series) -> int:
            return int((s != "MONITOR").sum())
        return _committed(winter["pred"]), _signed(winter["pred"]), _committed(spring["pred"]), _signed(spring["pred"])

    def _three_way_disagreement(
        self,
        row: pd.Series,
    ) -> bool:
        """Return True if at most ONE of {macro, prior, net_score} agrees with the majority direction."""
        macro_sgn = int(np.sign(row.get("macro_direction", 0)))
        prior_open = float(row.get("prior_open", 1/3))
        prior_hedge = float(row.get("prior_hedge", 1/3))
        prior_mon = float(row.get("prior_monitor", 1/3))
        if prior_open >= max(prior_hedge, prior_mon):
            prior_sgn = +1
        elif prior_hedge >= max(prior_open, prior_mon):
            prior_sgn = -1
        else:
            prior_sgn = 0
        gate_sgn = int(np.sign(row.get("net_score", 0)))
        signs = [s for s in (macro_sgn, prior_sgn, gate_sgn) if s != 0]
        if len(signs) < 2:
            return False
        majority = +1 if sum(signs) > 0 else -1
        n_agree = sum(1 for s in signs if s == majority)
        # Disagreement = strict minority of nonzero signs agree with majority
        return n_agree <= 1

    # ---------- main entry ----------
    def apply(
        self,
        decisions_df: pd.DataFrame,
        votes_long_df: pd.DataFrame,
        returns_series: pd.Series,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        cfg = self.config
        decisions_df = decisions_df.copy()
        decisions_df["date"] = pd.to_datetime(decisions_df["date"])
        decisions_df = decisions_df.sort_values("date").reset_index(drop=True)
        votes_long_df = votes_long_df.copy()
        votes_long_df["date"] = pd.to_datetime(votes_long_df["date"])
        returns_by_date = {pd.Timestamp(d): float(v) for d, v in returns_series.items()}
        sorted_dates = sorted(returns_by_date.keys())

        wrapped_rows: list[dict] = []
        diags: list[WrapperDayDiagnostic] = []

        for idx, row in decisions_df.iterrows():
            d = pd.Timestamp(row["date"])
            orig: Decision = str(row["decision"])  # type: ignore[assignment]

            # Detector (a) — running accuracy
            run_acc, run_n = self._running_acc(decisions_df, int(idx))
            fired_a = bool(
                cfg.use_running_acc
                and np.isfinite(run_acc)
                and run_acc < cfg.tau_run
                and run_n >= cfg.min_running_n
            )

            # Detector (b) — trend conflict
            r5 = self._realized_return_5d(returns_by_date, d, sorted_dates)
            net = float(row["net_score"])
            fired_b = False
            if cfg.use_trend_conflict and np.isfinite(r5) and abs(r5) > cfg.tau_trend and net != 0:
                if np.sign(r5) != np.sign(net):
                    fired_b = True

            # Detector (c) — cluster dispersion
            w_n, w_signed, s_n, s_signed = self._cluster_votes(votes_long_df, d)
            fired_c = bool(
                cfg.use_cluster_dispersion
                and w_n >= cfg.min_cluster_n
                and s_n >= cfg.min_cluster_n
                and w_signed != 0
                and s_signed != 0
                and np.sign(w_signed) != np.sign(s_signed)
            )

            # Detector (d) — 3-way disagreement
            fired_d = bool(
                cfg.use_three_way_disagreement
                and self._three_way_disagreement(row)
            )

            any_fired = fired_a or fired_b or fired_c or fired_d
            new_decision: Decision = "MONITOR" if (any_fired and orig != "MONITOR") else orig

            wrapped_rows.append({
                **row.to_dict(),
                "decision_wrapped": new_decision,
                "fired_running_acc": fired_a,
                "fired_trend": fired_b,
                "fired_dispersion": fired_c,
                "fired_three_way": fired_d,
                "wrapper_active": any_fired,
                "running_acc_5d": run_acc,
                "realized_return_5d": r5,
                "winter_vote_signed": w_signed,
                "spring_vote_signed": s_signed,
            })
            diags.append(WrapperDayDiagnostic(
                date=d,
                fired_running_acc=fired_a, fired_trend=fired_b,
                fired_dispersion=fired_c, fired_three_way=fired_d,
                any_fired=any_fired,
                running_acc_5d=float(run_acc) if np.isfinite(run_acc) else float("nan"),
                realized_return_5d=float(r5) if np.isfinite(r5) else float("nan"),
                winter_vote_signed=int(w_signed),
                spring_vote_signed=int(s_signed),
                final_decision=new_decision,
                original_decision=orig,
            ))
        wrapped = pd.DataFrame(wrapped_rows)

        # Recompute committed/correct using the wrapped decision + the same forward_return
        wrapped["committed_wrapped"] = wrapped["decision_wrapped"] != "MONITOR"
        wrapped["correct_wrapped"] = (
            ((wrapped["decision_wrapped"] == "HEDGE") & (wrapped["forward_return"] < 0))
            | ((wrapped["decision_wrapped"] == "OPEN") & (wrapped["forward_return"] > 0))
        )

        diag_df = pd.DataFrame([d.__dict__ for d in diags])
        return wrapped, diag_df
