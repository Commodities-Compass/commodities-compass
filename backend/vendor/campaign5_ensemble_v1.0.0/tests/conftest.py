"""Shared pytest fixtures + sys.path bootstrap.

The tests live under ``tests/`` inside the deliverable, so they need the
``ensemble`` package on ``sys.path``. Inserting the deliverable root one level
up makes ``import ensemble`` work without installing the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DELIVERABLE_ROOT = Path(__file__).resolve().parents[1]
if str(_DELIVERABLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_DELIVERABLE_ROOT))
