# Rankings Pipeline End-to-End Fix (Round 2) — 2026-04-14

Branch: `claude/fix-rankings-player-identity-dO6wW`
Audit dataset: `exports/latest/dynasty_data_2026-04-14.json`
Rebuilt contract dump: `exports/latest/dynasty_data_rebuilt_2026-04-14.json`

This round closes out every issue the user reported on the
"improved-but-still-broken" board.  See
`docs/rankings_identity_fix_2026-04-14.md` for the round-1 (alias /
1-src / collision / chip) fixes that this round builds on.

## Root cause summary (round 2)

Five distinct pipeline bugs all surfaced as different visible
symptoms.  They were entangled — fixing the wrong one would have
patched the symptom and left the underlying mismatch in place.

### 1. The canonical-engine overlay rewrote rank with per-universe values

`server.py::_apply_canonical_primary_overlay` (the `CANONICAL_DATA_MODE=
primary` path) loaded the canonical snapshot, computed its own rank
by sorting all 1311 flattened assets by `calibrated_value`, and
**overwrote** `playersArray[i].canonicalConsensusRank` with that
per-universe rank.  Two mutually-reinforcing bugs lived in this one
function:

* The canonical snapshot has **420 duplicate player names** because
  the IDPTradeCalc combined offense + IDP value pool gets
  categorised into both the `offense_vet` and `idp_vet` universes.
  Justin Jefferson, Lamar Jackson, Trey McBride, Amon-Ra St. Brown,
  Patrick Mahomes — every offensive star — exists twice.  The
  overlay's dedup logic kept the higher-value entry but the rank
  computation could still pick a per-universe slot for a player.
* The overlay's `calibrated_value`-based ranks come from the
  canonical engine's per-universe Hill curves (offense capped at
  7800, IDP capped at 5500).  When sorted together they don't
  preserve the contract layer's blended `rankDerivedValue` ordering,
  so the rank you saw next to a row no longer matched the value
  column.

Visible symptoms:

* Amon-Ra St. Brown ranked below Justin Jefferson despite a higher
  displayed value.
* Trey McBride ranked below Lamar Jackson despite a higher displayed
  value.
* Will Anderson and Ladd McConkey both at rank 46 (one IDP, one
  offense — same per-universe slot).
* Tyler Allgeier and Chig Okonkwo both at rank 220.

### 2. The contract layer didn't re-rank after value mutation

Even without the canonical overlay, anything downstream of
`_compute_unified_rankings` that mutated `rankDerivedValue` (the
final value-bundle write back into `players_by_name`, the
quarantine/trust pass, scoring adjustments, …) could have left the
rank field stale.  There was no single invariant assertion guarding
"rank must be the position of the row in the displayed-value sort".

### 3. The frontend tier label preferred a per-universe `canonicalTierId`

`frontend/lib/rankings-helpers.js::tierLabel` and
`effectiveTierId` consulted `row.canonicalTierId` (a per-universe
field from the canonical engine snapshot) before falling back to a
rank-based tier.  On the unified offense + IDP board the per-universe
tier IDs do not align with the displayed sort order — so a row
whose displayed rank put it inside "Solid Starter" could still
inherit the canonical engine's per-universe tier 5 ("Starter"), and
the section header inserted by the row separator logic would land
in the wrong place.

This is the "STARTER section header above DEPTH-labeled rows" /
"STARTER boundary appears inserted after a player instead of before
the full tier" the user reported.

### 4. Six headline players were still 1-src because IDPTradeCalc's autocomplete missed suffix names

The headline 1-src cohort (`Kenneth Walker`, `Marvin Harrison`,
`Brian Thomas`, `Michael Penix`, `Omar Cooper`, `Travis Hunter`)
were stuck at 1-src in round 1 because the IDPTradeCalc upstream
data simply did not return them.  Tracing further:

* `Dynasty Scraper.py::scrape_idptradecalc` falls back to typing
  each missing candidate into the IDPTC search box and reading the
  result via the regex
  `rf'{last_name}\s*\((\d+)\)\s*-\s*\w+'`.
* IDPTradeCalc's autocomplete renders generational-suffix entries
  as `"Kenneth Walker III (5700) - RB"`, `"Marvin Harrison Jr (4900) - WR"`,
  etc. — the suffix sits *between* the last name and the value
  parens.  The regex's `\s*\(` requires the open-paren immediately
  after the last name, so the match silently fails for every
  suffix-bearing player.

But fixing the regex only helps **future** scraper runs.  The
current snapshot has no IDPTC values for any of these players, so
the contract layer needed actual additional offense sources.

### 5. Two well-formed offense sources were sitting unused in `data/raw/`

`data/raw/dlf_sf/2026/.../dlf_superflex.csv` (DLF SuperFlex expert
board, 278 deep) and
`data/raw/fantasycalc/2026/.../fantasyCalc.csv` (FantasyCalc retail,
~456 deep) were both being scraped and committed but **neither was
wired into `_RANKING_SOURCES`** in `src/api/data_contract.py`.  Both
include the suffix-bearing names that IDPTradeCalc drops on the
floor:

```
DLF SF:        Kenneth Walker (val 61), Marvin Harrison Jr (47.4),
               Brian Thomas (46.6), Michael Penix (98.6), Travis Hunter (82.6)
FantasyCalc:   Kenneth Walker (4249), Marvin Harrison (3517),
               Brian Thomas (3409), Omar Cooper (2305),
               Michael Penix (1815), Travis Hunter (2215)
```

Wiring them in promoted every headline player to multi-source.

## What changed

### Server (`server.py`)

* `_apply_canonical_primary_overlay` — gutted the per-universe rank
  computation entirely.  The function now overlays *only* value
  fields (`_finalAdjusted`, `_composite`, `_rawComposite`,
  `_canonicalDisplayValue`) and immediately calls the contract-layer
  helpers `resort_unified_board_by_value` + `assert_rank_value_invariants`
  so the unified rank is renumbered from the post-overlay displayed
  values.  The `computed_ranks` / `has_ccr` fallback that produced
  the per-universe rank duplication is **gone**.

### Contract pipeline (`src/api/data_contract.py`)

* New `resort_unified_board_by_value(contract)` helper renumbers
  `playersArray[*].canonicalConsensusRank` 1..N strictly by
  displayed value (descending) and mirrors the new ranks back into
  `players[name]._canonicalConsensusRank`.  Tie-breakers:
  `blendedSourceRank` ascending then `canonicalName` lower-case.
* New `assert_rank_value_invariants(contract)` raises if any two
  rows share a `canonicalConsensusRank` or if the rank order is not
  monotonically non-increasing in `rankDerivedValue`.  Called from
  `build_api_data_contract` after every rebuild and from
  `_apply_canonical_primary_overlay` after every value overlay.
* `build_api_data_contract` now calls `resort_unified_board_by_value`
  + `assert_rank_value_invariants` as its final pass.  No code
  path can serve a board whose rank disagrees with its value.
* New `_RANKING_SOURCES` entries:
  - **dlfSf** — DLF SuperFlex offense, depth 278, weight 3.0,
    backbone=False, scope=overall_offense.  Loaded from
    `exports/latest/site_raw/dlfSf.csv` as a `name,rank` CSV.
  - **fantasyCalc** — FantasyCalc retail, depth 456, weight 1.0,
    is_retail=True, scope=overall_offense.  Loaded from
    `exports/latest/site_raw/fantasyCalc.csv` as `name,value`.
* `_OFFENSE_SIGNAL_KEYS` now includes `dlfSf`, `fantasyCalc`.
* `_SOURCE_CSV_PATHS` registers both new paths.
* `_percentile_rank_spread` switched from `pcts_sorted[len/2]`
  (upper-middle bias for even-length lists) to `statistics.median()`,
  fixing the false-positive cohort that surfaced after round 1.
* `_compute_anomaly_flags` `suspicious_disagreement` rule now
  requires **both** percentile spread > 0.20 AND raw rank spread > 80
  (with drop-one-outlier when 3+ sources contribute).  Drops the
  flag count from 110 → 34 while keeping every legitimate
  disagreement (Bobby Wagner, Nick Emmanwori, Aidan Hutchinson
  vs IDPTradeCalc dynasty deflation, etc.).

### Frontend (`frontend/lib/`, `frontend/app/rankings/page.jsx`)

* `lib/rankings-helpers.js::tierLabel` — derives the label strictly
  from `row.rank` and never reads `canonicalTierId`.  Fixes the
  off-by-one tier headers.
* `lib/rankings-helpers.js::effectiveTierId` — same change for
  numeric tier ID.
* `lib/dynasty-data.js::buildRows` — the per-row sort now sorts by
  displayed value (descending) and uses the post-sort index as
  `r.rank`.  The legacy `r.rank = r.canonicalConsensusRank ??
  r.computedConsensusRank` path is gone.  Defense in depth: even if
  some payload survives a stale `canonicalConsensusRank`, the
  rendered table cannot show a rank that disagrees with its value.

### Scraper (`Dynasty Scraper.py`)

* `scrape_idptradecalc`'s autocomplete-fallback regex now allows an
  optional generational suffix between the last name and the value
  parens:
  ```python
  suffix_gap = r'(?:\s+(?:Jr\.?|Sr\.?|II|III|IV|V|VI))?'
  pattern = re.compile(
      rf'{re.escape(last_name)}{suffix_gap}\s*\((\d+)\)\s*-\s*\w+',
      re.IGNORECASE
  )
  ```
  Future runs will recover Kenneth Walker III, Marvin Harrison Jr,
  Brian Thomas Jr from the IDPTradeCalc autocomplete instead of
  silently dropping them.

### Site-raw export bundle (`exports/latest/site_raw/`)

* New `dlfSf.csv` (278 rows, `name,rank`) — generated from
  `data/raw/dlf_sf/2026/.../dlf_superflex.csv` via the existing
  `scripts/convert_dlf_csv.py` shape.
* New `fantasyCalc.csv` (456 rows, `name,value`) — copied from
  `data/raw/fantasycalc/2026/.../fantasyCalc.csv`.

## Before / after table for every named player

| Player | Before (round 1) | After (round 2) | Notes |
|---|---|---|---|
| Kenneth Walker | 1-src `{ktc:5701}` | **3-src** ktc 44, dlfSf 63, fantasyCalc 40 → #51 | DLF SF + FantasyCalc rescue |
| Marvin Harrison | 1-src `{ktc:5027}` | **3-src** ktc 61, dlfSf 43, fantasyCalc 62 → #55 | Same |
| Brian Thomas | 1-src `{ktc:4921}` | **3-src** ktc 68, dlfSf 42, fantasyCalc 67 → #60 | Same |
| Michael Penix | 1-src `{ktc:3143}` | **3-src** ktc 157, dlfSf 92, fantasyCalc 139 → #132 | Same |
| Omar Cooper | 1-src `{ktc:3571}` | **2-src** ktc 127, fantasyCalc 103 → #133 | DLF SF doesn't carry him |
| Travis Hunter | 1-src + suspicious_disagreement | **4-src** + **no flag** → #84 | Robust drop-one outlier |
| Devin Bush | 1-src | 1-src (allow-listed) | Deep veteran outside DLF top-185 |
| Quay Walker | 1-src | 2-src no near_name flag → #236 | DLF IDP enrichment (round 1) |
| Jalon Walker | 1-src | 2-src no near_name flag → #278 | Same |
| Payton Wilson | 1-src | 2-src no near_name flag → #254 | Same |
| Nick Emmanwori | 1-src | 2-src **suspicious_disagreement** kept → #193 | Real IDPTC vs DLF disagreement |
| CJ Allen | 1-src | structurally_single_source → #256 | College rookie, DLF excludes rookies |
| Caleb Downs | 1-src | structurally_single_source → #172 | Same |
| Sonny Styles | 1-src | structurally_single_source → #169 | Same |
| Arvell Reese | 1-src | structurally_single_source → #125 | Same |
| David Bailey | 1-src | structurally_single_source → #206 | Same |
| Rueben Bain | 1-src | structurally_single_source → #260 | Same |
| Dillon Thieneman | 1-src | structurally_single_source → #275 | Same |
| Emmanuel McNeil-Warren | 1-src | structurally_single_source → #279 | Same |
| Aidan Hutchinson | 1-src `{idpTC:5667}` | 2-src → #44 | Same as round 1 |
| Will Anderson | 1-src `{idpTC:5963}` | 2-src → #45 | Same as round 1 |
| Micah Parsons | 1-src `{idpTC:5404}` | 2-src → #57 | Same as round 1 |
| Carson Schwesinger | 1-src `{idpTC:5651}` | 2-src → #63 | Same |
| Jack Campbell | 1-src `{idpTC:5637}` | 2-src → #62 | Same |
| Fred Warner | 1-src `{idpTC:5409}` | 2-src → #118 | Same |
| Nick Bosa | 1-src `{idpTC:3492}` | 2-src → #99 | Same |
| Brian Burns | 1-src `{idpTC:3606}` | 2-src → #171 | Same |
| Roquan Smith | 1-src `{idpTC:3600}` | 2-src → #176 | Same |
| T.J. Watt | 1-src `{idpTC:3288}` | 2-src → #186 | Same |
| Danielle Hunter | 1-src `{idpTC:3009}` | 2-src → #230 | Same |
| Brian Branch | 1-src `{idpTC:3596}` | 2-src → #218 | Same |
| Kyle Hamilton | 1-src `{idpTC:4164}` | 2-src → #199 | Same |
| Maxx Crosby | n/a | 2-src → #93 | Same |
| Jared Verse | n/a | 2-src → #76 | Same |

## Sort + value consistency proof

`exports/latest/dynasty_data_rebuilt_2026-04-14.json` — generated by
running `build_api_data_contract` on the live snapshot, asserts:

```
totalPlayers:    1101
ranked:          800
uniqueRanks:     800   (no duplicate canonicalConsensusRank values)
monotonic:       True  (strictly non-increasing rankDerivedValue by rank)
```

Top-board (rank 1-200) source distribution after the new offense
sources are wired in:

| sourceCount | players |
|---|---|
| 4 | 129 |
| 3 | 32 |
| 2 | 36 |
| 1 | 3 (all structurally single-source rookies / depth) |

Top-board *semantic* `isSingleSource` chips: **0**.  Every player in
the top 200 either has multiple matched sources or carries the
`solo` informational chip with `structurally_single_source`
reason — no silent matching failures remain.

`assert_rank_value_invariants` is now called inside
`build_api_data_contract` and inside
`_apply_canonical_primary_overlay`, so any future regression in
either pipeline fails the build instead of silently serving a
broken board.

## Tier rendering proof

The frontend now derives `tierLabel(row)` and `effectiveTierId(row)`
strictly from `row.rank` (which itself is the post-sort index in
`buildRows`).  The page renders the section header above the first
row of each new tier, computed off the same `row.rank` source the
row badge uses.  The two cannot disagree.

Two new test pins:

* `tests/api/test_player_identity_regression.py::TestUnifiedTierDerivation`
  scans `frontend/lib/rankings-helpers.js` and asserts that
  neither `tierLabel` nor `effectiveTierId` mentions
  `canonicalTierId`.
* `tests/api/test_player_identity_regression.py::TestFrontendSortsByDisplayedValue`
  asserts the frontend builder sets `r.rank = i + 1` (post-sort
  index) and never `r.rank = r.canonicalConsensusRank`.

## Anomaly flag distribution (after round 2)

```
suspicious_disagreement: 34   (was 110 with naive percentile,
                                 was 47 in round 1)
unsupported_position:     2   (pre-existing OL contamination)
position_source_contradiction: 2  (Elijah Mitchell, Milton Williams —
                                   pre-existing Sleeper map collision)
offense_as_idp:           1
```

Real disagreements (Bobby Wagner, Nick Emmanwori, …) still surface;
mid-tier WR / TE percentile false-positives are gone.

## Test counts

* **Backend**: 973 tests (was 961 before round 2)
  + 137 sub-tests, all green.
* **Frontend**: 293 tests (was 296 — three tests merged into more
  precise replacements), all green.
* New regression file `tests/api/test_player_identity_regression.py`
  now has 38 test cases (was 26 in round 1) covering monotonicity,
  no-duplicate-ranks, named-player-promotion, identity collision,
  expected-source refinement, frontend tier-label source pinning,
  and frontend sort-by-value pinning.

## Verification chain

```bash
# 1. Backend
python3 -m pytest tests/ -q
#   → 973 passed, 137 subtests passed

# 2. Frontend
cd frontend && ./node_modules/.bin/vitest run
#   → 9 files / 293 tests passed

# 3. Build the contract from live data
python3 -c "
import json
from src.api.data_contract import build_api_data_contract
with open('exports/latest/dynasty_data_2026-04-14.json') as f:
    raw = json.load(f)
c = build_api_data_contract(raw)
# assert_rank_value_invariants is called inside build_api_data_contract;
# it raises on any duplicate or monotonicity violation
print('rebuild OK', len(c['playersArray']), 'players')
"
#   → rebuild OK 1101 players

# 4. Spot check headline players
python3 -c "
import json
from src.api.data_contract import build_api_data_contract
with open('exports/latest/dynasty_data_2026-04-14.json') as f:
    raw = json.load(f)
c = build_api_data_contract(raw)
for r in c['playersArray']:
    if r['canonicalName'] in ('Kenneth Walker','Marvin Harrison','Brian Thomas','Travis Hunter'):
        print(r['canonicalName'], 'src=', r['sourceCount'], 'rank=', r.get('canonicalConsensusRank'))
"
#   → Kenneth Walker src= 3 rank= 51
#   → Marvin Harrison src= 3 rank= 55
#   → Brian Thomas src= 3 rank= 60
#   → Travis Hunter src= 4 rank= 84
```

The live page rebuilds at every server boot via
`server.py::_prime_latest_payload` → `build_api_data_contract` →
`_apply_canonical_primary_overlay` (in primary mode) →
`resort_unified_board_by_value` → `assert_rank_value_invariants`,
so restarting the FastAPI process picks up every fix without a
re-scrape.
