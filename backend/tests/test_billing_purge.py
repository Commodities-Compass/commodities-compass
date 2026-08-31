"""Tests for the 18-month purge of `aud_billing_event`.

The retention itself is a commitment we published: politique de confidentialité
§ 3, ligne 5 — « **18 mois** à compter de la fin de la période d'abonnement
couverte par le paiement concerné, puis purge automatique ».

The load-bearing test is `test_period_end_extends_retention`: the deadline runs
from the END OF THE SERVICE PERIOD, not from the day the webhook arrived. For a
subscription billed `à échoir` those differ by a full month, and getting it
wrong destroys evidence while the chargeback window is still open.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from scripts.billing_purge import main as purge

# 18 months ≈ 548 days. Offsets are chosen far enough from the boundary that a
# leap year or a month-length quirk can never flip a test.
LONG_AGO = 580  # ~19 months — past retention
RECENT = 520  # ~17 months — still within retention


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(
    session,
    *,
    days_ago: int,
    event_type: str = "invoice.paid",
    period_end: object = None,
) -> str:
    """Insert one raw event with a controlled `received_at`. Returns its id."""
    event_id = f"evt_{uuid.uuid4().hex[:20]}"
    obj: dict[str, object] = {"id": f"in_{uuid.uuid4().hex[:16]}"}
    if period_end is not None:
        obj["period_end"] = period_end
    session.execute(
        text(
            """
            INSERT INTO aud_billing_event
                (id, provider, event_id, event_type, payload, received_at)
            VALUES (:id, 'stripe', :eid, :etype, CAST(:payload AS jsonb), :ts)
            """
        ),
        {
            "id": uuid.uuid4(),
            "eid": event_id,
            "etype": event_type,
            "payload": json.dumps({"id": event_id, "data": {"object": obj}}),
            "ts": _now() - timedelta(days=days_ago),
        },
    )
    session.flush()
    return event_id


def _remaining(session) -> set[str]:
    rows = session.execute(text("SELECT event_id FROM aud_billing_event")).fetchall()
    return {r[0] for r in rows}


# --------------------------------------------------------------------------- #
# The anchor — which date the 18 months run from
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_purges_past_retention(sync_db_session) -> None:
    """No period in the payload → the anchor falls back to `received_at`."""
    old = _event(sync_db_session, days_ago=LONG_AGO, event_type="charge.succeeded")

    assert purge.purge(sync_db_session) == 1
    assert old not in _remaining(sync_db_session)


@pytest.mark.unit
def test_keeps_within_retention(sync_db_session) -> None:
    recent = _event(sync_db_session, days_ago=RECENT, event_type="charge.succeeded")

    assert purge.purge(sync_db_session) == 0
    assert recent in _remaining(sync_db_session)


@pytest.mark.unit
def test_period_end_extends_retention(sync_db_session) -> None:
    """The correction that matters: the clock starts at the END OF SERVICE.

    A payment received 19 months ago that covers a period ending 2 months ago is
    STILL within its chargeback window. Purging on `received_at` alone would
    delete the only proof of the transaction while it can still be contested.
    """
    period_end = int((_now() - timedelta(days=60)).timestamp())
    covered = _event(sync_db_session, days_ago=LONG_AGO, period_end=period_end)

    assert purge.purge(sync_db_session) == 0
    assert covered in _remaining(sync_db_session)


@pytest.mark.unit
def test_period_end_never_shortens_retention(sync_db_session) -> None:
    """A period that ended BEFORE the event arrived must not purge it early.

    Stripe can emit an event about an already-closed period. The anchor is the
    LATER of the two dates, never the earlier — a shorter retention than the
    policy announces is the failure mode we are guarding against.
    """
    period_end = int((_now() - timedelta(days=LONG_AGO + 200)).timestamp())
    recent = _event(sync_db_session, days_ago=RECENT, period_end=period_end)

    assert purge.purge(sync_db_session) == 0
    assert recent in _remaining(sync_db_session)


# --------------------------------------------------------------------------- #
# Malformed payloads must not crash the job
# --------------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize(
    "period_end",
    [None, "not-a-timestamp", {"nested": 1}, [], True],
    ids=["absent", "string", "object", "array", "bool"],
)
def test_non_numeric_period_end_falls_back(sync_db_session, period_end) -> None:
    """Anything that is not a JSON number is ignored, not cast and crashed.

    `aud_billing_event` archives whatever the provider sent, BEFORE
    interpretation — so the purge must survive a payload shape we never
    anticipated rather than take the whole job down with a cast error.
    """
    old = _event(sync_db_session, days_ago=LONG_AGO, period_end=period_end)

    assert purge.purge(sync_db_session) == 1
    assert old not in _remaining(sync_db_session)


# --------------------------------------------------------------------------- #
# survey() — what a dry run reports
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_survey_counts_without_deleting(sync_db_session) -> None:
    _event(sync_db_session, days_ago=LONG_AGO, event_type="invoice.paid")
    _event(sync_db_session, days_ago=LONG_AGO, event_type="invoice.paid")
    _event(sync_db_session, days_ago=LONG_AGO, event_type="charge.refunded")
    kept = _event(sync_db_session, days_ago=RECENT, event_type="invoice.paid")

    report = purge.survey(sync_db_session)

    assert report.total == 3
    assert report.by_type == (("invoice.paid", 2), ("charge.refunded", 1))
    assert report.oldest_anchor is not None
    assert len(_remaining(sync_db_session)) == 4  # survey writes nothing
    assert kept in _remaining(sync_db_session)


@pytest.mark.unit
def test_survey_on_empty_table(sync_db_session) -> None:
    report = purge.survey(sync_db_session)

    assert report.total == 0
    assert report.by_type == ()
    assert report.oldest_anchor is None


# --------------------------------------------------------------------------- #
# The invariant: purging evidence must not touch the accounting record
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_purge_leaves_the_invoice_mirror_intact(sync_db_session) -> None:
    """The two live on different clocks and that is the whole point.

    Raw payloads carry the payer's name, email and country and go at 18 months
    (§ 3 ligne 5). The structured invoice is an accounting record kept 10 years
    (§ 3 ligne 3, art. L123-22 C. com.). A purge that took both would be a
    bookkeeping breach; one that took neither would be an over-retention.
    """
    account_id = uuid.uuid4()
    sync_db_session.execute(
        text(
            "INSERT INTO tenant_account (id, code, name, tier) "
            "VALUES (:id, :code, 'Purge probe', 'internal')"
        ),
        {"id": account_id, "code": f"purge-{uuid.uuid4().hex[:8]}"},
    )
    sync_db_session.execute(
        text(
            """
            INSERT INTO tenant_billing_invoice
                (id, account_id, provider, provider_invoice_id,
                 amount_cents, currency, status, rail, issued_at)
            VALUES (:id, :aid, 'stripe', :pid, 30000, 'EUR', 'paid', 'card', :ts)
            """
        ),
        {
            "id": uuid.uuid4(),
            "aid": account_id,
            "pid": f"in_{uuid.uuid4().hex[:16]}",
            "ts": _now() - timedelta(days=LONG_AGO),
        },
    )
    _event(sync_db_session, days_ago=LONG_AGO)
    sync_db_session.flush()

    assert purge.purge(sync_db_session) == 1

    invoices = sync_db_session.execute(
        text("SELECT count(*) FROM tenant_billing_invoice WHERE account_id = :aid"),
        {"aid": account_id},
    ).scalar_one()
    assert invoices == 1


# --------------------------------------------------------------------------- #
# Retention is a published figure, not a tunable
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_retention_matches_the_published_policy() -> None:
    """18 months is in the privacy policy. Changing it here silently makes the
    published page false — this test is the tripwire that says so."""
    assert purge.RETENTION_MONTHS == 18
