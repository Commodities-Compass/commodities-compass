"""Tests for the billing socle.

Unit: `_billing_blocks` — the whole access decision, across every status ×
enforced/dark × paid_through past/future/NULL.

Integration: the gate on a real request, the webhook (signature, idempotency,
state transitions), and **the invariant that matters most** — a payment failure
must never touch `tenant_entitlement`.

Stripe is never contacted: signature verification and the SDK are stubbed.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Generator
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import entitlements as ent
from app.core import tenancy
from app.core.auth import get_current_user
from app.core.config import settings
from app.main import app
from app.models.tenant import TenantAccount, TenantEntitlement, TenantUser
from app.services import billing_service

V1 = settings.API_V1_STR
WEATHER = f"{V1}/dashboard/weather"
ME = f"{V1}/auth/me"
WEBHOOK = f"{V1}/webhooks/stripe"

YESTERDAY = date.today() - timedelta(days=1)
TOMORROW = date.today() + timedelta(days=1)


# --------------------------------------------------------------------------- #
# Unit — _billing_blocks is the entire decision
# --------------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize(
    "status", ["trialing", "active", "past_due", "unpaid", "canceled", "manual"]
)
def test_dark_mode_never_blocks(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    """BILLING_ENFORCED=false must be a hard no-op, whatever the state."""
    monkeypatch.setattr(settings, "BILLING_ENFORCED", False)
    assert tenancy._billing_blocks(status, None) is False
    assert tenancy._billing_blocks(status, YESTERDAY) is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "paid_through", "expected"),
    [
        # Paying, or inside the retry window → served.
        ("trialing", None, False),
        ("active", None, False),
        # past_due is Stripe Smart Retries (~2-3 weeks). Access is KEPT on
        # purpose: a UEMOA ceiling overrun is a banking incident, not an unpaid
        # invoice, and cutting on the first failure loses a recoverable client.
        ("past_due", None, False),
        # Retries exhausted / contract over → denied.
        ("unpaid", None, True),
        ("canceled", None, True),
        # Manual (wire / institutional) is gated purely on the date.
        ("manual", TOMORROW, False),
        ("manual", date.today(), False),
        ("manual", YESTERDAY, True),
        ("manual", None, True),
        # No billing row at all: billing is opt-in per account, so "unbilled"
        # must not read as "unpaid". Default-deny belongs to entitlement.
        (None, None, False),
    ],
)
def test_billing_blocks_matrix(
    monkeypatch: pytest.MonkeyPatch,
    status: str | None,
    paid_through: date | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True)
    assert tenancy._billing_blocks(status, paid_through) is expected


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _clear_principal_cache() -> Generator[None, None, None]:
    if tenancy._principal_cache is not None:
        tenancy._principal_cache.clear()
    yield
    if tenancy._principal_cache is not None:
        tenancy._principal_cache.clear()


@pytest.fixture
def auth_as() -> Generator[Callable[[str], None], None, None]:
    def _set(sub: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "sub": sub,
            "email": "t@example.com",
            "name": "T",
            "permissions": [],
        }

    yield _set
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def both_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENTITLEMENTS_ENFORCED", True)
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True)


async def _seed(
    db: AsyncSession,
    sub: str,
    keys: set[str],
    *,
    tier: str = "export_premium",
    billing_status: str = "manual",
    paid_through: date | None = None,
) -> uuid.UUID:
    account = TenantAccount(
        code=f"acct-{uuid.uuid4().hex[:8]}",
        name="T",
        tier=tier,
        billing_status=billing_status,
        paid_through=paid_through,
    )
    db.add(account)
    await db.flush()
    db.add(TenantUser(account_id=account.id, auth0_sub=sub))
    for key in keys:
        db.add(
            TenantEntitlement(
                account_id=account.id,
                entitlement_key=key,
                effective_from=date.today(),
                active=True,
            )
        )
    await db.flush()
    return account.id


# --------------------------------------------------------------------------- #
# Integration — the gate on a real request
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.asyncio
async def test_unpaid_account_is_denied(
    client: AsyncClient, db_session: AsyncSession, auth_as, both_enforced
) -> None:
    sub = "auth0|unpaid"
    await _seed(db_session, sub, {ent.SECTION_WEATHER}, billing_status="unpaid")
    auth_as(sub)
    assert (await client.get(WEATHER)).status_code == 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_past_due_keeps_access(
    client: AsyncClient, db_session: AsyncSession, auth_as, both_enforced
) -> None:
    """The retry window must serve normally — this is decision #10, not an oversight."""
    sub = "auth0|past-due"
    await _seed(db_session, sub, {ent.SECTION_WEATHER}, billing_status="past_due")
    auth_as(sub)
    assert (await client.get(WEATHER)).status_code != 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_manual_account_expired_is_denied_but_current_is_served(
    client: AsyncClient, db_session: AsyncSession, auth_as, both_enforced
) -> None:
    lapsed = "auth0|wire-lapsed"
    await _seed(
        db_session,
        lapsed,
        {ent.SECTION_WEATHER},
        billing_status="manual",
        paid_through=YESTERDAY,
    )
    auth_as(lapsed)
    assert (await client.get(WEATHER)).status_code == 403

    if tenancy._principal_cache is not None:
        tenancy._principal_cache.clear()
    current = "auth0|wire-current"
    await _seed(
        db_session,
        current,
        {ent.SECTION_WEATHER},
        billing_status="manual",
        paid_through=TOMORROW,
    )
    auth_as(current)
    assert (await client.get(WEATHER)).status_code != 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_internal_tier_is_never_billing_gated(
    client: AsyncClient, db_session: AsyncSession, auth_as, both_enforced
) -> None:
    """The trap: internal accounts sit at ('manual', NULL) by default.

    Without the explicit exclusion in resolve_principal, flipping
    BILLING_ENFORCED would blank every staff/grandfathered login — the exact
    failure the entitlement backfill existed to prevent.
    """
    sub = "auth0|staff"
    await _seed(
        db_session,
        sub,
        set(),
        tier=ent.INTERNAL,
        billing_status="manual",
        paid_through=None,
    )
    auth_as(sub)
    assert (await client.get(WEATHER)).status_code != 403


@pytest.mark.integration
@pytest.mark.asyncio
async def test_payment_failure_never_touches_entitlement_grants(
    client: AsyncClient, db_session: AsyncSession, auth_as, both_enforced
) -> None:
    """THE critical invariant (design §9 / entitlement §11.4).

    Grants record what was BOUGHT; billing records whether they PAID. A denied
    account must keep every grant row, so restoring payment restores access with
    no re-provisioning — and so the sale keeps its provenance.
    """
    sub = "auth0|keeps-grants"
    account_id = await _seed(
        db_session,
        sub,
        {ent.SECTION_WEATHER, ent.SECTION_SIGNAL},
        billing_status="unpaid",
    )

    before = sorted(
        r[0]
        for r in (
            await db_session.execute(
                select(TenantEntitlement.entitlement_key).where(
                    TenantEntitlement.account_id == account_id
                )
            )
        ).all()
    )

    auth_as(sub)
    assert (await client.get(WEATHER)).status_code == 403

    after = sorted(
        r[0]
        for r in (
            await db_session.execute(
                select(TenantEntitlement.entitlement_key).where(
                    TenantEntitlement.account_id == account_id
                )
            )
        ).all()
    )
    assert before == after == [ent.SECTION_SIGNAL, ent.SECTION_WEATHER]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_auth_me_surfaces_billing_status(
    client: AsyncClient, db_session: AsyncSession, auth_as, both_enforced
) -> None:
    """The banner's only data source — past_due still holds its full key set."""
    sub = "auth0|banner"
    await _seed(db_session, sub, {ent.SECTION_WEATHER}, billing_status="past_due")
    auth_as(sub)
    body = (await client.get(ME)).json()
    assert body["billing_status"] == "past_due"
    assert ent.SECTION_WEATHER in body["entitlements"]


# --------------------------------------------------------------------------- #
# Integration — the webhook
# --------------------------------------------------------------------------- #
@pytest.mark.integration
@pytest.mark.asyncio
async def test_subscription_records_the_legal_regime_per_contract(
    db_session: AsyncSession,
) -> None:
    """French consumer protections bind at CONTRACT FORMATION.

    Which regime applied therefore has to live on the contract row, not be
    derived from a current account attribute — an account can change status,
    and a contract signed last year cannot be re-qualified retroactively. The
    column is constant `business` while we sell B2B only; that is the point.
    """
    sub = "auth0|regime"
    await _seed(db_session, sub, {ent.SECTION_WEATHER})
    account = (
        await db_session.execute(
            select(TenantAccount)
            .join(TenantUser, TenantUser.account_id == TenantAccount.id)
            .where(TenantUser.auth0_sub == sub)
        )
    ).scalar_one()

    # Default: a row written without naming the regime is a B2B contract.
    await db_session.execute(
        text(
            """
            INSERT INTO tenant_billing_subscription
                (id, account_id, provider, tier, currency, amount_cents,
                 billing_interval, status, effective_from, active)
            VALUES (:id, :aid, 'stripe', :tier, 'EUR', 30000, 'month',
                    'active', CURRENT_DATE, true)
            """
        ),
        {"id": uuid.uuid4(), "aid": account.id, "tier": account.tier},
    )
    # And a consumer contract can be recorded explicitly, so opening to B2C
    # later does not leave earlier contracts undocumented.
    await db_session.execute(
        text(
            """
            INSERT INTO tenant_billing_subscription
                (id, account_id, provider, provider_subscription_id, tier,
                 customer_type, currency, amount_cents, billing_interval,
                 status, effective_from, active)
            VALUES (:id, :aid, 'stripe', 'sub_b2c', :tier, 'consumer', 'EUR',
                    3000, 'month', 'active', CURRENT_DATE, true)
            """
        ),
        {"id": uuid.uuid4(), "aid": account.id, "tier": account.tier},
    )
    await db_session.flush()

    regimes = sorted(
        r[0]
        for r in (
            await db_session.execute(
                text(
                    "SELECT customer_type FROM tenant_billing_subscription "
                    "WHERE account_id = :aid"
                ),
                {"aid": account.id},
            )
        ).all()
    )
    assert regimes == ["business", "consumer"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_rejects_a_bad_signature(client: AsyncClient) -> None:
    """400, not 500: a forged payload is not a retry candidate."""
    r = await client.post(
        WEBHOOK, content=b'{"id":"evt_x"}', headers={"Stripe-Signature": "nope"}
    )
    assert r.status_code == 400


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webhook_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Stripe redelivery must be a no-op, not a second application."""
    sub = "auth0|idem"
    await _seed(db_session, sub, {ent.SECTION_WEATHER}, billing_status="past_due")
    account = (
        await db_session.execute(
            select(TenantAccount)
            .join(TenantUser, TenantUser.account_id == TenantAccount.id)
            .where(TenantUser.auth0_sub == sub)
        )
    ).scalar_one()
    await db_session.commit()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": account.code,
                "customer": "cus_1",
                "subscription": "sub_1",
            }
        },
    }
    monkeypatch.setattr(billing_service, "verify_and_parse", lambda p, s: event)

    first = await client.post(
        WEBHOOK,
        content=json.dumps(event).encode(),
        headers={"Stripe-Signature": "t=1,v1=x"},
    )
    second = await client.post(
        WEBHOOK,
        content=json.dumps(event).encode(),
        headers={"Stripe-Signature": "t=1,v1=x"},
    )

    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "duplicate"

    rows = (
        await db_session.execute(
            text("SELECT count(*) FROM aud_billing_event WHERE event_id = :e"),
            {"e": event["id"]},
        )
    ).scalar_one()
    assert rows == 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_invoice_paid_activates_and_records_the_rail(
    db_session: AsyncSession,
) -> None:
    """A wire settles via paid_out_of_band on the SAME event as a card."""
    sub = "auth0|wire-paid"
    await _seed(db_session, sub, {ent.SECTION_WEATHER}, billing_status="past_due")
    account = (
        await db_session.execute(
            select(TenantAccount)
            .join(TenantUser, TenantUser.account_id == TenantAccount.id)
            .where(TenantUser.auth0_sub == sub)
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO tenant_billing_subscription
                (id, account_id, provider, provider_customer_id, tier, currency,
                 amount_cents, billing_interval, status, effective_from, active)
            VALUES (:id, :aid, 'stripe', 'cus_w', :tier, 'EUR', 30000, 'month',
                    'active', CURRENT_DATE, true)
            """
        ),
        {"id": uuid.uuid4(), "aid": account.id, "tier": account.tier},
    )
    await db_session.flush()

    subs = await billing_service.apply_event(
        db_session,
        {
            "id": "evt_paid",
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_1",
                    "customer": "cus_w",
                    "amount_due": 30000,
                    "amount_paid": 29960,  # correspondent-bank skim
                    "currency": "eur",
                    "status": "paid",
                    "paid_out_of_band": True,
                }
            },
        },
    )
    await db_session.flush()

    assert subs == [sub]  # the principal to invalidate → instant access restore

    refreshed = (
        await db_session.execute(
            select(TenantAccount).where(TenantAccount.id == account.id)
        )
    ).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.billing_status == "active"

    inv = (
        await db_session.execute(
            text(
                "SELECT rail, amount_cents, amount_received_cents "
                "FROM tenant_billing_invoice WHERE provider_invoice_id = 'in_1'"
            )
        )
    ).first()
    assert inv is not None
    assert inv[0] == "wire"
    # The gap is stored, not silently dropped — that is what makes a short wire
    # queryable instead of a failed exact-match reconciliation.
    assert inv[1] - inv[2] == 40


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unknown_subscription_status_leaves_billing_untouched(
    db_session: AsyncSession,
) -> None:
    """An unmapped Stripe status must never silently deny a paying client."""
    sub = "auth0|unknown-status"
    await _seed(db_session, sub, {ent.SECTION_WEATHER}, billing_status="active")
    account = (
        await db_session.execute(
            select(TenantAccount)
            .join(TenantUser, TenantUser.account_id == TenantAccount.id)
            .where(TenantUser.auth0_sub == sub)
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO tenant_billing_subscription
                (id, account_id, provider, provider_customer_id, tier, currency,
                 amount_cents, billing_interval, status, effective_from, active)
            VALUES (:id, :aid, 'stripe', 'cus_u', :tier, 'EUR', 30000, 'month',
                    'active', CURRENT_DATE, true)
            """
        ),
        {"id": uuid.uuid4(), "aid": account.id, "tier": account.tier},
    )
    await db_session.flush()

    subs = await billing_service.apply_event(
        db_session,
        {
            "id": "evt_weird",
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_u", "status": "some_new_status"}},
        },
    )
    assert subs == []
    refreshed = (
        await db_session.execute(
            select(TenantAccount).where(TenantAccount.id == account.id)
        )
    ).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.billing_status == "active"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unhandled_event_types_never_touch_the_database(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stripe emits far more than we subscribe to.

    One `stripe trigger invoice.payment_failed` delivered 11 events, of which we
    handle exactly one. Without an early return, each of the other ten cost a
    join and logged a misleading "unknown customer" warning — the customer is
    beside the point when the type would be ignored anyway.
    """
    calls: list[str] = []

    async def _spy(session, customer_id):  # noqa: ANN001
        calls.append(customer_id)
        return None

    monkeypatch.setattr(billing_service, "_account_by_customer", _spy)

    for etype in (
        "payment_intent.created",
        "charge.failed",
        "invoice.finalized",
        "invoice.updated",
        "customer.updated",
    ):
        assert etype not in billing_service.HANDLED_EVENTS
        assert (
            await billing_service.apply_event(
                db_session,
                {
                    "id": f"evt_{etype}",
                    "type": etype,
                    "data": {"object": {"customer": "cus_whatever"}},
                },
            )
            == []
        )

    assert calls == []  # not one lookup for five ignored events
