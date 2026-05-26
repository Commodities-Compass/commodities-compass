"""Configuration constants for the ensemble explainer (LLM commentary writer).

This job runs AFTER cc-ensemble-compute (which has written the wrapped decision
to the ensemble row of pl_indicator_daily). The job's role is to enrich that
ensemble row with narrative LLM-generated fields (eco, confidence, direction,
conclusion) by reading the structured ensemble diagnostics + press review +
meteo + recent technicals and producing one human-readable commentary.

The LLM CANNOT modify the decision — it only explains why.
"""

from __future__ import annotations

# Target algorithm version (must already exist in pl_algorithm_version with rows
# in pl_orchestrator_decision + pl_indicator_daily for the target_date).
ALGORITHM_NAME = "ensemble_v1_softgate_wrapper"
ALGORITHM_VERSION = "1.0.0"

# OpenAI model — gpt-4o-mini is cheap, fast (~3s, ~$0.001 per call).
# If we want richer prose, upgrade to gpt-4-turbo (~$0.05 per call).
MODEL_ID = "gpt-4o-mini"
MAX_TOKENS = 2048
TEMPERATURE = 0.6

# Hard caps on output field lengths (truncated client-side before DB write).
ECO_MAX_CHARS = 300
CONCLUSION_MAX_CHARS = 2000

# Confidence is 1..5 inclusive.
CONFIDENCE_MIN = 1
CONFIDENCE_MAX = 5

# Direction enum (matches legacy daily_analysis output_parser).
ALLOWED_DIRECTIONS = ("HAUSSIERE", "BAISSIERE", "NEUTRE")

# Allowed decision values (cross-check against ensemble decision_wrapped).
ALLOWED_DECISIONS = ("OPEN", "HEDGE", "MONITOR")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
