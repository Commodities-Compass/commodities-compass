"""Press review coverage gap diagnostic.

Quantifies how often each of the 4 dashboard themes (production / chocolat /
transformation / economie) ends up with confidence < 0.2 (= the threshold above
which the frontend renders the sentiment gauge; below it shows "Pas de
couverture"). Also reports source_count distribution + day-of-week patterns so we
can target the Phase 2/3 enrichment.

Usage (from backend/), against LOCAL sync of GCP data:
    poetry run python scripts/_analyze_press_review_gaps.py

Or against GCP prod via IAP bastion tunnel on port 5434:
    DATABASE_SYNC_URL="postgresql+psycopg2://cc_app:<pwd>@127.0.0.1:5434/commodities_compass" \\
        poetry run python scripts/_analyze_press_review_gaps.py
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import create_engine, text

WINDOWS_DAYS = (30, 60)
NO_COVERAGE_CONFIDENCE_THRESHOLD = (
    0.20  # mirrors frontend/src/components/sentiment-gauges.tsx
)
THEMES = ("production", "chocolat", "transformation", "economie")

SEGMENTS_QUERY = """
SELECT
    s.article_date,
    s.theme,
    s.sentiment_score::float AS sentiment_score,
    s.confidence::float      AS confidence,
    s.llm_provider,
    s.extraction_version,
    a.source_count,
    a.total_sources,
    a.is_active
FROM pl_article_segment s
JOIN pl_fundamental_article a ON a.id = s.article_id
WHERE s.article_date >= :start_date
  AND a.is_active = TRUE
  AND s.extraction_version = 'inline_v1'
  AND s.zone = 'all'
ORDER BY s.article_date, s.theme
"""

ARTICLES_QUERY = """
SELECT
    date,
    source_count,
    total_sources,
    llm_provider
FROM pl_fundamental_article
WHERE date >= :start_date
  AND is_active = TRUE
ORDER BY date
"""


def _resolve_db_url() -> tuple[str, str]:
    """Return (url, label) — label is 'LOCAL' or 'GCP-via-bastion' for logging."""
    url = os.environ.get(
        "DATABASE_SYNC_URL",
        "postgresql+psycopg2://postgres:password@localhost:5433/commodities_compass",
    )
    if "5434" in url or "10.119.160" in url:
        label = "GCP (via IAP bastion on :5434)"
    elif "localhost" in url or "127.0.0.1:5433" in url:
        label = "LOCAL (port 5433)"
    else:
        label = url.split("@", 1)[-1] if "@" in url else url
    return url, label


def _print_per_theme(df: pd.DataFrame, window_days: int) -> None:
    cutoff = date.today() - timedelta(days=window_days)
    sub = df[df["article_date"] >= cutoff].copy()
    n_days = sub["article_date"].nunique()

    print(
        f"\n=== Per-theme coverage on last {window_days} days "
        f"({sub['article_date'].min()} → {sub['article_date'].max()}, n_days={n_days}) ==="
    )
    print(
        f"{'theme':<16} {'n_rows':>6} {'< 0.2 conf':>10} {'% gap':>7} "
        f"{'mean_conf':>10} {'median_conf':>12} {'mean_|score|':>13}"
    )
    print("-" * 80)
    for theme in THEMES:
        t = sub[sub["theme"] == theme]
        if t.empty:
            print(
                f"{theme:<16} {'0':>6} {'-':>10} {'-':>7} {'-':>10} {'-':>12} {'-':>13}"
            )
            continue
        n_rows = len(t)
        n_gap = int((t["confidence"] < NO_COVERAGE_CONFIDENCE_THRESHOLD).sum())
        pct_gap = 100.0 * n_gap / n_rows if n_rows else 0.0
        mean_conf = float(t["confidence"].mean())
        median_conf = float(t["confidence"].median())
        mean_abs_score = float(t["sentiment_score"].abs().mean())
        print(
            f"{theme:<16} {n_rows:>6} {n_gap:>10} {pct_gap:>6.1f}% "
            f"{mean_conf:>10.3f} {median_conf:>12.3f} {mean_abs_score:>13.3f}"
        )


def _print_dow_pattern(df: pd.DataFrame, window_days: int) -> None:
    cutoff = date.today() - timedelta(days=window_days)
    sub = df[df["article_date"] >= cutoff].copy()
    if sub.empty:
        return
    sub["dow"] = pd.to_datetime(sub["article_date"]).dt.day_name()
    sub["is_gap"] = (sub["confidence"] < NO_COVERAGE_CONFIDENCE_THRESHOLD).astype(int)

    print(
        f"\n=== % de gauges 'pas de couverture' par jour de la semaine (last {window_days}d) ==="
    )
    print(f"{'day_of_week':<12} {'n_rows':>7} {'n_gap':>7} {'% gap':>7}")
    print("-" * 40)
    dow_order = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    for dow in dow_order:
        d = sub[sub["dow"] == dow]
        if d.empty:
            continue
        n_rows = len(d)
        n_gap = int(d["is_gap"].sum())
        pct = 100.0 * n_gap / n_rows
        print(f"{dow:<12} {n_rows:>7} {n_gap:>7} {pct:>6.1f}%")


def _print_articles_summary(articles: pd.DataFrame, window_days: int) -> None:
    cutoff = date.today() - timedelta(days=window_days)
    sub = articles[articles["date"] >= cutoff].copy()
    if sub.empty:
        print(
            f"\n=== Articles (pl_fundamental_article) last {window_days}d ===\nAucune ligne."
        )
        return

    print(
        f"\n=== Articles (pl_fundamental_article) last {window_days}d — "
        f"{sub['date'].min()} → {sub['date'].max()}, n={len(sub)} ==="
    )
    print(
        "source_count distribution (= nb of httpx/playwright sources that succeeded):"
    )
    print(sub["source_count"].describe().to_string())
    print("\ntotal_sources distribution (= nb attempted):")
    print(sub["total_sources"].describe().to_string())
    n_thin = int((sub["source_count"] < 4).sum())
    pct_thin = 100.0 * n_thin / len(sub)
    print(
        f"\nDays with source_count < 4 (= < 50% of 8 direct sources OK): "
        f"{n_thin}/{len(sub)} ({pct_thin:.1f}%)"
    )

    worst = sub.nsmallest(10, "source_count")[["date", "source_count", "total_sources"]]
    print("\n10 worst days by source_count:")
    print(worst.to_string(index=False))


def _write_csv(df: pd.DataFrame) -> None:
    out_dir = os.path.join(os.path.dirname(__file__), "julien_handoff")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir, f"press_review_gaps_{date.today().isoformat()}.csv"
    )
    df.to_csv(out_path, index=False)
    print(f"\nCSV: {out_path}")


def main() -> int:
    url, label = _resolve_db_url()
    print(f"DB: {label}")
    engine = create_engine(url)

    start_date = date.today() - timedelta(days=max(WINDOWS_DAYS))

    with engine.connect() as conn:
        segments = pd.read_sql(
            text(SEGMENTS_QUERY), conn, params={"start_date": start_date}
        )
        articles = pd.read_sql(
            text(ARTICLES_QUERY), conn, params={"start_date": start_date}
        )

    if segments.empty:
        print("Aucune ligne dans pl_article_segment sur la fenêtre. Rien à analyser.")
        return 0

    print(f"\nFenêtre: {start_date} → {date.today()} ({max(WINDOWS_DAYS)}d)")
    print(f"Segments lus: {len(segments)} | Articles lus: {len(articles)}")
    print(f"Providers segments: {dict(segments['llm_provider'].value_counts())}")

    for window in WINDOWS_DAYS:
        _print_per_theme(segments, window)

    _print_dow_pattern(segments, max(WINDOWS_DAYS))
    _print_articles_summary(articles, max(WINDOWS_DAYS))
    _write_csv(segments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
