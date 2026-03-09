# Scoring Adjustment Migration Notes (2026-03-09)

## What changed
- Added a modular scoring package under `src/scoring/`.
- Refactored `compute_empirical_lam(...)` to use modular baseline/league config ingestion and scoring delta-map outputs.
- Preserved legacy `_formatFit*` and `_leagueAdjusted` compatibility fields for frontend continuity.

## New artifacts written to `data/`
- `baseline_scoring_config.json`
- `custom_scoring_config.json`
- `scoring_delta_map.json`
- `scoring_backtest_report.json` (via script)

## Compatibility
- Existing market/composite engine remains unchanged.
- Existing final-value pipeline remains backward-compatible.
- Existing frontend fields are preserved; new scoring fields are additive.

## New commands
- Run scoring module tests:
  - `python -m unittest tests.scoring.test_scoring_modules`
- Generate scoring backtest report:
  - `python scripts/backtest_scoring_adjustment.py`

