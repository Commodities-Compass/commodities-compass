"""Billing watchdog — surface the payment failures nobody would otherwise see.

Design: docs/architecture/billing-and-collection.md §9

Three checks, in decreasing order of "would silently cost you a client":

1. **First off-session failure.** An ``invoice.payment_failed`` on an account
   that was ``active`` is the signal *"this issuer mishandles merchant-initiated
   transactions"*. It is the ONLY early warning that exists: the first payment
   is on-session and 3DS-authenticated, the monthly debit is not, and an issuer
   can accept one and refuse the other. No test card reveals this ahead of a
   full billing cycle (§13) — so it is instrumented instead of tested.

2. **Card about to expire.** Stripe's Card Account Updater covers Visa only in
   the UK and Europe, and Mastercard globally, so **a Visa issued in Abidjan is
   probably not covered**: the card expires, the subscription dies quietly, and
   nobody notices until the client asks why the dashboard went blank.

3. **Stripe ⇄ DB drift.** Our ``billing_status`` is what gates access. If it
   disagrees with Stripe, one of the two is lying about whether a client paid.

Checks 2 and 3 need Stripe credentials. Without them the job reports what it
skipped and exits 0 — the same "nothing to do today" posture as the
calendar-gated grindings scrapers, not a silent swallow.

CLI: ``poetry run billing-watchdog [--dry-run] [--verbose] [--expiry-days N]``
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import sentry_sdk
from sentry_sdk.crons import monitor
from sqlalchemy import text

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("billing-watchdog", script_file=__file__)

#: How far ahead to warn about an expiring card. 30 days leaves time for the
#: client to reach their bank, which in West Africa is not a same-day errand.
DEFAULT_EXPIRY_DAYS = 30

#: Look-back for "first failure". Matches the daily cadence: a failure is
#: reported once, the day after it happens.
FAILURE_LOOKBACK_HOURS = 26


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "Billing watchdog (payment failures, expiring cards, Stripe/DB drift)",
        include_force=False,
    )
    parser.add_argument(
        "--expiry-days",
        type=int,
        default=DEFAULT_EXPIRY_DAYS,
        help=f"Warn this many days before a card expires (default: {DEFAULT_EXPIRY_DAYS}).",
    )
    return parser.parse_args()


def _recent_payment_failures(session, hours: int) -> list[tuple[str, str, str]]:
    """(account_code, billing_status, event_id) for fresh payment failures.

    Read from ``aud_billing_event`` rather than from a dedicated flag: the
    webhook already archives every event, so "did a debit fail recently" needs
    no extra state and cannot drift from what Stripe actually sent.
    """
    rows = session.execute(
        text(
            """
            SELECT a.code, a.billing_status, e.event_id
            FROM aud_billing_event e
            JOIN tenant_billing_subscription s
              ON s.provider_customer_id = e.payload->'data'->'object'->>'customer'
             AND s.active
            JOIN tenant_account a ON a.id = s.account_id
            WHERE e.event_type = 'invoice.payment_failed'
              AND e.received_at >= now() - CAST(:window AS interval)
            ORDER BY e.received_at DESC
            """
        ),
        {"window": f"{hours} hours"},
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def _expiring_cards(session, api, horizon: date) -> list[tuple[str, str, str]]:
    """(account_code, brand/last4, expiry) for cards expiring before `horizon`."""
    subs = session.execute(
        text(
            """
            SELECT a.code, s.provider_subscription_id
            FROM tenant_billing_subscription s
            JOIN tenant_account a ON a.id = s.account_id
            WHERE s.active
              AND s.provider = 'stripe'
              AND s.provider_subscription_id IS NOT NULL
              AND s.status IN ('active', 'trialing', 'past_due')
            """
        )
    ).all()

    expiring: list[tuple[str, str, str]] = []
    for code, sub_id in subs:
        try:
            sub = api.Subscription.retrieve(sub_id, expand=["default_payment_method"])
            pm = sub.get("default_payment_method")
            card = (pm or {}).get("card") if isinstance(pm, dict) else None
            if not card:
                continue
            exp = date(int(card["exp_year"]), int(card["exp_month"]), 1)
            if exp <= horizon:
                expiring.append(
                    (code, f"{card.get('brand')}••{card.get('last4')}", exp.isoformat())
                )
        except Exception as exc:  # one bad subscription must not kill the sweep
            logger.warning("Could not read the card for %s (%s): %s", code, sub_id, exc)
    return expiring


def _drift(session, api) -> list[tuple[str, str, str]]:
    """(account_code, our_status, stripe_status) where the two disagree."""
    rows = session.execute(
        text(
            """
            SELECT a.code, a.billing_status, s.provider_subscription_id
            FROM tenant_billing_subscription s
            JOIN tenant_account a ON a.id = s.account_id
            WHERE s.active AND s.provider = 'stripe'
              AND s.provider_subscription_id IS NOT NULL
            """
        )
    ).all()

    from app.services.billing_service import _STATUS_MAP

    drifted: list[tuple[str, str, str]] = []
    for code, ours, sub_id in rows:
        try:
            remote = str(api.Subscription.retrieve(sub_id).get("status") or "")
            expected = _STATUS_MAP.get(remote)
            if expected is not None and expected != ours:
                drifted.append((code, ours, remote))
        except Exception as exc:
            logger.warning("Could not read subscription %s (%s): %s", sub_id, code, exc)
    return drifted


@monitor(monitor_slug="billing-watchdog")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    horizon = date.today() + timedelta(days=args.expiry_days)
    logger.info("=" * 60)
    logger.info("Billing Watchdog")
    logger.info(
        "Mode: %s (expiry horizon=%s, failure look-back=%dh)",
        "DRY RUN" if args.dry_run else "LIVE",
        horizon,
        FAILURE_LOOKBACK_HOURS,
    )
    logger.info("=" * 60)

    from app.core.config import settings
    from scripts.db import get_session

    problems = 0

    try:
        with get_session() as session:
            # --- 1. First off-session failure (DB only — always runs) --------
            failures = _recent_payment_failures(session, FAILURE_LOOKBACK_HOURS)
            if failures:
                problems += len(failures)
                logger.error("%d payment failure(s) in the last 26h:", len(failures))
                for code, status_, event_id in failures:
                    logger.error("  %s (now %s) — event %s", code, status_, event_id)
                sentry_sdk.set_context(
                    "billing_payment_failures",
                    {"items": [f"{c} ({s})" for c, s, _ in failures]},
                )
                sentry_sdk.capture_message(
                    f"{len(failures)} billing payment failure(s) in the last 26h — "
                    "check whether the issuer refuses off-session debits (MIT).",
                    level="error",
                )
            else:
                logger.info("No payment failure in the look-back window.")

            # --- 2 & 3 need Stripe -------------------------------------------
            if not settings.STRIPE_SECRET_KEY:
                logger.info(
                    "STRIPE_SECRET_KEY unset — skipping the expiring-card and "
                    "drift checks (nothing to compare against yet)."
                )
                return 1 if problems else 0

            import stripe

            stripe.api_key = settings.STRIPE_SECRET_KEY

            expiring = _expiring_cards(session, stripe, horizon)
            if expiring:
                problems += len(expiring)
                logger.error("%d card(s) expiring before %s:", len(expiring), horizon)
                for code, card, exp in expiring:
                    logger.error("  %s — %s expires %s", code, card, exp)
                sentry_sdk.set_context(
                    "billing_expiring_cards",
                    {"items": [f"{c} {card} {exp}" for c, card, exp in expiring]},
                )
                sentry_sdk.capture_message(
                    f"{len(expiring)} card(s) expiring within {args.expiry_days} days "
                    "— send the Customer Portal link (ACU does not cover CIV Visa).",
                    level="error",
                )
            else:
                logger.info("No card expiring before %s.", horizon)

            drifted = _drift(session, stripe)
            if drifted:
                problems += len(drifted)
                logger.error("%d account(s) drifted from Stripe:", len(drifted))
                for code, ours, remote in drifted:
                    logger.error("  %s — ours=%s stripe=%s", code, ours, remote)
                sentry_sdk.set_context(
                    "billing_status_drift",
                    {"items": [f"{c}: ours={o} stripe={r}" for c, o, r in drifted]},
                )
                sentry_sdk.capture_message(
                    f"{len(drifted)} account(s) where billing_status disagrees with "
                    "Stripe — access may be granted or denied wrongly.",
                    level="error",
                )
            else:
                logger.info("No Stripe/DB drift.")

        if problems:
            logger.error("Watchdog found %d problem(s).", problems)
            return 1
        logger.info("Billing clean. Exit 0.")
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("Billing watchdog failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
