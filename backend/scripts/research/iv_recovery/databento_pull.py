"""RESEARCH — pull ICE London Cocoa option settlements from Databento (IFEU.IMPACT, symbol C).

SAFETY: always runs `metadata.get_cost` first and ABORTS if the estimate exceeds --max-cost (default $5).
The historical ICE feed is usage-based pay-per-GB with NO exchange license (the $875/mo license is LIVE-only),
and a daily-settlement-only pull for one option family/7y fits inside the $125 free sign-up credit (~$0).
NEVER request the order book (mbo/mbp-10) — that's the huge/expensive part. We only pull `definition` + `statistics`.

Prereq: `pip install databento`, and export DATABENTO_API_KEY=...

Usage:
    # 1) Cost probe only (safe, ~$0) — ALWAYS run first
    poetry run python scripts/research/iv_recovery/databento_pull.py --cost-only

    # 2) Narrow 2019 probe — verify cocoa OPTIONS have settlement depth that far back before pulling 7y
    poetry run python scripts/research/iv_recovery/databento_pull.py --start 2019-01-01 --end 2019-02-01 --pull

    # 3) Full pull once the probe looks clean
    poetry run python scripts/research/iv_recovery/databento_pull.py --start 2019-01-01 --end 2026-06-12 --pull

    # 4) Inspect what we got (columns / sample / date range) — finalize the build mapping from this
    poetry run python scripts/research/iv_recovery/databento_pull.py --inspect
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DATASET = "IFEU.IMPACT"
SYMBOL = "C"  # ICE Europe London Cocoa (futures + options under parent symbology)
STYPE_IN = "parent"
SCHEMAS = ("definition", "statistics")
DATA_DIR = Path(__file__).parent / "data"


def _client():
    try:
        import databento as db
    except ImportError:
        sys.exit("databento not installed — run: pip install databento")
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        sys.exit(
            "DATABENTO_API_KEY not set — export it (self-serve key from databento.com)."
        )
    return db.Historical(key)


def cmd_cost(client, start: str, end: str) -> float:
    total = 0.0
    for sch in SCHEMAS:
        c = client.metadata.get_cost(
            dataset=DATASET,
            symbols=SYMBOL,
            stype_in=STYPE_IN,
            schema=sch,
            start=start,
            end=end,
        )
        print(f"  get_cost[{sch}] {start}->{end}: ${c:.4f}")
        total += float(c)
    print(f"  TOTAL estimate: ${total:.4f}")
    return total


def cmd_pull(client, start: str, end: str, max_cost: float) -> None:
    est = cmd_cost(client, start, end)
    if est > max_cost:
        sys.exit(
            f"ABORT: estimate ${est:.2f} exceeds --max-cost ${max_cost:.2f}. "
            f"Re-run with a tighter window or raise --max-cost deliberately."
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for sch in SCHEMAS:
        print(f"Pulling {sch} {start}->{end} ...")
        df = client.timeseries.get_range(
            dataset=DATASET,
            symbols=SYMBOL,
            stype_in=STYPE_IN,
            schema=sch,
            start=start,
            end=end,
        ).to_df()
        out = DATA_DIR / f"{sch}_{start}_{end}.parquet"
        try:
            df.to_parquet(out)
        except Exception:  # noqa: BLE001 — fall back to csv if no parquet engine
            out = out.with_suffix(".csv")
            df.to_csv(out, index=False)
        print(
            f"  saved {len(df):,} rows -> {out.name}  (cols: {list(df.columns)[:12]}{'...' if len(df.columns) > 12 else ''})"
        )


def cmd_inspect() -> None:
    import pandas as pd

    files = sorted(DATA_DIR.glob("*.parquet")) + sorted(DATA_DIR.glob("*.csv"))
    if not files:
        sys.exit(f"No pulled files in {DATA_DIR} — run --pull first.")
    for f in files:
        df = pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f)
        print(f"\n=== {f.name} : {len(df):,} rows ===")
        print("columns:", list(df.columns))
        # surface the fields we'll need for Black-76
        for col in (
            "instrument_class",
            "raw_symbol",
            "strike_price",
            "expiration",
            "stat_type",
            "price",
            "ts_event",
            "ts_ref",
        ):
            if col in df.columns:
                vals = df[col].dropna().unique()[:6]
                print(f"  {col}: sample {list(vals)}")
        print(df.head(3).to_string())


def main() -> None:
    p = argparse.ArgumentParser(
        description="Pull ICE London Cocoa option settlements from Databento"
    )
    p.add_argument("--start", default="2019-01-01")
    p.add_argument("--end", default="2026-06-12")
    p.add_argument(
        "--cost-only", action="store_true", help="get_cost estimate only, no pull"
    )
    p.add_argument(
        "--pull",
        action="store_true",
        help="pull definition + statistics (after cost guard)",
    )
    p.add_argument(
        "--inspect",
        action="store_true",
        help="print columns/sample of already-pulled files",
    )
    p.add_argument("--max-cost", type=float, default=5.0)
    args = p.parse_args()

    if args.inspect:
        cmd_inspect()
        return
    client = _client()
    if args.cost_only:
        cmd_cost(client, args.start, args.end)
    elif args.pull:
        cmd_pull(client, args.start, args.end, args.max_cost)
    else:
        p.error("choose one of --cost-only / --pull / --inspect")


if __name__ == "__main__":
    main()
