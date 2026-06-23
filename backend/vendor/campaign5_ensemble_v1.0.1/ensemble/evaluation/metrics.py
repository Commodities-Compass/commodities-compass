"""Metrics: efficacite_vs_oracle (selection metric) + classification suite.

Spec: methodology/framework-spec.md §4.9.

Selection metric: **efficacite_vs_oracle** ∈ [-1, 1]. Negative = anti-skill.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ensemble.models.base import CLASS_ORDER


@dataclass(frozen=True)
class MetricsResult:
    efficacite_vs_oracle: float
    coverage: float
    accuracy_conditional: float
    precision_per_class: dict[str, float]
    recall_per_class: dict[str, float]
    f1_per_class: dict[str, float]
    youden_j_per_class: dict[str, float]
    confusion_matrix: np.ndarray
    calibration_data: dict[str, np.ndarray]
    n_total: int
    n_committed: int

    def to_summary_dict(self) -> dict[str, float]:
        d = {
            "efficacite_vs_oracle": self.efficacite_vs_oracle,
            "coverage": self.coverage,
            "accuracy_conditional": self.accuracy_conditional,
            "n_total": self.n_total,
            "n_committed": self.n_committed,
        }
        for cls in self.precision_per_class:
            d[f"precision_{cls}"] = self.precision_per_class[cls]
            d[f"recall_{cls}"] = self.recall_per_class[cls]
            d[f"f1_{cls}"] = self.f1_per_class[cls]
            d[f"youden_j_{cls}"] = self.youden_j_per_class[cls]
        return d


def efficacite_vs_oracle(
    y_pred: pd.Series | np.ndarray,
    returns: pd.Series | np.ndarray,
    *,
    open_decision: str = "OPEN",
    hedge_decision: str = "HEDGE",
) -> float:
    """Selection metric: PnL_pred / PnL_oracle.

    PnL_pred =  sum over HEDGE rows of -returns  (avoid down move)
             + sum over OPEN rows of  +returns  (capture up move)
             + 0 for MONITOR rows
    PnL_oracle = sum of |returns|.

    Returns 0.0 if PnL_oracle == 0 (degenerate). Range is [-1, 1].
    """
    y_pred = np.asarray(y_pred)
    r = np.asarray(returns, dtype=float)
    if y_pred.shape != r.shape:
        raise ValueError(f"shape mismatch: y_pred={y_pred.shape} returns={r.shape}")

    pnl = np.where(
        y_pred == hedge_decision,
        -r,
        np.where(y_pred == open_decision, r, 0.0),
    )
    pnl_oracle = np.nansum(np.abs(r))
    if pnl_oracle == 0.0:
        return 0.0
    return float(np.nansum(pnl) / pnl_oracle)


def coverage(y_pred: pd.Series | np.ndarray, monitor_decision: str = "MONITOR") -> float:
    y_pred = np.asarray(y_pred)
    if len(y_pred) == 0:
        return 0.0
    return float((y_pred != monitor_decision).mean())


def accuracy_conditional(
    y_true_decision: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    monitor_decision: str = "MONITOR",
) -> float:
    """Accuracy among rows where the predictor committed (i.e. not MONITOR)."""
    y_true_decision = np.asarray(y_true_decision)
    y_pred = np.asarray(y_pred)
    mask = y_pred != monitor_decision
    if mask.sum() == 0:
        return 0.0
    return float((y_true_decision[mask] == y_pred[mask]).mean())


def _classification_breakdown(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    classes: tuple[str, ...],
) -> tuple[np.ndarray, dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    n_classes = len(classes)
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    for i, true_cls in enumerate(classes):
        for j, pred_cls in enumerate(classes):
            cm[i, j] = int(((y_true == true_cls) & (y_pred == pred_cls)).sum())

    precision: dict[str, float] = {}
    recall: dict[str, float] = {}
    f1: dict[str, float] = {}
    youden: dict[str, float] = {}
    n_total = cm.sum()
    for i, cls in enumerate(classes):
        tp = int(cm[i, i])
        fn = int(cm[i, :].sum() - tp)
        fp = int(cm[:, i].sum() - tp)
        tn = int(n_total - tp - fn - fp)
        precision[cls] = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall[cls] = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        denom = precision[cls] + recall[cls]
        f1[cls] = (2 * precision[cls] * recall[cls] / denom) if denom > 0 else 0.0
        sensitivity = recall[cls]
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0
        youden[cls] = sensitivity + specificity - 1.0
    return cm, precision, recall, f1, youden


def calibration_curve(
    p_down: pd.Series | np.ndarray,
    actual_down: pd.Series | np.ndarray,
    n_bins: int = 10,
) -> dict[str, np.ndarray]:
    """Reliability curve for the P_down probability."""
    p_down = np.asarray(p_down, dtype=float)
    actual = np.asarray(actual_down, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.clip(np.digitize(p_down, edges) - 1, 0, n_bins - 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    mean_pred = np.zeros(n_bins, dtype=float)
    mean_actual = np.zeros(n_bins, dtype=float)
    counts = np.zeros(n_bins, dtype=np.int64)
    for b in range(n_bins):
        mask = bin_idx == b
        counts[b] = int(mask.sum())
        if counts[b] > 0:
            mean_pred[b] = float(p_down[mask].mean())
            mean_actual[b] = float(actual[mask].mean())
    return {
        "bin_centers": centers,
        "mean_pred": mean_pred,
        "mean_actual": mean_actual,
        "counts": counts,
    }


def directional_accuracy(
    y_pred: pd.Series | np.ndarray,
    returns: pd.Series | np.ndarray,
    *,
    monitor_decision: str = "MONITOR",
) -> tuple[float, int, int]:
    """Daily directional accuracy among committed predictions.

    A prediction is *correct* if:
        - HEDGE and forward_return < 0
        - OPEN and forward_return > 0

    MONITOR rows are excluded from the denominator (don't penalize abstention).
    Forward_return == 0 rows are excluded as well (degenerate sign).

    Returns:
        (accuracy, n_correct, n_committed). accuracy = 0.0 if n_committed == 0.
    """
    y_pred = np.asarray(y_pred)
    r = np.asarray(returns, dtype=float)
    mask = (y_pred != monitor_decision) & (r != 0.0) & ~np.isnan(r)
    if mask.sum() == 0:
        return 0.0, 0, 0
    correct = ((y_pred[mask] == "HEDGE") & (r[mask] < 0)) | (
        (y_pred[mask] == "OPEN") & (r[mask] > 0)
    )
    n_correct = int(correct.sum())
    n_committed = int(mask.sum())
    return n_correct / n_committed, n_correct, n_committed


def monthly_accuracy(
    dates: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    returns: pd.Series | np.ndarray,
    *,
    monitor_decision: str = "MONITOR",
) -> pd.DataFrame:
    """Per-(year, month) directional accuracy table.

    Returns: DataFrame with columns ``year``, ``month``, ``accuracy``, ``n_correct``,
    ``n_committed``, ``n_total``, ``coverage``.
    """
    dates = pd.to_datetime(pd.Series(dates))
    r = np.asarray(returns, dtype=float)
    y = np.asarray(y_pred)
    df = pd.DataFrame({
        "year": dates.dt.year.values,
        "month": dates.dt.month.values,
        "pred": y,
        "r": r,
    })
    rows = []
    for (yr, mo), grp in df.groupby(["year", "month"], sort=True):
        acc, n_c, n_e = directional_accuracy(grp["pred"], grp["r"].to_numpy(), monitor_decision=monitor_decision)
        rows.append({
            "year": int(yr),
            "month": int(mo),
            "n_total": int(len(grp)),
            "n_committed": n_e,
            "coverage": (n_e / len(grp)) if len(grp) > 0 else 0.0,
            "n_correct": n_c,
            "accuracy": acc,
        })
    return pd.DataFrame(rows)


def compute_metrics(
    y_true: pd.Series | np.ndarray,
    y_pred: pd.Series | np.ndarray,
    p_down: pd.Series | np.ndarray,
    returns: pd.Series | np.ndarray,
) -> MetricsResult:
    """Compute the full metric suite.

    Args:
        y_true: target classes in {'DOWN', 'FLAT', 'UP'}.
        y_pred: predicted decisions in {'HEDGE', 'MONITOR', 'OPEN'}.
        p_down: predicted P(DOWN) per row.
        returns: realized forward returns aligned 1:1 with y_true.
    """
    y_true_arr = np.asarray(y_true, dtype=object)
    y_pred_arr = np.asarray(y_pred, dtype=object)

    # Map true class -> committed decision (DOWN->HEDGE, UP->OPEN, FLAT->MONITOR)
    true_decision = np.where(
        y_true_arr == "DOWN",
        "HEDGE",
        np.where(y_true_arr == "UP", "OPEN", "MONITOR"),
    )

    eff = efficacite_vs_oracle(y_pred_arr, returns)
    cov = coverage(y_pred_arr)
    acc = accuracy_conditional(true_decision, y_pred_arr)

    classes = CLASS_ORDER
    pred_class = np.where(
        y_pred_arr == "HEDGE",
        "DOWN",
        np.where(y_pred_arr == "OPEN", "UP", "FLAT"),
    )
    cm, prec, rec, f1, youden = _classification_breakdown(y_true_arr, pred_class, classes)
    calib = calibration_curve(p_down, (y_true_arr == "DOWN").astype(float))

    return MetricsResult(
        efficacite_vs_oracle=eff,
        coverage=cov,
        accuracy_conditional=acc,
        precision_per_class=prec,
        recall_per_class=rec,
        f1_per_class=f1,
        youden_j_per_class=youden,
        confusion_matrix=cm,
        calibration_data=calib,
        n_total=int(len(y_pred_arr)),
        n_committed=int((y_pred_arr != "MONITOR").sum()),
    )
