# C5-WAR-01 — Deterministic Core (Realized VORP, Actual WAR, WAB, Game Changer)

**Status:** DELIVERED 2026-08-20 — deterministic core only, xWAR and consumer
migration deliberately deferred
**Unit:** `C5-WAR-01`, part of C5 Seasonal Intelligence
**Governing spec:** `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md`
**Owner:** `src/war/standings.py` + `src/war/player_impact.py`
**Lane:** Claude 11 — C5, under the POST-V1 C-Series mass-build campaign
(`docs/EXECUTION_PLAN.md` §0, owner directive 2026-08-20)

## What this unit is

Four of the spec's five metrics — Realized Lineup VORP (§2), Actual WAR
(§3), Wins Above Bench (§5), and Game Changer Points (§6) — as pure,
deterministic functions over already-extracted primitives (real per-player
weekly points, a resolved replacement-level expectation, a roster pool for
one week). No Sleeper fetch, no snapshot parsing, no HTTP route, no write
path. Wiring these to a real league's history is a deliberate follow-on
(see "What's next" below), the same staged shape `C5-PROJ-A` used for
source acquisition before automation.

## What this unit deliberately excludes: xWAR

The spec's fourth metric, xWAR (§4), needs "the same archived no-lookahead
league-week scoring distribution/simulation" that `docs/GAME_DAY_PROBABILITY_SPEC.md`
also requires — a joint weekly Monte Carlo simulation across the whole
league, which does not exist in this codebase yet (see the Game Day
assessment in `docs/cseries-delivery/CLAUDE_11.md` §7 for why building one
is genuinely multi-session scope, not a rushed addition here). Building a
standalone simulation just to unblock xWAR would be exactly the "second
matchup model" `docs/GAME_DAY_PROBABILITY_SPEC.md` §10 forbids — Game Day
and xWAR must share one simulation owner, not each grow their own.

A caller needing xWAR today must report it **unavailable**, per spec §9/§11
("missing historical xWAR must display unavailable/insufficient-history,
not 0.00") — never approximate it from Actual WAR or VORP, which the spec
explicitly separates for a reason (§3: "WAR is intentionally
leverage-sensitive... must not be the sole MVP metric").

## Design decisions worth recording

### Replacement level has one consumer relationship, not a new computation

`src/scoring/replacement_level.py::replacement_per_game` is the declared
canonical owner (`scripts/replacement_census.py` row `B`). This module
never derives its own replacement baseline — every function takes an
already-resolved `replacement_expectation: float | None` argument. A
caller building the full pipeline computes `PlayerSeasonRow`s and calls the
owner directly; this unit does not duplicate that math.

### Team scores are summed from real points, never from the solver's objective

`src/ros/lineup.py::LineupAssignment.score` applies the solver's own
health-penalty objective (`max(0.0, ros_value)` for a non-injured player),
which would silently floor a legitimately negative historical score. Every
team total in this module is computed by summing the real
`points_by_id[player_id]` for the players an assignment started —
`_team_score_for_assignment` in `player_impact.py` — never `.score`.
Callers must also pass `injured=False, bye=False` explicitly on every
`RosterPlayer` for a historical week; those flags exist for the solver's
*live* health-penalty use case, which does not apply to a week that has
already been played.

### The counterfactual median is genuinely recalculated, not reused

Spec §3's own "Mandatory" instruction — recalculate the league median
after replacing the player's score, never hold the actual week's median
fixed — is implemented literally: `actual_war_for_week` and
`wins_above_bench_for_week` both build a fresh score list with this team's
entry replaced by the counterfactual total before computing the
counterfactual credit. `tests/war/test_player_impact.py::TestActualWar::test_recalculated_median_diverges_from_a_stale_one`
pins a case where a stale (actual-week) median and the honestly
recalculated one would disagree, so the test cannot pass by accident if a
future edit reintroduces the stale-median defect.

### A whole-week refusal, not a zero-credit week, when the team's score can't be located

Both `actual_war_for_week` and `wins_above_bench_for_week` require the
caller's `all_scores_this_week` to contain the team's own actual (or
with-player) total. If it is not present — a caller bug, or a genuinely
incomplete score set — the function returns `None` for the whole week
rather than silently computing a counterfactual median that omits the
team. This is "missing is never zero" applied to a case that isn't a
missing *value* but a missing *membership fact*; treating it as a zero-WAR
week would be a wrong answer presented as a real one.

### Median-game tie handling is a labelled PRIOR, not a verified rule

`docs/GAME_DAY_PROBABILITY_SPEC.md` §3 names Sleeper/host median-tie and
odd/even-league-size behaviour as something to "verify... rather than
guessing." This environment has no network egress to do that verification.
`src/war/standings.py` implements the standard statistical median (average
of the middle two for an even-sized league) with half-credit ties,
matching the tie convention `src/public_league/metrics.py` already uses
for H2H ties (`winPct = (wins + ties*0.5) / games`) — internally
consistent, but not yet checked against Sleeper's actual median-game rule.
Recorded explicitly so this does not get promoted to a validated
methodology without that check, per the calibration policy's "every
consequential tunable is MEASURED/VALIDATED, MECHANICALLY REQUIRED, or
PRIOR/HEURISTIC" rule — this one is PRIOR.

### Season totals carry their own coverage state

`SeasonTotal` (a sum plus `weeks_known`/`weeks_missing`/`complete`) rather
than a bare float — a season total from 12 of 14 known weeks is a
different claim than one from 14 of 14, and collapsing them into one
number would be exactly the missing-is-never-zero violation this whole
spec exists to prevent (§11: "missing historical xWAR must display
unavailable/insufficient-history, not 0.00" — the same discipline applies
to VORP/WAR/WAB season totals, not only xWAR).

## An existing but spec-noncompliant implementation, found and not touched here

`src/public_league/awards.py:1441-1444` already computes a playoff VORP
(`vorp = max(0.0, r["starterPoints"] - replacement_per_game * games)`).
Two measured discrepancies against the binding spec: it **floors at 0.0**
(spec §2/§11: "Negative VORP is valid"), and it is **season-aggregate**,
not per-week (spec §2 defines `weeklyVORP` per best-ball-counted
player-week, summed to `seasonVORP`). This is C9-AWARD scope (Claude 13's
lane, POST-V1 DEFERRED per `docs/VERSION_1_COMPLETION_CONTRACT.md` §4.1),
not repaired here — but the real canonical owner now exists for that lane
to retire the inline calculation into, per ONE CONCEPT ONE CANONICAL
OWNER, once it picks up that consumer migration.

## Validation

`tests/war/test_standings.py` — 16 tests: H2H credit (win/loss/tie),
median value (odd/even league size, unavailable-when-empty), median
credit, and `standings_credit` worked examples including the spec's own
"2-0 week" framing and both single-flip cases.

`tests/war/test_player_impact.py` — 24 tests, directly pinning the spec's
own §12 validation criteria: no result flip → WAR 0; H2H-only flip → +1;
median-only flip → +1; both flips → +2; below-replacement performance can
produce negative WAR; the counterfactual median is recalculated (with a
case that specifically diverges from a stale-median answer); a
non-counted best-ball player-week is exactly 0.0 (not `None`, not
missing); Wins Above Bench re-solves the full lineup including a FLEX
reassignment (removing a starting WR promotes a bench TE into FLEX, not
"the next WR"); Game Changer Points equals the same remove-and-resolve
primitive's score delta exactly (spec §6: "do not implement separate
Game Changer math"); every missing-evidence path (`None` replacement,
team score not found) returns `None` rather than a zero.

`tests/lineup/test_single_owner.py` — 16/16, confirming this unit calls
the canonical lineup solver rather than reimplementing assignment logic
(the guard scans `src/` by source text, not behaviour, for a second
"iterate slots, claim best eligible" engine).

Full suite: `tests/war/` 40/40, `tests/war/ + tests/lineup/ + tests/scoring/`
combined 180/180, zero regressions. `ruff check .` and `ruff format --check .`
both clean across the whole repository.

## What's next (not this unit's scope)

1. **Consumer wiring** — a module that walks `PublicLeagueSnapshot`/
   `SeasonSnapshot` (per-player-week points via
   `src.public_league.awards._starter_scoring_walk`-adjacent helpers,
   full-roster pools via `_roster_player_points`) and calls this unit's
   functions for a real league/season. Needs real `PlayerSeasonRow`
   aggregation into `replacement_per_game` per position, and real
   `RosterPlayer` construction with correct `fantasy_positions` from
   Sleeper metadata.
2. **§10's immutable historical contract** — a new lightweight store
   (not `src/history/store.py`, which is scoped to asset value/rank
   observations with a different identity shape — confirmed by reading
   its schema before ruling it out). Per-`(league, season, week, player)`
   versioned rows: actual/counterfactual scores, replacement
   method/version, best-ball lineup, H2H/median results, calc
   version/timestamp.
3. **xWAR** — waits on the joint weekly simulation (shared with Game Day).
4. **C9-AWARD-02 migration** — retiring `awards.py`'s inline VORP into a
   call to this owner (Claude 13's lane, POST-V1).
5. **Median-tie verification** — confirm Sleeper's actual median-game tie
   and odd/even-size behaviour against a live league before promoting the
   PRIOR tie convention to VALIDATED.

## Deliberately NOT claimed

xWAR itself; any Game Day work; any consumer wiring to real Sleeper data;
`src/public_league/awards.py`'s spec-noncompliant VORP repair (C9-AWARD
scope); any change to `src/scoring/replacement_level.py` or
`src/ros/lineup.py` (both consumed as-is); the historical evidence store;
MVP/OPOY/DPOY methodology (spec §7/§8, itself explicitly deferred pending
"the C-series Awards methodology pass" and owner approval).
