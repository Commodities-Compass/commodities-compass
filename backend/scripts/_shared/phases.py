"""Which calendar contract each scheduled job obeys — the pipeline's phase registry.

The pipeline has two shapes, and every scheduled job is one of them:

**Phase A — market close.** Weekday-only cron (``* * 1-5``), keyed to the session
that just traded. The scheduler itself bounds the run; the job needs no gate for
weekends.

**Phase B — next-session refresh.** DAILY cron, because the eve of Monday is a
Sunday and the eve of a post-holiday session is a holiday. The scheduler cannot
express "eve of a trading day", so **the job owns the gate**: it calls
``phase_b_should_skip()`` and exits 0 cleanly when tomorrow is not a session, and
it derives its dates from ``resolve_phase_b_dates()`` rather than inventing them.

Why this file exists: ``cc-regime-brief`` shipped daily and ungated (2026-08-19,
PR #98), resolving its session as ``MAX(date) FROM pl_regime_shadow``. On every
non-eve evening the decision table stood still and the brief re-processed the
last decided session — burning LLM calls and overwriting an already-published
narrative and Drive brief, while reporting ``SUCCESS``. The invariant existed
only in prose, so nothing caught it.

``tests/test_pipeline_phase_contract.py`` turns this registry into a build-time
check: a job whose cron can fire on a non-trading day must appear in one of the
two collections below, and a Phase-B job must actually call the gate.

See .claude/rules/pipeline-phase-contract.md
"""

from __future__ import annotations

# Jobs that MUST call phase_b_should_skip() in their entry point AND be
# scheduled daily. Keyed by the Terraform/Cloud-Run job name (without the "cc-"
# prefix), which is also the module directory once dashes become underscores.
PHASE_B_JOBS = frozenset(
    {
        "press-review-agent",
        "meteo-agent",
        "regime-shadow",
        "regime-brief",
    }
)

# Jobs that fire on non-trading days ON PURPOSE. Each needs a reason someone can
# review — "it was already like that" is not one.
CALENDAR_EXEMPT_JOBS: dict[str, str] = {
    "publish-session": (
        "The publication gate itself. It polls every 30 min from the evening "
        "through 09:30 the next morning precisely to catch a session becoming "
        "complete (data + audio) outside session hours, and it is idempotent — "
        "it stamps pl_session_release once. Gating it on the trading calendar "
        "would defeat the morning fallback that stops a late podcast from "
        "freezing the dashboard."
    ),
    "billing-watchdog": (
        "Billing has no session dimension: a card expires on a Sunday, and "
        "Stripe retries a failed debit whenever its own schedule says so. The "
        "job's 26h look-back is calibrated to a DAILY cadence — a weekday-only "
        "cron would silently drop every failure landing Friday evening through "
        "Sunday, and the first off-session refusal is the only early warning "
        "that an issuer rejects merchant-initiated transactions."
    ),
    "billing-purge": (
        "Enforces the 18-month retention the privacy policy publishes (§3 "
        "ligne 5). A legal deadline runs on the civil calendar, not the "
        "exchange one — skipping weekends would over-retain identifying "
        "payload past a date we committed to in writing. Idempotent by "
        "construction: a day with nothing past retention is a clean exit 0."
    ),
    "enso-scraper": (
        "Monthly (20th at 22:00 UTC) and NOT session-keyed: NOAA publishes ONI "
        "and Nino 3.4 per calendar month into pl_external_indicator, which the "
        "engine joins with a 14-day backward lag at compute time. The 20th can "
        "fall on a weekend; running then is correct, because the data has no "
        "trading-session dimension to be wrong about."
    ),
}


def main_module_for(job_name: str) -> str:
    """Entry-point path, relative to ``backend/scripts``, for a scheduler job name."""
    return f"{job_name.replace('-', '_')}/main.py"
