"""Coverage + accuracy report comparing the local PR 1+2+3 backfill to R&D's expected numbers.

Reads pl_orchestrator_decision (ensemble_v1) joined to the chained
v_contract_data_chained VIEW to compute the 6d forward return per row,
then aggregates monthly + YTD soft-gate and wrapper coverage / accuracy.

Usage (from backend/):
    poetry run python scripts/_analyze_backfill_coverage.py
"""

from __future__ import annotations

import os

import pandas as pd
from sqlalchemy import create_engine, text

ENSEMBLE_VERSION_ID = os.environ.get(
    "ENSEMBLE_VERSION_ID", "73f1fa9f-904f-4c92-9a4c-4ae4a4fa690a"
)

# R&D's expected numbers (from user's screenshot).
RND = {
    "2026-01": {"sg_acc": "9/13", "sg_cov": "13/19", "wr_acc": "6/6", "wr_cov": "6/19"},
    "2026-02": {
        "sg_acc": "16/20",
        "sg_cov": "20/21",
        "wr_acc": "14/15",
        "wr_cov": "15/21",
    },
    "2026-03": {
        "sg_acc": "10/22",
        "sg_cov": "22/22",
        "wr_acc": "6/9",
        "wr_cov": "9/22",
    },
    "2026-04": {
        "sg_acc": "12/17",
        "sg_cov": "17/20",
        "wr_acc": "7/10",
        "wr_cov": "10/20",
    },
    "2026-05": {"sg_acc": "3/5", "sg_cov": "5/7", "wr_acc": "1/1", "wr_cov": "1/7"},
    "YTD": {"sg_acc": "50/77", "sg_cov": "77/89", "wr_acc": "34/41", "wr_cov": "41/89"},
}


QUERY = """
WITH base AS (
    SELECT
        o.date::DATE                              AS date,
        o.soft_gate_decision                      AS sg,
        o.decision_wrapped                        AS wr,
        cur.close                                 AS close_t,
        (
            SELECT close FROM v_contract_data_chained f
            WHERE f.date > o.date
            ORDER BY f.date ASC OFFSET 5 LIMIT 1
        )                                         AS close_t6
    FROM pl_orchestrator_decision o
    JOIN v_contract_data_chained cur ON cur.date = o.date
    WHERE o.algorithm_version_id = :algo
      AND o.date BETWEEN '2026-01-01' AND '2026-05-31'
)
SELECT
    date,
    sg,
    wr,
    CASE
        WHEN close_t6 IS NULL OR close_t IS NULL THEN NULL
        ELSE close_t6 / close_t - 1.0
    END AS fwd_ret
FROM base
ORDER BY date
"""


def _is_correct(decision: str, fwd_ret: float | None) -> bool | None:
    if fwd_ret is None or pd.isna(fwd_ret):
        return None
    if decision == "OPEN":
        return fwd_ret > 0
    if decision == "HEDGE":
        return fwd_ret < 0
    return None  # MONITOR is not scored


def main() -> int:
    url = os.environ.get(
        "DATABASE_SYNC_URL",
        "postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass",
    )
    engine = create_engine(url)

    with engine.connect() as conn:
        df = pd.read_sql(text(QUERY), conn, params={"algo": ENSEMBLE_VERSION_ID})

    if df.empty:
        print("No ensemble_v1 rows found in [2026-01-01, 2026-05-31]")
        return 0

    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.strftime("%Y-%m")
    df["fwd_ret"] = pd.to_numeric(df["fwd_ret"], errors="coerce")

    df["sg_correct"] = df.apply(lambda r: _is_correct(r["sg"], r["fwd_ret"]), axis=1)
    df["wr_correct"] = df.apply(lambda r: _is_correct(r["wr"], r["fwd_ret"]), axis=1)
    # Scorable = forward_return realized (6-day horizon closed). Pending rows
    # are excluded from BOTH numerator and denominator so the metrics aren't
    # diluted by recent dates whose outcome isn't known yet.
    df["scorable"] = df["fwd_ret"].notna()

    scorable_df = df[df["scorable"]].copy()
    n_scorable_total = len(scorable_df)
    n_pending = len(df) - n_scorable_total

    print(
        f"\nBackfill rows: {len(df)} (dates {df['date'].min().date()} → {df['date'].max().date()})"
    )
    print(f"Scorable: {n_scorable_total} | Pending forward_return: {n_pending}")
    print(
        "R&D reference: YTD soft-gate 50/77 (acc 64.9%) / cov 77/89 (86.5%) — wrapper 34/41 (acc 82.9%) / cov 41/89 (46.1%)\n"
    )

    print(
        f"{'Month':<10} {'SG_acc':<14} {'SG_cov':<14} {'WR_acc':<14} {'WR_cov':<14} | R&D SG_acc R&D SG_cov R&D WR_acc R&D WR_cov"
    )
    print("-" * 130)

    for month_str in sorted(scorable_df["month"].unique()):
        sub = scorable_df[scorable_df["month"] == month_str]
        n_days = len(sub)
        sg_committed = sub[sub["sg"] != "MONITOR"]
        sg_correct = sg_committed["sg_correct"].fillna(False).astype(bool).sum()
        wr_committed = sub[sub["wr"] != "MONITOR"]
        wr_correct = wr_committed["wr_correct"].fillna(False).astype(bool).sum()
        rnd_row = RND.get(month_str, {})
        print(
            f"{month_str:<10} "
            f"{int(sg_correct)}/{len(sg_committed):<11} "
            f"{len(sg_committed)}/{n_days:<11} "
            f"{int(wr_correct)}/{len(wr_committed):<11} "
            f"{len(wr_committed)}/{n_days:<11} | "
            f"{rnd_row.get('sg_acc', '-'):<10} "
            f"{rnd_row.get('sg_cov', '-'):<10} "
            f"{rnd_row.get('wr_acc', '-'):<10} "
            f"{rnd_row.get('wr_cov', '-')}"
        )

    print("-" * 130)
    # YTD aggregate — scorable only
    sg_committed = scorable_df[scorable_df["sg"] != "MONITOR"]
    sg_correct = sg_committed["sg_correct"].fillna(False).astype(bool).sum()
    wr_committed = scorable_df[scorable_df["wr"] != "MONITOR"]
    wr_correct = wr_committed["wr_correct"].fillna(False).astype(bool).sum()
    n_days = n_scorable_total
    print(
        f"{'YTD':<10} "
        f"{int(sg_correct)}/{len(sg_committed):<11} "
        f"{len(sg_committed)}/{n_days:<11} "
        f"{int(wr_correct)}/{len(wr_committed):<11} "
        f"{len(wr_committed)}/{n_days:<11} | "
        f"50/77      77/89      34/41      41/89"
    )

    sg_cov_pct = 100.0 * len(sg_committed) / n_days if n_days else 0.0
    wr_cov_pct = 100.0 * len(wr_committed) / n_days if n_days else 0.0
    sg_acc_pct = (
        100.0 * int(sg_correct) / len(sg_committed) if len(sg_committed) else 0.0
    )
    wr_acc_pct = (
        100.0 * int(wr_correct) / len(wr_committed) if len(wr_committed) else 0.0
    )
    print()
    print("Compass YTD (scorable only):")
    print(
        f"  SG accuracy {sg_acc_pct:.1f}% (R&D 64.9%) | SG coverage {sg_cov_pct:.1f}% (R&D 86.5%)"
    )
    print(
        f"  WR accuracy {wr_acc_pct:.1f}% (R&D 82.9%) | WR coverage {wr_cov_pct:.1f}% (R&D 46.1%)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
