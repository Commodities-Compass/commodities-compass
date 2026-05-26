"""Write LLM commentary fields onto the ensemble row of pl_indicator_daily.

The ensemble row already exists (created by cc-ensemble-compute) with
``decision``, ``conclusion`` (terse auto-generated). This writer UPDATEs only
the LLM-enriched narrative fields:
  - ``eco``
  - ``confidence``
  - ``direction``
  - ``conclusion`` (overwrites the terse one with the LLM richer version)

Scope is locked to ``algorithm_version_id`` = ensemble version. Legacy row is
never touched.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from scripts.ensemble_explainer.output_parser import ExplainerOutput

logger = logging.getLogger(__name__)


class ExplainerWriteError(RuntimeError):
    """Raised when the UPDATE affects 0 rows (ensemble row not present)."""


def update_ensemble_narrative(
    session: Session,
    target_date: date,
    contract_id: Any,
    algorithm_version_id: Any,
    output: ExplainerOutput,
) -> int:
    """UPDATE the ensemble row of pl_indicator_daily with LLM narrative fields.

    Returns the number of rows updated (must be 1, otherwise raises).
    """
    result = session.execute(
        text(
            """
            UPDATE pl_indicator_daily
            SET eco = :eco,
                confidence = :confidence,
                direction = :direction,
                conclusion = :conclusion
            WHERE date = :date
              AND contract_id = :contract
              AND algorithm_version_id = :algo
            """
        ),
        {
            "eco": output.eco,
            "confidence": output.confidence,
            "direction": output.direction,
            "conclusion": output.conclusion,
            "date": target_date,
            "contract": contract_id,
            "algo": algorithm_version_id,
        },
    )
    n = result.rowcount or 0
    if n != 1:
        raise ExplainerWriteError(
            f"UPDATE pl_indicator_daily affected {n} rows for "
            f"date={target_date} contract={contract_id} algo={algorithm_version_id}. "
            "Ensemble row must exist (cc-ensemble-compute should have created it)."
        )
    session.flush()
    logger.info(
        "Updated ensemble narrative for %s contract=%s (confidence=%d direction=%s)",
        target_date,
        contract_id,
        output.confidence,
        output.direction,
    )
    return n
