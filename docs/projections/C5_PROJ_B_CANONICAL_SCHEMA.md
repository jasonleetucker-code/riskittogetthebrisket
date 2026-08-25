# C5-PROJ-B — Canonical Projection-Stat Schema + Exact-League Rescoring

**Status:** DELIVERED 2026-08-20 — schema + rescoring wrapper for the two
LIVE sources `C5-PROJ-A` found; ensemble aggregation itself is `C5-PROJ-C/D`
**Unit:** `C5-PROJ-B`, second sub-unit of `C5-U1`
**Governing plan:** `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` §4/§5/§6
**Owner:** `src/ros/projection_observations.py`
**Depends on:** `C5-PROJ-A` (`src/ros/projection_source_census.py`,
`config/projections/source_capability_census.json`)
**Lane:** Claude 11 — C5, under the POST-V1 C-Series mass-build campaign
(`docs/EXECUTION_PLAN.md` §0, owner directive 2026-08-20)

## What this unit is

`C5-PROJ-A` found that two of the ensemble plan's target sources — Mike
Clay/ESPN and The IDP Show — already have real, working
`PROJECTION_MODEL` implementations inside `src.bdvm`, built on a working
schema (`ProjectionRecord`) with a working exact-league rescorer
(`ProjectionRecord.resolve_fpg`, which itself reuses
`src.nfl_data.realized_points.compute_weekly_points` — the same scoring
engine that scores realized history, per `src/bdvm/scoring.py`'s own
docstring: "reuses the production stats→points path ... rather than
introducing a second scoring engine").

This unit does not duplicate either. `src/ros/projection_observations.py`
wraps `ProjectionRecord` into the seasonal ensemble's own observation
contract (plan §4's field list) and calls `resolve_fpg` for rescoring —
adding exactly the four fields the DYNASTY-fundamental BDVM engine has no
reason to carry (`evidenceClass`, `horizon`, `accessPosture`,
`providerFamily`), all sourced from `C5-PROJ-A`'s census, never invented
here.

## Design decisions worth recording

### A `ProjectionObservation` cannot exist for an uncensused source

`rescore_projection_record` raises `ProjectionObservationError` if
`census_source_key` has no entry in the `C5-PROJ-A` census. This is
deliberate: a projection observation with no recorded evidence class,
horizon, or access posture would be indistinguishable from one the
ensemble's independence rules (plan §6) simply haven't classified yet —
exactly the ambiguity the census exists to remove. A future fetcher must
be added to the census before it can be wrapped, not after.

### `RANKINGS_ONLY` sources refuse to be rescored as projections

The same function refuses a source whose census `evidenceClass` is
`RANKINGS_ONLY` — rescoring a rankings feed through exact-league scoring
would manufacture a per-player point projection a source never published,
exactly the defect `C5-PROJ-A`'s own brief warned about ("Flag any source
that is rankings-only rather than a true projection model"). This is a
structural enforcement of that flag, not merely documentation of it.

### Proxy rows are excluded by default, and stay labelled when included

`ProjectionRecord.is_proxy=True` marks BDVM's own reconstructed-baseline
rows — a Brisket-internal estimate, not a vendor's real projection, and
not independent evidence for the ensemble's family-counting purposes (plan
§6). `rescore_projection_record` returns `None` (a refusal, not an error)
for a proxy row unless the caller passes `include_proxy=True` explicitly
— and even then the resulting `ProjectionObservation.is_proxy` stays
`True`, so nothing downstream can mistake it for real vendor evidence by
construction rather than by caller discipline.

### Native totals are diagnostic; only the rescored figure feeds anything

`ProjectionObservation.native_fpg` carries the source's own reported
per-game figure before any league rescoring — display/audit only, per
plan §4 ("preserve the native total as a diagnostic"). Every consumer
that blends or ranks must read `league_scored_fpg`, the output of
`resolve_fpg` under the caller's exact league scoring settings.

### A single-horizon limitation, named rather than silently guessed

`ProjectionRecord` carries no horizon field of its own — every BDVM
snapshot today is `PRESEASON_FULL_SEASON`. `rescore_projection_record`
infers the horizon from the census entry only when it names exactly one
candidate, and raises otherwise. A future source censused for multiple
horizons (e.g. a vendor with both a real weekly and a real ROS product)
will need either a horizon-aware `ProjectionRecord` source or an explicit
horizon argument added to this function — recorded as a known limitation
rather than resolved by guessing which horizon a given snapshot actually
is.

### The stat-line vocabulary trap this unit's own tests caught

Writing this unit's tests surfaced a real distinction worth recording for
whoever writes `C5-PROJ-C`: a projection's raw `stat_line` uses nflverse
COLUMN names (`receptions`, `receiving_yards`, `receiving_tds` — what
`compute_weekly_points` reads), not Sleeper SCORING-KEY names (`rec`,
`rec_yd`, `rec_td` — what `scoring_settings` dicts use). The two
vocabularies look similar enough to confuse; a stat line built with
scoring-key names silently scores as 0.0 rather than raising, because
`compute_weekly_points` simply finds no matching columns. Not a defect in
`score_stat_line_per_game` (correctly documented in its own module
docstring) — recorded here because it is exactly the kind of drift the
ensemble plan's "ingest the source's raw projected football stat line"
instruction (§4) depends on getting right at every future adapter.

## Validation

`tests/ros/test_projection_observations.py` — 12 tests: native-vs-rescored
value separation, census field propagation, proxy exclusion (default and
explicit-include), uncensused-source refusal, `RANKINGS_ONLY`-source
refusal, real stat-line rescoring through exact league scoring (with the
column-vocabulary distinction above made explicit in the test itself), a
missing-evidence `ProjectionRecord` construction refusal (inherited from
BDVM's own `__post_init__`, not re-validated here), and
`load_and_rescore_source`'s three states (`ok` / `no_snapshot` /
`no_census_entry`) including a real snapshot round-trip through
`write_snapshot` → `load_and_rescore_source` that confirms proxy exclusion
and per-source filtering both hold against a real file, not just
in-memory records.

`tests/api/test_canonical_ownership_protections.py::test_no_seasonal_lane_module_assigns_a_canonical_alias`
(20/20 overall) — confirms this new `src/ros/` module writes no canonical
dynasty value or alias.

`tests/bdvm/test_engine_parity.py` (7/7) — confirms BDVM's frozen
Appendix-C reference fixture is untouched; this unit consumes
`ProjectionRecord`/`resolve_fpg`/`latest_snapshot_path`/`load_snapshot`
read-only and modifies nothing in `src/bdvm/`.

Combined `tests/ros/` + `tests/bdvm/`: 550 passed / 1 skipped
(livedata-marked), zero regressions. `ruff check .` + `ruff format --check .`
clean.

## What's next (not this unit's scope)

1. **`C5-PROJ-C`** — weekly offense + IDP ensemble aggregation, consuming
   `ProjectionObservation` rows from this module (and, per `C5-PROJ-A`'s
   census, waiting on further sources to move from `GREENFIELD` to `LIVE`
   before the ensemble has more than two families to blend).
2. **`C5-PROJ-D`** — ROS/full-season ensemble, horizon-matched — needs the
   same schema plus real ROS-horizon sources, which do not exist yet
   per the census.
3. **Multi-horizon sources** — extend `rescore_projection_record` with an
   explicit horizon argument once a source publishes more than one.
4. **Weekly `ProjectionRecord` sources** — `ProjectionRecord`/BDVM's
   snapshot model is season-oriented; a real WEEKLY source will need to
   confirm the schema still fits before this unit's wrapper is reused
   for it.

## Deliberately NOT claimed

Any change to `src/bdvm/projections.py`, `src/bdvm/scoring.py`, or any
other BDVM file (all consumed read-only); `C5-PROJ-C`/`C5-PROJ-D` ensemble
aggregation itself; any new fetcher or acquisition code; the DFS/betting-
market discovery lanes (still `GREENFIELD` per the census).
