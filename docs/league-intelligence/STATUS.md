# League Intelligence — Status

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
