"""Thin shim — R&D forwards to ``methodology.data_loader``, prod raises.

The ``maximal`` feature panel (used by ``exp_optim_017_bull_8``) needs the
canonical 10y dataset at training time so it can enumerate every numeric
column as a feature spec. R&D's data loader lives in the parent
``methodology/`` package and reads from the local Parquet snapshot. Production
NEVER calls this code path during inference (the pickled candidates already
carry their ``_feature_specs``); production CAN call it during the monthly
retrain of the maximal-panel specialist, in which case prod must override
this module with its own implementation that reads from ``pl_contract_data_daily``.

Inside R&D, the import succeeds transparently via ``methodology.data_loader``.
In a clean prod environment with no ``methodology`` package, ``load_dataset``
raises a clear, actionable error.
"""

from __future__ import annotations

from typing import Any

try:
    from methodology import data_loader as _rd_loader  # type: ignore[import-not-found]
except ImportError:
    _rd_loader = None


def load_dataset(*args: Any, **kwargs: Any):
    if _rd_loader is None:
        raise NotImplementedError(
            "ensemble.data_loader.load_dataset is an R&D-only shim. "
            "Production code calling it during a maximal-panel monthly retrain "
            "MUST replace this module with an implementation backed by "
            "pl_contract_data_daily."
        )
    return _rd_loader.load_dataset(*args, **kwargs)
