# Scoring Refactor Checklist (15-Part Prompt)

1. **Repo audit** — Done. See `docs/scoring_adjustment_audit_2026-03-09.md`.
2. **Scoring translation architecture** — Done via `src/scoring/*` and `compute_empirical_lam` integration.
3. **Data model** — Done via dataclasses in `src/scoring/types.py`.
4. **Historical pipeline (2023-2025)** — Done via Sleeper weekly export in scraper + optional nfl-data-py script.
5. **Feature engineering layer** — Done via `src/scoring/feature_engineering.py`.
6. **Layered model structure** — Done (deterministic scoring, archetype layer, player shrinkage).
7. **Structured output bundle** — Done (`playerFits[].scoringAdjustment` + legacy-compatible fields).
8. **Final adjustment structure decision** — Done (hybrid bounded multiplier + production-slice application).
9. **Exact formula implementation** — Done in `src/scoring/player_adjustment.py`.
10. **Backtesting/validation** — Done in `src/scoring/backtest.py` + `scripts/backtest_scoring_adjustment.py`.
11. **Modular code architecture** — Done (`src/scoring/` package).
12. **Sleeper ingestion APIs/functions** — Done (`fetch_league`, `extract_scoring_settings`, `normalize_scoring_settings`, `compare_to_baseline`, persistence helpers).
13. **Integration without replacing raw market engine** — Done (raw engine untouched; scoring layer additive).
14. **Deliverables (code/tests/docs)** — Done.
15. **Constraints (baseline vs custom separation, compatibility)** — Done with baseline versioning + preserved UI contract fields.

