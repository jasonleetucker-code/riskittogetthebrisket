# W1-14 / W1-15 — private Week-N matchup intelligence

**Rows:** `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md`

- **W1-14** — *"Authenticated owner-facing Week 1 matchup-intelligence surface/
  section exists without duplicating public or canonical data owners."*
- **W1-15** — *"Private matchup intelligence reuses canonical lineup,
  strength/weakness, power/playoff, and projection inputs with source/freshness
  lineage."*

`GET /api/matchup/intel` (private, league-scoped, `no-store`), assembled by
`src/api/matchup_intel.py`.

---

## 1. The public/private split, made concrete

The public `matchupPreview` section (audited in
`W1_10_WEEK1_MATCHUP_AUDIT_2026-09-05.md`) is **factual and retrospective**:
head-to-head record, last meetings, recent form. Safe for `/league`.

This endpoint is **projections, win and beat-median probabilities, expected
best-ball lineups, and roster weaknesses**. CLAUDE.md §5 puts all four on the
private side of the boundary — "proprietary values, edges, targets,
weaknesses, forecasts". So it is authenticated, `Cache-Control: no-store`, and
nothing here is added to the public contract.

## 2. It computes nothing of its own

| quantity | owner |
|---|---|
| roster membership, positions, IR/taxi subtraction | `src/ros/game_day_capture.py` |
| starter slots and slot eligibility | `src/ros/lineup.py` |
| the expected best-ball lineup | `lineup.solve_optimal_assignment` |
| per-player distribution, win % / beat-median % | `src/ros/game_day_sim.py` |
| resolving a live league-week into those inputs | `src/ros/game_day_week.py` |
| projections | `src/ros/projection_ensemble.py` |
| roster strength / weakness / age-value | `src/api/roster_intelligence.py` |
| league identity and rules | `src/api/league_registry.py` + the host |

The module's own contribution is the **assembly and the lineage**. That is not
a small thing: a win probability with no stated projection source, coverage or
threshold-semantics flag is a number, not intelligence, and W1-15 asks for
exactly the second one.

`rosterIntelligence` is the canonical owner's *own* answer for each side,
copied — not a re-derivation. When the contract does not hold a team (a
different fact from the host not holding it) that block degrades to `null`
rather than failing the matchup.

## 3. What it refuses, and why refusing is the right answer

| condition | response |
|---|---|
| week already in progress | **409 `week_in_progress`** |
| host states no season/week and none passed | **503 `clock_unavailable`** |
| owner holds no roster in this league | 404 `team_not_found` |
| unknown / inactive league | 400, per the standard table |

**`week_in_progress` is a state, not an error.** Telling a finished player from
a mid-game one needs a live game-state feed this repo does not wire, and
collapsing them double-projects (`GAME_DAY_PROBABILITY_SPEC.md` §6). A distinct
409 lets a caller render "come back after the games" instead of an error page.

**`clock_unavailable` exists because the clock is the host's.** Deriving the
season and week from the calendar is how a surface ends up describing a
different week than the league is playing — the same class of error
`src/bdvm/actuals.py` documents for `currentDraftYear`. If Sleeper does not
state it and the caller does not pass it, the endpoint says so.

## 4. Missing is never zero, at every layer

- A league with **no projection snapshot** still answers: the matchup, both
  rosters, and the full lineage come back; `outcome` is `null` and a note says
  why. **Never a fabricated 50%.**
- An **unpriced** player is `state="unknown"` in the resolver, excluded from
  every draw, reported in `unsimulablePlayerIds` and in each side's
  `unpricedPlayerIds` — and he never enters the expected-lineup pool, where he
  would otherwise be a `0.0` the solver could seat on a thin roster.
- An **ineligible** (IR / taxi) player is reported separately, because "cannot
  start" and "nobody priced him" are different facts.
- `estimateCoverage` is `{priced, active}` — two numbers, not a ratio — so "no
  projections at all" and "thin coverage" cannot read the same.
- A team with **no scheduled opponent** gets `opponent: null` and a note, never
  a 50% against a game that is not on the schedule.
- `thresholdSemanticsVerified: false` travels on every response. W1-23 is
  `BLOCKED` on host evidence, and a private decision surface must not present
  the median leg as settled just because it serialized cleanly.

The projection lineage carries its own caveat verbatim: the only live
`PROJECTION_MODEL` sources are `PRESEASON_FULL_SEASON` horizon, so the per-game
figure is a full-season projection's, and `projectionHorizonNote` says so. The
note is **absent** when there is no source at all — a caveat about a projection
that does not exist would be noise.

## 5. Verified against the live league

2026-09-05, `dynasty_main`, Week 1, unplayed, no contract loaded and
`data/bdvm/projections/` absent (it is gitignored and lives only on the box):

```
team:     JasonLeeTucker / Medical Murrayjuana   roster 1
opponent: CollinFoz / CollinFoz                  roster 4
outcome:  None
notes:    ["no projection snapshot: every player is unsimulable, so no
           probability is derivable for this week"]
lineage:  projectionSource null · sourcesUnavailable [clayProjections,
          idpShowProjections] · coverage {priced 0, active 674} ·
          starterSlotSource sleeper_roster_positions · bestBall true ·
          medianEnabled true · teamCount 12
```

The matchup is correct (roster 1 ↔ 4 matches Sleeper), and **the degraded state
is the point**: explicit nulls with a named reason, not a number. The
probability half resolves on production, where the snapshots exist.

The priced path is exercised by the unit tests, where both sides' win
percentages plus the tie sum to 100.0.

## 6. Tests

- `tests/api/test_matchup_intel.py` — 15 tests on the assembly: identity,
  complementary probabilities, no-projections → `null` (not 50%), unpriced
  players reported on their own side and kept out of the lineup pool, both
  refusals, and four on lineage.
- `tests/api/test_matchup_intel_endpoint.py` — 12 contract tests on the route:
  the routing table, `week_in_progress` as its own 409, `clock_unavailable`,
  an explicit week bypassing the host clock, `no-store`, not reachable under
  `/api/public/`, and the lineage reaching the wire.

## 7. Row status

**W1-14 and W1-15 stay `NOT STARTED`.** The backend exists and is tested, but
W1-14 asks for a *surface* and W1-16 for production verification of the owner's
experience. A tested endpoint is neither. The frontend section and the
production verification are the remaining work, and the numerator does not move
on this.
