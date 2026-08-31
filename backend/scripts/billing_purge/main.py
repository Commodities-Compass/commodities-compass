"""Billing archive purge — enforce the 18 months we published.

Politique de confidentialité § 3, ligne 5: the raw payload of every payment
notification is kept « **18 mois** à compter de la fin de la période
d'abonnement couverte par le paiement concerné, puis purge automatique ».

That sentence is a commitment made to every client and to the CNIL. Until this
job runs, the page documents a breach rather than a practice — which is why the
counsel's note puts it first among the items that must exist *before*
publication, not after.

**The anchor is the end of the service period, not the day the webhook landed.**
Card networks allow a dispute up to ~540 days, and for a service delivered
*after* payment that window runs from delivery. A subscription billed `à échoir`
is paid a month before the period it covers ends, so purging on `received_at`
would destroy the only raw proof of a transaction that can still be contested.
The anchor is therefore `GREATEST(received_at, period_end)` — the later of the
two, never the earlier.

**What is NOT purged.** `tenant_billing_invoice` mirrors the same payments in
structured form and is an accounting record kept 10 years (art. L123-22 du code
de commerce, § 3 ligne 3). Two finalities, two clocks — see the counsel's note
§ 4. So this job removes identifying payload (payer name, email, country) while
the bookkeeping trail survives. A dispute raised past 18 months still has the
invoice; it loses only the verbatim provider payload, which is why no
legal-hold mechanism is needed here.

`RETENTION_MONTHS` is deliberately NOT a CLI flag: it is a published figure, and
a job that can be told to keep less than the page promises is a job that will
one day be told exactly that.

CLI: ``poetry run billing-purge [--dry-run] [--verbose]``
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import datetime

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("billing-purge", script_file=__file__)

#: Published in the privacy policy. Changing it here without changing the page
#: makes the page false — `test_retention_matches_the_published_policy` is the
#: tripwire that refuses to let that happen quietly.
RETENTION_MONTHS = 18

#: The retention clock. `jsonb_typeof(...) = 'number'` is what keeps a malformed
#: payload from taking the whole job down on a cast error: this table archives
#: whatever the provider sent, BEFORE interpretation, so it will eventually hold
#: a shape nobody anticipated. GREATEST ignores NULL, and `received_at` is NOT
#: NULL, so the fallback is total.
_ANCHOR = """
    GREATEST(
        received_at,
        CASE
            WHEN jsonb_typeof(payload #> '{data,object,period_end}') = 'number'
            THEN to_timestamp(
                (payload #>> '{data,object,period_end}')::double precision
            )
        END
    )
"""

_EXPIRED = f"{_ANCHOR} < now() - make_interval(months => :months)"


@dataclass(frozen=True)
class PurgeReport:
    """What a purge would remove. Produced without writing anything."""

    total: int
    by_type: tuple[tuple[str, int], ...]
    oldest_anchor: datetime | None
    newest_anchor: datetime | None


def survey(session, *, retention_months: int = RETENTION_MONTHS) -> PurgeReport:
    """Report what is past retention. Reads only — never deletes."""
    rows = session.execute(
        text(
            f"""
            SELECT event_type, count(*) AS n, min(anchor) AS oldest,
                   max(anchor) AS newest
            FROM (
                SELECT event_type, {_ANCHOR} AS anchor
                FROM aud_billing_event
            ) t
            WHERE anchor < now() - make_interval(months => :months)
            GROUP BY event_type
            ORDER BY n DESC, event_type
            """
        ),
        {"months": retention_months},
    ).fetchall()

    if not rows:
        return PurgeReport(total=0, by_type=(), oldest_anchor=None, newest_anchor=None)

    return PurgeReport(
        total=sum(r.n for r in rows),
        by_type=tuple((r.event_type, r.n) for r in rows),
        oldest_anchor=min(r.oldest for r in rows),
        newest_anchor=max(r.newest for r in rows),
    )


def purge(session, *, retention_months: int = RETENTION_MONTHS) -> int:
    """Delete every event past retention. Returns the number removed."""
    result = session.execute(
        text(f"DELETE FROM aud_billing_event WHERE {_EXPIRED}"),
        {"months": retention_months},
    )
    return result.rowcount or 0


def _parse_args() -> argparse.Namespace:
    return build_base_argparser(
        f"Purge aud_billing_event past {RETENTION_MONTHS} months",
        include_force=False,
    ).parse_args()


@monitor(monitor_slug="billing-purge")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("Billing archive purge — retention %d months", RETENTION_MONTHS)
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    from scripts.db import get_session

    try:
        with get_session() as session:
            report = survey(session)

            if report.total == 0:
                logger.info("Nothing past retention. Exit 0.")
                return 0

            logger.info(
                "%d event(s) past retention (anchors %s → %s):",
                report.total,
                report.oldest_anchor,
                report.newest_anchor,
            )
            for event_type, count in report.by_type:
                logger.info("  %-40s %d", event_type, count)

            if args.dry_run:
                logger.info("[DRY RUN] Nothing deleted.")
                return 0

            deleted = purge(session)

            # The survey and the delete run in the same transaction, so a
            # mismatch means the anchor expression disagrees with itself —
            # loud, because a purge is irreversible.
            if deleted != report.total:
                raise RuntimeError(
                    f"Purge deleted {deleted} rows but surveyed {report.total}. "
                    "Refusing to report success on an inconsistent purge."
                )

            logger.info("Purged %d event(s). Exit 0.", deleted)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("Billing purge failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
