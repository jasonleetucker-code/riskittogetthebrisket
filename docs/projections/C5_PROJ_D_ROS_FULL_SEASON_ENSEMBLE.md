# C5-PROJ-D — ROS / Full-Season Projection Ensemble

**Status:** DELIVERED 2026-08-22 — cross-family combination for the two
LIVE `PRESEASON_FULL_SEASON` sources; consumer migration is `C5-PROJ-F`
**Unit:** `C5-PROJ-D`, fourth sub-unit of `C5-U1`
**Governing plan:** `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` §6/§9 item 4
**Owner:** `src/ros/projection_ensemble.py`
**Depends on:** `C5-PROJ-A` (`src/ros/projection_source_census.py`),
`C5-PROJ-B` (`src/ros/projection_observations.py`)
**Lane:** Claude 11 — C5, under the POST-V1 C-Series mass-build campaign
(`docs/EXECUTION_PLAN.md` §0, owner directive 2026-08-20)

## Why C5-PROJ-D before C5-PROJ-C

The plan's own decomposition (§9) lists the six `C5-U1` sub-units in
execution order: A → B → **C** (weekly ensemble) → **D** (ROS/full-season
ensemble) → E → F. This unit is delivered out of that order, for a
measured reason rather than a preference.

The `C5-PROJ-A` census
(`config/projections/source_capability_census.json`) has exactly two
`implementationStatus: LIVE` sources with a real fetcher —
`clayProjections` (family `espnClay`) and `idpShowProjections` (family
`theIdpShow`) — and **both declare `horizons: ["PRESEASON_FULL_SEASON"]`
only**. Every `WEEKLY`-horizon census entry (`cbsSportsFantasyProjections`,
`nflFantasyProjections`, `fantasyProsProjections`) is `GREENFIELD` — no
fetcher exists. Building `C5-PROJ-C` today would have zero real inputs to
combine, and writing a new `WEEKLY` fetcher is source acquisition, out of
this lane's scope this session (`acquisitionOwnerLane` on several of the
named vendors points elsewhere).

`C5-PROJ-D`'s own charter name in `docs/C_SERIES_EXECUTION_MAP.md:409`
("ROS / full-season ensemble — horizon-matched") explicitly covers
`PRESEASON_FULL_SEASON`, not only the narrower `REST_OF_SEASON` census
label — so building this unit against the two live full-season sources is
squarely in-charter.

**One correction worth making explicit**: `docs/projections/
C5_PROJ_B_CANONICAL_SCHEMA.md`'s own "what's next" section says
`C5-PROJ-D` "needs... real ROS-horizon sources, which do not exist yet per
the census." That statement is true only in the narrow sense that zero
`REST_OF_SEASON` census entries are `LIVE` — it should not be read as
"`C5-PROJ-D` has no real inputs at all." `PRESEASON_FULL_SEASON` is real,
live, and named in this unit's own charter.

`C5-PROJ-C` stays undone here, honestly, rather than built around the gap
with synthetic or rankings-derived stand-in data.

## What this unit is

`src/ros/projection_ensemble.py` combines `ProjectionObservation` rows
(`C5-PROJ-B`) across independent provider families, per plan §6: "count
independent model families, not pages... Start with simple robust
family-level baselines rather than learned weights from a tiny sample:
equal-family mean; median; trimmed/robust mean. Reliability/adaptive
weighting is challenger methodology only after sufficient leakage-safe
history exists." `COMBINATION_METHODS` is a closed three-item set with no
weight parameter anywhere in the module — the entire combination
mechanism, so nothing can be silently tuned later without a deliberate
code change and review.

Distinct from `src/ros/aggregate.py`, which blends *rank/ranking* evidence
into `rosValue` — a different input population and a different consumer
contract, not touched here.

This unit stops at the combined `EnsembleObservation`. No downstream
consumer (Game Day, Power, Playoff, waivers, lineup, Universal Player
Profile) is wired — that is `C5-PROJ-F`'s job. No DFS/betting-market
evidence class is handled — no live source of either class exists, and
the plan wants those "separately lineage-aware," never blindly pooled. No
fetcher or acquisition code is added — this module only calls
`C5-PROJ-B`'s `load_and_rescore_source`.

## Design decisions worth recording

### Within-family reduction is median, not mean

`reduce_family` reduces a family's observations (today always exactly
one, since no family has more than one live source) with
`statistics.median` when more than one exists, not a mean — chosen so one
outlier product cannot dominate a family's single cross-family vote once
a family does have more than one live source. Pinned with a hand-computed
divergent case (median 12 vs mean 14 over `[10, 12, 20]`).

### n=1 is a forced, honest passthrough — never a fabricated ensemble of one

`combine_ensemble`'s `combination_method` is forced to
`"single_family_passthrough"` when only one family covers a player,
**even when the caller passes an explicit `method="median"`** — a
single-source value must never be labelled as a multi-source consensus.
Pinned directly (the override fires regardless of the requested method).

### Disagreement is `None`, never `0.0`, below two families

`disagreement_spread`/`disagreement_stddev` are `None` when
`family_count < 2` — disagreement cannot be measured from one point, and
coercing it to zero would read as "these families agree perfectly," a
claim single-source evidence cannot support ("missing is never zero").
Mutation-proved: hand-changing the n=1 branch's `None` to `0.0` sends
`test_n1_disagreement_is_none_not_zero` RED — the test asserts `is None`
specifically, since a falsy-style check (`assert not x`) would not catch
a `0.0` regression.

### Structural cross-horizon/cross-season refusal

`_assert_single_horizon_and_season` raises rather than silently averaging
across horizons or seasons — the concrete enforcement of plan §9 item 4's
"no weekly/ROS semantic mixing," even though only one horizon exists in
practice today. Mutation-proved: disabling the horizon-mismatch branch
sends `test_refuses_to_combine_two_horizons_in_one_call` RED; restoring
returns it to GREEN (mutation not committed, applied and reverted by hand
during this unit's build).

### Proxy and non-`PROJECTION_MODEL` evidence is refused, defensively

`_assert_real_projection_evidence` raises on `is_proxy=True` or
`evidence_class != "PROJECTION_MODEL"`. `C5-PROJ-B`'s
`load_and_rescore_source` already excludes proxy rows by default, so this
is defensive — a caller who constructs an observation directly (bypassing
that filter) and passes it here must not silently have it blended into
what's presented as multi-vendor consensus.

### The real Clay/IDP-Show overlap is exercised, not hypothetical

`src/bdvm/clay_projections.py`'s own module docstring: "IDP Show records
carry through untouched, so defenders covered by both feeds get a genuine
two-source consensus." Confirmed by a real synthetic-snapshot round-trip
test (`test_real_snapshot_round_trip_produces_family_count_2_for_a_shared_defender`):
a defender covered by both sources lands at `family_count == 2` with a
real computed mean; an offense player Clay alone covers lands at
`family_count == 1`/passthrough. The n=2 combination path is not
speculative scaffolding for a future that may never arrive — it fires on
real IDP players today.

### `games` disagreement is reported, not averaged

Clay and IDP Show may assume different `games` denominators (e.g. a
bye-adjusted count) for the same player. `EnsembleObservation.games` is
`None` when contributing families disagree, rather than averaged — an
averaged games count is not a number either source actually published.
This is a judgment call, named as one rather than asserted as obviously
correct.

### `trimmed_mean` exists for spec completeness, not because it fires today

With only two live families total, `trimmed_mean` (which needs at least
three to trim both ends and have something left) can only run against
today's real data if a third family is added — it raises
`ProjectionEnsembleError` at `family_count == 2`. Included because plan §6
names it explicitly as one of the three approved primitives, not because
current data exercises it.

### Known, pre-existing limitation not repaired here

`player_key` is a normalized-name join key inherited from BDVM, not a
stable canonical player ID. Two different real players colliding on a
normalized name would incorrectly merge into one `family_count=2`
ensemble row. This limitation predates this unit (it is `C5-PROJ-B`'s and
BDVM's own join-key convention) and is not addressed here.

## Validation

`tests/ros/test_projection_ensemble.py` — 21 tests: within-family
median reduction (hand-computed divergent case), mixed-family/mixed-player
reduction refusals, n=1 forced passthrough (including the method-override
proof), n=1 disagreement-is-`None` (mutation-proved), n=2 equal-family-mean
(hand-computed against an independently-computed `statistics.pstdev`),
median-vs-mean divergence over three synthetic families, `trimmed_mean`'s
n<3 refusal and its n=3 both-ends-trimmed computation, contributing-family
naming, `games` agreement/disagreement handling, cross-horizon and
cross-season refusals (both mutation-proved), an empty-input refusal,
proxy and `RANKINGS_ONLY` evidence refusals, and a real snapshot
round-trip (`write_snapshot` → `build_ros_full_season_ensemble`) proving
the n=1 and n=2 paths both fire on realistic data, plus named
`sources_unavailable` on a missing snapshot and a refusal when asked for a
horizon no named source publishes.

`tests/api/test_canonical_ownership_protections.py` (20/20) — confirms
this new `src/ros/` module writes no canonical dynasty value or alias
(the existing seasonal-lane guard already scans everything under
`src/ros/`; no new guard was written).

`tests/bdvm/test_engine_parity.py` (7/7) — confirms this unit's read-only
consumption of BDVM/`C5-PROJ-B` data disturbs nothing in `src/bdvm/`.

Combined `tests/ros/`: 252 passed / 1 skipped (livedata-marked), zero
regressions. `ruff check .` + `ruff format --check .` clean (checked
before pushing).

## What's next (not this unit's scope)

1. **`C5-PROJ-C`** — weekly offense + IDP ensemble. Blocked on a live
   `WEEKLY`-horizon source; the census confirms zero exist today. Not a
   defect of this unit — a source-acquisition gap owned elsewhere.
2. **`C5-PROJ-E`** — immutable archive + leakage-safe backtesting.
3. **`C5-PROJ-F`** — consumer migration + production proof (Game Day,
   Power, Playoff, waivers, lineup intelligence, Universal Player
   Profile — none of these are wired to this module).
4. **Learned/adaptive weighting** — explicitly reserved by plan §6 for
   after `C5-PROJ-E`'s leakage-safe history exists and beats the simple
   champion baseline out of sample.

## Deliberately NOT claimed

`C5-PROJ-C` (blocked on a live weekly source); `C5-PROJ-E`/`C5-PROJ-F`;
any downstream consumer wiring; any DFS/betting-market evidence-class
handling (zero live sources of either class); any learned/adaptive
weighting; any change to `src/bdvm/*`, `src/ros/projection_observations.py`,
`src/ros/projection_source_census.py`, or `src/ros/aggregate.py` (all
consumed or left alone, read-only); the `player_key` name-collision
limitation (pre-existing, not repaired here).
