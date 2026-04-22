# Pipeline Error Handling — Fail Loud, No Silent Recovery

> Origin: 2026-04-22 — press review agent returned malformed JSON from OpenAI. Temptation was to add auto-retry with a fallback provider. Rejected: silent recovery masks root causes and erodes trust in pipeline output.

## The Principle

Pipeline agents (scrapers, LLM agents, compute jobs) must **fail loud and stop**. The recovery path is always: diagnose → fix root cause → manual relaunch. Never auto-recover in a way that hides the original failure.

## Rules

### 1. No automatic retry or provider fallback

If an LLM call fails (bad JSON, API error, timeout), the agent logs the error and exits with a non-zero code. It does NOT:
- Retry the same provider silently
- Fall back to a different provider automatically
- Degrade to partial output without explicit logging

**Why**: Auto-retry masks flaky prompts, bad parsing, and upstream API regressions. If OpenAI returns garbage JSON today, it'll do it again tomorrow — the fix is hardening the parser or the prompt, not papering over it with a retry.

### 2. No silent error swallowing

Every error must be:
- Logged at ERROR level with enough context to reproduce
- Reported to Sentry with structured context
- Reflected in the exit code (non-zero = something failed)

Never `except: pass`. Never `try/except` that converts an error into a default value without logging.

### 3. Graceful degradation is for CONSUMERS, not PRODUCERS

Downstream consumers (daily analysis, compass brief, dashboard) MAY degrade gracefully when upstream data is missing — e.g., running with an empty press review. This is correct because the consumer didn't fail; its input was incomplete.

But the **producer** that failed (press review agent) must NOT try to produce partial or fallback output. It either succeeds fully or fails fully.

### 4. Manual relaunch is the recovery path

When a pipeline job fails:
1. Diagnose from logs (Cloud Run execution logs, Sentry)
2. Fix the root cause (code, prompt, parser, infra)
3. Deploy if needed
4. Manually relaunch the failed job + any downstream jobs that ran with degraded input

```bash
# Example: relaunch press review + downstream
gcloud run jobs execute cc-press-review-agent --region=europe-west9 --project=cacaooo
# Wait for completion, then:
gcloud run jobs execute cc-daily-analysis --region=europe-west9 --project=cacaooo
gcloud run jobs execute cc-compass-brief --region=europe-west9 --project=cacaooo
```

## When to check

Before adding any `retry`, `fallback`, `max_retries`, or `backoff` logic to a pipeline agent — stop and ask: "Am I fixing the root cause, or am I hiding it?"
