# Pipeline Phase Contract — Every Scheduled Job Declares Its Calendar

> Origin: 2026-08-30 — `cc-regime-brief` shipped with a DAILY cron and no
> eve-of-trading gate, resolving its session as `MAX(date) FROM pl_regime_shadow`.
> On every non-eve evening `cc-regime-shadow` skipped, the decision table stopped
> advancing, and the brief cheerfully re-briefed the last decided session: two
> fresh LLM calls, an overwrite of the published narrative on the served row, and
> an overwrite of the Drive `.txt` the NotebookLM podcast is cut from. It ran 5
> times in 11 days and logged `SUCCESS — 2 brief(s) uploaded` every time, so every
> monitor stayed green. It only surfaced when a random word choice tripped an
> unrelated leak guard.

## The Principle

The cocoa market has sessions; the cron has days. **Every scheduled job must say
which of the two it obeys** — and that declaration must be mechanical, not prose.

There are exactly two shapes, plus a narrow exemption.

### Phase A — market close

Weekday-only cron (`m h * * 1-5`), keyed to the session that just traded. The
scheduler bounds the run; the job needs no weekend gate. Examples:
`barchart-scraper`, `compute-indicators`, `roll-watchdog`.

### Phase B — next-session refresh

**DAILY cron** (`m h * * *`), because the eve of Monday is a Sunday and the eve of
a post-holiday session is a holiday. Cron cannot express "eve of a trading day",
so **the job owns the gate**:

```python
if phase_b_should_skip(session_date, force):
    return 0                      # clean exit — Sentry cron reads it as success
```

and it derives its dates from `resolve_phase_b_dates()` — `PhaseBDates(target_date,
data_date)` — rather than inventing them. Every Phase-B DB write is keyed to
`data_date`.

### Calendar-exempt

A job that fires on non-trading days *on purpose*. Legitimate, but it must carry a
**written reason someone can review**. "It was already like that" is not one.

## Rules

### 1. A daily cron obliges a gate

If the day-of-week field is `*`, the job **will** run on Saturdays, Sundays and
exchange holidays. It must therefore be listed in `backend/scripts/_shared/phases.py`
— either in `PHASE_B_JOBS` (and actually call `phase_b_should_skip`) or in
`CALENDAR_EXEMPT_JOBS` with a reason. `tests/test_pipeline_phase_contract.py`
enforces this by parsing `infra/terraform/scheduler.tf`: **a new daily job that
declares nothing fails the build.**

### 2. "Which session" is not "whether to run"

The defect that caused this rule was a *correct* answer to the wrong question.
`_resolve_session_date` reasoned: *"the brief speaks for a decision, so it can only
exist where that decision does"* → anchor on `MAX(date)`. Sound for **which**
session. But by decoupling from the calendar it silently also answered **when to
run**, and deleted the gate.

Any resolver of the form `MAX(date)` / `latest row` / `most recent decision`
answers **which**. It never answers **whether**. Both questions need an explicit
answer, and the second one belongs to the calendar.

### 3. A job that re-processes an already-published session is a bug

Briefs, narratives and podcast source files for past sessions are **frozen
published editions** (same rule as `docs/runbooks/contract-roll-procedure.md`:
never regenerate a past brief). Re-running a producer over a session that already
has output must be an explicit operator act (`--session-date` / `--force`), never
something a cron does on its own.

### 4. Success is not evidence

This ran for 11 days reporting `SUCCESS`. Exit 0 and a green Sentry cron monitor
mean "the code did not crash" — they never mean "the job did the right work".
When a job's output is keyed to a date, the date it chose is part of what must be
observable: **log the resolved session, and make the phase contract a test**.

## When to check

Before merging **any** of: a new Cloud Run job · a new `scheduler.tf` entry · a
change to a cron expression · a change to how a job resolves its session date ·
splitting or merging pipeline jobs.

Ask: *on a Saturday evening, or the eve of a holiday, what does this job do?*
If the answer is not "exits 0 without writing", it needs a gate or an exemption.
