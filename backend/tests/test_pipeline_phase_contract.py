"""Every scheduled job must declare which calendar contract it obeys.

Origin: 2026-08-30. ``cc-regime-brief`` shipped (PR #98) with a DAILY cron and no
eve-of-trading gate, while resolving its session as ``MAX(date) FROM
pl_regime_shadow``. On every non-eve evening ``cc-regime-shadow`` skipped, the
decision table stopped advancing, and the brief happily re-briefed the LAST
decided session — 2 fresh LLM calls, an overwrite of the published narrative in
``pl_indicator_daily`` and an overwrite of the Drive ``.txt`` that feeds the
NotebookLM podcast. It ran 5 times in 11 days and reported ``SUCCESS`` every
time, so no monitor ever went red.

It slipped through because nothing *structurally* tied "this job has a daily
cron" to "this job must own a calendar gate". CLAUDE.md asserted the invariant
in prose and the code simply did not honour it.

These tests make the invariant mechanical:

* a job whose cron can fire on a non-trading day MUST be classified — either it
  owns the Phase-B gate, or it is explicitly exempt with a written reason;
* a job classified Phase-B MUST actually call ``phase_b_should_skip`` in its
  entry point, and MUST be scheduled daily (a weekday-only cron never sees the
  Sunday eve that Phase B exists to catch).

Adding a new daily job without classifying it fails here, by construction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts._shared.phases import (
    CALENDAR_EXEMPT_JOBS,
    PHASE_B_JOBS,
    main_module_for,
)

_SCHEDULER_TF = (
    Path(__file__).resolve().parents[2] / "infra" / "terraform" / "scheduler.tf"
)
_SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"


def _scheduled_jobs() -> dict[str, str]:
    """job name -> cron expression, parsed from the Terraform source of truth."""
    text = _SCHEDULER_TF.read_text(encoding="utf-8")
    jobs: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        opened = re.match(r"^    ([a-z0-9-]+) = \{", line)
        if opened:
            current = opened.group(1)
        sched = re.search(r'^\s*schedule\s*=\s*"([^"]+)"', line)
        if sched and current:
            jobs[current] = sched.group(1)
            current = None
    return jobs


def _fires_on_non_trading_days(cron: str) -> bool:
    """True when the day-of-week field is unrestricted.

    Such a cron fires on Saturdays, Sundays and exchange holidays, so the job
    itself must decide whether that run is meaningful. A ``1-5`` cron is already
    bounded by the scheduler and needs no in-code gate for weekends (holidays
    are handled per-job where relevant).
    """
    fields = cron.split()
    return len(fields) == 5 and fields[4].strip() == "*"


def test_scheduler_is_parseable():
    jobs = _scheduled_jobs()
    assert len(jobs) >= 15, (
        f"parsed only {len(jobs)} jobs — did scheduler.tf change shape?"
    )


class TestEveryDailyJobIsClassified:
    def test_no_unclassified_daily_job(self):
        """A new daily-cron job must declare its phase. This is the guard."""
        unclassified = sorted(
            name
            for name, cron in _scheduled_jobs().items()
            if _fires_on_non_trading_days(cron)
            and name not in PHASE_B_JOBS
            and name not in CALENDAR_EXEMPT_JOBS
        )
        assert not unclassified, (
            "These jobs fire on non-trading days but declare no calendar contract: "
            f"{unclassified}. Add each to PHASE_B_JOBS (and call phase_b_should_skip "
            "in its main) or to CALENDAR_EXEMPT_JOBS with a written reason. "
            "See .claude/rules/pipeline-phase-contract.md"
        )

    def test_exemptions_carry_a_reason(self):
        for name, reason in CALENDAR_EXEMPT_JOBS.items():
            assert reason and len(reason) > 30, (
                f"{name} is calendar-exempt but its reason is too thin to review: {reason!r}"
            )


class TestPhaseBJobsOwnTheGate:
    @pytest.mark.parametrize("job", sorted(PHASE_B_JOBS))
    def test_main_calls_phase_b_should_skip(self, job: str):
        """The regime-brief defect: declared Phase B, never gated."""
        module = _SCRIPTS_ROOT / main_module_for(job)
        assert module.is_file(), f"{job}: no entry point at {module}"
        source = module.read_text(encoding="utf-8")
        assert "phase_b_should_skip(" in source, (
            f"{job} is a Phase-B job but {module.name} never calls phase_b_should_skip(). "
            "Without it the job runs on non-eve evenings and re-processes the last "
            "session it can find. See .claude/rules/pipeline-phase-contract.md"
        )

    @pytest.mark.parametrize("job", sorted(PHASE_B_JOBS))
    def test_is_scheduled_daily(self, job: str):
        """A weekday-only cron never sees the Sunday eve Phase B exists for."""
        cron = _scheduled_jobs().get(job)
        assert cron is not None, f"{job} is declared Phase B but has no scheduler entry"
        assert _fires_on_non_trading_days(cron), (
            f"{job} is Phase B but its cron {cron!r} restricts the day-of-week. "
            "Phase B must fire daily; the in-code gate decides whether to run."
        )

    def test_a_job_cannot_be_both_gated_and_exempt(self):
        overlap = sorted(PHASE_B_JOBS & set(CALENDAR_EXEMPT_JOBS))
        assert not overlap, f"declared both Phase-B and exempt: {overlap}"
