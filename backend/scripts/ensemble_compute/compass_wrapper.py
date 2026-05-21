"""Compass-side override of the R&D TransitionProtectionWrapper.

The vendored wrapper combines its 4 detectors with a pure OR — any single
fire forces MONITOR. Empirically this is too aggressive: on our 2026
backfill, ``cluster_dispersion`` alone vetoed 28/63 soft-gate commits
while ``running_acc_5d`` averaged 0.981 on those same days (i.e. the
algorithm was on a strong winning streak when the wrapper killed the
commit). Wrapper coverage stayed at 17% vs R&D 46.1%.

This subclass relaxes that veto by post-processing the wrapped DataFrame
the vendor produced. The rule:

  fired_running_acc  → veto (unchanged — gate-accuracy is direct signal)
  fired_trend        → veto (unchanged — off in v1.0.0 anyway)
  fired_three_way    → veto (unchanged — off in v1.0.0 anyway)
  fired_dispersion alone, with running_acc_5d ≥ threshold → RELEASE
  fired_dispersion + low running_acc_5d              → veto (still legitimate)

Zero code duplication: we call ``super().apply()`` to get the canonical
output + diagnostics, then rewrite the rows that should be released.
Audit-friendly: every flip is reflected in ``wrapper_active=False`` on
the wrapped row and ``any_fired=False`` on the diagnostic row, so the
audit trail still tells you which rows were released by this override.
"""

from __future__ import annotations

import pandas as pd

from ensemble.orchestrator.transition_wrapper import (
    TransitionProtectionWrapper,
    WrapperConfig,
)


class CompassTransitionWrapper(TransitionProtectionWrapper):
    """Vendor wrapper with an AND-gated relaxation of the dispersion veto.

    The ``dispersion_with_acc_threshold`` parameter is required: it is loaded
    from ``pl_algorithm_config`` (key
    ``compass_wrapper_dispersion_with_acc_threshold``) by the caller — see
    ``scripts.ensemble_compute.cluster_mapping_loader.load_compass_wrapper_threshold``.
    No hardcoded fallback by design (north-star rule #4: config as data).
    """

    def __init__(
        self,
        *,
        dispersion_with_acc_threshold: float,
        config: WrapperConfig | None = None,
        cluster_mapping: dict[str, str] | None = None,
    ) -> None:
        super().__init__(config=config, cluster_mapping=cluster_mapping)
        self.dispersion_with_acc_threshold = float(dispersion_with_acc_threshold)

    def apply(
        self,
        decisions_df: pd.DataFrame,
        votes_long_df: pd.DataFrame,
        returns_series: pd.Series,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        wrapped, diag_df = super().apply(decisions_df, votes_long_df, returns_series)

        if wrapped.empty:
            return wrapped, diag_df

        # Defensive copy: super().apply() returns a freshly-built frame in
        # the current vendor implementation, but we mutate it below — copy
        # to keep the override side-effect-free if the vendor ever caches.
        wrapped = wrapped.copy()

        threshold = self.dispersion_with_acc_threshold

        # Release condition: only dispersion fired, no other detector. When
        # running_acc_5d is finite we require it to be ≥ threshold (the gate
        # was on a healthy streak). When it's NaN (bootstrap / cold-start
        # window without enough prior committed rows), default-allow: with no
        # accuracy signal available, dispersion alone is too weak to veto
        # (empirically it vetoes 73% of soft-gate commits in our backfill,
        # most of them wrongly when measured against forward return).
        running_acc_ok = wrapped["running_acc_5d"].isna() | (
            wrapped["running_acc_5d"] >= threshold
        )
        release_mask = (
            (~wrapped["fired_running_acc"].astype(bool))
            & (~wrapped["fired_trend"].astype(bool))
            & (~wrapped["fired_three_way"].astype(bool))
            & wrapped["fired_dispersion"].astype(bool)
            & running_acc_ok
        )

        if not release_mask.any():
            return wrapped, diag_df

        # Restore the original soft-gate decision for released rows.
        wrapped.loc[release_mask, "decision_wrapped"] = wrapped.loc[
            release_mask, "decision"
        ]
        wrapped.loc[release_mask, "wrapper_active"] = False

        # Re-derive committed/correct on the released rows.
        wrapped["committed_wrapped"] = wrapped["decision_wrapped"] != "MONITOR"
        if "forward_return" in wrapped.columns:
            fr = pd.to_numeric(wrapped["forward_return"], errors="coerce")
            wrapped["correct_wrapped"] = (
                (wrapped["decision_wrapped"] == "HEDGE") & (fr < 0)
            ) | ((wrapped["decision_wrapped"] == "OPEN") & (fr > 0))

        # Mirror the release in the diagnostic frame so audits stay consistent.
        if not diag_df.empty:
            diag_df = diag_df.copy()
            released_dates = set(
                pd.to_datetime(wrapped.loc[release_mask, "date"]).tolist()
            )
            diag_mask = pd.to_datetime(diag_df["date"]).isin(released_dates)
            diag_df.loc[diag_mask, "final_decision"] = diag_df.loc[
                diag_mask, "original_decision"
            ]
            diag_df.loc[diag_mask, "any_fired"] = False

        return wrapped, diag_df
