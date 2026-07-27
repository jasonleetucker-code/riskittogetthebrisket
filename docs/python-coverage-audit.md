# Python Coverage Audit — 2026-07-27

Measured, not estimated. Every number below comes from a real command
run against `origin/main @ 57b030b01` in this repo.

**Method**

```bash
python -m pip install coverage pytest-cov pytest-xdist
python -m pytest tests/ -q -m "not livedata" -p no:randomly -n 4 --dist loadfile \
  --cov=src --cov=server --cov-report=term
```

`-m "not livedata"` mirrors what CI actually gates on, so these are
**CI-blocking** coverage numbers, not "if you also had live exports"
numbers. `-n 4 --dist loadfile` keeps each test file on one worker;
the full suite runs in ~4 minutes instead of ~22 serial.

---

## 1. Headline numbers

| | Before | After | Δ |
|---|---|---|---|
| Tests collected (`not livedata`) | 3,927 | 4,012 | **+85** |
| Tests passing | 3,926 | 4,011 | +85 |
| Total statement coverage (`src/` + `server.py`) | **80.1%** | **80.5%** | +0.4pp |
| Statements missed | 6,570 | 6,431 | −139 |

One test fails in the parallel run both before and after —
`tests/intel/test_endpoints.py::TestLeagueScoping::test_reads_go_through_the_league_resolver`.
It **passes serially** (`python -m pytest tests/intel/test_endpoints.py`
→ 21 passed). It is a cross-file registry-state leak that only appears
under `--dist loadfile` grouping, pre-existing and unrelated to this
branch. Not fixed here — it is a test-isolation issue in a file this
work did not otherwise touch.

### Coverage of the modules that actually decide money

| Module | Before | After |
|---|---|---|
| `src/api/data_contract.py` (valuation engine) | 79.8% | 80.1% |
| `src/canonical/player_valuation.py` (Hill curves) | 97.7% | 97.7% |
| `src/trade/finder.py` | 95.7% | 95.7% |
| `src/trade/suggestions.py` | 94.1% | 94.1% |
| `src/league_intel/replacement.py` | 95.0% | 95.0% |
| `src/trade/faab_recommender.py` | 93.2% | 93.2% |
| `src/trade/faab_contention.py` | 85.4% | 85.4% |
| **`src/trade/waiver.py`** | **27.0%** | **99.2%** |
| `server.py` | 51.3% | 51.8% |

The honest read: **the money paths were already well covered by line
count.** The exception was `src/trade/waiver.py` — live behind
`POST /api/waiver/suggestions`, and the only module under `src/trade/`
with no dedicated test file at all.

The valuation engine's 80% is the more interesting number, and section
3 explains why the line percentage overstates the real protection.

---

## 2. Ranked gaps: uncovered statements × logic density

Ranked by *consequence*, not raw miss count. Density judged by reading:
branching, arithmetic, error handling, external-input parsing.

| # | Module | Stmts | Miss | Cov | Density | Why it ranks here |
|---|---|---|---|---|---|---|
| 1 | `src/api/data_contract.py` | 2,889 | 585 | 79.8% | **Very high** | Every live player value. Dense arithmetic + branching. The 585 misses are concentrated in scrape-bridge/enrichment branches, but stage constants had *zero* CI-blocking assertions (§3). |
| 2 | `server.py` | 4,511 | 2,195 | 51.3% | **High** | Largest absolute hole. Much is route glue and error handlers, but includes league resolution, auth gating, and every trade/terminal entry point. |
| 3 | `src/trade/waiver.py` | 122 | 89 | 27.0% | **High** | Live endpoint. FAAB bid arithmetic = literal money. **Closed → 99.2%.** |
| 4 | `src/ros/scrape.py` | 277 | 207 | 25.3% | Medium | External HTML/JSON parsing — high density, but network-bound and seasonal. |
| 5 | `src/api/chat.py` | 113 | 113 | **0.0%** | Medium | Entirely untested module. |
| 6 | `src/ros/sources/draftsharks_ros.py` | 92 | 92 | **0.0%** | Medium | External-input parser, zero coverage. |
| 7 | `src/ros/sources/fantasypros_ros_overall.py` | 59 | 59 | **0.0%** | Medium | Same. |
| 8 | `src/ros/sources/fantasypros_ros_idp.py` | 43 | 43 | **0.0%** | Medium | Same. |
| 9 | `src/ros/api.py` | 182 | 115 | 36.8% | Medium | ROS surface. |
| 10 | `src/scoring/feature_engineering.py` | 50 | 45 | 10.0% | Medium | Arithmetic-dense but offline/analytical, not live valuation. |
| 11 | `src/scoring/archetype_model.py` | 53 | 46 | 13.2% | Medium | As above. |
| 12 | `src/scoring/backtest.py` | 57 | 51 | 10.5% | Low-Med | Offline tooling. |
| 13 | `src/public_league/awards.py` | 900 | 76 | 91.6% | Low | Big module, mostly already covered; remainder is display copy. |

Deliberately ranked *low* despite large miss counts: `src/api/terminal.py`
(153 miss / 80.0%) and `src/api/sleeper_overlay.py` (119 miss / 82.5%)
— both are aggregation/display layers over already-validated values.

---

## 3. High line-coverage, weak assertions

Coverage is a floor. These execute a lot and assert little; the
percentage they contribute is not protection.

### W-1 — `tests/api/test_market_corridor_clamp.py::test_fallback_chain_covers_all_scope_sources` *(fixed in this branch)*

The clearest case in the repo. Its docstring claimed:

> "Safety rail: every IDP-scope and offense-scope value+rank source in
> the registry should be somewhere in the fallback chain… Catches a new
> source being added to `_RANKING_SOURCES` without being added to the
> anchor chain."

It computed `offense_sources`, `idp_sources`, `chain_offense`,
`chain_idp` — and **compared none of them**. Ruff flagged all four as
`F841` unused. The only real assertions were that each chain's first
element matches the declared primary anchor. The promised guard did not
exist.

Fixed by renaming to
`test_fallback_chain_starts_with_the_declared_primary_anchor`, removing
the dead locals, and rewriting the docstring to describe what is
verified. The registry-coverage assertion was **not** added: an inline
comment records that the chain is a deliberately curated shortlist, so
a subset assertion would be wrong. Clears 4 pre-existing ruff errors.

### W-2 — `tests/api/test_single_source_resolution.py`

Executes **31.7% of `src/api/data_contract.py`** (917 of 2,889
statements) on its own:

```
$ python -m pytest tests/api/test_single_source_resolution.py \
    --cov=src.api.data_contract --cov-report=term
src/api/data_contract.py    2889   1972  31.7%
18 passed
```

Its 18 tests assert **no computed value whatsoever** — only boolean
flags (`isSingleSource`, `isStructurallySingleSource`), name-normalisation
equality, and allowlist membership. Nearly a third of the valuation
engine's line coverage comes from a file that would stay green if every
player's value changed.

Not a criticism of the tests — they correctly cover what they are for.
The point is that `data_contract.py`'s 80% must not be read as "80% of
the valuation logic is verified".

### W-3 — the `livedata` CI blind spot (structural)

`tests/conftest.py::_LIVEDATA_MODULES` marks 16 modules `livedata`; CI
runs `-m "not livedata"`, so they are **deselected**. Among them are
`test_data_contract.py`, `test_single_curve_live.py`,
`test_pick_rookie_anchor.py` and `test_picks_end_to_end.py` — i.e. most
of the whole-board valuation assertions.

Before this branch, grepping the live constants across `tests/`:

| Pipeline stage | Referenced only in |
|---|---|
| `_SINGLE_SOURCE_VALUE_RETENTION` / `singleSourceValuePenaltyApplied` | `test_single_curve_live.py` *(livedata)*, `test_data_contract.py` *(livedata)*, `test_compact_view.py` (**fixture field name only, no math**) |
| `_ALPHA_SHRINKAGE` / `alphaShrinkage` | same three |
| `_apply_pick_year_discount_to_blend` | `test_picks_end_to_end.py` *(livedata)*, `test_frontend_migration.py` |
| pick tethering / `_rookie_pool_value` | `test_pick_rookie_anchor.py` *(livedata)*, `test_data_contract.py` *(livedata)* |

So the single-source haircut, α-shrinkage and pick tethering had **no
CI-blocking test at all**. Changing `0.30` to `0.50` — a board-wide
repricing — would have gone green in CI.

### W-4 — guards that cannot fire, cited in source as if they can

`src/api/data_contract.py` (~line 7281) says:

> "…`tests/api/test_single_curve_live.py::TestOffenseHasNoCalibrationLayer`
> fails if that reference ever starts mutating live values."

It cannot. That module is `livedata` (deselected in CI) **and** every
test in it calls `self.skipTest("No live data")` when no export is on
disk. Two independent reasons it never runs in CI. The same applies to
`TestVolatilityPassIsRemoved` and `TestValueChain` in that file.

This is the exact anti-pattern the audit brief warned about. Addressed
by adding CI-blocking, synthetic-fixture equivalents
(`TestRetiredPassesStayRetired`) rather than touching the livedata
copies, which remain useful as live-board checks.

---

## 4. Defects

### D-1 — one out-of-range source value rescales the entire board *(**RESOLVED 2026-07-27**)*

> **Resolution.** Fixed in `src/api/data_contract.py` by
> `_partition_value_source_ranges` + `_value_is_in_declared_range`.
> Operator decision was **"B with a C escalation"**:
>
> * **B** — an out-of-range row is dropped from the value-direct path
>   for that source only and falls through to the existing rank→Hill
>   fallback, exactly as a missing value already does. Every other
>   player is untouched.
> * **C** — above `_VALUE_RANGE_ESCALATION_FRACTION` (2%) out-of-range
>   rows the vendor has changed their scale rather than glitched, so
>   the whole source is suppressed from the value-direct path (it still
>   votes via rank→Hill) and the run logs an ERROR.
> * **Minimum sample** — `_VALUE_RANGE_ESCALATION_MIN_ROWS` (50). Below
>   that we always take policy B. Escalation C is a claim about the
>   *source*, and a fraction over a handful of rows cannot support it:
>   on a 4-row fixture one glitch is 25%. This was caught by a test,
>   not by review.
> * The ceiling is **per source**, not a global 9999 — `dynastyNerdsSfTep`
>   publishes up to 10256, so a hardcoded ceiling would be wrong the
>   moment a differently-scaled board joins `_VALUE_BASED_SOURCES`.
>
> **It changed no live number.** Verified against the real board on the
> day of the fix: `ktcSfTep` 464 rows / 0 out of range / max 9999;
> `idpTradeCalc` 814 rows / 0 out of range / max 9999; nothing
> suppressed. A tripwire, not a repricing.
>
> The characterisation test below
> (`test_out_of_range_finite_value_rescales_the_board`) has been
> converted to the no-contamination assertion it asked for and renamed
> `test_out_of_range_finite_value_does_not_rescale_the_board`.
> `tests/api/test_value_range_guard.py` adds 15 more.
>
> The original write-up is retained below because the measurement and
> the policy reasoning are the load-bearing part.

**Where** `src/api/data_contract.py::_compute_unified_rankings`, the
`value_source_max` construction (~line 6597) feeding the value-direct
branch (~line 6673):

```python
if raw_f > value_source_max.get(key, 0.0):
    value_source_max[key] = raw_f      # unbounded max
...
value = raw_f / site_max * 9999.0      # every player divided by it
```

`site_max` is an unbounded maximum over the pool. Because the formula
is `raw / site_max × 9999`, **a single out-of-scale cell in one
value-based source deflates every player's contribution from that
source, proportionally.**

**Reproduced through the real entry point** (`build_api_data_contract`,
120-player board, one extra row):

| Player | Clean | +1 row at `ktcSfTep=99990` | +1 row at `950000` |
|---|---|---|---|
| Player 000 | 9999 | 5474 (**−45.3%**) | 5049 (**−49.5%**) |
| Player 010 | 9202 | 5038 (−45.3%) | 4647 (−49.5%) |
| Player 040 | 6814 | 3730 (−45.3%) | 3441 (−49.5%) |
| Player 080 | 3630 | 1987 (−45.3%) | 1833 (−49.5%) |

99990 is a plausible extra-digit scrape glitch; 950000 is the shape of
a rank-encoding value leaking into a value column. Both are silent —
no warning, no health alert, correct-looking ordering, ~45% wrong
magnitudes everywhere.

**What already protects it, and what does not.** `_safe_num` rejects
non-finite input (`inf`, `nan`, non-numeric), so those cannot poison
`site_max` — verified, and now regression-tested. Nothing anywhere
validates that a value-based source's numbers stay inside its declared
0–9999 scale: `src/api/source_health_alerts.py` only checks staleness,
and `src/api/startup_validation.py` has no range check.

**Why not fixed here.** The guard is unambiguous in *need* but not in
*shape*, and the choice changes numbers:
clamp `site_max` at 9,999? drop the offending row? reject the source as
unhealthy and fall back? Each has different consequences for a real bad
scrape. CLAUDE.md rule 3 (preserve working behaviour absent a verified
flaw) plus rule 7 (smallest correct change) make this a decision for the
owner, not a unilateral edit.

**Pinned meanwhile.** `TestSiteMaxContamination` in
`tests/api/test_valuation_degraded_inputs.py` has two tests: one asserts
the non-finite guard holds (a real regression guard), one *characterises*
the current deflation and tells the next reader to update this document
when a range guard is added.

### D-2 — `/api/draft-capital` does not honour the documented 503 *(UNRESOLVED — documented, not fixed)*

CLAUDE.md's error table lists `/api/draft-capital` among endpoints that
must return `503 data_not_ready` "whenever the loaded contract's
`leagueKey` doesn't match the request".

It returns **200**. `get_draft_capital` calls
`_resolve_league_for_request(request)` **without**
`require_loaded_contract=True`, then for any non-default league builds a
Sleeper-derived answer from that league's own roster data. The handler's
own docstring describes this as intentional ("Angle-finder + roster picks
still work across leagues via the Sleeper overlay").

So CLAUDE.md and the code disagree, and the code's divergence looks
deliberate and newer.

**The safety-relevant part is fine**: it consults the *requested*
league's Sleeper ID, not the loaded league's — verified by test and by
mutation (pointing it at `default_cfg.sleeper_league_id` turns the test
red). No cross-league roster leak.

**The subtler issue**: the fallback prices League B's picks using
`latest_contract_data`, which is League A's contract. Pick values follow
the *scoring profile*, and there is no profile check on this path —
`/api/data` 503s when profiles differ
(`test_api_data_503s_when_scoring_profile_differs`), `/api/draft-capital`
does not. With the two leagues on different profiles, League B gets
League A's rankings.

**Why not fixed here.** Three defensible resolutions (503 per the table /
add a profile guard mirroring `/api/data` / keep the fallback and correct
CLAUDE.md), and choosing between them is a product decision. Also,
`server.py` endpoints are actively being worked on by another agent this
session.

**Pinned meanwhile.** `TestDraftCapitalCrossLeagueFallback` in
`tests/api/test_league_isolation_invariants.py` characterises the actual
behaviour and hard-asserts the no-cross-league-roster-leak property.

### D-3 — CLAUDE.md stage 10 documents code that does not exist *(documentation defect)*

CLAUDE.md's Live Value Pipeline lists as stage 10:

> "IDP calibration post-pass (`_apply_idp_calibration_post_pass` reads
> `config/idp_calibration.json`), contained by the market corridor clamp"

Neither exists:

```bash
$ grep -rn "_apply_idp_calibration_post_pass" --include=*.py .   # no matches
$ ls config/idp_calibration.json                                  # No such file
```

`src/api/data_contract.py` is explicit — "**Phase 4c: removed** — The
IDP calibration post-pass … has been retired." The market corridor clamp
half of stage 10 *is* real and wired
(`_apply_market_corridor_clamp`, line 7265).

The live pipeline therefore has 11 implemented stages, not 12. Left for
the owner to correct in CLAUDE.md rather than edited here — other agents
are working against that file this session. Pinned by
`TestRetiredPassesStayRetired::test_idp_calibration_config_and_helper_are_really_gone`
so the drift cannot widen unnoticed.

### D-4 — `leagueKey` echo on 503 is inconsistent *(minor, documented)*

CLAUDE.md: league-aware endpoints "all stamp `leagueKey` on their
response". On the 503 path, `/api/trade/simulate` and `/api/terminal` do;
`/api/trade/suggestions` and `/api/trade/finder` do not — their body is
`{"error": "data_not_ready", "message": "..."}` with the league named
only in prose.

Low impact (the status code and `error` code clients branch on are
correct everywhere), and adding a field is an API-shape change, so not
altered. Pinned by
`test_leaguekey_echo_on_503_is_inconsistent_across_routes`.

### D-5 — pre-existing parallel-run test isolation leak *(not fixed)*

`tests/intel/test_endpoints.py::TestLeagueScoping::test_reads_go_through_the_league_resolver`
expects an empty registry (404 `no_leagues_configured`) and gets 503
`data_not_ready` when another file's registry state precedes it on the
same xdist worker. Passes serially; fails under `-n 4 --dist loadfile`,
before and after this branch. Only affects parallel runs, which CI does
not currently use.

---

## 5. Tests added

All are pure-logic, no network, no `livedata` marker — they run in CI.
**Every test below was verified to fail against a deliberate mutation of
the code it covers** (see §6).

| File | Tests | Covers |
|---|---|---|
| `tests/api/test_valuation_pipeline_stages.py` | 24 | Single-source haircut (0.30, exactly, and pick exemption); α-shrinkage routing (0.10 for IDP + picks, flat blend for offense); value-direct vs Hill voting membership; routed-curve reference denominators; percentile clamp past N=500 driven through the pipeline; pick-year discount reaching `rankDerivedValue`; λ·MAD staying retired; CI-blocking retired-pass guards |
| `tests/api/test_valuation_degraded_inputs.py` | 14 | Empty/absent sources; zero variance; negative/zero/None/non-finite; site-max contamination (D-1); ties; duplicate names; no-NaN-escapes sweep |
| `tests/api/test_league_isolation_invariants.py` | 17 | No raw Sleeper league ID on `/api/leagues` (anon + authed); league-scoped endpoints refusing foreign leagues; unknown/inactive 400 sweep; D-2 and D-4 characterisation |
| `tests/trade/test_waiver.py` | 30 | Two-source minimum; `MIN_WAIVER_VALUE` floor; roster exclusion; rookie window; full FAAB bid arithmetic; grouping/caps; degraded inputs; drop candidates |
| **Total** | **85** | |

Plus one existing test corrected (W-1).

---

## 6. Mutation verification

Each mutation was applied to the source, the suite run, then reverted.

| # | Mutation | Result |
|---|---|---|
| 1 | `_SINGLE_SOURCE_VALUE_RETENTION` 0.30 → 0.50 | 4 red (`1500→2000`, `1200→2000`) |
| 2 | `_ALPHA_SHRINKAGE` 0.10 → 0.25 | 3 red |
| 3 | `use_hierarchical_blend = True` (routes offense through the α path) | 2 red (`6000→3600`) |
| 4 | `_PERCENTILE_REFERENCE_N` 500 → 800 | 1 red |
| 5 | `_MAD_PENALTY_LAMBDA` 0.0 → 0.5 | 4 red |
| 6 | pick-year discount application disabled | 2 red |
| 7 | remove clamp in `data_contract` only | **green** — clamp is defence-in-depth; `percentile_to_value` clamps too |
| 8 | remove **both** clamps | 1 red (`2370 ≠ 2335`) |
| D1 | remove `math.isfinite` from `_safe_num` | 2 red (`OverflowError`) |
| D4 | phase-1 positivity gate disabled | 1 red (`900 → 6405`) |
| D3′ | `sourceSpread` stamp drops `0.0` | 2 red |
| R1 | revive `offenseCalibrationMultiplier` | 1 red |
| V1 | add `dlfSf` to `_VALUE_BASED_SOURCES` | 2 red |
| V2 | mark the ROOKIE Hill master `routed=True` | 2 red |
| W1 | remove waiver two-source minimum | 2 red |
| W2 | FAAB `0.05 + 0.25·share` → `0.10 + …` | 5 red |
| W3 | remove waiver roster exclusion | 1 red |
| W4 | `MIN_WAIVER_VALUE` 500 → 200 | 2 red |
| W5 | drop-candidate sort reversed | 1 red |
| L1 | `public_dict` leaks `sleeperLeagueId` | 3 red |
| L2 | draft-capital uses default league's Sleeper ID | 1 red |

Mutation 7 is worth keeping: it proves the percentile clamp is
implemented twice, so removing either one alone is silently harmless.
The test was rewritten mid-audit after it initially passed against a
clamp removal — the first version re-implemented the formula instead of
driving the pipeline, which is the same manufactured-confidence failure
this document criticises elsewhere.

---

## 7. Which parts of the valuation pipeline still have no meaningful test

The most useful section for the owner. Numbering follows CLAUDE.md's
12 stages.

**Now covered by CI-blocking tests (this branch):** stage 2 clamp,
stage 4 value-direct voting membership, stage 6 α-routing, stage 7
count-aware tiers (already unit-tested in `test_count_aware_blend.py`),
stage 8 λ retirement, stage 9 haircut, stage 12 pick-year discount.

**Still without a meaningful CI-blocking test:**

1. **Stage 11 — pick tethering.** The largest remaining hole. Current-year
   slot picks inherit the merged rookie pool's values, and that logic is
   exercised only by `test_pick_rookie_anchor.py` and
   `test_picks_end_to_end.py` — **both `livedata`, both deselected in
   CI**. A regression that mis-tethers every 2027 pick would ship green.
   Hardest to fixture (needs a rookie pool plus 72 slot picks), which is
   presumably why it was left to the live board.

2. **Stage 3/5 — per-source curve routing.** This branch adds guards that
   the routed scope curves share one reference denominator and that the
   ROOKIE master stays unrouted. What is still unasserted is that a
   *specific source key* routes to a *specific* curve: `_curve_for_source`
   is a **nested closure inside `_compute_unified_rankings`**, so it
   cannot be imported and called directly. Testing it properly needs
   either a per-source curve stamp on the row or lifting the closure to
   module scope. Mis-routing IDP sources to the OFFENSE master would
   shift every defender without failing anything.

3. **Stage 10 — market corridor clamp band arithmetic.**
   `test_market_corridor_clamp.py` covers anchor selection and helpers;
   the P90 drift-band computation itself is not asserted numerically.
   (Stage 10's IDP-calibration half does not exist — D-3.)

4. **Stage 6 — the pick-row anchor widening.** CLAUDE.md: "Pick rows
   widen the anchor set to include `ktcSfTep` so the two real pick
   markets average as peers." No test asserts the widened set.

5. **The Hampel filter *inside* the pipeline.** `test_hampel_filter.py`
   unit-tests the function thoroughly, but nothing asserts that a real
   outlier source is dropped from a player's blend end-to-end, or that
   `_SINGLE_SOURCE_VALUE_RETENTION` fires on a row reduced to one source
   *by Hampel* (as opposed to one that only ever had one).

6. **`server.py` at 51.8%.** Route-level behaviour for most endpoints is
   untested. Highest-value remaining targets: `_resolve_league_for_request`
   pass 3 (a user's saved `activeLeagueKey` pointing at an inactive
   league silently falls through to the default — untested), and the
   `/api/rankings/overrides` delta merge under partial source failure.

7. **`src/api/chat.py` (0%), `src/ros/sources/*` (0%).** Whole modules
   with no test. The ROS source parsers take untrusted external HTML/JSON
   — the classic place for a silent parse regression.
