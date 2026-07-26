# League Intelligence — Status

**2026-07-26 (LI-5)** — coverage fix + replacement levels (ADR-008).

- **ADR-007 coverage defect fixed.** `_positional_coverage` returned
  **exactly 100.00 for all 12 teams** — a constant, not just an
  IDP-blind heuristic.  Now slot-derived, demand-weighted and
  eligibility-aware; live range 90.87–100.00.  Because it carries only
  5% weight it moves composites by ≤0.46 — honest conclusion: it is
  now *correct* but still a weak signal, and the real upgrade is
  quality-adjusted depth off the new replacement levels.
- **Replacement levels** (`src/league_intel/replacement.py`): four
  tiers (starter / bestBallStarter / roster / waiver) with smoothed
  ±2-rank bands, computed off the real 12×58 pool (666 rostered).
- **Endogenous flex allocation** — measured, not assumed.  FLEX takes
  WR/RB 50/50 and **never a TE**; SUPER_FLEX is **75% QB**.  An even
  split understates QB demand 40% and overstates TE 46%.
- **Six separate scarcity components**, not one score.  QB
  waiverScarcity 0.75 vs RB 0.21 — the defining fact of a superflex
  league, which a blended number would bury.
- **Data-quality findings to hand off (not mine to fix):**
  `data/ros/aggregate/latest.json` carries **6 duplicate player rows**
  (same player as both lowercase and Title Case: `nate landman`,
  `cam skattebo`, `cam ward`, `tank dell`, `cam bynum`,
  `mitch tinsley`) and 16 rows with non-lowercase `canonicalName` — the
  aggregate mixes two naming conventions, so any join against it is
  lossy.  40 of 666 rostered players fail to match it.  This inflates
  the waiver tier; the waiver numbers above are provisional until the
  identity join is fixed.

**2026-07-26 (LI-3 + LI-4)** — best-ball exactness + value schema.

- **LI-3** (`src/ros/lineup.py`, ADR-007): audit found the optimizer
  was a slot-ordered greedy that is optimal *only* for laminar slot
  structures — correct today by an unstated precondition, silently
  wrong the moment a non-laminar slot appears.  Replaced with an exact
  maximum-weight assignment (matroid greedy + augmenting paths,
  dependency-free) behind the same interface, plus a canonicalization
  pass that keeps slot LABELS intuitive without changing scores.
- **Bigger find:** eligibility was checked against a single `position`
  string, but **Sleeper uses `fantasy_positions`** — DL/LB hybrids were
  locked out of half their legal slots and the live ROS path discarded
  the field entirely.  Now wired end-to-end (scrape → team_strength →
  RosterPlayer, back-compatible default).
- Validation: brute-force equivalence, a non-laminar counterexample,
  and historical reconstruction vs real Sleeper best-ball weeks —
  **10/10 team-weeks reproduce the host's awarded total**; the 2 of 10
  with a different starter set score identically, which **resolves the
  tie-handling open question**.
- **LI-4** (`src/league_intel/values.py`): parallel value schema
  (`marketValue` / `consensusValue` / `leagueAdjustedDynastyValue` with
  schema+model+config+dataThrough stamps) and the single
  `get_active_value(player, mode, context)` selector.  Backend only.
  The no-op guarantee is enforced in construction — no adjusted number
  is ever computed until LI-7, so no page can show an unvalidated
  value.  Consensus is read from the live contract, never recomputed.
- Known gap logged, not changed: `_positional_coverage` still scores
  only QB/RB/WR/TE depth (ignores K + 9 IDP starters); fixing it moves
  live team-strength numbers, so it is deferred to LI-5/LI-8.

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
