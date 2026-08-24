# Entitlement Enforcement — Operations

> **Status: LIVE in production since 2026-08-24** (revision `backend-00255-mqs`).
> `ENTITLEMENTS_ENFORCED=true`. Six Auth0 logins are seated on the `internal` account.
> Design: [entitlement-and-tenancy.md](../architecture/entitlement-and-tenancy.md) · Rollout history: §10 there.

Enforcement is **default-deny**: an authenticated login with no `tenant_user` row resolves to an
empty entitlement set and every gated endpoint returns `403`. That is the whole point — and the
whole risk. This runbook covers the two things you will actually do (onboard a client, roll back)
and the traps that come with them.

---

## 1. The rule that matters most

**A new client must be provisioned BEFORE their first login.**

There is no self-service and no implicit grant. An Auth0 user who signs in without a seat gets a
blank dashboard — not an error page, not a "contact us" screen. Just nothing. They will assume the
product is broken.

Order is therefore always: Auth0 user exists → you copy their `sub` → you provision → they log in.

---

## 2. Onboarding a new client

```bash
# 1. The Auth0 identity must already exist.
#    Auth0 Dashboard → User Management → Users → copy the `user_id` column
#    (e.g. auth0|68f3c…, google-oauth2|1234…).

# 2. Create the account and expand its tier into per-key grants.
poetry run create-tenant --code acme --name "Acme SA" --tier export_premium

# 3. Attach the seat.
poetry run link-seat --account acme --auth0-sub "auth0|68f3c…" --email ops@acme.com

# 4. (WatchAI benchmark only) give the account its exporter identity.
poetry run map-exporter --account acme --list        # find the exact name first
poetry run map-exporter --account acme --entity "ACME EXPORT SA"
```

Valid tiers: the 7 commercial ones (`coop_essentiel`, `coop_premium`, `export_essentiel`,
`export_premium`, `export_pro`, `signal_plus`, `origin_desk`) plus `internal`.

**Never put a real client on `internal`.** It resolves to the complete catalogue at read time,
including every key added in the future — it is a staff/grandfather marker, not a commercial tier.

A grant or revoke takes up to `PRINCIPAL_CACHE_TTL` (10 min in prod) to bite. Restart the service
for an immediate effect.

---

## 3. Verifying before anyone complains

```bash
# Which accounts, which seats?
./.local/db-prod.sh up
./.local/db-prod.sh exec "SELECT code, name, tier, max_seats, is_active FROM tenant_account ORDER BY code"
./.local/db-prod.sh exec "SELECT a.code, u.auth0_sub, u.email, u.is_active
                          FROM tenant_user u JOIN tenant_account a ON a.id = u.account_id
                          ORDER BY a.code"
# What does an account actually hold?
./.local/db-prod.sh exec "SELECT entitlement_key FROM v_tenant_entitlement_current
                          WHERE account_id = (SELECT id FROM tenant_account WHERE code='acme')
                          ORDER BY 1"
./.local/db-prod.sh down     # always — the bastion VM is billed while it lives
```

From the outside, without a token:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://api.com-compass.com/health                    # 200
curl -s -o /dev/null -w "%{http_code}\n" "https://api.com-compass.com/v1/audio/stream?target_date=2026-08-22"  # 403
curl -s -o /dev/null -w "%{http_code}\n" https://api.com-compass.com/v1/dashboard/weather      # 401
```

`401` on `/dashboard/*` is correct and unrelated to entitlement — every dashboard route requires a
token first. "Ungated" (`/dashboard/non-trading-days`) means *no entitlement key required*, **not**
*public*. A `500` anywhere here is the real alarm.

---

## 4. Rolling back

Two places hold the flag. Change **both**, or the next deploy silently re-enables it.

```bash
# Immediate (~30 s):
gcloud run services update backend --region=europe-west9 --project=cacaooo \
  --update-env-vars ENTITLEMENTS_ENFORCED=false

# Durable — otherwise deploy.yml re-applies `true` from the GitHub var:
gh variable set ENTITLEMENTS_ENFORCED --body false
```

Use `--update-env-vars`, **never** `--set-env-vars` (the latter wipes every other variable).

Rolling back is safe at any time: the entitlement grants are append-only and untouched, so
re-enabling later needs no re-seeding.

---

## 5. The backfill CLI (`seed-internal-tenants`)

`backend/scripts/seed_internal_tenants.py` seats a batch of Auth0 logins on the full-access
`internal` account. It exists for the flip, but stays useful for adding staff.

```bash
poetry run seed-internal-tenants --from-file ../.local/internal-subs.txt --dry-run   # readiness check
poetry run seed-internal-tenants --from-file ../.local/internal-subs.txt             # apply
poetry run seed-internal-tenants --sub "auth0|abc" --sub "auth0|def,x@acme.com"      # or inline
```

File format: one `sub` or `sub,email` per line; `#` comments and blank lines ignored.

- **`--dry-run` is the gate.** It reports `+ would be seated` / `= already here` / `! elsewhere`
  and writes nothing. It is safe to flip only when **nothing shows `+`**.
- **Idempotent** — re-running skips seated logins.
- **Fails loud on a malformed sub** (no `|`). This is deliberate: a typo writes a seat nobody owns
  while the real login stays unseeded, and only surfaces as a blank dashboard after the flip.
- **Refuses to repurpose a client account** (tier ≠ `internal` → abort) and **never moves a login
  already seated elsewhere** — it warns and leaves it, so a provisioned client keeps its own tier.

Against prod, point it at the tunnel (the script reads `DATABASE_SYNC_URL`):

```bash
./.local/db-prod.sh up
cd backend
eval "$(grep -E '^(DB_USER|DB_NAME|DB_PASSWORD|DB_PORT_LOCAL)=' ../.local/db-prod.sh)"
export DATABASE_SYNC_URL="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${DB_PORT_LOCAL}/${DB_NAME}"
poetry run seed-internal-tenants --from-file ../.local/internal-subs.txt --dry-run
cd .. && ./.local/db-prod.sh down
```

There is **no Auth0 Management API** wired into this codebase (only `AUTH0_DOMAIN`, `CLIENT_ID`,
`API_AUDIENCE`, `ALGORITHMS`, `ISSUER`). Subs are copied from the Auth0 dashboard by hand — which
is fine at this scale, but means the list is never auto-discovered. **If someone creates an Auth0
user and nobody runs `link-seat`, nothing will tell you until that person complains.**

---

## 6. The audio boundary

`/audio/stream` cannot carry an `Authorization` header (the HTML `<audio>` element won't send one),
so under enforcement it is gated by a signed capability token instead:

- `/dashboard/audio` (behind `read:section:podcast`) mints an HMAC token bound to
  `(target_date, version, language)` with a 1 h expiry.
- `/audio/stream` verifies it. In dark mode the endpoint stays open — which is why the flip is the
  moment this path changes behaviour.

`AUDIO_URL_SECRET` lives in Secret Manager (`europe-west9`) and is injected by `deploy.yml` on the
**backend service only** — no Cloud Run Job streams audio. `sign_stream_token` raises
`AudioSigningError` on an empty secret, so a missing secret fails loud rather than serving
unsigned URLs.

> **Known debt**: the secret was created by hand and carries the label
> `managed_by: manual-pending-tf-import`. It is absent from Terraform state. Benign today
> (Terraform only destroys what it knows), but adding it to `secrets.tf` without
> `terraform import 'google_secret_manager_secret.app_secrets["AUDIO_URL_SECRET"]' projects/cacaooo/secrets/AUDIO_URL_SECRET`
> first will fail the apply with "already exists". Do **not** add a `google_secret_manager_secret_version`
> for it — that would put the HMAC key into Terraform state.

---

## 7. Symptom → cause

| Symptom | Likely cause |
|---|---|
| A user sees a completely blank dashboard | No `tenant_user` row. Run `link-seat`. |
| A user lost one section after a tier change | `set-tier` does **not** auto-revoke keys outside the new tier, but the frontend gates on the resolved set. Check `v_tenant_entitlement_current`. |
| Podcast fails, everything else fine | `AUDIO_URL_SECRET` missing/rotated on the service, or the token expired (1 h). |
| A grant was made but nothing changed | The 10-minute `PRINCIPAL_CACHE_TTL`. Wait, or restart the service. |
| Everyone lost access at once | The flag flipped without a backfill, or `tenant_account.is_active` was set false. Roll back (§4). |
| `500` on a gated endpoint | Not entitlement — enforcement only ever produces `401`/`403`. Check Sentry. |

---

## 8. Deployment timing

A full `Deploy` run takes **~9-10 min**: `Deploy Backend` (~3 min) then `Deploy Cloud Run Jobs`
(~4 min, 19 jobs updated sequentially), plus image builds. Flipping one env var pays that entire
cost, because the pipeline is all-or-nothing.

`gh run rerun` on a `Deploy` run works but the run stays reported as `queued` by
`gh run view --json status` long after it has actually started — query
`gh api repos/:owner/:repo/actions/runs/<id>` instead, which reports the true `status` and
`run_attempt`.
