# V1-51 — one owner for the league's playoff bracket

**Status:** implemented, unmerged, not deployed. Production verification
has not been done.

## What V1-51 asks

One canonical playoff-probability engine. The owner direction that opened
this unit is the part worth restating, because it is what the work turns
on:

> Intentional v1/v2 duplication is not automatically equivalent to one
> canonical production owner.

That is the right test, and applying it found something better than
duplication: the two simulators did not disagree about the *answer*, they
disagreed about the *question*.

## The defect, measured

Three engines simulate this league's postseason:

| module | reads `settings.playoff_teams`? |
|---|---|
| `public_league/playoff_odds.py` (public `/league`) | yes — else silently `DEFAULT_PLAYOFF_SPOTS = 6` |
| `ros/playoff_sim.py` (private intelligence) | **no** — `playoff_seeds: int = 6` hardcoded |
| `ros/championship.py` (private intelligence) | **no** — `playoff_seeds: int = 6` hardcoded |

There are **four** such defaults in total — `simulate_playoff_odds`,
`simulate_championship_odds`, `simulate_trade_impact` and the public
module's `DEFAULT_PLAYOFF_SPOTS` — and each was invisible on its own,
because the parameter looked configurable and nothing configured it.
Neither private engine's production caller overrides it: `ros/scrape.py`
calls `simulate_playoff_odds(snap, best_ball=bb)` and
`simulate_championship_odds(snap, best_ball=bb)`, passing no bracket.

Measured 2026-08-19 against the live league,
`GET https://api.sleeper.app/v1/league/1312006700437352448`:

```
playoff_teams: 7    playoff_seed_type: 1
playoff_type:  1    playoff_week_start: 15
num_teams:     12
```

**The league takes seven. Both private engines simulated six.**

On a 12-team league that is precisely the difference between sixth and
seventh place mattering — it changes every team's playoff odds, and the
championship simulation is more sensitive still, because the bye count
decides who skips a round. The pre-existing audit capture
`docs/master-site-audit/evidence/W30/playoff-odds-two-engines.json`
records the two engines side by side at `playoffSpots: 7` (public) against
`playoffSeeds: 6` (private), which is the same finding seen from outside.

**A fourth parser exists** — `league_intel/config.py::LeagueIntelConfig`
carries `playoff_teams`, and `tests/league_intel/test_config.py` asserts
it equals 7. It reads from a different snapshot directory than the two
simulators, so it is not a drop-in owner for them; it is recorded here
because it is a fourth place that knows this fact and a candidate for a
later consolidation.

## The fix

`src/public_league/playoff_structure.py` resolves the bracket once, from
the league's own settings, and all three engines consume it.

**Byes are derived, not configured.** A single-elimination bracket pads to
the next power of two and the teams that would have played the empty slots
get the byes:

    byes = next_power_of_two(teams) - teams

That reproduces the pair the code already hardcoded — 6 teams → 2 byes —
which is the evidence it generalises the existing behaviour rather than
inventing new methodology. It also gives 7 → 1, which is what the live
league plays and which no constant could have produced.

Sleeper's `playoff_type` (0 single-elimination, 1 with a third-place game,
2 two-week rounds) changes how rounds are *scheduled*, not how many teams
qualify or sit out round one, so it is deliberately not modelled.

**An explicit bracket still wins.** `simulate_trade_impact` pins both arms
of its A/B to one bracket; if resolution overrode that, the two arms could
be different leagues and the delta would measure the bracket rather than
the trade.

## Missing is never six

A league that does not publish `playoff_teams` has an **unknown** bracket,
and all three engines now say so instead of substituting a number:

| surface | behaviour |
|---|---|
| `compute_playoff_odds` | `playoffSpots: null`, `simulated: false`, `scheduleCertainty: "unknown_bracket"`, every owner `playoffProbability: null`, plus an `unsimulable` block naming the reason |
| `simulate_playoff_odds` | `playoffOdds: []`, `playoffSeeds: null`, `unsimulable` with the reason |
| `simulate_championship_odds` | `championshipOdds: []`, same shape |

The rows are still there — the owners are real — and only the certainty is
withheld. This is the same posture the module already used for a preseason
league and for a league with no games played and none scheduled.

`DEFAULT_PLAYOFF_SPOTS` is **deleted**, not deprecated. It was wrong for
the league it served, and a plausible default left in scope is how a guess
gets re-adopted. `test_there_is_no_default_playoff_spot_count_any_more`
asserts its absence.

Every payload now stamps `playoffStructure` — the resolved bracket, its
source and, when unknown, the reason — so "which bracket produced these
odds" is never implicit.

## What this does NOT do

It does not merge the two simulation cores. They remain two engines with
genuinely different outputs (`playoffProbability` vs `playoffOdds` plus
bye/top-seed/seed-distribution) and different evidence (`playoff_sim`
blends ROS forward-looking strength at `ROS_BLEND = 0.20`; the public one
is purely empirical). `playoff_sim`'s own docstring claims "Outputs match
the v1 schema so the frontend can swap data sources without a contract
fork" — that is **false today**: `numSims` vs `n_simulations`,
`playoffSpots` vs `playoffSeeds`, `playoffProbability` vs `playoffOdds`.

Merging them is a bigger unit and needs the public/private lens decision
the owner made for the power ranking applied here explicitly. What this
change establishes is the precondition: **the two engines now agree about
what league they are simulating.** A shared core cannot be built on top of
two different brackets.

## Tests

`tests/public_league/test_playoff_structure.py` — the live 7/1 case, the
bye derivation across nine bracket sizes, seven ways a bracket can be
unknown each with its reason code, both engines taking the league's
bracket, the explicit override surviving, and the agreement property
across four bracket sizes.

Plus a **structural AST guard** — `test_no_production_module_still_hardcodes_a_six_team_bracket`
walks every function in `src/` and `scripts/` and fails on any integer
default for `playoff_seeds` or `bye_seeds`. Written as AST rather than a
text search because the first version matched this document's own prose
describing the defect.

Mutation-checked in three places: restoring `= 6` in the public engine,
the playoff engine or the championship engine each turns tests RED.
