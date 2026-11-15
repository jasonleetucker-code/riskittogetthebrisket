# Outlier-integrity-v2 root-cause reproduction (directive deliverable A)

Authority: owner directive 2026-10-20 "Fix the outlier filter and restore DLF IDP voting",
§1 and §6. This is a measurement, not a proposal. It changes no code path, no flag default
and no value. The DLF IDP hold (`dlf_offense_only_vote`) is lifted only inside the local
build process for board B, through `RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0`.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## How to reproduce

```bash
bash docs/sources/outlier_integrity_v2/rootcause/run_all.sh [OUT_DIR]
```

* Code: `f631607ff3` (origin/main when measured). Override with `CODE_SHA=`.
* Inputs: `CSVs/` and `data/` pinned to each input commit (`pin_inputs.sh`), and the
  committed `exports/latest/dynasty_data_2026-10-19.json` of that commit.

| pin | input | payload sha256 | scrape |
|---|---|---|---|
| **pin2015** (owner package) | refresh `d9680440a5` (= archive `dynasty_export_20261019_201546`) | `3ef54acd…9199` | 2026-10-19T20:15Z |
| **pin0527** (the documented 31/18/10/3) | refresh `eb10d3e12d` (= archive `dynasty_export_20261019_052349`, the V1 diagnosis board) | `b639608f…` | 2026-10-19T05:23Z |

* `rc_build.py` builds one board through `build_api_data_contract` and wraps
  `data_contract._hampel_filter_per_player` read-only: every call logs the row, every vote
  (source, value, path, method, raw and effective rank, anchor, weight), the median, MAD,
  2.75·MAD, threshold, floor binding, n and the dropped votes. The wrapper returns the
  original result unchanged, except in the diagnostic `RC_NO_IDP_FILTER=1` build, which
  stands the decision-bearing filter down on IDP rows so DLF's own vote can be separated
  from the filter's reaction. That hook exists only in this script.
* `rc_analyze.py` compares A and B. `rc_decompose.py` splits each move into DLF's own vote
  (A → Bnf) and the filter's reaction (Bnf → B) and runs exact counterfactuals with an
  independent re-implementation of the filter. `rc_tables.py` renders the vote tables.

Checks: the re-implementation reproduces every B decision (0 mismatches); rebuilding A gives
a byte-identical `playersArray`; the filter function and its constants (K 2.75, MIN_N 4,
floor 1,000) are byte-identical at every commit involved.

## Summary of the output (`output/`)

| | pin2015 | pin0527 |
|---|---|---|
| IDP rows reaching the filter, A → B | 0 → 158 | 0 → 158 |
| IDP votes dropped, A → B | 0 → 32 | 0 → 32 |
| of which DLF's own | 1 (dlfIdp, Jared Verse) | 1 (same) |
| **other-source votes dropped** | **31 on 30 rows** | **31 on 30 rows** |
| by source | Draft Sharks 18, FantasyPros 10, IDP Trade Calculator 3 | same |
| by position | LB 20, DL 9, DB 2 | same |
| offense drops, A and B | 99 and 99 (same set) | 98 and 98 (same set) |

The set of 31 (row, source) pairs is identical on both pins
(`../manifests/REGRESSION_SET.json`).

### Moves of 30% or more (pin2015)

| player | A → B | total | DLF's own vote | filter's reaction | dropped in B |
|---|---|---|---|---|---|
| Trevin Wallace | 1937 → 885 | −54.3% | −0.1% | −54.3% | Draft Sharks |
| Myles Garrett | 3555 → 5266 | +48.1% | −1.8% | +50.9% | Draft Sharks |
| CJ Allen | 3987 → 2164 | −45.7% | +0.9% | −46.2% | Draft Sharks |
| T.J. Watt | 2394 → 3431 | +43.3% | +0.7% | +42.4% | Draft Sharks |
| Josiah Trotter | 2368 → 3379 | +42.7% | +4.4% | +36.6% | FantasyPros, Draft Sharks |
| Will Anderson | 4354 → 5967 | +37.0% | +0.9% | +35.8% | Draft Sharks |
| Aidan Hutchinson | 4772 → 6422 | +34.6% | 0.0% | +34.6% | Draft Sharks |
| Danielle Hunter | 2333 → 3041 | +30.3% | −0.8% | +31.4% | Draft Sharks |

On pin0527 the seven documented 34–54% movers reproduce (Wallace 1916 → 885, Garrett
3597 → 5267, Watt 2418 → 3431, Trotter 2390 → 3379, Anderson 4395 → 5966, Hutchinson
4802 → 6422). CJ Allen's B value is 2163 against the documented 2162; the filter is
byte-identical, so the 1-point gap is attributed to the code revision and was not traced
further. Danielle Hunter crosses 30% only on the newer pin.

DLF's own vote across all 179 moved IDP rows: max 5.5%, p90 3.1%, median 1.0%. All 21 IDP
moves of 10% or more carry a filter drop.

## Root cause

1. **Board A never filters an IDP row.** IDP Show combined is freshness-withheld and DLF is
   held, so no IDP row has more than 3 voters, below the filter's minimum of 4.
2. **DLF makes n ≥ 4 on 158 rows.** Without DLF's votes the filter runs on 0 of the 30 drop
   rows. At n = 4, with votes sorted x1 ≤ x2 ≤ x3 ≤ x4, the median is (x2 + x3)/2 and
   MAD = ((x3 − x2)/2 + min(m − x1, x4 − m))/2: the farther outer vote never enters the
   scale. The closed form matches the logged MAD on every n = 4 row.
3. **The cluster is tight largely by construction.** FantasyPros IDP, DLF IDP and DLF
   Rookie IDP are priced through IDP Trade Calculator's own player order (method `exact`,
   pool `shared_market`), so equal positional ranks land on the same converted rank and the
   same value (Aidan Hutchinson: IDP Trade Calculator, DLF and FantasyPros all at converted
   rank 29). Draft Sharks is the one IDP source priced from its own combined list; it is
   the dissent on 18 of the 31 drops.
4. **The 1,000-point floor sets the band on 21 of the 30 rows** (22 of 31 with Jared Verse's row), i.e. a ~16% gap at 6,227
   and a ~50% gap at 2,000. It is not the cause: without the floor the same 31 votes drop.
5. **The dropped votes are disagreement, not corruption.** The median dropped vote sits 49%
   from the row median; no identity, scale or freshness defect was found on any of them.
6. Counting DLF's two boards as one observation rescues 4 rows (5 votes); counting identical
   values once rescues 2 rows. Both are contributors, not the driver.

### Already in production (confidence only)

The same statistic runs on production IDP rows inside the B11 lost-evidence replay (voting
votes plus the withheld IDP Show vote). On board A it rejects a vote on 28 IDP rows (Draft
Sharks 18, FantasyPros 8, IDP Trade Calculator 1, IDP Show 1). It removes no vote, but it
decides lost-evidence seats, so the defect already shapes IDP confidence.

## Files

* `run_all.sh`, `pin_inputs.sh`, `rc_build.py`, `rc_analyze.py`, `rc_decompose.py`,
  `rc_tables.py`: the reproduction.
* `output/analysis_<pin>.{json,txt}`, `output/decompose_<pin>.json`,
  `output/vote_tables_<pin>.txt`: the summarized output (full vote tables for the 31 drops
  and the focus rows). `output/inputs_<pin>.sha` is the hash of the pinned CSV + data tree
  listing. The full per-build logs (~7 MB each) are not committed; `run_all.sh` regenerates
  them.
