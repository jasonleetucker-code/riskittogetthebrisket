"""Canonical valuation engine used by the live pipeline.

The offline canonical-build path (``src.canonical.transform`` +
``src.canonical.pipeline`` + ``scripts/canonical_build.py``) has been
retired — the live ``/api/data`` contract and ``/api/trade/suggestions``
endpoint now own the full valuation flow through
``src.api.data_contract._compute_unified_rankings``.  What remains in
``src.canonical`` is the scope-level Hill curves + the ``run_valuation``
pipeline used by ``data_contract.py``.
"""
from .player_valuation import (
    run_valuation,
    build_player_inputs_from_raw_records,
    build_player_inputs_from_record_objects,
    valuation_result_to_asset_dicts,
    PlayerInput,
    PlayerValuation,
    ValuationResult,
)

__all__ = [
    "run_valuation",
    "build_player_inputs_from_raw_records",
    "build_player_inputs_from_record_objects",
    "valuation_result_to_asset_dicts",
    "PlayerInput",
    "PlayerValuation",
    "ValuationResult",
]
