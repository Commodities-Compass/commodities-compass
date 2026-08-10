"""Tunable knobs for the `judge` overlay.

Every policy threshold lives here, NOT in the prompt — so the fusion behaviour
is auditable and re-tunable without re-prompting the LLM. Change a number here,
re-run the tests, and the golden fixture tells you what moved.
"""

from __future__ import annotations

from typing import Final

# --- Fusion thresholds (see judge/policy.py) ---------------------------------
# Overriding the base algorithm's *direction* (flip, or commit from MONITOR) is
# a strong claim -> high bar. Abstaining (-> MONITOR) is cheap -> lower bar.
FLIP_CONF_MIN: Final[int] = 4          # judge confidence needed to flip / commit
MONITOR_CONFLICT_CONF: Final[int] = 3  # contradiction strong enough to abstain
IGNORE_CONF_MAX: Final[int] = 2        # at/below this, judge is noise -> keep base

# MONITOR fires on genuine CONFLICT, never on quiet. A calm/neutral day keeps the
# base call so commit-rate is preserved (base must commit >= ~50% of the time).
ABSTAIN_ON_QUIET: Final[bool] = False

# --- Brief window ------------------------------------------------------------
BRIEF_WINDOW: Final[int] = 3  # today + 2 prior briefs feed the drift + judge

# --- LLM (prod path) ---------------------------------------------------------
# Pinned for auditability. Not byte-reproducible, but a given (prompt, model)
# is re-runnable and every call is logged.
PROMPT_VERSION: Final[str] = "judge_prompt_v1"
JUDGE_MODEL_ID: Final[str] = "claude-sonnet-4-5-20250929"
JUDGE_TEMPERATURE: Final[float] = 0.0
SELF_CONSISTENCY_DRAWS: Final[int] = 1  # single draw (Hedi's call)
