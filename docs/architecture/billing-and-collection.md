# Billing & Collection — Design

> **Status**: **socle IMPLEMENTED and shipped dark** (`BILLING_ENFORCED=false`) — migration `b1i2l3l4i5n6`, 3 tables, the gate in `resolve_principal`, the Stripe webhook, and the ops CLI. **Live Stripe account since 2026-09-03.** Prod is at Alembic `b1i2l3l4i5n6`, the 3 tables exist, `cc-billing-watchdog` + `cc-billing-purge` run daily, and the live webhook (`2026-07-29.dahlia`, 5 events) points at `https://api.com-compass.com/v1/webhooks/stripe`. `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` are in Secret Manager and wired; `BILLING_ENFORCED` defaults to `false`, so the gate is still inert. Remaining: live Products/Prices, then the flip.
> **Goal**: recurring EUR billing by **card on file with automatic debit**, for 7 negotiated tiers sold by hand.
> **Prerequisite, already met**: per-client entitlement is LIVE and enforced ([entitlement-and-tenancy.md](./entitlement-and-tenancy.md) · [runbook](../runbooks/entitlement-enforcement.md)). Billing plugs into `resolve_principal`; it does not replace it.
> **How these decisions were reached**, what was rejected on what evidence, and what we got wrong on the way: [billing-decision-log.md](./billing-decision-log.md).
> **Guardrails**: [north-star-alignment](../../.claude/rules/north-star-alignment.md) · [pipeline-error-handling](../../.claude/rules/pipeline-error-handling.md) · [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md) · [no-workaround-without-asking](../../.claude/rules/no-workaround-without-asking.md).

---

## 0. Locked decisions

| # | Fork | Decision | Consequence |
|---|---|---|---|
| 1 | Provider | **Stripe**, French/EU invoicing entity | Côte d'Ivoire is not a Stripe country (only via Paystack, a separate platform). The *payer* location is unconstrained — only the merchant's is. |
| 2 | Currency | **EUR only** | XOF is pegged to EUR at a fixed 655.957, so an Ivorian client reads a stable FCFA price. No local-currency pricing, no FX hedging conversation. |
| 3 | Rail | **Card on file + merchant-initiated recurring debit** | The explicit product requirement: the client enters a card once, we debit automatically. Mobile money is structurally excluded (§12). |
| 4 | Stripe product | **Billing (subscriptions)**, not Invoicing | Auto-debit needs a Subscription object. Costs 0.7% on top of processing; Invoicing's $2 cap does not apply to recurring. |
| 5 | Card capture | **Checkout in `subscription` mode**, Stripe-hosted | Card fields never touch our frontend → no PCI scope. Handles 3DS, the mandate text, and receipts. One link emailed per client. |
| 6 | Card updates | **Stripe Customer Portal**, mandatory not optional | When a card fails, the client fixing it themselves *is* the recovery loop. Without it, every failure becomes a support ticket. |
| 7 | Cadence | **Monthly**, not annual | Counter-intuitive: a 300 € debit clears a UEMOA card ceiling that 3 600 € will not. |
| 8 | Source of truth for access | **Our DB, not Stripe** | Stripe reports "paid"; `resolve_principal` decides access. Lets a second collector be added later without touching entitlement. |
| 9 | Where billing bites | **`tenant_account.billing_status`, AND-ed in `resolve_principal`** | Billing NEVER writes `tenant_entitlement`. Grants record *what was bought*; billing answers *did they pay*. Orthogonal axes (entitlement doc §11.4). |
| 10 | Failure policy | **Keep access through `past_due`** | Stripe Smart Retries run ~2-3 weeks. A UEMOA ceiling overrun is a banking incident, not an unpaid invoice — cutting on day 1 loses a client you were about to recover. |
| 11 | Non-card clients | **`billing_status = 'manual'` + `paid_through`** | Institutions, donors and NGOs cannot put a card on file (procurement). They wire; ops marks paid. Same webhook path via `paid_out_of_band`. |
| 12 | Enforcement toggle | **`BILLING_ENFORCED`, its own flag** | Separate from `ENTITLEMENTS_ENFORCED`. Ships dark, flips independently, rolls back independently. |
| 13 | Not built | No pricing page, no signup funnel, no card form, no invoice PDF generation, no dunning emails | Seven tiers sold by hand. Stripe's hosted pages are the entire client-facing surface. |

**Core principle**: *Stripe collects and chases. Our database decides who sees what.*

---

## Part 1 — The socle

### 1. What Stripe is, and is not

Stripe is a **collection + dunning engine that emits events**. It is not the access-control system, and its subscription status is not copied into entitlements.

That separation is what makes a second rail cheap: card, wire and (hypothetically) mobile money all converge on **one event**:

```
card (automatic)          ─┐
wire (paid_out_of_band)   ─┼──▶  Stripe: invoice.paid  ──▶  webhook  ──▶  billing_status
mobile money (if ever)    ─┘
```

One webhook, one state machine, one place where access flips.

### 2. Data model — 2 columns + 3 tables

On the existing `tenant_account` ([models/tenant.py](../../backend/app/models/tenant.py)):

```
billing_status  VARCHAR(20) NOT NULL DEFAULT 'manual'
paid_through    DATE NULL
```

`DEFAULT 'manual'` is what makes the migration non-breaking: every existing account keeps working with no backfill, and accounts opt into card billing one at a time. (Contrast with entitlement, where default-deny forced a mandatory backfill — see the runbook.)

Three new tables, in the `tenant_*` / `aud_*` convention, temporal append-only where it matters:

```
tenant_billing_subscription     -- what they are signed up to
  id UUID PK
  account_id UUID FK -> tenant_account
  provider VARCHAR              -- 'stripe' today; the column exists so a second one is not a migration
  provider_customer_id VARCHAR
  provider_subscription_id VARCHAR
  tier VARCHAR                  -- denormalised for audit: what was sold, at the time
  customer_type VARCHAR         -- 'business'|'consumer': the LEGAL regime at contract
                                --  formation. Same denormalisation logic as `tier` —
                                --  French consumer protections bind when the contract
                                --  is formed, so it cannot be derived later from a
                                --  current account attribute. Constant while B2B-only.
  currency VARCHAR              -- 'EUR'
  amount_cents INTEGER
  billing_interval VARCHAR      -- 'month' | 'year' (`interval` is a SQL keyword)
  status VARCHAR                -- mirror of Stripe's subscription status
  current_period_end TIMESTAMPTZ
  effective_from DATE, active BOOLEAN
  UNIQUE(account_id, provider_subscription_id, effective_from)

tenant_billing_invoice          -- history + PDF links, mirrored from Stripe
  id UUID PK
  account_id UUID FK
  provider VARCHAR, provider_invoice_id VARCHAR UNIQUE
  number VARCHAR
  amount_cents INTEGER, amount_received_cents INTEGER, currency VARCHAR
  status VARCHAR                -- draft|open|paid|uncollectible|void
  rail VARCHAR                  -- 'card' | 'wire' | 'manual'
  issued_at, due_at, paid_at TIMESTAMPTZ
  hosted_url, pdf_url VARCHAR

aud_billing_event               -- raw webhook archive + idempotency
  id UUID PK
  provider VARCHAR, event_id VARCHAR
  event_type VARCHAR            -- (`type` is a SQL keyword)
  payload JSONB
  received_at, processed_at TIMESTAMPTZ, error TEXT
  UNIQUE(provider, event_id)
```

`amount_received_cents` is not decoration: correspondent banks skim SWIFT transfers, so a wire routinely arrives short of the invoice. Storing both makes the gap visible instead of silently failing an exact-match reconciliation.

**North Star check**: all of this is serving-layer and tenant-scoped. Nothing touches a `pl_*` computation table — no `tenant_id` column, no join into a series loader. The [timeseries-uniqueness](../../.claude/rules/timeseries-uniqueness.md) fan-out risk does not apply because the pipeline never reads these tables.

### 3. The state machine

`tenant_account.billing_status`:

| Status | Access | Meaning |
|---|:--:|---|
| `trialing` | ✅ | Subscription created, first debit not yet due. |
| `active` | ✅ | Paid, current. |
| `past_due` | ✅ | A debit failed; Stripe Smart Retries are running (~2-3 weeks). **Access is deliberately kept** (decision #10). |
| `unpaid` | ❌ | Retries exhausted. The subscription is **not** cancelled — a card update revives it. |
| `canceled` | ❌ | Contract ended. |
| `manual` | ✅ if `paid_through >= today` | Wire / institutional client. No Stripe subscription. |

Only two states deny. Everything else, including the entire retry window, serves normally.

### 4. Enforcement — two lines

The entire boundary, inside [`resolve_principal`](../../backend/app/core/tenancy.py) (the same single chokepoint entitlement uses):

```python
# tenancy.py — the SQL already selects 6 columns from tenant_account; add two.
if _billing_blocks(billing_status, paid_through):
    entitlements = frozenset()      # deny access, grants untouched
```

```python
def _billing_blocks(status: str, paid_through: date | None) -> bool:
    if not settings.BILLING_ENFORCED:
        return False
    if status == "manual":
        return paid_through is None or paid_through < date.today()
    return status in {"unpaid", "canceled"}
```

Because `resolve_principal` is one function that every authenticated request passes through, billing costs almost nothing to enforce. That is the payoff of how entitlement was built.

**Cache**: the principal is cached for `PRINCIPAL_CACHE_TTL` (10 min in prod). The webhook calls the existing [`invalidate_principal(sub)`](../../backend/app/core/tenancy.py) on `invoice.paid`, so **a client who fixes their card regains access immediately** rather than waiting out the TTL. The hook already exists — it was written before there was a caller.

`/auth/me` gains `billing_status` so the frontend can render the banner. `UserResponse` in [schemas/auth.py](../../backend/app/schemas/auth.py) already carries `tier`, `entitlements`, `enforced` — this is one more field on the same response, no new endpoint.

### 5. The webhook

`POST /v1/webhooks/stripe` — the only always-on piece.

1. **Verify the signature** (`STRIPE_WEBHOOK_SECRET`). Reject unsigned.
2. **Idempotency**: `INSERT INTO aud_billing_event … ON CONFLICT (provider, event_id) DO NOTHING`. If no row was inserted, the event was already handled → return 200 and stop. Stripe redelivers; that must be harmless.
3. **Archive the raw payload** before interpreting it. When something is wrong six months from now, the payload is the evidence.
4. **Handle** the events that matter:

| Event | Effect |
|---|---|
| `checkout.session.completed` | Link `provider_customer_id` / `provider_subscription_id`, `billing_status='active'` |
| `invoice.paid` | Mirror the invoice, `active`, **`invalidate_principal(sub)`** |
| `invoice.payment_failed` | `past_due` — access kept |
| `customer.subscription.updated` | Mirror Stripe's status |
| `customer.subscription.deleted` | `canceled` |

5. **On processing failure: log, Sentry, return 500** so Stripe retries.

> That retry is **not** a violation of [pipeline-error-handling](../../.claude/rules/pipeline-error-handling.md). That rule forbids a *producer* from silently retrying to hide a root cause. Here the retry is the webhook transport contract, the failure is loud (Sentry + non-2xx), and the alternative — swallowing a payment event — is exactly what the rule exists to prevent. Put this comment in the code; it will otherwise be "fixed" by someone applying the rule mechanically.

### 6. What the client actually experiences

**Souscription (once).** Opens the emailed link → Stripe-hosted page → enters card → 3DS → redirected back. Two minutes. Stripe stores the card **and** collects the mandate authorising later off-session debits — that mandate is what makes recurring possible.

SCA note: with an EEA acquirer (FR) and a non-EEA issuer (CIV), the transaction is **one-leg-out and out of SCA scope**, so 3DS is not forced. Request it anyway on the card-save (`request_three_d_secure: 'any'`) — it shifts chargeback liability and establishes the mandate. Do it on the save, not on every charge.

**Every month.** Nothing. Stripe debits off-session, emails a PDF invoice, notifies us. Invisible by design.

**When the card fails.** `past_due`, access kept, a banner appears at the top of the dashboard linking to the Customer Portal. Stripe relaunches on its own schedule for 2-3 weeks and sends its own reminders. On success, access is restored instantly (§4). On exhaustion, `unpaid` and the dashboard falls back to the "not in your plan" state entitlement already renders.

**Frontend**: one new `components/billing-banner.tsx` (~60 lines) reading `billingStatus` from the existing `EntitlementsContext`, mounted in `dashboard-layout.tsx`. No new page, no payment form.

### 7. The three rails

**Card** — the default. `collection_method='charge_automatically'`.

**Wire** — for a client whose card cannot work. The invoice lives in Stripe with `collection_method='send_invoice'`; the money lands on our own bank account; ops closes the loop:

```python
stripe.Invoice.pay(invoice_id, paid_out_of_band=True)   # → invoice.paid → same webhook path
```

> **A Stripe EUR virtual IBAN cannot receive an Abidjan wire.** Stripe's docs are explicit: international SWIFT is supported for **US accounts, in USD only**; an EU account's virtual IBAN accepts SEPA credit transfers (`network: "sepa"`). Do not rediscover this — the wire must land on a real bank account (Qonto and Wise both expose incoming-transfer webhooks if reconciliation is ever automated).

**Manual** — institutions and donors, who never get a Stripe subscription at all. `billing_status='manual'` + `paid_through`, set by CLI. Long payment terms (net-60/90), PO numbers as Stripe invoice custom fields, and Stripe's automatic reminders turned **off** for that segment — dunning an institution is a human job.

### 8. Provisioning CLI

Extends the existing tenant CLI ([tenant_admin.py](../../backend/scripts/tenant_admin.py)), same append-only spirit:

```bash
poetry run create-tenant --code acme --name "Acme SA" --tier export_premium \
    --billing stripe --interval month        # + Stripe Customer + Checkout link, printed
poetry run billing-status --account acme     # Stripe's view vs ours, and any disagreement
poetry run mark-paid --account acme --until 2027-08-31   # the manual/wire escape hatch
```

No admin UI (entitlement decision #3 carries over).

### 8 bis. The live catalogue

Created 2026-09-03. Monthly, EUR, `tax_behavior: exclusive` (CGV art. 8.1 — prices are quoted *hors taxes*), each carrying `metadata.tier` so a price resolves to a tier without guesswork.

| tier | price id | € / month | published FCFA |
|---|---|---|---|
| `coop_essentiel` | `price_1UBcCjPXtvTEVYwgj9vxKic9` | 762.25 | 500 000 |
| `coop_premium` | `price_1UBcCkPXtvTEVYwgFvPRtYBj` | 990.92 | 650 000 |
| `export_essentiel` | `price_1UBcClPXtvTEVYwgjQP7cx01` | 1 143.37 | 750 000 |
| `export_pro` | `price_1UBcCmPXtvTEVYwgPzZ7sZNx` | 1 524.49 | 1 000 000 |

**Amounts are the fixed-peg conversion**, not a commercial rounding: XOF is pegged to EUR at 655.957, so the exact cent reproduces the advertised FCFA figure to within 3 francs on 500 000. Rounding the EUR would have made the client's bank statement disagree with the price list.

**`export_premium`, `signal_plus` and `origin_desk` have no live price.** The tiers work for entitlement; they simply cannot be sold by card until a price exists. A placeholder `Export Premium` at 300 €/month, typed to get through Stripe's setup wizard on 2026-09-02, was **archived** the next day — it carried no `tier`, its `tax_behavior` was `unspecified`, and 300 € sat *below* both tiers it was supposed to sit between. Nothing had ever used it.

⚠️ **`unit_amount` and `tax_behavior` are immutable on a Stripe Price.** Repricing is never an edit: it is a new Price plus an archive of the old one. Existing subscriptions keep billing at the price they were created with, which is what makes the 12-month commitment of CGV art. 7.1 hold — and what makes a mis-typed price expensive to unwind.

### 9. `cc-billing-watchdog` — the highest-ROI 80 lines

A daily Cloud Run Job, same shape as `cc-publication-calendar-watchdog`:

- emails a Customer Portal link **30 days before** a card expires;
- Sentry-alerts on any account where Stripe's status and `billing_status` disagree;
- **Sentry-alerts on the FIRST off-session failure of any account** — an `invoice.payment_failed` on an account that was `active` is the signal *"this issuer mishandles merchant-initiated transactions"*, and it is the only early warning that exists (§13).

**Why it is not optional**: Stripe's Card Account Updater covers Visa only in the UK and Europe, and Mastercard globally. **A Visa issued in Abidjan is therefore probably not covered** — the card expires, the subscription dies quietly, and nobody notices until the client asks why the dashboard went blank.

### 9 bis. `cc-billing-purge` — the 18 months we published

`aud_billing_event` archives every provider payload verbatim, before
interpretation. Those payloads carry the payer's name, email and country, so
they are the one billing table with a short clock. The privacy policy (§ 3,
ligne 5) commits to **18 months, then automatic purge** — and counsel is blunt
about the ordering: *« Une politique qui annonce dix-huit mois alors que le
système ne purge pas est une pièce à charge signée : elle établit à la fois la
connaissance du manquement et sa date. »* The job therefore has to exist
**before** the page goes live, not after.

**The anchor is the end of the service period, not the arrival of the webhook.**
Card networks allow a dispute up to ~540 days (≈17.7 months, which is where the
18 comes from), and for a service delivered *after* payment that window runs
from delivery. A subscription billed `à échoir` is paid a month before the
period it covers ends, so purging on `received_at` alone would delete the proof
of a transaction that can still be contested. The anchor is
`GREATEST(received_at, payload.data.object.period_end)` — the later of the two,
never the earlier, and a malformed `period_end` falls back to `received_at`
rather than crashing the job.

**What survives**: `tenant_billing_invoice` mirrors the same payments in
structured form and is an accounting record kept **10 years** (art. L123-22 du
code de commerce, § 3 ligne 3). Two finalities, two clocks. This is why no
legal-hold mechanism is needed: a dispute raised past 18 months still has the
invoice, it loses only the verbatim payload.

`RETENTION_MONTHS` is a module constant and deliberately **not** a CLI flag — a
job that can be told to keep less than the published page promises is a job that
will one day be told exactly that. `test_retention_matches_the_published_policy`
is the tripwire.

Cron: daily, `0 3 * * *`, declared in `infra/terraform/scheduler.tf` and
classified `CALENDAR_EXEMPT` in `scripts/_shared/phases.py` — a legal deadline
runs on the civil calendar, not the exchange one. Over-retaining by up to a day
is harmless; under-retaining is the thing being guarded against.

### 10. Testing

- **Unit**: `_billing_blocks` across all 6 statuses × enforced/dark × `paid_through` past/future/NULL; webhook signature verification; idempotency (same `event_id` twice → one effect).
- **Integration**: seeded account, each webhook event → expected `billing_status`; `past_due` still serves 200; `unpaid` returns 403; `manual` with an expired `paid_through` returns 403.
- **The critical test**: an `active` account whose payment fails **keeps its entitlement grants** — assert `tenant_entitlement` is byte-identical before and after. That is decision #9, and it is the one a future refactor is most likely to break.
- Stripe is mocked; no test hits the network. Target ≥ 80% (testing rule).

### 11. Rollout

Mirrors the entitlement rollout, which worked:

1. **Ship dark** — migration + tables + webhook + gate, `BILLING_ENFORCED=false`. Every account defaults to `manual`, `_billing_blocks` returns `False` unconditionally → zero behaviour change. Migration reaches prod via `main` only.
2. **Wire one real client** in Stripe **test mode**, end to end: Checkout → webhook → `active` → simulate a failed payment → `past_due` → portal → recovery.
3. **Backfill**: set `paid_through` on the existing accounts so nobody is caught by the flip. Unlike entitlement, the `manual` default means this is a safety net, not a prerequisite.
4. **Flip** `BILLING_ENFORCED=true` via the GitHub variable + deploy — and remember the flag lives in **two places** (GitHub var and Cloud Run env); a rollback must change both.

---

## Part 2 — What we are not building, and why

### 12. Rejected options

Do not re-litigate these without new information.

**Mobile money, in general.** It is a **push** rail: the payer authorises every single transaction with a PIN. pawaPay's own documentation states it — *"the user has to explicitly authorise each payment […] the merchant is not involved."* There is no stored credential, no mandate, no merchant-initiated pull. A "recurring" mobile money payment is a reusable link the customer chooses to pay again — a recurring *invoice*, not a recurring *debit*, and strictly worse to chase than a card that fails loudly.

**Jèko** (jeko.africa) — evaluated against its OpenAPI 3.2.0 spec, not its marketing. Zero occurrences of card, token, recurring, mandate, EUR or sandbox. `currency` enum is `["XOF"]`; the pay-in `paymentMethod` is typed `MobileMoneyPaymentMethod` = `[orange, wave, mtn, moov, djamo]`. No card pay-in at all (the Visa/Mastercard logos are the physical Box terminal). Also: Ivorian merchant entity required, production-only server, no refund endpoint. **Wrong category** — a merchant acquiring product, not a billing platform.

**pawaPay** — same structural no, but a genuinely good product. **Kept as the designated mobile-money fallback** if the card test fails for coops: EUR/USD/GBP cross-border settlement to a bank account outside the operating countries, UK entity (no local subsidiary), a real sandbox, 20 countries including Ghana, 1% markup. Strictly better than Jèko on every axis that matters here. Not built — only reached for if a signed deal blocks on it.

**Merchant of Record** (Paddle / Lemon Squeezy / Stripe Managed Payments) — ~5% vs ~2%, weak on negotiated B2B contracts and wire payment. Its value is VAT complexity we do not have: B2B services to a non-EU business are outside French VAT scope. *Caveat to verify with the accountant*: if a donor or institution turns out to be a **French** entity, that flips into 20% TVA **and** into the French e-invoicing reform, where a Stripe PDF is not a compliant Factur-X invoice and a PDP is required.

### 13. What cannot be tested in advance — and how it is instrumented instead

This section originally said "run a card test before writing code". That was wrong on two counts, and the correction matters more than the original advice.

**First**: the real risk was overstated for the segment that matters. An exporter or trading house doing international business holds a card that works in international e-commerce. The domestic-only GIM-UEMOA problem is a **coop and individual** risk, not a corporate one.

**Second, and decisive**: the failure mode that actually kills a subscription is **not the first payment — it is the second**.

The souscription charge is *on-session*: the client is at their screen, 3DS runs, the issuer sees an authenticated cardholder. The monthly debit is a *merchant-initiated transaction*: nobody is present, and the issuer sees only a mandate. **An issuer can accept the first and refuse the second**, and several West African banks handle MITs badly. No test card reveals this — even holding a real Ivorian card today, you would have to wait a full billing cycle. **The only reliable signal is month 2 of the first real client.**

So the gate is removed. Since it cannot be tested ahead of time, the failure is made **loud and early** instead:

| Risk | How it surfaces |
|---|---|
| Issuer refuses the off-session MIT | `cc-billing-watchdog` Sentry-alerts on the **first** `invoice.payment_failed` of an `active` account (§9) — same day, not as churn three months later |
| Card expires, ACU does not cover it | Portal link emailed 30 days ahead (§9) |
| Low monthly ceiling | Same alert path; mitigated up front by monthly billing (decision #7) |
| Domestic-only card (coops) | Visible at souscription — the card simply cannot be saved. Falls back to `manual`. |

**The escape hatch is in from day one.** Any account that turns out not to be debitable moves to `billing_status='manual'` with one command (`poetry run mark-paid`) and pays by wire. No code to write, no deploy.

Coops remain genuinely unknown — but that is a commercial question answered when one is signed, not a technical one to settle now. If card fails for that segment, §12's pawaPay note becomes the live option.

Roughly 80% of Part 1 is invariant to any of this (model, gate, webhook, `manual` path).

### 14. If we open to consumers (B2C) later

Not planned, but cheap to keep possible. What would return: 14-day withdrawal, electronic cancellation, renewal notice, TTC public pricing, and VAT at the consumer's country rate via the OSS one-stop shop — so Stripe Tax, deliberately left off today.

**One thing is anticipated, and only one**: `tenant_billing_subscription.customer_type`. The reason is legal, not technical — **French consumer protections bind at contract formation**, so which regime applied has to be recorded per contract. It cannot be derived afterwards from a current account attribute, because an account can change status while a contract signed last year cannot be re-qualified. It is constant `business` while we sell B2B only; that is the point.

**What already serves a future B2C without having been built for it:**
- `aud_billing_event` archives raw payloads → turning on Checkout `consent_collection` makes the withdrawal-waiver proof land there automatically. Nothing to build.
- The Customer Portal is already wired (`POST /v1/billing/portal-session`) → that is the "cancel as easily as you subscribed" mechanism. It would only need surfacing permanently instead of on payment failure.
- Stripe Tax is off by configuration, not absent — a flip, not a rewrite.

**Deliberately not built**: consent collection, permanent portal link, Stripe Tax + OSS registration, TTC price grid. These do not pre-build usefully.

**A misconception worth killing**: B2C does *not* require self-serve signup. What requires it is an acquisition motion where a consumer discovers the product and buys unassisted — a question of decision window, not of volume. Selling to individuals we are already in contact with works with today's manual provisioning unchanged. If self-serve ever ships, the hard part is not scale: it is **binding a Stripe payment to an Auth0 identity** when the two are created independently, and an email is not proof of identity until Auth0 has verified it.

---

## Appendix A — Implementation checklist

**DB**
- [x] Alembic migration `b1i2l3l4i5n6`: `billing_status` + `paid_through` on `tenant_account`; `tenant_billing_subscription`, `tenant_billing_invoice`, `aud_billing_event`. Idempotent, via `main`.

**Backend**
- [x] `stripe` dependency in `pyproject.toml`
- [x] `app/models/billing.py` — 3 models (+ `customer_type` on the subscription)
- [x] `app/services/billing_service.py` — customer, checkout session, portal session, mark-paid
- [x] `app/api/api_v1/endpoints/billing.py` — `POST /v1/webhooks/stripe`, `POST /v1/billing/portal-session`
- [x] `app/core/tenancy.py` — `_billing_blocks` + 2 columns in the `resolve_principal` SELECT
- [x] `app/core/config.py` — `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `BILLING_ENFORCED`
- [x] `app/schemas/auth.py` — `billing_status` on `UserResponse`
- [x] CLI (`scripts/billing_admin.py`): `billing-status`, `mark-paid`, `create-checkout-link`
- [x] `cc-billing-watchdog` job (`scripts/billing_watchdog/`) + `deploy.yml` entry — **scheduler still TODO** (`infra/terraform/scheduler.tf`, suggested `0 15 * * 1-5`); until then the job exists but never fires

**Frontend**
- [x] `components/billing-banner.tsx` (+ 9 tests, FR/EN copy)
- [x] `billingStatus` through `EntitlementsContext`
- [x] Mount the banner in `dashboard-layout.tsx`

**Ops** — all of this is Hedi's, and none of it blocks the code
- [ ] Stripe account (French entity) — **not created yet**
- [ ] `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` in Secret Manager + `deploy.yml` (backend service only)
- [ ] 7 Products/Prices in EUR
- [ ] Customer Portal configured (card update + invoice history)
- [ ] Smart Retries + dunning emails configured; reminders **off** for the institutional segment
- [ ] Cloud Scheduler entry for `cc-billing-watchdog` in `infra/terraform/scheduler.tf` (suggested `0 15 * * 1-5`, before the evening pipeline)

**Public site — the real activation blocker.** Stripe reviews it manually, and per their own guide this stops more activations than the Kbis does. The landing (`landing/`, Astro FR+EN) is live and has a contact section, but lacks: mentions légales, CGV, politique de confidentialité, and a page stating the billing model (monthly recurring EUR, price on quote, how to cancel). Note that most of the French *consumer* obligations Stripe's guide lists — 14-day withdrawal, three-click cancellation, tacit renewal, OSS VAT — do **not** apply to B2B sales to non-EU clients. The three legal pages are owed anyway (LCEN, GDPR, art. L441-1 Code de commerce); Stripe only forces the timing. Have a lawyer review before publishing.

---

## Appendix B — Open items

- **The two billing schedulers are declared in `infra/terraform/scheduler.tf`** (`billing-watchdog` at `0 15 * * *`, `billing-purge` at `0 3 * * *`) and classified `CALENDAR_EXEMPT` in `scripts/_shared/phases.py`. Both are **daily, not weekday-only**: billing has no session dimension, and the watchdog's 26h look-back would drop every Friday-to-Sunday payment failure under a `1-5` cron. They exist in code from this PR; they exist in GCP only after `terraform apply`.
- **Flipping `BILLING_ENFORCED` is one place, not two.** It is driven by the `BILLING_ENFORCED` repo variable read by `deploy.yml`. Do NOT set it on the Cloud Run service: that is the trap `ENTITLEMENTS_ENFORCED` fell into, where the next deploy silently reverted it.
- **`customer.subscription.updated` and `.deleted` have never been received for real.** Unit-tested only — no such event exists in `aud_billing_event`. That is the path Stripe takes when retries are exhausted and the subscription is marked `unpaid`, i.e. **the path that suspends a client**. Watch it on the first real failed debit rather than discovering it six weeks in.
- **The card go/no-go test** (§13) — the only real unknown.
- Whether coops get card or `manual` from day one — falls out of the test.
- Automating wire reconciliation (Qonto or Wise incoming-transfer webhook → matcher → `paid_out_of_band`). Deferred until manual reconciliation actually hurts; at ~10-30 invoices a year it does not.
- Proration and self-serve upgrade/downgrade — only if the sales motion asks.
- VAT: confirm with the accountant that no client is a French entity (§12 caveat).
- `tier` is denormalised onto `tenant_billing_subscription` for audit. If a tier change must reprice automatically, that becomes a real coupling to design — today it is two deliberate ops steps (`set-tier` + a Stripe price change).
