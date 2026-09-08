"""Tests for the two defects the 2026-09-08 live test exposed.

Both were invisible to the existing suite, and for the same reason: its
fixtures pre-establish the binding that production does not have yet.
`test_invoice_paid_activates_and_records_the_rail` seeds
`provider_customer_id = 'cus_w'` *before* delivering the event — so it asserts
the happy path of a customer already known, which is precisely the state the
first payment of a client is NOT in.

**Defect 1 — the first-payment race.** Stripe creates the customer, the
subscription and the invoice *before* it completes the Checkout session. Only
`checkout.session.completed` carries `client_reference_id`, so it is the only
event that can bind a Stripe customer to an account. Everything Stripe delivers
before it therefore hits `_account_by_customer` → `None` → "unknown customer,
ignored", in a clean `200`. Observed in production: `invoice.payment_failed`
(10:24:33), `customer.subscription.updated` and `invoice.paid` (10:28:12) were
all dropped; the first invoice was never mirrored and a genuinely failed first
attempt never marked the account `past_due`. The final state was right only
because `checkout.session.completed` happened to land last.

**Defect 2 — the redirect.** `success_url` was built from `settings.frontend_url`,
which derives from the CORS origins of *the machine minting the link*. Run from
a laptop, it sends a paying client to `http://localhost:3000`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import TenantAccount, TenantUser
from app.services import billing_service
from scripts.billing_admin import LocalReturnUrlError, resolve_return_base


# --------------------------------------------------------------------------- #
# Defect 2 — the return URL may never come from the operator's machine
# --------------------------------------------------------------------------- #
@pytest.mark.unit
@pytest.mark.parametrize(
    "configured",
    [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
        "https://localhost",
    ],
)
def test_a_local_origin_is_refused(configured: str) -> None:
    """Fail loud rather than mint a link that strands a paying client.

    The client is charged either way — Stripe has taken the money before the
    redirect. A dead landing page therefore does not fail the payment, it makes
    a successful payment *look* failed, which is worse: the client retries.
    """
    with pytest.raises(LocalReturnUrlError):
        resolve_return_base(explicit=None, configured=configured)


@pytest.mark.unit
def test_an_explicit_override_wins_over_the_environment() -> None:
    """The operator states the client's URL; the laptop never gets a vote."""
    assert (
        resolve_return_base(
            explicit="https://app.com-compass.com", configured="http://localhost:3000"
        )
        == "https://app.com-compass.com"
    )


@pytest.mark.unit
def test_an_explicit_local_override_is_refused_too() -> None:
    """`--frontend-url http://localhost:3000` is the same mistake, typed out."""
    with pytest.raises(LocalReturnUrlError):
        resolve_return_base(
            explicit="http://localhost:3000", configured="https://app.com-compass.com"
        )


@pytest.mark.unit
def test_a_public_configured_origin_is_used_as_is() -> None:
    """On the deployed service the CORS origin is already correct."""
    assert (
        resolve_return_base(explicit=None, configured="https://app.com-compass.com/")
        == "https://app.com-compass.com"
    )


# --------------------------------------------------------------------------- #
# Defect 1 — bind the customer when the link is minted, not when Stripe says so
# --------------------------------------------------------------------------- #
class _FakeStripe:
    """Minimal stand-in: records what was asked of Stripe, invents nothing."""

    def __init__(self) -> None:
        self.customers_created: list[dict[str, Any]] = []
        self.sessions_created: list[dict[str, Any]] = []
        self.checkout = self

    class _Obj:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    @property
    def Customer(self) -> Any:  # noqa: N802 — mirrors the Stripe SDK
        outer = self

        class _Customer:
            @staticmethod
            def create(**kw: Any) -> Any:
                outer.customers_created.append(kw)
                return _FakeStripe._Obj(id="cus_new")

        return _Customer

    @property
    def Session(self) -> Any:  # noqa: N802 — mirrors the Stripe SDK
        outer = self

        class _Session:
            @staticmethod
            def create(**kw: Any) -> Any:
                outer.sessions_created.append(kw)
                return _FakeStripe._Obj(url="https://checkout.stripe.com/c/pay/cs_x")

        return _Session


@pytest.mark.unit
@pytest.mark.asyncio
async def test_checkout_creates_the_customer_and_returns_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The customer id must come back so the caller can persist it NOW.

    Computing it and dropping it is the leak `pipeline-continuity` describes:
    the writer would then have nothing to store, and the binding would wait on
    a webhook that arrives after the events that need it.
    """
    fake = _FakeStripe()
    monkeypatch.setattr(billing_service, "_client", lambda: fake)

    handle = await billing_service.create_checkout_session(
        account_code="acme",
        price_id="price_x",
        success_url="https://app.com-compass.com/dashboard?billing=ok",
        cancel_url="https://app.com-compass.com/dashboard?billing=cancelled",
    )

    assert handle.customer_id == "cus_new"
    assert handle.url.startswith("https://checkout.stripe.com/")
    # The account code travels on the customer too, so a human staring at the
    # Stripe dashboard can tell whose customer this is without a join.
    assert fake.customers_created == [{"metadata": {"account_code": "acme"}}]
    assert fake.sessions_created[0]["customer"] == "cus_new"
    assert fake.sessions_created[0]["client_reference_id"] == "acme"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_known_customer_is_reused_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-issuing a link (the first expired) must not fork the client in two.

    Two Stripe customers for one account means two payment methods, two
    invoice histories, and an `_account_by_customer` lookup that resolves for
    one of them and not the other.
    """
    fake = _FakeStripe()
    monkeypatch.setattr(billing_service, "_client", lambda: fake)

    handle = await billing_service.create_checkout_session(
        account_code="acme",
        price_id="price_x",
        success_url="https://app.com-compass.com/ok",
        cancel_url="https://app.com-compass.com/ko",
        customer_id="cus_existing",
    )

    assert handle.customer_id == "cus_existing"
    assert fake.customers_created == []
    assert fake.sessions_created[0]["customer"] == "cus_existing"


# --------------------------------------------------------------------------- #
# Defect 1 — the regression, in the order production actually delivers
# --------------------------------------------------------------------------- #
async def _account_with_row(
    db: AsyncSession, *, customer_id: str | None
) -> TenantAccount:
    account = TenantAccount(
        code=f"acct-{uuid.uuid4().hex[:8]}",
        name="T",
        tier="coop_premium",
        billing_status="manual",
    )
    db.add(account)
    await db.flush()
    db.add(TenantUser(account_id=account.id, auth0_sub=f"auth0|{uuid.uuid4().hex[:8]}"))
    await db.execute(
        text(
            """
            INSERT INTO tenant_billing_subscription
                (id, account_id, provider, provider_customer_id, tier, currency,
                 amount_cents, billing_interval, status, effective_from, active)
            VALUES (:id, :aid, 'stripe', :cid, :tier, 'EUR', 100, 'month',
                    'incomplete', CURRENT_DATE, true)
            """
        ),
        {
            "id": uuid.uuid4(),
            "aid": account.id,
            "cid": customer_id,
            "tier": account.tier,
        },
    )
    await db.flush()
    return account


def _invoice_paid(customer_id: str) -> dict[str, Any]:
    return {
        "id": "evt_first_invoice",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_first",
                "number": "XBTDW5MH-0001",
                "customer": customer_id,
                "amount_due": 100,
                "amount_paid": 100,
                "currency": "eur",
                "status": "paid",
                "created": 1788863000,
            }
        },
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_first_invoice_is_mirrored_before_checkout_completes(
    db_session: AsyncSession,
) -> None:
    """`invoice.paid` lands FIRST — as it did in production — and still applies.

    This is the whole fix: because `create-checkout-link` writes
    `provider_customer_id` when it mints the link, the account is resolvable
    from the very first event Stripe sends, whatever order it chooses.
    """
    account = await _account_with_row(db_session, customer_id="cus_bound")

    await billing_service.apply_event(db_session, _invoice_paid("cus_bound"))
    await db_session.flush()

    mirrored = (
        await db_session.execute(
            text(
                "SELECT number, amount_cents, amount_received_cents FROM "
                "tenant_billing_invoice WHERE account_id = :aid"
            ),
            {"aid": account.id},
        )
    ).all()
    assert mirrored == [("XBTDW5MH-0001", 100, 100)]

    status = (
        await db_session.execute(
            text("SELECT billing_status FROM tenant_account WHERE id = :aid"),
            {"aid": account.id},
        )
    ).scalar_one()
    assert status == "active"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_unbound_row_still_loses_the_event(
    db_session: AsyncSession,
) -> None:
    """The defect, pinned — so a regression is a failing test, not an incident.

    With `provider_customer_id` NULL the event is dropped, silently and with a
    `200`. That is deliberate (a 5xx would make Stripe retry forever an event
    we can never resolve), which is exactly why the binding has to happen
    upstream, at link time. If this test ever starts failing because the event
    now applies, the race has been fixed somewhere else and this file should
    say so.
    """
    account = await _account_with_row(db_session, customer_id=None)

    await billing_service.apply_event(db_session, _invoice_paid("cus_unbound"))
    await db_session.flush()

    count = (
        await db_session.execute(
            text("SELECT count(*) FROM tenant_billing_invoice WHERE account_id = :aid"),
            {"aid": account.id},
        )
    ).scalar_one()
    assert count == 0

    status = (
        await db_session.execute(
            text("SELECT billing_status FROM tenant_account WHERE id = :aid"),
            {"aid": account.id},
        )
    ).scalar_one()
    assert status == "manual"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_failed_first_attempt_marks_past_due(
    db_session: AsyncSession,
) -> None:
    """The production case that was lost: the FIRST attempt failing.

    On 2026-09-08 `invoice.payment_failed` arrived four minutes before the
    successful retry and was dropped, so the account never went `past_due`.
    Harmless there because the retry succeeded; not harmless for a client whose
    card simply does not work.
    """
    account = await _account_with_row(db_session, customer_id="cus_bound2")

    await billing_service.apply_event(
        db_session,
        {
            "id": "evt_first_failure",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_fail",
                    "number": "XBTDW5MH-0002",
                    "customer": "cus_bound2",
                    "amount_due": 100,
                    "amount_paid": 0,
                    "currency": "eur",
                    "status": "open",
                    "created": 1788862000,
                }
            },
        },
    )
    await db_session.flush()

    status = (
        await db_session.execute(
            text("SELECT billing_status FROM tenant_account WHERE id = :aid"),
            {"aid": account.id},
        )
    ).scalar_one()
    assert status == "past_due"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_effective_date_is_the_row_the_link_created(
    db_session: AsyncSession,
) -> None:
    """One account, one active subscription row — the webhook updates, never forks.

    `checkout.session.completed` fills in the subscription id on the row
    `create-checkout-link` already wrote; it must not leave a second active row
    behind, or `_account_by_customer`'s `LIMIT 1` starts picking arbitrarily.
    """
    account = await _account_with_row(db_session, customer_id="cus_bound3")

    await billing_service.apply_event(
        db_session,
        {
            "id": "evt_done",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "client_reference_id": account.code,
                    "customer": "cus_bound3",
                    "subscription": "sub_bound3",
                }
            },
        },
    )
    await db_session.flush()

    rows = (
        await db_session.execute(
            text(
                "SELECT provider_customer_id, provider_subscription_id, status "
                "FROM tenant_billing_subscription WHERE account_id = :aid AND active"
            ),
            {"aid": account.id},
        )
    ).all()
    assert rows == [("cus_bound3", "sub_bound3", "active")]
