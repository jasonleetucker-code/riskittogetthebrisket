"""Leakage-safe source-quality evaluator and source-weight challengers (Batch 3 B/C).

Evidence only.  Nothing in this package changes a production weight, flag or
value: candidate weights are evaluated through the EXISTING source-override
path (``value_replay.build`` -> ``build_api_data_contract(source_overrides=)``
-> ``_compute_unified_rankings``) and every candidate stays SHADOW.  Promotion
belongs to the model-registry / feature-flag path and a human review.

Modules:

* :mod:`panel` -- point-in-time observation panel from the git history of the
  source CSVs (optionally the temporal ledger), as published, never rebuilt.
* :mod:`metrics` -- leave-the-evaluated-family-out targets, market lead/lag,
  stability/noise, event responsiveness, and the fundamental-foresight and
  transaction-fit seams.
* :mod:`bootstrap` -- seeded date-block bootstrap.
* :mod:`challengers` -- equal-family champion and the predeclared challengers
  (shrunk toward 1.0, capped, family-level).
* :mod:`evaluate` -- walk-forward evaluation, preregistered gates, whole-board
  impact through the override path, archive records.
"""

SCHEMA = "source-quality-eval/v1"
