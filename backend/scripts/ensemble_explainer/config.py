"""Configuration constants for the ensemble explainer wrapper.

The job is a thin wrapper around the legacy DBAnalysisEngine. The constants
here are the few values the wrapper itself needs (algorithm version identity
for the pre-flight check, logging format). All other knobs (LLM model, prompts,
output schema, max-tokens, temperatures) live in scripts.daily_analysis and
are inherited by reusing that engine.
"""

from __future__ import annotations

# Identity of the ensemble algorithm version this wrapper targets. Used by the
# pre-flight check in main.py to confirm cc-ensemble-compute has populated the
# ensemble row before invoking the engine.
ALGORITHM_NAME = "ensemble_v1_softgate_wrapper"
ALGORITHM_VERSION = "1.0.0"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
