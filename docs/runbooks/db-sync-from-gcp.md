# DB Sync from GCP — Operational Runbook

## When to use this runbook

Use this runbook when you need a recent snapshot of GCP production data on your local Postgres. Typical triggers:

- **Before generating an Alembic autogenerate migration** — local schema must match prod, otherwise autogen creates spurious "drop column" / "add column" diffs
- **Debugging a prod issue locally** — reproduce dashboard / agent behavior with real data
- **Before a major refactor** — work against current data to avoid surprises

This is **read-only on GCP** (never writes prod) but **destructive on local** (truncates and re-inserts `pl_*`, `ref_*`, `aud_*` tables).

## Pre-requisites

- `gcloud` CLI authenticated as a user with IAP tunnel permission on `cc-bastion`
- Local Postgres running on port 5433: `pnpm db:up`
- Bastion tunnel password retrieved from Secret Manager:

```bash
gcloud secrets versions access latest --secret=cc-cloudsql-app-password --project=cacaooo
```

- Local `backend/.env` includes:

```bash
GCP_DATABASE_URL=postgresql+psycopg2://cc_app:<password>@localhost:5434/commodities_compass
```

## Procedure

### Step 1 — Open the IAP bastion tunnel

In a dedicated terminal (keep it running for the whole session):

```bash
gcloud compute ssh cc-bastion \
  --zone europe-west9-a \
  --tunnel-through-iap \
  --project cacaooo \
  -- -N -L 5434:10.119.160.3:5432
```

Flags explained:
- `-N` — no remote command, just port forward
- `-L 5434:10.119.160.3:5432` — local port 5434 → Cloud SQL private IP

If the tunnel hangs or disconnects, see Troubleshooting below.

### Step 2 — Verify the tunnel works

In a second terminal:

```bash
psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass -c "SELECT version();"
```

Should return the Postgres version banner. If "connection refused", the tunnel isn't up.

### Step 3 — Run the sync

```bash
cd backend
poetry run python scripts/sync_from_gcp.py
```

The script copies all `pl_*`, `ref_*`, `aud_*` tables from GCP to local. Progress is logged per table. Typical duration: 30s-2min depending on volume.

### Step 4 — Verify locally

```bash
psql -h localhost -p 5433 -U postgres -d commodities_compass -c "
SELECT
  (SELECT COUNT(*) FROM pl_contract_data_daily)        AS market_rows,
  (SELECT COUNT(*) FROM pl_indicator_daily)            AS indicator_rows,
  (SELECT MAX(date) FROM pl_contract_data_daily)       AS latest_date;
"
```

Compare counts and `latest_date` against the dashboard to confirm the sync is current.

### Step 5 — Tear down the tunnel

When done, `Ctrl+C` in the terminal running the SSH command.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `gcloud compute ssh` hangs > 30s | IAP firewall lag, first connection of the day | Wait up to 60s, then retry |
| `Permission denied (publickey)` | SSH key not provisioned | Re-run `gcloud compute config-ssh` |
| `connection refused` on port 5434 | Tunnel not up or already used | Kill any existing tunnel, restart Step 1 |
| `password authentication failed` | Wrong password in `.env` | Re-fetch from Secret Manager (Step 0), check no whitespace |
| Sync script writes 0 rows | `GCP_DATABASE_URL` points to local | Verify env var contains `127.0.0.1:5434` not `5433` |
| Local table missing column | Local schema older than prod | Run `poetry run alembic upgrade head` first |

## Background

- Cloud SQL is **private IP only** (`10.119.160.3`). No public endpoint by design — exposure is via the IAP bastion VM (`cc-bastion`)
- The bastion uses Workload Identity, no SA key
- The tunnel works with **DBeaver** and any standard PostgreSQL client (just point at `127.0.0.1:5434`)
- Full infra context: `infra/INFRASTRUCTURE.md`

## Related files

- Sync script: `backend/scripts/sync_from_gcp.py`
- Bastion Terraform: `infra/terraform/bastion.tf`
- Cloud SQL Terraform: `infra/terraform/cloudsql.tf`
- Full infra reference: `infra/INFRASTRUCTURE.md`
