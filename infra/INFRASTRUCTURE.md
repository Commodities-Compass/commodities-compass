# Infrastructure — GCP / Terraform

> Provisioned 2026-03-12 (Phase 0.2). Terraform manages the platform layer.
> Cloud Run services are deployed by GitHub Actions (`deploy.yml`), not Terraform.

## GCP Project

| Key | Value |
|-----|-------|
| Project ID | `cacaooo` |
| Project Number | `229076583962` |
| Organization | `710889932` |
| Region | `europe-west9` (Paris) |
| TF State | `gs://tf-state-cacaooo` (versioning enabled) |

## Architecture Overview

```
                  GitHub Actions (OIDC)
                         │
                    WIF Provider
                         │
                  ┌──────▼──────┐
                  │  Artifact   │
                  │  Registry   │
                  └──────┬──────┘
                         │ docker push/pull
           ┌─────────────┼─────────────┐
           │             │             │
     ┌─────▼─────┐ ┌────▼────┐ ┌─────▼──────┐
     │ Cloud Run │ │Cloud Run│ │ Cloud Run  │
     │  Backend  │ │Frontend │ │   Jobs     │
     │(cc-api SA)│ │         │ │(cc-jobs SA)│
     └─────┬─────┘ └─────────┘ └─────┬──────┘
           │                          │
           │    VPC Connector         │
           │   (cc-vpc-connector)     │
           └──────────┬───────────────┘
                      │
              ┌───────▼────────┐
              │   cc-vpc       │
              │  10.0.0.0/24   │
              │  (private IP)  │
              └───────┬────────┘
                      │ PSA Peering
              ┌───────▼────────┐
              │  Cloud SQL     │
              │  cc-postgres   │
              │  PG15 priv only│
              └───────┬────────┘
                      │ private IP (10.119.160.3)
              ┌───────▼────────┐
              │  cc-bastion    │
              │  e2-micro      │
              │  (no public IP)│
              └───────┬────────┘
                      │ IAP TCP tunnel (SSH)
              ┌───────▼────────┐
              │  Local Dev     │
              │ (psql/DBeaver) │
              └────────────────┘
```

## Terraform Files

```
infra/terraform/
├── main.tf              # Provider, backend, 14 API enablements
├── variables.tf         # All variable declarations
├── terraform.tfvars     # Non-sensitive values (committed)
├── vpc.tf               # VPC, subnet, PSA, VPC connector
├── cloudsql.tf          # Cloud SQL PG15, database, user
├── bastion.tf           # IAP bastion VM (e2-micro) + firewall rule
├── artifact_registry.tf # Docker repo + cleanup policies
├── secrets.tf           # Secret Manager (13 secrets)
├── iam.tf               # 3 service accounts + IAM bindings
├── wif.tf               # Workload Identity Federation (GitHub OIDC)
├── scheduler.tf         # 8 cron jobs (active, 19:00-19:30 UTC)
├── monitoring.tf        # Email alerts: Cloud SQL, Job failures, 5xx, uptime
├── outputs.tf           # Key outputs + github_vars map
└── .terraform.lock.hcl  # Provider pinning (committed)
```

## Resources (67 total)

### Networking (`vpc.tf`)

| Resource | Name | Details |
|----------|------|---------|
| VPC | `cc-vpc` | Custom, no auto-subnets |
| Subnet | `cc-vpc-subnet` | `10.0.0.0/24`, private Google access |
| PSA Range | `cc-private-ip-range` | `/20` internal for Cloud SQL peering |
| PSA Connection | — | Peers Google-managed VPC with ours |
| VPC Connector | `cc-vpc-connector` | `10.8.0.0/28`, 200-300 Mbps |

### Database (`cloudsql.tf`)

| Resource | Name | Details |
|----------|------|---------|
| Instance | `cc-postgres` | PG15, `db-f1-micro`, ZONAL, **private IP only** |
| Database | `commodities_compass` | — |
| User | `cc_app` | 32-char random password (no special chars) |
| Private IP | `10.119.160.3` | Cloud Run connects via VPC connector, local dev via bastion |

### Bastion (`bastion.tf`)

| Resource | Name | Details |
|----------|------|---------|
| VM | `cc-bastion` | e2-micro (free tier), COS-stable, no public IP, shielded |
| SA | `cc-bastion` | Logging only — no DB or secret access |
| Firewall | `cc-allow-iap-ssh` | IAP range `35.235.240.0/20` → port 22, bastion tag |

The bastion provides a secure tunnel from developer machines to the private Cloud SQL instance via IAP. See [Local Development Access](#local-development-access) for usage.

- 10GB SSD, autoresize enabled
- SSL: `ENCRYPTED_ONLY` (all connections must use TLS)
- Backups at 03:00 UTC, 7 days retention, no PITR
- Maintenance: Sunday 04:00 UTC, stable track
- `deletion_protection = true`
- Flags: `log_checkpoints`, `log_connections`, `log_disconnections`

### Artifact Registry (`artifact_registry.tf`)

| Resource | Name | Details |
|----------|------|---------|
| Docker Repo | `commodities-compass` | DOCKER format, europe-west9 |

- Cleanup: keep latest 10 tagged, delete untagged > 7 days

### Secret Manager (`secrets.tf`)

13 secrets, single replica `europe-west9`:

| Secret | Source |
|--------|--------|
| `DATABASE_URL` | Auto-computed by Terraform (`postgresql+asyncpg://...`) |
| `DATABASE_SYNC_URL` | Auto-computed by Terraform (`postgresql+psycopg2://...`) |
| `AUTH0_DOMAIN` | Manual |
| `AUTH0_CLIENT_ID` | Manual |
| `AUTH0_API_AUDIENCE` | Manual |
| `AUTH0_ISSUER` | Manual |
| `GOOGLE_SHEETS_CREDENTIALS_JSON` | Manual |
| `GOOGLE_SHEETS_SCRAPER_CREDENTIALS_JSON` | Manual |
| `GOOGLE_DRIVE_CREDENTIALS_JSON` | Manual (SA for Drive audio + brief upload) |
| `SENTRY_DSN` | Manual |
| `ANTHROPIC_API_KEY` | Manual |
| `OPENAI_API_KEY` | Manual |
| `GEMINI_API_KEY` | Manual |

### IAM (`iam.tf`)

| Service Account | Purpose | Key Roles |
|----------------|---------|-----------|
| `cc-cloud-run-api` | Backend + Frontend Cloud Run | secretmanager.secretAccessor, cloudsql.client, logging.logWriter, monitoring.metricWriter |
| `cc-cloud-run-jobs` | Scrapers, Agents | Same as API + **run.developer** (required for Cloud Scheduler to trigger job executions) |
| `cc-github-actions` | CI/CD deploy | artifactregistry.writer, run.admin, iam.serviceAccountUser, secretmanager.secretAccessor |
| `cc-bastion` | IAP bastion VM | logging.logWriter (minimal — tunnel only, no DB creds) |

### Workload Identity Federation (`wif.tf`)

| Resource | Value |
|----------|-------|
| Pool | `github-actions` |
| Provider | `github-oidc` (OIDC issuer: `token.actions.githubusercontent.com`) |
| Condition | `assertion.repository == 'Commodities-Compass/commodities-compass'` |

Keyless auth: GitHub OIDC token exchanged for short-lived GCP access token at each workflow run.

### Load Balancer (`loadbalancer.tf`)

Global HTTPS LB routing custom domains to Cloud Run services. Required because Cloud Run domain mappings are not supported in `europe-west9`.

| Resource | Value |
|----------|-------|
| Static IP | `34.36.87.103` (`cc-lb-ip`) |
| SSL certs | `cc-ssl-app` (app.com-compass.com), `cc-ssl-api` (api.com-compass.com) — Google-managed, auto-renew |
| Frontend NEG | `cc-neg-frontend` → Cloud Run `frontend` |
| Backend NEG | `cc-neg-backend` → Cloud Run `backend` |
| URL map | Host-based: `app.*` → frontend, `api.*` → backend |
| HTTP redirect | Port 80 → 301 → HTTPS (port 443) |
| Cost | ~$18/mo (forwarding rule) |

DNS (Squarespace Domains): A records `app` and `api` → `34.36.87.103`.

### Cloud Scheduler (`scheduler.tf`)

8 cron jobs, **all active** since 2026-03-30.
Region: `europe-west1` (europe-west9 not supported for Scheduler).
Timezone: UTC. Pipeline starts ~1.5h after ICE Europe close (17:30 London).

| Job | Schedule (UTC) | Stage |
|-----|---------------|-------|
| `cc-barchart-scraper` | `0 19 * * 1-5` | 1 — scrapers (parallel) |
| `cc-ice-stocks-scraper` | `0 19 * * 1-5` | 1 |
| `cc-cftc-scraper` | `0 19 * * 1-5` | 1 |
| `cc-press-review-agent` | `0 19 * * 1-5` | 1 — agents (parallel) |
| `cc-meteo-agent` | `0 19 * * 1-5` | 1 |
| `cc-compute-indicators` | `15 19 * * 1-5` | 2 — compute (needs scraper data) |
| `cc-daily-analysis` | `20 19 * * 1-5` | 3 — analysis (needs indicators) |
| `cc-compass-brief` | `30 19 * * 1-5` | 4 — brief (needs everything) |

HTTP targets invoke Cloud Run Jobs execution API. OAuth token via `cc-cloud-run-jobs` SA (requires `run.developer` role).

### Monitoring (`monitoring.tf`)

| Resource | Details |
|----------|---------|
| Notification Channel | Email to CTO |
| Alert: Cloud SQL Down | Instance `cc-postgres` down > 5 min |
| Alert: Cloud Run Job Failed | Any job execution failure |
| Alert: Backend 5xx Errors | > 5 server errors in 5 min |
| Alert: Backend Uptime | `/health` endpoint unresponsive > 5 min |
| Uptime Check | HTTPS GET `backend-*.run.app/health` every 5 min |

## GitHub Repository Variables

Set via `gh variable set`, used by `deploy.yml`:

| Variable | Used by | Value |
|----------|---------|-------|
| `GCP_PROJECT_ID` | Deploy infra | `cacaooo` |
| `GCP_REGION` | Deploy infra | `europe-west9` |
| `GCP_WIF_PROVIDER` | Deploy auth | `projects/229076583962/locations/global/...` |
| `GCP_SA_EMAIL` | Deploy auth | `cc-github-actions@cacaooo.iam.gserviceaccount.com` |
| `AUTH0_DOMAIN` | Frontend build | `dev-1vqq5xiywmfinkgk.us.auth0.com` |
| `AUTH0_CLIENT_ID` | Frontend build | SPA client ID |
| `AUTH0_API_AUDIENCE` | Frontend build | `https://api.commodities-compass.com` |
| `AUTH0_ISSUER` | Frontend build | `https://dev-1vqq5xiywmfinkgk.us.auth0.com/` |
| `FRONTEND_URL` | Frontend build (redirect_uri) | `https://app.com-compass.com` |
| `API_BASE_URL` | Frontend build (Axios baseURL) | `https://api.com-compass.com/v1` |
| `GOOGLE_DRIVE_AUDIO_FOLDER_ID` | Cloud Run env vars | Drive folder ID |
| `GOOGLE_DRIVE_BRIEFS_FOLDER_ID` | Cloud Run env vars | Drive briefs folder ID |
| `BACKEND_CORS_ORIGINS` | Backend env var | `https://app.com-compass.com` |

## Operations

### Run Terraform

```bash
cd infra/terraform
terraform init          # first time or after provider changes
terraform plan          # preview changes
terraform apply         # apply (requires confirmation)
terraform output        # show outputs
terraform output -json github_vars  # GitHub vars to copy
```

### Populate a Secret

```bash
echo -n "value" | gcloud secrets versions add SECRET_NAME --data-file=-
gcloud secrets versions access latest --secret=SECRET_NAME  # verify
```

### Verify Infrastructure

```bash
gcloud compute networks describe cc-vpc
gcloud sql instances describe cc-postgres
gcloud secrets list --filter="name:projects/cacaooo"
gcloud iam service-accounts list --filter="email:cc-*"
gcloud scheduler jobs list --location=europe-west1
```

## Local Development Access

### Cloud SQL (production — private IP only)

The instance has **no public IP** — all access is via the private VPC. Developer machines reach it through an IAP TCP tunnel via the `cc-bastion` VM.

**Prerequisites (one-time):**
```bash
gcloud auth application-default login
```

**Step 1 — Start the IAP tunnel (in a dedicated terminal):**
```bash
gcloud compute ssh cc-bastion --zone europe-west9-a --tunnel-through-iap \
  --project cacaooo -- -N -L 5434:10.119.160.3:5432
```

This forwards `localhost:5434` → Cloud SQL private IP via the bastion. Keep this terminal open.

**Step 2 — Connect via psql:**
```bash
psql -h 127.0.0.1 -p 5434 -U cc_app -d commodities_compass
```

**DBeaver / GUI client:**

| Field | Value |
|-------|-------|
| Host | `127.0.0.1` |
| Port | `5434` |
| Database | `commodities_compass` |
| User | `cc_app` |
| Password | *(in Terraform state — see below)* |
| SSL | Disabled (tunnel handles encryption) |

**Retrieve password:**
```bash
cd infra/terraform
terraform state pull | python3 -c "
import json, sys
state = json.load(sys.stdin)
for r in state['resources']:
    if r.get('type') == 'google_sql_user' and r.get('name') == 'app':
        print(r['instances'][0]['attributes']['password'])
        break
"
```

**Sync GCP to local DB:**
```bash
# With IAP tunnel running on port 5434:
GCP_DATABASE_URL=postgresql+psycopg2://cc_app:<password>@localhost:5434/commodities_compass \
  poetry run python scripts/sync_from_gcp.py
```

**How it works:**
- `cc-bastion` is an e2-micro VM (free tier) inside `cc-vpc` with no public IP
- IAP authenticates with your Google account (IAM-based, no SSH keys to manage)
- The bastion simply forwards TCP — it has no database credentials
- Firewall rule `cc-allow-iap-ssh` only allows traffic from IAP's IP range (`35.235.240.0/20`)

**Troubleshooting:**
- `invalid_grant` / `invalid_rapt` → re-run `gcloud auth application-default login`
- `address already in use` on port 5434 → `kill $(lsof -i :5434 -t)` then retry
- First connection may be slow (SSH key generation + metadata propagation)

### Railway (DECOMMISSIONED)

Railway crons paused since 2026-03-30. Google Sheets ETL removed. All data flows through GCP Cloud Run Jobs → PostgreSQL.

## Cost Estimate

| Resource | $/mo |
|----------|------|
| Cloud SQL db-f1-micro + 10GB SSD + backups | ~$10 |
| VPC Connector (min throughput) | ~$7 |
| Bastion e2-micro (free tier eligible) | ~$0 |
| Artifact Registry | ~$0.50 |
| Secret Manager (13 secrets) | ~$0.10 |
| Cloud Scheduler (8 jobs) | ~$0.30 |
| Cloud Run (backend + frontend + jobs) | ~$5-15 |
| Monitoring | $0 |
| **Total** | **~$23-33/mo** |

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Flat files, no modules | Single env, single region | Modules add indirection unjustified at this stage |
| Cloud SQL `db-f1-micro` | 353 rows, 1 user | Upgrade via `db_tier` variable |
| Cloud SQL ZONAL | No HA | Doubles cost, no business justification yet |
| Cloud SQL private IP only | No public IP — hardened in Phase 5 | Cloud Run uses VPC connector; local dev uses IAP bastion tunnel |
| IAP bastion (e2-micro) | Zero-cost secure access to private DB | IAM-authenticated, no public IP on bastion, no SSH keys to rotate |
| 2 runtime SAs | `cc-api` + `cc-jobs` | Audit separation, future per-secret scoping |
| Cloud Run outside TF | GitHub Actions deploys | Intentional boundary — TF owns platform, GHA owns app |
| `disable_on_destroy = false` | All API enablements | Prevents accidental API disable breaking other services |
| `.terraform.lock.hcl` committed | Provider pinning | Reproducible builds across machines |
| Scheduler in `europe-west1` | europe-west9 not supported | Only affects cron trigger location, not job execution |

## Caveats

1. **Cloud SQL takes ~12 min** to provision on first `terraform apply`
2. **PSA peering takes ~5-10 min** — dependency chain handles ordering
3. **WIF attribute condition is case-sensitive** — `Commodities-Compass/commodities-compass` must match exactly
4. **db-f1-micro has 614 MB RAM** — sufficient for 353 rows / 1 user, watch for OOM on heavy Alembic migrations
5. **No Redis/Memorystore** — `REDIS_URL` is declared in config but never imported in `app/`, dev-only dependency
