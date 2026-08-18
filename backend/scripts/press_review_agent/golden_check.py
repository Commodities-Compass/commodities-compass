"""Check the golden corpus against the press reviews actually produced.

    poetry run press-review-golden [--language fr] [--verbose]

Reads ``pl_fundamental_article`` and reports, per entry, whether the fact the
brief had to carry is in there. Exit code is 1 when a ``MUST_HOLD`` entry is
missing — that is a regression, and it is the only thing that fails the run.
``KNOWN_MISS`` entries are reported, never fatal: they are the target, and one
turning green is news worth printing rather than a build breaking.

This is a report, not a pytest test, on purpose: it needs a database with real
history, and it is meant to be read by a human deciding whether a prompt change
was worth shipping.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import text

from scripts.db import get_session
from scripts.press_review_agent.golden import (
    GOLDEN,
    GoldenEntry,
    Status,
    is_replayable,
)

logger = logging.getLogger(__name__)

_ARTICLE_SQL = """
    SELECT coalesce(summary, '') || ' ' || coalesce(impact_synthesis, '')
           || ' ' || coalesce(keywords, '')
    FROM pl_fundamental_article
    WHERE date = :d AND is_active AND language = :lang
    LIMIT 1
"""


def _covered(text_blob: str, entry: GoldenEntry) -> tuple[bool, str]:
    """Is the fact in there? Returns (present, why).

    Every ``required`` marker must appear AND at least one ``any_of``. The
    conjunction is what ties the fact to its actor: a lone generic token matches
    unrelated prose and reports a miss as covered.
    """
    low = text_blob.lower()
    missing = [m for m in entry.required if m.lower() not in low]
    if missing:
        return False, f"missing {missing}"
    if entry.any_of:
        hits = [m for m in entry.any_of if m.lower() in low]
        if not hits:
            return False, f"none of {list(entry.any_of)}"
        return True, f"matched {entry.required + tuple(hits)}"
    return True, f"matched {list(entry.required)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", default="fr", choices=["fr", "en"])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    regressions: list[GoldenEntry] = []
    recovered: list[GoldenEntry] = []
    absent: list[GoldenEntry] = []

    with get_session() as session:
        print(f"\nGolden corpus — {len(GOLDEN)} entries, language={args.language}\n")
        for entry in sorted(GOLDEN, key=lambda e: e.session_date):
            row = session.execute(
                text(_ARTICLE_SQL), {"d": entry.session_date, "lang": args.language}
            ).fetchone()
            if row is None:
                print(f"  {entry.session_date}  [{entry.status:<10}]  NO ARTICLE")
                absent.append(entry)
                continue

            present, detail = _covered(str(row[0]), entry)
            if entry.status == Status.MUST_HOLD and not present:
                mark, note = "REGRESSION", "the agent used to carry this"
                regressions.append(entry)
            elif entry.status == Status.KNOWN_MISS and present:
                mark, note = "RECOVERED", "a known miss now covered"
                recovered.append(entry)
            elif present:
                mark, note = "ok", detail
            else:
                mark = "still missing"
                why = (
                    "not replayable — sources gone"
                    if not is_replayable(entry)
                    else "target"
                )
                note = f"{why} ({detail})"

            print(f"  {entry.session_date}  [{entry.status:<10}]  {mark:<13} {note}")
            if args.verbose or not present:
                print(f"      fact  : {entry.fact}")
                if entry.displaced_by:
                    print("      instead the brief led with:")
                    for d in entry.displaced_by:
                        print(f"        - {d}")

    print()
    if recovered:
        print(f"  {len(recovered)} known miss(es) now covered — update their status.")
    if absent:
        print(f"  {len(absent)} entr(ies) have no article on that date.")
    if regressions:
        print(f"  {len(regressions)} REGRESSION(S): a fact we used to carry is gone.")
        return 1
    print("  no regression.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
