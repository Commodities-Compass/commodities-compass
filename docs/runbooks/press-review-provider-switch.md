# Press Review Provider Switch — Operational Runbook

## When to use this runbook

Run this when you want to switch the production LLM provider for the daily press review (e.g., `OpenAI o4-mini → Anthropic Claude → Google Gemini`). Typical triggers:

- Quality regression on the current provider (verified via watchlist evaluation)
- Cost optimization (provider pricing change)
- Outage on the current provider, fallback needed for ≥ 1 day
- A/B test results favor a shadow provider

The dashboard displays only one provider at a time, controlled by `pl_fundamental_article.is_active`.

## Pre-requisites

- The new provider has been running in **shadow mode** (writes rows but `is_active = false`) for **≥ 1 week** — verify quality and parsing reliability
- API key for the new provider is in GCP Secret Manager (named `cc-<provider>-api-key`)
- Watchlist evaluation report shows acceptable directional accuracy on the new provider's outputs (see `backend/scripts/watchlist_eval/`)

## Procedure

### Step 1 — Verify shadow mode is healthy

```sql
-- Run via bastion tunnel (see db-sync-from-gcp.md)
SELECT
  llm_provider,
  COUNT(*) AS rows_last_30d,
  COUNT(*) FILTER (WHERE is_active = true) AS active_rows,
  MAX(date) AS latest_date
FROM pl_fundamental_article
WHERE date >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY llm_provider
ORDER BY llm_provider;
```

The new provider must have ~daily rows and a recent `latest_date`. Aborted/empty rows indicate a parsing issue — fix before switching.

### Step 2 — Update `PRODUCTION_PROVIDER` in code

Edit `backend/scripts/press_review_agent/config.py`:

```python
# Change this constant
PRODUCTION_PROVIDER = "<new_provider>"  # one of: 'openai' | 'claude' | 'gemini'
```

Commit:

```bash
git add backend/scripts/press_review_agent/config.py
git commit -m "chore: switch press review production provider to <new_provider>"
git push origin main
```

This deploys via CI/CD. Wait for the Cloud Run Jobs deploy step to finish (~5 min).

### Step 3 — Backfill `is_active` flag in DB

The constant change only affects future articles. Past articles still flagged with the old provider need to be flipped:

```sql
-- Run via bastion tunnel
BEGIN;

-- Flip active flag
UPDATE pl_fundamental_article
SET is_active = false
WHERE llm_provider = '<old_provider>' AND is_active = true;

UPDATE pl_fundamental_article
SET is_active = true
WHERE llm_provider = '<new_provider>'
  AND is_active = false
  AND date >= CURRENT_DATE - INTERVAL '90 days';  -- only flip recent articles

-- Verify before commit
SELECT llm_provider, COUNT(*) FILTER (WHERE is_active) AS active_count
FROM pl_fundamental_article
WHERE date >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY llm_provider;

-- If correct
COMMIT;
-- Else
-- ROLLBACK;
```

### Step 4 — Verify dashboard

1. Open `https://app.com-compass.com/dashboard`
2. The "Revue de presse" card should now display content authored by the new provider
3. Spot-check tone, structure, and any provider-specific quirks
4. Check sentiment gauges (theme_sentiments) populated correctly — they're computed from the active provider's articles

### Step 5 — Monitor for 48h

- Watch Sentry for press review parsing errors tagged with the new provider
- Compare watchlist hit-rate over the next week vs the previous provider
- If quality regresses, follow Rollback below

## Rollback

Revert the provider switch:

```bash
# Code: revert PRODUCTION_PROVIDER to old value, push
git revert <commit_hash>
git push origin main
```

```sql
-- DB: flip is_active back
BEGIN;
UPDATE pl_fundamental_article SET is_active = false WHERE llm_provider = '<new_provider>' AND is_active = true;
UPDATE pl_fundamental_article SET is_active = true  WHERE llm_provider = '<old_provider>'
  AND date >= CURRENT_DATE - INTERVAL '90 days';
COMMIT;
```

Both steps must happen — code-only rollback leaves stale `is_active` rows on the new provider.

## Background

- The press review agent runs all 3 providers in parallel when invoked with `--provider all` (testing). In production, only `PRODUCTION_PROVIDER` is invoked
- `is_active` is the single source of truth for the dashboard. Multiple providers can have rows for the same date, but at most one can be active per (date, contract)
- Each provider has its own pricing, output format quirks, and failure modes. Always shadow-test before promoting

## Related files

- Config: `backend/scripts/press_review_agent/config.py` (`PRODUCTION_PROVIDER` constant)
- LLM provider abstraction: `backend/scripts/press_review_agent/llm_provider.py`
- DB writer: `backend/scripts/press_review_agent/db_writer.py`
- Quality evaluation: `backend/scripts/watchlist_eval/`
