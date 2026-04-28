"""Report generation for watchlist evaluation results."""

import csv
from collections import defaultdict
from pathlib import Path

from .types import EvalResult, WatchlistItem


def _pct(numerator: int, denominator: int) -> str:
    """Format as percentage string."""
    if denominator == 0:
        return "N/A"
    return f"{numerator / denominator * 100:.1f}%"


def _hit_icon(hit: bool | None) -> str:
    if hit is True:
        return "HIT"
    if hit is False:
        return "---"
    return "N/A"


def _dir_icon(correct: bool | None) -> str:
    if correct is True:
        return "OK"
    if correct is False:
        return "WRONG"
    return "-"


def print_global_stats(
    items: list[WatchlistItem],
    results: list[EvalResult],
) -> None:
    """Print global statistics to stdout."""
    total_items = len(items)
    parse_high = sum(1 for i in items if i.parse_confidence == "HIGH")
    parse_medium = sum(1 for i in items if i.parse_confidence == "MEDIUM")
    parse_low = sum(1 for i in items if i.parse_confidence == "LOW")

    print("\n" + "=" * 70)
    print("  WATCHLIST EVALUATION — GLOBAL STATS")
    print("=" * 70)

    print(f"\n  Total items extracted:    {total_items}")
    print(
        f"  Parse confidence:         HIGH={parse_high}  MEDIUM={parse_medium}  LOW={parse_low}"
    )
    print(f"  Parse success rate:       {_pct(parse_high + parse_medium, total_items)}")
    print(f"  Items evaluated:          {len(results)}")

    # Filter to evaluable results (with threshold)
    evaluable = [r for r in results if r.item.threshold is not None]
    if not evaluable:
        print("\n  No evaluable results (all items missing thresholds).")
        return

    # Hit rates
    j1_hits = sum(1 for r in evaluable if r.j1_condition_hit is True)
    j2_hits = sum(1 for r in evaluable if r.j2_condition_hit is True)
    j3_hits = sum(1 for r in evaluable if r.j3_condition_hit is True)
    any_hit = sum(1 for r in evaluable if r.first_hit_day is not None)
    j1_evaluable = sum(1 for r in evaluable if r.j1_condition_hit is not None)
    j2_evaluable = sum(1 for r in evaluable if r.j2_condition_hit is not None)
    j3_evaluable = sum(1 for r in evaluable if r.j3_condition_hit is not None)

    print("\n  --- HIT RATES ---")
    print(f"  J+1:    {j1_hits}/{j1_evaluable} = {_pct(j1_hits, j1_evaluable)}")
    print(f"  J+2:    {j2_hits}/{j2_evaluable} = {_pct(j2_hits, j2_evaluable)}")
    print(f"  J+3:    {j3_hits}/{j3_evaluable} = {_pct(j3_hits, j3_evaluable)}")
    print(f"  Any:    {any_hit}/{len(evaluable)} = {_pct(any_hit, len(evaluable))}")

    # Directional accuracy (only when hit + non-neutral)
    dir_evaluable = [r for r in evaluable if r.direction_correct is not None]
    dir_correct = sum(1 for r in dir_evaluable if r.direction_correct is True)

    print("\n  --- DIRECTIONAL ACCURACY (at first hit) ---")
    print(
        f"  Correct:  {dir_correct}/{len(dir_evaluable)} = {_pct(dir_correct, len(dir_evaluable))}"
    )

    # By implied direction
    for direction in ("HAUSSIERE", "BAISSIERE", "NEUTRE"):
        subset = [r for r in evaluable if r.item.implied_direction == direction]
        hits = sum(1 for r in subset if r.first_hit_day is not None)
        print(
            f"  {direction:12s}: {len(subset):3d} items, hit rate = {_pct(hits, len(subset))}"
        )


def print_by_indicator(results: list[EvalResult]) -> None:
    """Print breakdown by indicator type."""
    evaluable = [r for r in results if r.item.threshold is not None]
    if not evaluable:
        return

    by_indicator: dict[str, list[EvalResult]] = defaultdict(list)
    for r in evaluable:
        by_indicator[r.item.indicator].append(r)

    print("\n  --- BY INDICATOR ---")
    print(
        f"  {'INDICATOR':<16} {'COUNT':>6} {'HIT J+1':>8} {'HIT ANY':>8} {'DIR ACC':>8}"
    )
    print(f"  {'-' * 16} {'-' * 6} {'-' * 8} {'-' * 8} {'-' * 8}")

    for indicator in sorted(by_indicator.keys()):
        group = by_indicator[indicator]
        count = len(group)
        j1_eval = [r for r in group if r.j1_condition_hit is not None]
        j1_hits = sum(1 for r in j1_eval if r.j1_condition_hit is True)
        any_hits = sum(1 for r in group if r.first_hit_day is not None)
        dir_eval = [r for r in group if r.direction_correct is not None]
        dir_correct = sum(1 for r in dir_eval if r.direction_correct is True)

        print(
            f"  {indicator:<16} {count:>6} "
            f"{_pct(j1_hits, len(j1_eval)):>8} "
            f"{_pct(any_hits, count):>8} "
            f"{_pct(dir_correct, len(dir_eval)):>8}"
        )


def print_timeline(results: list[EvalResult], verbose: bool = True) -> None:
    """Print detailed timeline of each item evaluation."""
    if not verbose:
        return

    sorted_results = sorted(results, key=lambda r: r.item.date)

    print(f"\n{'=' * 70}")
    print("  TIMELINE DETAIL")
    print("=" * 70)

    current_date = None
    for r in sorted_results:
        if r.item.date != current_date:
            current_date = r.item.date
            print(f"\n  --- {current_date} (CLOSE={r.close_on_issue:.0f}) ---")

        threshold_str = f"{r.item.threshold:.2f}" if r.item.threshold else "?"
        comparator_str = r.item.comparator

        # J+1 detail
        j1_str = ""
        if r.j1_actual_value is not None:
            j1_str = f"J+1: {r.j1_actual_value:.2f} {_hit_icon(r.j1_condition_hit)}"
        else:
            j1_str = "J+1: N/A"

        # J+2 detail
        j2_str = ""
        if r.j2_actual_value is not None:
            j2_str = f"J+2: {r.j2_actual_value:.2f} {_hit_icon(r.j2_condition_hit)}"

        # J+3 detail
        j3_str = ""
        if r.j3_actual_value is not None:
            j3_str = f"J+3: {r.j3_actual_value:.2f} {_hit_icon(r.j3_condition_hit)}"

        # Direction
        dir_str = f"DIR={_dir_icon(r.direction_correct)}" if r.first_hit_day else ""

        print(
            f"    [{r.item.indicator} {comparator_str} {threshold_str}] "
            f"{r.item.implied_direction:10s} | {j1_str} | {j2_str} | {j3_str} | {dir_str}"
        )
        print(f'      raw: "{r.item.raw_text[:80]}"')


def export_csv(results: list[EvalResult], output_path: Path) -> None:
    """Export detailed results to CSV."""
    fieldnames = [
        "date",
        "raw_text",
        "indicator",
        "comparator",
        "threshold",
        "implied_direction",
        "parse_confidence",
        "close_on_issue",
        "j1_hit",
        "j1_value",
        "j1_close",
        "j2_hit",
        "j2_value",
        "j2_close",
        "j3_hit",
        "j3_value",
        "j3_close",
        "first_hit_day",
        "direction_correct",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for r in sorted(results, key=lambda x: x.item.date):
            writer.writerow(
                {
                    "date": r.item.date.isoformat(),
                    "raw_text": r.item.raw_text,
                    "indicator": r.item.indicator,
                    "comparator": r.item.comparator,
                    "threshold": r.item.threshold,
                    "implied_direction": r.item.implied_direction,
                    "parse_confidence": r.item.parse_confidence,
                    "close_on_issue": r.close_on_issue,
                    "j1_hit": r.j1_condition_hit,
                    "j1_value": r.j1_actual_value,
                    "j1_close": r.j1_close,
                    "j2_hit": r.j2_condition_hit,
                    "j2_value": r.j2_actual_value,
                    "j2_close": r.j2_close,
                    "j3_hit": r.j3_condition_hit,
                    "j3_value": r.j3_actual_value,
                    "j3_close": r.j3_close,
                    "first_hit_day": r.first_hit_day,
                    "direction_correct": r.direction_correct,
                }
            )

    print(f"\n  CSV exported to: {output_path}")
