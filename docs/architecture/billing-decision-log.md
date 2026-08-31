# Billing — Decision Log

> **What this file is.** [billing-and-collection.md](./billing-and-collection.md) describes the
> design that was built. This one records **how those decisions were reached**: what was
> considered and rejected, on what evidence, and what we got wrong on the way there.
>
> Written 2026-08-25, at the end of the design + implementation pass. The reasoning here is not
> derivable from the code, and it is exactly what gets re-litigated eighteen months later by
> someone — possibly us — who no longer remembers why.

---

## 1. State when this was written

| | |
|---|---|
| Stripe account | Created, **France** (irreversible, and correct). Sandbox keys wired, connectivity verified. KYC not submitted. |
| Socle | Built, tested, shipped **dark** (`BILLING_ENFORCED=false`, every account defaults to `manual`) |
| Entitlement | **Enforced in production** since 2026-08-24 — the prerequisite, see §2.4 |
| Webhook | Validated end-to-end against real Stripe events: 11 delivered, 11 archived, 0 errors |
| Watchdog | Alert path **observed firing** against a real `invoice.payment_failed` |
| Blocking | The four legal pages (Stripe activation) and the pricing grid (ability to charge) — neither is technical |

---

## 2. Four reframings

The design changed shape four times. Each change invalidated work, and each was caused by
something that could not have been known at the start.

### 2.1 The question was not "which Stripe brick"

The opening ask was a simple Stripe integration, in EUR, usable from Côte d'Ivoire. The useful
reframing was that **Stripe was never the hard part** — the merchant entity is French, so Stripe
is available; the payer's location is unconstrained. The real questions were *who signs the
cheque* and *by what rail*.

Answering them (French entity, non-EU payers, mixed cadence) is what produced every subsequent
decision. Starting from "how do I integrate Stripe" would have produced a technically correct
integration of the wrong thing.

### 2.2 A wire-first design, killed by one line of Stripe documentation

Given payers who were exporters, coops and institutions, the first design made Stripe an
**invoicing engine** and the wire the primary rail: Stripe issues the invoice, the client wires
EUR onto Stripe's virtual IBAN, reconciliation happens there.

That design is impossible. **A French Stripe account's EUR virtual IBAN accepts SEPA credit
transfers only** — international SWIFT is supported for US accounts, in USD only. An Abidjan wire
cannot land there.

Discovering this before writing code, rather than in week three, is the single highest-value
research result of the whole pass. It is recorded in the design doc §7 so nobody rediscovers it.

### 2.3 Card-on-file, which changed everything again

The product requirement, once stated plainly, was: *the client enters a card once, we debit
automatically.* That is not what the wire-first design does.

Consequences: Stripe **Billing** (subscriptions) rather than Invoicing; Checkout in
`subscription` mode; the Customer Portal becomes mandatory rather than optional; and monthly
rather than annual billing — counter-intuitively, because a 300 € debit clears a UEMOA card
ceiling that 3 600 € will not.

The wire path survives, demoted: `paid_out_of_band` for institutions who structurally cannot put
a card on file.

### 2.4 Billing could not ship before entitlement was enforced

The gate billing needs (`resolve_principal`) only bites when `ENTITLEMENTS_ENFORCED` is on. It
was off. So a billing suspension would have been decorative.

Flipping it surfaced something worse: **`tenant_account`, `tenant_user` and `tenant_entitlement`
were 0 rows in production.** Flipping without a backfill would have blanked every single login,
including ours. There was no backfill script and no Auth0 Management API to enumerate users.

That produced `seed-internal-tenants` (idempotent, `--dry-run` as the readiness gate), the
seeding of 6 logins onto an `internal` account, and the flip — 2026-08-24. The `--dry-run` gate
is the entire safety net; treat it as mandatory.

---

## 3. Locked decisions, and why

Recorded because each one has a plausible-sounding opposite.

**Billing never writes `tenant_entitlement`.** Grants record *what was bought* (append-only, with
provenance); `billing_status` answers *did they pay*. A payment incident must not destroy the
record of a sale, and restoring payment must not require re-provisioning. There is a dedicated
test asserting grant rows are byte-identical before and after a denial — it is the one a future
refactor is most likely to break.

**`past_due` keeps full access.** Stripe Smart Retries run 2-3 weeks. A UEMOA card-ceiling
overrun is a banking incident, not an unpaid invoice; cutting on the first failed debit loses a
client who was about to be recovered by a card update. Only `unpaid` and `canceled` deny.

**`internal` is excluded from the billing gate** — load-bearing, not cosmetic. Internal accounts
sit at `('manual', NULL)` by default, which `_billing_blocks` would treat as unpaid. Without the
exclusion, flipping `BILLING_ENFORCED` would blank all six grandfathered logins: the exact
failure the entitlement backfill existed to prevent, reproduced one layer up. It has its own test.

**`/billing/portal-session` is deliberately NOT entitlement-gated.** A client denied for
non-payment must still reach the portal to fix their card. Gating it would make recovery
impossible — a trap that only shows up when someone is already locked out.

**`customer_type` is recorded per contract, not per account.** French consumer protections bind
at contract formation. An account can change status; a contract signed last year cannot be
re-qualified. Deriving the regime later from a current account attribute would give a wrong
answer. Constant `business` while we sell B2B only — that is the point, not an oversight.

**The webhook returns 500 so Stripe retries.** This is *not* a violation of
[pipeline-error-handling](../../.claude/rules/pipeline-error-handling.md), which forbids a
*producer* from silently retrying to hide a root cause. Here the retry is the transport contract,
the failure is loud (ERROR + Sentry + a persisted `error` column), and the alternative —
swallowing a payment event with a 200 — is precisely the silent wrong state the rule exists to
prevent. The rationale is in the code so it does not get "fixed" by someone applying the rule
mechanically.

---

## 4. Rejected, with the evidence

Do not re-evaluate these without new information.

**Mobile money, as a category.** It is a *push* rail: the payer authorises every transaction with
a PIN. pawaPay's own documentation states it — *"the user has to explicitly authorise each
payment […] the merchant is not involved."* There is no stored credential, no mandate, no
merchant-initiated pull. A "recurring" mobile money payment is a reusable link the customer
chooses to pay again — a recurring *invoice*, not a recurring *debit*, and strictly harder to
chase than a card that fails loudly.

**Jèko** (jeko.africa) — judged on its OpenAPI 3.2.0 spec, not its marketing. A keyword census of
the bundled spec: **zero** hits for `card`, `carte`, `visa`, `mastercard`, `token`, `recurring`,
`mandate`, `EUR`, `sandbox`. `currency` enum is `["XOF"]`. The pay-in `paymentMethod` is typed
`MobileMoneyPaymentMethod` = `[orange, wave, mtn, moov, djamo]` — no card pay-in exists in the
API at all, despite Visa/Mastercard on the marketing site (that is the physical POS terminal).
Also: Ivorian merchant entity required, production-only server, no refund endpoint. Wrong
category — a merchant acquiring product, not a billing platform.

**pawaPay** — same structural no, but a good product, and **kept as the designated mobile-money
fallback** if the card rail ever fails for coops: EUR/USD/GBP cross-border settlement to a bank
account outside the operating countries, UK contracting entity, a real sandbox, 20 countries
including Ghana, 1% markup. Strictly better than Jèko on every axis that matters here.

**Merchant of Record** — rejected twice, once on paper and once live in the Stripe onboarding
("Let us handle it", +3.5% per transaction). It absorbs global VAT complexity we do not have:
B2B services to non-EU businesses are outside French VAT scope. It would also break B2B
invoicing — the invoice would come from Stripe, not Compass, and an exporter needs an invoice
from its supplier. And the `manual`/wire path does not exist in that model.

**Stripe Tax** — declined during onboarding. It computes the consumer's country VAT for EU B2C
via the OSS one-stop shop. Out of scope, billed per use, and **actively harmful if
misconfigured**: it could add 20% VAT to an invoice for an Ivorian exporter. A wrong invoice at a
client's is harder to unwind than a missing feature. Reversible if an EU client appears — which
is also the moment the CGV would need revisiting.

---

## 5. What we got wrong

The corrections are more instructive than the conclusions.

**Migration/model drift, again.** `billing_status` and `paid_through` were added to the migration
but not to the `TenantAccount` model. The test database is built from the models, so 8 entitlement
tests failed on `column a.billing_status does not exist`. Same failure class that broke a deploy
in July. **Migration column lists must follow the models, and a parity check costs one command.**

**"The card test blocks everything" — overstated.** The recommendation was to run a live
`SetupIntent` on a real Ivorian card before writing any code. Re-examined, ~80% of Part 1 is
invariant to the result (model, gate, webhook, `manual` path). The test decides the *rail
strategy*, not whether to start.

**And the test would not have told us what mattered anyway.** The failure mode that kills a
subscription is not the first payment — it is the second. The souscription charge is *on-session*
with 3DS; the monthly debit is a *merchant-initiated transaction* with nobody present. An issuer
can accept one and refuse the other, and several West African banks handle MITs badly. No test
card reveals this ahead of a full billing cycle. **So it is instrumented instead of tested**: the
watchdog alerts on the first off-session failure of any account.

**"B2C implies self-serve signup" — wrong.** What requires self-serve is an *acquisition motion*
where a consumer discovers the product and buys unassisted, which is a question of decision
window, not volume. Selling to individuals already in contact works with today's manual
provisioning unchanged. And the hard part of ever automating it is not scale: it is **binding a
Stripe payment to an Auth0 identity** when the two are created independently, since an email is
not proof of identity until Auth0 has verified it.

**"The client creates their access" — wrong.** There is no signup route in the frontend; the
Auth0 user is created by us. The runbook already documented it. The correct order is: Auth0 user
→ `create-tenant` → `link-seat` → Checkout link. And credentials are never emailed — Auth0's
change-password ticket is the mechanism, so we never know the client's password.

**A comment that would have broken the deploy.** The explanatory note about `AUDIO_URL_SECRET`
was first written *inside* `deploy.yml`'s `secrets: |` block. That is a literal string, not YAML —
the `#` lines would have been parsed as secret entries. Caught by parsing the result rather than
eyeballing it.

**Sentry was missing from the RGPD inventory.** The processor list was Auth0, Stripe, Google
Cloud. But [`auth.py:138`](../../backend/app/core/auth.py) calls
`sentry_sdk.set_user({"id": sub, "email": email})` on every authenticated request. `send_default_pii=False`
does not protect against it — that flag governs *automatic* collection, not an explicit call.
Sentry receives the email of every authenticated user, on both backend and frontend. An inventory
omitting the tool that receives all the emails is the kind of gap that costs in an audit.

---

## 6. What only the live test revealed

One `stripe trigger invoice.payment_failed` delivered **11 events, of which we handle exactly
one**. The code queried the database to resolve the account *before* checking the event type — so
ten of eleven events cost a pointless join and logged a misleading `"unknown customer"` warning,
when the customer was beside the point.

Fixed with an early return on unhandled types, and a regression test asserting five ignored types
trigger zero lookups. **No unit test could have caught this**: it required seeing the real event
volume. This is the argument for wiring the CLI rather than stopping at mocks.

The same session also produced the first observed firing of the watchdog's alert path, by binding
a probe account to the real failed event's Stripe customer. An alert nobody has ever seen fire is
an alert you do not know you have.

---

## 7. Open, with owner

| Item | Owner | Blocks |
|---|---|---|
| The four legal pages | Lawyer (briefed) | **Stripe activation** |
| Pricing grid — at least one fixed tier, amount, cadence | Commercial | **Ability to charge**, not activation |
| Cloud Scheduler entry for `cc-billing-watchdog` | Tech | The job deploys but never fires |
| Purge job for `aud_billing_event` (18-month retention) | Tech | Must exist **before** the privacy policy goes live |
| Chargeback handling — alert to two addresses, written trace of each decision | Tech + ops | Nothing today |
| `AUDIO_URL_SECRET` Terraform import | Tech | Benign drift |
| Portal self-cancellation vs the 12-month commitment | Lawyer | Portal configuration |

**The last one is the sharpest.** The Customer Portal lets a client cancel in a few clicks. That
appears forbidden for a professional committed for 12 months, and required for a non-professional
under art. L215-1-1. The same feature, contradictory obligations — coherent with the differentiated
regime being drafted, but it needs an instruction. And Stripe bills monthly and will **never**
enforce a 12-month commitment: the remaining balance is recovered by contract, not by the system.

---

## 8. If you are picking this up

Read [billing-and-collection.md](./billing-and-collection.md) for the design, then
[entitlement-enforcement.md](../runbooks/entitlement-enforcement.md) for the layer underneath —
billing is meaningless without it.

Two things that look like bugs and are not: `past_due` serving normally, and `customer_type`
being constant. Both are §3.

One thing that looks fine and is not: any change that makes billing write to
`tenant_entitlement`. That is the invariant, and the test guarding it is
`test_payment_failure_never_touches_entitlement_grants`.
