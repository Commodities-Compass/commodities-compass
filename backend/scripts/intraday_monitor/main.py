"""Intraday threshold monitor — 15-min polling, London session, alerts.

Usage:
    poetry run intraday-monitor
    poetry run intraday-monitor --dry-run --verbose
    poetry run intraday-monitor --force        # bypass day/session gates

Cron (prod):
    */5 8-16 * * 1-5     # UTC, wide window; in-code London gate trims DST edges

Flow: gates → resolve front-month → fetch delayed price (httpx) → append
pl_contract_data_intraday → evaluate ref_alert_rule levels (S1/R1 from the
last COMPLETED session — the levels shown on the dashboard today), firing ONLY
when the break INVALIDATES the day's signal (OPEN→S1, HEDGE→R1; MONITOR/absent
→ nothing) → on first cross per (rule, session): aud_alert_event + AlertSender.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timezone

import sentry_sdk
from sentry_sdk.crons import monitor

from scripts._shared.cli import build_base_argparser
from scripts._shared.logging import configure_logging
from scripts._shared.sentry import bootstrap_scraper

configure_logging()
logger = logging.getLogger(__name__)

bootstrap_scraper("intraday-monitor", script_file=__file__)


def _parse_args() -> argparse.Namespace:
    parser = build_base_argparser(
        "Intraday threshold monitor (Barchart delayed price → level alerts)"
    )
    return parser.parse_args()


@monitor(monitor_slug="intraday-monitor")
def main() -> int:
    args = _parse_args()
    configure_logging(verbose=args.verbose)

    from scripts.db import should_skip_non_trading_day

    if should_skip_non_trading_day(force=args.force):
        return 0

    from datetime import datetime

    from scripts.intraday_monitor.session_gate import (
        in_london_session,
        london_session_date,
    )

    now_utc = datetime.now(timezone.utc)
    if not in_london_session(now_utc) and not args.force:
        logger.info("Outside London session window — skipping (exit 0)")
        return 0

    logger.info("=" * 60)
    logger.info("Intraday Monitor - Barchart delayed → threshold alerts")
    logger.info("Mode: %s", "DRY RUN" if args.dry_run else "LIVE")
    logger.info("=" * 60)

    try:
        from scripts.contract_resolver import resolve_active, resolve_active_code
        from scripts.db import get_previous_session_date, get_session
        from scripts.intraday_monitor.db_writer import (
            append_observation,
            insert_alert_event,
            load_enabled_rules,
            load_levels,
            load_prev_price,
            load_signal_decision,
            update_delivery,
        )
        from scripts.intraday_monitor.engine import evaluate_rules, render_message
        from scripts.intraday_monitor.scraper import fetch_delayed_quote
        from scripts.intraday_monitor.senders import AlertPayload, build_sender

        with get_session() as session:
            contract_id = resolve_active(session)
            contract_code = resolve_active_code(session)

        quote = fetch_delayed_quote(contract_code)
        session_date = london_session_date(quote.observed_at)
        levels_date = get_previous_session_date(session_date)
        logger.info(
            "Session %s (levels from %s), %s last=%s",
            session_date,
            levels_date,
            contract_code,
            quote.last_price,
        )

        sender = build_sender()
        n_fired = 0
        n_deduped = 0

        with get_session() as session:
            rules = load_enabled_rules(session)
            levels = load_levels(session, contract_id, levels_date)
            # prev BEFORE appending the current observation
            prev_price = load_prev_price(
                session,
                contract_id=contract_id,
                session_date=session_date,
                fallback_date=levels_date,
            )
            signal_decision = load_signal_decision(session, contract_id, levels_date)

            firings = evaluate_rules(
                rules, levels, prev_price, quote.last_price, signal_decision
            )
            logger.info(
                "Evaluated %d rules (signal=%s): prev=%s curr=%s → %d invalidation(s)",
                len(rules),
                signal_decision or "None",
                prev_price,
                quote.last_price,
                len(firings),
            )

            if args.dry_run:
                for firing in firings:
                    logger.info(
                        "[DRY RUN] Would fire %s (level %s, %s → %s)",
                        firing.rule.rule_key,
                        firing.level_value,
                        firing.prev_price,
                        firing.curr_price,
                    )
                logger.info("[DRY RUN] Skipping DB writes and delivery")
            else:
                append_observation(
                    session,
                    contract_id=contract_id,
                    session_date=session_date,
                    observed_at=quote.observed_at,
                    last_price=quote.last_price,
                    trade_time=quote.trade_time,
                )

                for firing in firings:
                    event_id = insert_alert_event(
                        session,
                        firing=firing,
                        contract_id=contract_id,
                        session_date=session_date,
                        observed_at=quote.observed_at,
                        signal_decision=signal_decision,
                        channel=sender.channel,
                    )
                    if event_id is None:
                        n_deduped += 1
                        logger.info(
                            "Rule %s already fired for session %s — dedup skip",
                            firing.rule.rule_key,
                            session_date,
                        )
                        continue

                    text = render_message(
                        contract_code=contract_code,
                        price=firing.curr_price,
                        level_label=firing.rule.level_label,
                        level_value=firing.level_value,
                        observed_at=quote.observed_at,
                        signal_decision=signal_decision,
                    )
                    payload = AlertPayload(
                        text=text,
                        rule_key=firing.rule.rule_key,
                        variables={
                            "contract": contract_code,
                            "price": str(firing.curr_price),
                            "level_label": firing.rule.level_label,
                            "level_value": str(firing.level_value),
                            "signal": signal_decision or "",
                        },
                    )
                    try:
                        result = sender.send(payload)
                    except Exception:
                        # Record the failed delivery, then fail loud.
                        update_delivery(
                            session,
                            event_id=event_id,
                            status="failed",
                            provider_message_id=None,
                            payload={"text": text, **payload.variables},
                        )
                        session.commit()
                        raise
                    update_delivery(
                        session,
                        event_id=event_id,
                        status=result.status,
                        provider_message_id=result.provider_message_id,
                        payload={"text": text, **payload.variables},
                    )
                    n_fired += 1
                    logger.info(
                        "Alert %s delivered via %s",
                        firing.rule.rule_key,
                        result.channel,
                    )

                session.commit()

        sentry_sdk.set_context(
            "intraday_tick",
            {
                "contract": contract_code,
                "session_date": str(session_date),
                "levels_date": str(levels_date),
                "last_price": str(quote.last_price),
                "n_rules": len(rules),
                "n_fired": n_fired,
                "n_deduped": n_deduped,
                "dry_run": args.dry_run,
            },
        )

        logger.info("=" * 60)
        logger.info("SUCCESS: tick recorded (%d fired, %d deduped)", n_fired, n_deduped)
        logger.info("=" * 60)
        return 0

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        # Fail-loud: log + Sentry + non-zero exit. NO retry, NO fallback.
        logger.exception("Intraday monitor failed: %s", exc)
        sentry_sdk.capture_exception(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
