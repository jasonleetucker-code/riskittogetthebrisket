"""Canonical curve, tiering and calibration primitives.

The offline canonical-build path (``src.canonical.transform`` +
``src.canonical.pipeline`` + ``scripts/canonical_build.py``) has been
retired — the live ``/api/data`` contract and ``/api/trade/suggestions``
endpoint now own the full valuation flow through
``src.api.data_contract._compute_unified_rankings``.

Its engine (``player_valuation.run_valuation`` and the ``PlayerInput`` /
``PlayerValuation`` / ``ValuationResult`` dataclasses and adapter
bridges it needed) outlived that path with no production caller and was
deleted on 2026-07-29; this package no longer re-exports it.  Do not
confuse it with the live ``src.bdvm.service.run_valuation``, which is a
different function belonging to the BDVM fundamental-value engine.

What remains in ``src.canonical`` are the shared primitives the live
pipeline imports directly from their own modules — this ``__init__``
intentionally exports nothing, so importing the package has no side
effects and no name is offered that lacks a live consumer:

* ``player_valuation`` — the rank-form and percentile-form Hill curves
  (``rank_to_value``, ``rank_to_value_for_scope``,
  ``percentile_to_value``) plus scope-level curve constants and
  rank-gap tier detection (``detect_tiers``).  Consumed by
  ``src.api.data_contract`` (percentile curves + ``detect_tiers``),
  ``src.api.rank_history`` and ``src.api.terminal``
  (``rank_to_value_for_scope`` fallbacks), ``src.model_registry``
  (reads/writes the eight percentile constants) and the offline fit /
  backtest scripts.
* ``calibration`` — legacy display-scale helpers; ``to_display_value``
  is consumed by ``src.trade.suggestions``.
* ``idp_backbone`` — consumed by ``src.api.data_contract``.
* ``normalization_validator`` — consumed by ``server.py``.

Not audited as part of the 2026-07-29 dead-code pass, and flagged here
rather than silently vouched for: ``confidence_intervals`` and
``rank_history_band`` currently have NO production importer — only
tests reference them.  They are gated behind the
``value_confidence_intervals`` feature flag (default off), so treat
them as dormant-pending-decision, not as live code.
"""
