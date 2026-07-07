# Session Publish Gate — `cc-publish-session`

> How the dashboard's "latest session" flip works, why it's gated, and how to
> operate it. Read alongside [date-semantics.md](../architecture/flows/date-semantics.md).

## What it does

The dashboard's default/newest view is **gated on `pl_session_release`**. A
session (row date `T` = `data_date`) becomes the newest selectable day only once
a row exists in that table. The `cc-publish-session` job stamps it, so the flip
is **atomic** (all sections + the NotebookLM audio at once) and can happen the
**same evening `T`** instead of waiting for the `T+1` calendar date.

Before this gate, `latest_trading_day = MAX(display_date) WHERE display_date <= today()`
surfaced a session only when the UTC calendar reached its `display_date` (the
morning after) — and could briefly show a half-filled session while Phase B was
still writing rows.

## The pieces

| Piece | Where |
|---|---|
| Marker table | `pl_session_release(session_date PK, published_at, has_audio, source)` — migration `a9b8c7d6e5f4` |
| Dashboard gate | `backend/app/api/api_v1/endpoints/dashboard.py` — `non-trading-days` endpoint: `MAX(display_date)` joined to `pl_session_release`, with a **safe fallback** to the old `<= today()` query while the table is empty |
| Publisher job | `backend/scripts/publish_session/main.py` (`poetry run publish-session`) |
| Schedule | `*/30 20-23,0-9 * * *` (scheduler.tf) — every 30 min, evening → 09:30 UTC next morning |

## Release rules (per candidate session `T`)

A candidate = a recent session that has a `pl_indicator_daily` row and no release
row yet. For each:

1. **Normal path** — data fully complete (`pl_indicator_daily` + `pl_fundamental_article` + `pl_weather_observation` for `T`) **and** the served-version audio is present in Drive → release with `has_audio=true`. This fires the same evening, once you upload the NotebookLM audio.
2. **Morning fallback** — if the audio never arrives, release data-only (`has_audio=false`) once we pass `display_date(T)` 09:00 UTC (the morning after `T`'s data lands). Guarantees the dashboard never freezes on yesterday. **The audio still plays when uploaded later** — the audio endpoint fetches Drive independently; `has_audio` is only metadata.
3. Otherwise → skip (wait for audio / completeness).

`display_date(T)` = next trading day, so the deadline lands on the real morning
the data surfaces: Mon session → Tue 09:00 UTC; Fri session (Phase-B rows written
Sunday eve) → Mon 09:00 UTC.

## Operating it

```bash
R="--region=europe-west9 --project=cacaooo --wait"

# Dry-run the decision for the recent window (no writes):
gcloud run jobs execute cc-publish-session $R --args="publish-session,--dry-run,--verbose"

# Force-publish a specific session now (audio-agnostic; data must exist):
gcloud run jobs execute cc-publish-session $R --args="publish-session,--session-date,2026-07-06,--force"
```

Local:
```bash
poetry run publish-session --dry-run --verbose
poetry run publish-session --session-date 2026-07-06        # runs the normal checks
poetry run publish-session --session-date 2026-07-06 --force # release now, audio-agnostic
```

## Rollback / disable

The gate is **non-breaking by construction**: if `pl_session_release` is empty
the dashboard falls back to the legacy `MAX(display_date) <= today()` behavior.

- **Pause the flip** without code changes: pause the scheduler
  (`cc-publish-session`) and `TRUNCATE pl_session_release` — the dashboard
  immediately reverts to next-morning behavior via the fallback.
- **Full rollback**: `alembic downgrade -1` drops the table (via a migration-only
  PR to `main`, per [migrations-prod-via-main-only](../../.claude/rules/migrations-prod-via-main-only.md)); the endpoint's fallback already handles the missing table gracefully once the table is gone only if the code also reverts — so revert the endpoint change in the same PR.

## Verifying a flip

```sql
-- what's released, newest first
SELECT session_date, published_at, has_audio FROM pl_session_release
ORDER BY session_date DESC LIMIT 5;

-- what the dashboard will surface as "latest"
SELECT MAX(cd.display_date)
FROM pl_contract_data_daily cd
JOIN pl_session_release r ON r.session_date = cd.date;
```
