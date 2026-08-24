# Billing & Collection — Design

> **Status**: DESIGN ONLY — no code, no `stripe` dependency, no Stripe account as of 2026-08-24.
> **Goal**: recurring EUR billing by **card on file with automatic debit**, for 7 negotiated tiers sold by hand.
> **Prerequisite, already met**: per-client entitlement is LIVE and enforced ([entitlement-and-tenancy.md](./entitlement-and-tenancy.md) · [runbook](../runbooks/entitlement-enforcement.md)). Billing plugs into `resolve_principal`; it does not replace it.
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
  currency VARCHAR              -- 'EUR'
  amount_cents INTEGER
  interval VARCHAR              -- 'month' | 'year'
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
  type VARCHAR
  payload JSONB
  received_at, processed_at TIMESTAMPTZ
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

### 9. `cc-billing-watchdog` — the highest-ROI 80 lines

A daily Cloud Run Job, same shape as `cc-publication-calendar-watchdog`:

- emails a Customer Portal link **30 days before** a card expires;
- Sentry-alerts on any account where Stripe's status and `billing_status` disagree.

**Why it is not optional**: Stripe's Card Account Updater covers Visa only in the UK and Europe, and Mastercard globally. **A Visa issued in Abidjan is therefore probably not covered** — the card expires, the subscription dies quietly, and nobody notices until the client asks why the dashboard went blank.

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

### 13. The go/no-go test — run this before writing code

Take **one real Ivorian card from an exporter and one from a coop**. Run a live `SetupIntent`, then a charge at the actual tier amount. A month later, confirm the off-session renewal.

Twenty minutes. It answers what no amount of desk research can:

| Risk | What the test reveals |
|---|---|
| Domestic-only GIM-UEMOA cards | The card cannot be saved at all |
| International e-commerce disabled by default at the bank | Fails until the client phones their bank — belongs in the onboarding checklist, not the code |
| Low monthly online ceilings | The tier amount is refused; confirms decision #7 (monthly) or forces it lower |
| Issuers that mishandle off-session MITs | Only visible at the *second* debit, a month later |

**Outcome → action**: both cards work → build as specced. Exporter works, coop does not → build as specced and put coops on `manual`. Neither works → the rail is wrong, and §12's pawaPay note becomes the live option.

Roughly 80% of Part 1 is invariant to this result (model, gate, webhook, `manual` path). The test decides the **rail strategy**, not whether to start.

---

## Appendix A — Implementation checklist

**DB**
- [ ] Alembic migration: `billing_status` + `paid_through` on `tenant_account`; `tenant_billing_subscription`, `tenant_billing_invoice`, `aud_billing_event`. Idempotent, via `main`.

**Backend**
- [ ] `stripe` dependency in `pyproject.toml`
- [ ] `app/models/billing.py` — 3 models
- [ ] `app/services/billing_service.py` — customer, checkout session, portal session, mark-paid
- [ ] `app/api/api_v1/endpoints/billing.py` — `POST /v1/webhooks/stripe`, `POST /v1/billing/portal-session`
- [ ] `app/core/tenancy.py` — `_billing_blocks` + 2 columns in the `resolve_principal` SELECT
- [ ] `app/core/config.py` — `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `BILLING_ENFORCED`
- [ ] `app/schemas/auth.py` — `billing_status` on `UserResponse`
- [ ] CLI: `--billing` on `create-tenant`, plus `billing-status`, `mark-paid`
- [ ] `cc-billing-watchdog` job + scheduler + `deploy.yml` entry

**Frontend**
- [ ] `components/billing-banner.tsx`
- [ ] `billingStatus` through `EntitlementsContext`
- [ ] Mount the banner in `dashboard-layout.tsx`

**Ops**
- [ ] Stripe account (French entity) — **not created yet**
- [ ] `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` in Secret Manager + `deploy.yml` (backend service only)
- [ ] 7 Products/Prices in EUR
- [ ] Customer Portal configured (card update + invoice history)
- [ ] Smart Retries + dunning emails configured; reminders **off** for the institutional segment

---

## Appendix B — Open items

- **The card go/no-go test** (§13) — the only real unknown.
- Whether coops get card or `manual` from day one — falls out of the test.
- Automating wire reconciliation (Qonto or Wise incoming-transfer webhook → matcher → `paid_out_of_band`). Deferred until manual reconciliation actually hurts; at ~10-30 invoices a year it does not.
- Proration and self-serve upgrade/downgrade — only if the sales motion asks.
- VAT: confirm with the accountant that no client is a French entity (§12 caveat).
- `tier` is denormalised onto `tenant_billing_subscription` for audit. If a tier change must reprice automatically, that becomes a real coupling to design — today it is two deliberate ops steps (`set-tier` + a Stripe price change).
