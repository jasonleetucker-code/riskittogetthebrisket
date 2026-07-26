# League Intelligence — Status

**2026-07-26 (later)** — LI-1 + LI-2 complete.

- `src/league_intel/config.py` — versioned canonical config
  (configVersion 1) loaded from the dated snapshot; validation +
  polite live-refresh path that reports drift and writes a NEW dated
  snapshot (never mutates the stored one).
- `config/leagues/registry.json` dynasty_main rosterSettings
  corrected to live truth (TE 2, K 1, DL/LB/DB 3, IDP_FLEX 0,
  rosterSize 58, taxiSize 0, 21 starters).  All consumers verified
  with tests (`tests/league_intel/test_registry_consumers.py`);
  `src/trade/suggestions.py::DEFAULT_STARTER_NEEDS` updated (TE 1→2,
  DB 2→3) to stop mirroring the stale lineup.
- `src/league_intel/scorer.py` — deterministic exact scorer.
  **Golden-validated: Sleeper scoring is a pure dot product over
  shared stat keys — 1,415/1,415 rostered 2025 player-weeks reconcile
  within 0.011**, plus 2 full team totals.  All stacking questions
  answered empirically (see SCORING_VALIDATION.md); 16 archetype
  fixtures + 2 team fixtures committed.
- 2026 has no scored weeks yet (offseason) — mechanics validated on
  the completed 2025 season (same key vocabulary, different rates);
  base-`rec` stacking at a nonzero rate flagged for re-confirmation
  after 2026 week 1.

**2026-07-26** — LI-0 complete.

- Live Sleeper config fetched and snapshotted
  (`config/league_intel/sleeper_league_snapshot_2026-07-26.json`).
- Settings audit complete: host API ↔ screenshots agree on all 141 scoring
  keys and the 21-slot best-ball lineup; **repository registry
  rosterSettings are stale on 8 fields** (P1 — see SETTINGS_AUDIT.md).
- §3.11 unknowns resolved: taxi 0, IR 0, playoff 7 teams from wk 15,
  6 rookie rounds, FAAB $100, no base-FG points, no volume bonuses.
- Open empirical questions (LI-2 golden tests): pick-six stacking (−6?),
  first-down bonus semantics, reception base+band stacking, IDP multi-event
  stacking.
- ADRs 001–005 recorded. LI-1/LI-2 dispatched to a dedicated agent
  (isolated territory: src/league_intel/, tests/league_intel/,
  config/league_intel/ + coordinated registry fix).
- League-adjusted values remain **unpublished** — nothing user-visible
  changes until the scorer passes golden validation (spec Phase 3 no-op
  rule).
