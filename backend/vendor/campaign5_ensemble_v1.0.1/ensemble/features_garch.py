"""GARCH(1,1) residual features (Engle 1982; Bollerslev 1986).

For each row t, compute the standardised residual of a GARCH(1,1) fit to the
*causal* past window of daily returns. This deflates the return by its
conditional volatility, isolating the "surprise" component.

CLAUDE.md context: NM-002 confirms GARCH(1,1) on cocoa eliminates ARCH (LM 206 →
6.9). Whether this adds *incremental predictive value* over rolling pctrank is
OQ-020 — this module is the prerequisite to that test.

References:
    - Engle (1982) — ARCH.
    - Bollerslev (1986) — GARCH(1,1).
    - `arch` package: https://pypi.org/project/arch/
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


def garch_residual_series(
    df: pd.DataFrame,
    *,
    fit_window: int = 500,
    refit_every: int = 22,
    return_col: str = "daily_return",
) -> pd.Series:
    """Causal rolling GARCH(1,1) standardised residuals.

    Strategy: re-fit GARCH(1,1) every ``refit_every`` rows on a trailing window of
    ``fit_window`` returns; between refits, propagate the conditional vol using
    the last fit. This balances cost vs accuracy.

    Returns:
        Series aligned to df.index. The first ``fit_window`` rows are NaN.
    """
    if return_col not in df.columns:
        raise ValueError(f"DataFrame missing {return_col!r}")
    r = df[return_col].astype(float).fillna(0.0).to_numpy() * 100.0  # rescale (arch convention)
    n = len(r)
    resid_std = np.full(n, np.nan, dtype=float)
    from arch import arch_model

    last_omega = last_alpha = last_beta = None
    last_sigma2 = None

    for t in range(n):
        if t < fit_window:
            continue
        need_refit = (t == fit_window) or ((t - fit_window) % refit_every == 0)
        if need_refit:
            try:
                window = r[t - fit_window : t]
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    am = arch_model(window, vol="GARCH", p=1, q=1, mean="Zero", dist="normal")
                    res = am.fit(disp="off", show_warning=False, options={"maxiter": 50})
                params = res.params
                last_omega = float(params.get("omega", 0.0))
                last_alpha = float(params.get("alpha[1]", 0.0))
                last_beta = float(params.get("beta[1]", 0.0))
                # Initial sigma2 = last conditional variance
                last_sigma2 = float(res.conditional_volatility.iloc[-1]) ** 2 if hasattr(res.conditional_volatility, "iloc") else float(res.conditional_volatility[-1]) ** 2
            except Exception:
                # If GARCH fitting fails (rare), keep the last params; mark NaN this step
                continue
        # Propagate sigma2 one step using last params and the previous return
        if last_omega is None or last_sigma2 is None:
            continue
        prev_r = float(r[t - 1])
        next_sigma2 = last_omega + last_alpha * prev_r ** 2 + last_beta * last_sigma2
        if next_sigma2 <= 0.0 or not np.isfinite(next_sigma2):
            continue
        resid_std[t] = float(r[t]) / float(np.sqrt(next_sigma2))
        last_sigma2 = next_sigma2

    return pd.Series(resid_std, index=df.index, name=f"garch_resid_w{fit_window}")
