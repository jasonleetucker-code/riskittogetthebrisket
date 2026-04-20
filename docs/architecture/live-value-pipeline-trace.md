# Live Value Pipeline Trace

Codified from the 2026-04-20 pipeline audit.  This is a reference for
what actually runs in production, not a design document.  When the
pipeline changes, update this doc.  When this doc drifts from the
code, trust the code.

## Live path

```
scraper bundle (dynasty_data_YYYY-MM-DD.json)
        │
        ▼
server.py::_prime_latest_payload
        │
        ▼
src/api/data_contract.py::build_api_data_contract
        │
        ▼
src/api/data_contract.py::_compute_unified_rankings   ← core value engine
        │
        ▼
/api/data, /api/rankings/overrides                     ← contract v2026-03-10.v2
```

The `src/canonical/*` modules are **NOT** on the live path except for
three imports (`rank_to_value`, Hill constants, `detect_tiers`).  The
full 6-step canonical engine runs only via
`scripts/canonical_build.py --engine canonical` or the shadow
comparison (`CANONICAL_DATA_MODE` != `off`, default `off`).

## Data sources (live)

Declared in `_RANKING_SOURCES` at `src/api/data_contract.py:674`.
Each source stamps `sourceRanks[source_key]` and
`canonicalSiteValues[source_key]` on every matched player row.

| Key | Scope | Weight | Depth | Special flags |
|---|---|---|---|---|
| `ktc` | overall_offense | 1.0 | — | `is_retail` |
| `idpTradeCalc` | overall_idp (+ offense extra_scope) | **2.0** | — | `is_backbone`, dual-scope |
| `dlfIdp` | overall_idp | 1.0 | 185 | `shared_market_translation`, `excludes_rookies` |
| `dlfSf` | overall_offense | 1.0 | 280 | |
| `dynastyNerdsSfTep` | overall_offense | 1.0 | 300 | `is_tep_premium` |
| `fantasyProsSf` | overall_offense | 1.0 | 250 | |
| `dynastyDaddySf` | overall_offense | 1.0 | 320 | |
| `fantasyProsIdp` | overall_idp | 1.0 | 100 | `shared_market_translation`, `excludes_rookies` |
| `flockFantasySf` | overall_offense | 1.0 | 370 | |
| `footballGuysSf` | overall_offense | 1.0 | 500 | |
| `footballGuysIdp` | overall_idp | 1.0 | 400 | `shared_market_translation` |
| `yahooBoone` | overall_offense | 1.0 | 500 | `is_tep_premium` |
| `dlfRookieSf` | overall_offense | 1.0 | 50 | `rookie_translation` (KTC anchor) |
| `dlfRookieIdp` | overall_idp | 1.0 | 50 | `rookie_translation` (IDPTC anchor) |
| `draftSharks` | overall_offense | 1.0 | 500 | |
| `draftSharksIdp` | overall_idp | 1.0 | 400 | |

## Ingestion

1. Per-source scripts (`scripts/fetch_*.py`, `Dynasty Scraper.py`) write
   per-source CSVs to `CSVs/site_raw/<key>.csv`.
2. The scraper bundle is pickled into `exports/latest/dynasty_data_*.json`
   and served as `data` to `_prime_latest_payload` at startup.
3. Per-source CSVs are re-read at contract build time by
   `_enrich_from_source_csvs` (`src/api/data_contract.py:2632`).  Canonical
   join key: `_canonical_match_key(name)` + position group.
4. Universe classification is **position-driven**, not source-bucket-driven.
   `_scope_eligible(pos, scope, position_group)` at
   `src/api/data_contract.py:1229` reads `row["position"]`.
   `_derive_player_row` reconciles sleeper-map position + adapter
   position + signal presence with an explicit guardrail for name
   collisions.

## Build phases (`_compute_unified_rankings`)

Phase numbering matches the source comments.

### Phase -1 — TEP-premium resolution (L5598-5644)

`_derive_tep_multiplier_from_league` reads Sleeper `bonus_rec_te`:
- `bonus_rec_te == 0.5` → `tep_multiplier = 1.15`
- `bonus_rec_te == 0` → `tep_multiplier = 1.0`

`tep_native_correction = tep_multiplier / _TEP_NATIVE_ASSUMED_MULTIPLIER`
(1.15 assumed baked into TEP-native sources).

### Phase 0 — Row construction (L5656-5724)

- `_derive_player_row` constructs one row per player.
- `_enrich_from_source_csvs` grafts per-source values and returns `csv_index`.
- `_strip_mismatched_family_tags` re-classifies offense/IDP after enrichment.

### Phase 1 — IDP backbone + shared-market ladder (L4334-4362)

First active source with `is_backbone=True` and `scope=overall_idp`
(IDPTC) builds the ladder.  `shared_idp_ladder()` crosswalks
within-IDP rank into combined offense+IDP pool rank.

### Phase 2 — Per-source ordinal assignment (L4418-4578)

For each active source:
1. Gather eligible rows across all declared scopes into one pool.
2. Sort by raw value desc, tiebreak by lowercased canonical name.
3. Dense-rank.
4. Apply rookie-exclusion self-correct: `excludes_rookies` sources
   drop rookie rows ranked beyond the bottom 20% of their pool.
5. Translate raw rank → effective rank via:
   - `position_idp` → `backbone.ladder_for(position_group)`
   - `needs_shared_market_translation` IDP → `shared_market_ladder`
   - `needs_rookie_translation` → rookie ladder (KTC for offense,
     IDPTC for IDP)
   - everything else → direct passthrough

### Phase 3 — Percentile Hill + hierarchical anchor + MAD penalty

For each row with any per-source rank:

**Step 2 — Per-source percentile (framework step 1):**
```
p = (effective_rank − 1) / (_PERCENTILE_REFERENCE_N − 1)
```
`_PERCENTILE_REFERENCE_N = 500` (KTC's native pool size, the retail
market's natural scale).  Effective ranks are post-ladder, so every
source contributes in the same combined-pool coordinate system.

**Step 3 — Percentile-to-value Hill (framework step 3):**
```
value = percentile_to_value(p, midpoint=c, slope=s)
      = 9999 / (1 + (p / c)^s)
```
**Scope-level master curves (updated framework)**: each source's
contribution uses its SCOPE-appropriate master, not the player's
position family.  Three masters:

| Scope | Routing | Constants | Fit source(s) |
|---|---|---|---|
| GLOBAL | anchor source (`is_anchor=True` — IDPTC) | `HILL_GLOBAL_PERCENTILE_C=0.1880`, `_S=0.780` | IDPTC's combined offense+IDP pool |
| OFFENSE | non-anchor sources with offense scope | `HILL_PERCENTILE_C=0.1100`, `_S=1.210` | mean-of-curves from KTC + DynastyDaddy + DynastyNerds |
| IDP | non-anchor sources with IDP scope | `IDP_HILL_PERCENTILE_C=0.1130`, `_S=0.850` | IDPTC's IDP slice |

Fit methodology (see `scripts/fit_hill_curve_percentile.py`):
1. Fit each value-based source's implied Hill curve individually.
2. For each scope, combine the per-source curves via unweighted mean
   of V_j(p) at every percentile p.
3. Fit a single Hill against the resulting master (p, V*(p)) curve.

The per-source-then-combine methodology replaced the older pooled-fit
(which weighted sources by their data-point count).  Under the updated
framework, each source is the training set for its scope master.

TEP application on TE rows only:
- `is_tep_premium=False` sources: `value *= tep_multiplier`
- `is_tep_premium=True` sources: `value *= tep_native_correction`

**Step 4a — Soft fallback (framework step 9):**
For each active source whose scope admits this player's position but
which DIDN'T rank them, synthesize a "just past the published list"
contribution:
```
fallback_rank = pool_size + round(pool_size * _SOFT_FALLBACK_DISTANCE)
fallback_V    = percentile_to_value(
                    (fallback_rank - 1) / (_PERCENTILE_REFERENCE_N - 1),
                    midpoint=hill_c, slope=hill_s
                )
```
`_SOFT_FALLBACK_DISTANCE = 0.0` (fallback = pool + 1, the slot just
past the source's list — 79% stability improvement over disabled per
the backtest; see `reports/soft_fallback_backtest_full.md`).  Every
fallback contribution enters the blend exactly like a real source
contribution.  The per-row `softFallbackCount` stamp tells the
frontend how many sources contributed via fallback.

**Step 4b — Hierarchical anchor + subgroup (framework steps 5, 7, 8):**
- **Anchor source**: the single source with `is_anchor=True` in
  `_RANKING_SOURCES` (currently IDPTC, because it prices both
  offense and IDP on a shared combined pool).
  `anchor_value` = IDPTC's value for the player (real rank if
  covered, otherwise the soft-fallback value).
- **Subgroup blend**: the unweighted trimmed mean-median (framework
  step 5) of every non-anchor source's value (real or fallback).
  - For ≥ 3 subgroup sources: drop highest + lowest, average
    `(trimmed_mean + trimmed_median) / 2`.
  - For 2: mean.
  - For 1: passthrough.
- **α-shrinkage combine** (framework step 8):
  ```
  center = anchor_value + α · (subgroup_blend − anchor_value)
  ```
  `_ALPHA_SHRINKAGE = 0.3` (chosen via
  `scripts/backtest_alpha_shrinkage.py`; clean unimodal optimum on
  both unweighted and value-weighted rank stability).

**Step 5 — MAD volatility penalty (framework step 6):**
- `MAD = mean(|v − trimmed_mean| for v in trimmed)` across the full
  set of contributing per-source values (anchor + subgroup).
- `penalty = min(center, λ · MAD)` — clamped so blended never goes
  negative.
- `final = center − penalty` (players), or `final = center` (picks —
  exempt because pick-tier MAD is a structural artifact of KTC vs
  IDPTC using different tier systems, not true source uncertainty).
- `λ = _MAD_PENALTY_LAMBDA = 0.5`.

Per-row diagnostics: `sourceMAD` and `madPenaltyApplied` are stamped
on every multi-source non-pick row.  Per-source meta includes
`percentile`, `valueContribution`, and `isAnchor` stamps so the
frontend value-chain can show the hierarchy transparently.

The previous `rank_to_value`-based blend has been retired from the
live path.  The function remains in `src/canonical/player_valuation.py`
for the canonical-engine alternate path.

### Phase 3a — Pick year discount (L4739)

Multiplicative future-year discount applied to pick rows only.  Config
at `config/promotion/pick_year_discount.json`.

### Phase 4 — Global sort + stamp (L4744-4983)

Sort descending by blended value, tiebreak by name.  Assign
`canonicalConsensusRank`.  Stamp all value, rank, confidence, and
audit fields.

### Phase 4b — Pre-calibration snapshot (L4999-5012)

Snapshot `rankDerivedValue` into `rankDerivedValueUncalibrated` and
`canonicalConsensusRank` into `canonicalConsensusRankUncalibrated`.

### Phase 4c — IDP calibration (L5014)

`_apply_idp_calibration_post_pass`:
- Strict no-op when `config/idp_calibration.json` absent.
- When active, multiplies IDP `rankDerivedValue` by
  `get_idp_bucket_multiplier(pos, position_rank, mode)` which already
  folds `family_scale` into its return value.
- `idpCalibrationMultiplier` stamped = pure bucket component.
- `idpFamilyScale` stamped = family scalar.
- Combined factor applied **once** (see load-bearing comment at
  `src/api/data_contract.py:3186-3195`; regression test at
  `tests/idp_calibration/test_family_scale_once_only.py`).

Offense calibration is **commented out** at L5021.  Regression test
at `tests/api/test_single_curve_live.py` asserts no offense row
carries `offenseCalibrationMultiplier`.

### Phase 4d — Volatility compression (REMOVED)

The prior ±8% compress/boost post-pass and its 75-point monotonicity
cap were removed in PR 1.  Replaced in PR 2 by the MAD penalty
integrated directly into the Phase 3 blend (see above).

Fields `preVolatilityValue` and `volatilityCompressionApplied` are no
longer stamped.

### Phase 5 — Pick refinement + recompact (L5040-5111)

1. `_reassign_pick_slot_order` — monotonic slot order within (year,
   round).
2. `_suppress_generic_pick_tiers_when_slots_exist` — hide "2026 Early
   1st" when "2026 Pick 1.01" exists.
3. `_anchor_current_year_picks_to_rookies` — slot picks inherit the
   nth merged-rookie `rankDerivedValue` at roster-count-aware index.
4. Re-sort by `-rankDerivedValue`, compact ranks, clear ranks of
   slot-specific picks so they don't consume rank slots.
5. `_compute_value_based_tier_ids` — rolling-median-normalized gap
   detection on the compacted value series.

### Phase 5b — Identity quarantine (L5761)

`_validate_and_quarantine_rows` degrades `confidenceBucket` for
suspicious rows.  Never removes rows.

### Phase 6 — Mirror + value-authority (L5769-5770)

Mirror canonical fields into the legacy `players_by_name` dict so the
runtime view (`/api/data?view=app`) still has per-row data after
`playersArray` is stripped.

## Outputs

- `rankDerivedValue` — authoritative display value (1..9999)
- `canonicalConsensusRank` — authoritative rank (1..N)
- `canonicalTierId` — value-gap-detected tier index
- `rankDerivedValueUncalibrated` — pre-IDP-calibration snapshot
- `sourceRanks`, `sourceRankMeta` — per-source transparency
- `confidenceBucket`, `confidenceLabel` — display badge
- `anomalyFlags` — diagnostic flags
- `marketGap*` — KTC retail vs rest arbitrage signal
- `sourceAudit` — coverage + allowlist block

The chain identity (pinned in `tests/api/test_single_curve_live.py`):

```
For each source: V = percentile_to_value((rank-1)/(N-1)), post-TEP
anchor_value     = V from the anchor source (IDPTC)
subgroup_blend   = trimmed_mean_median(V for every non-anchor source)
center           = anchor_value + α·(subgroup_blend − anchor_value)
rankDerivedValueUncalibrated = center − λ·MAD          ← players only
                               = center                ← picks (exempt)
    × (idpCalibrationMultiplier × idpFamilyScale)      ← IDP only, if active
    = rankDerivedValue
```

## Regression tests pinning this pipeline

- `tests/canonical/test_ktc_reconciliation.py` — Hill vs KTC at 10
  pinned ranks with tiered tolerance (±2/±3/±10 pp).
- `tests/canonical/test_canonical_single_curve.py` — canonical engine's
  single-pass invariant + double-calibration guard.
- `tests/api/test_single_curve_live.py` — live chain identity
  (calibration × volatility) and no offense calibration leakage.
- `tests/idp_calibration/test_family_scale_once_only.py` — family_scale
  folded exactly once.
- `tests/api/test_pick_refinement.py::TestPlayerRankingsUnchanged` —
  invariant bands on 10 offense + 6 IDP anchor players.

## Re-tuning the constants

The backtest harnesses that exercise these constants:

- `scripts/backtest_mad_lambda.py` — sweeps `_MAD_PENALTY_LAMBDA`.
  Output: `reports/mad_lambda_backtest_full.md`.
- `scripts/backtest_ktc_volatility.py` — empirical KTC drift bands per
  rank.  Output: `reports/ktc_volatility_backtest_full.md`.

`HILL_MIDPOINT` / `HILL_SLOPE` / `IDP_HILL_*` are fit by
`scripts/fit_hill_curve_from_market.py` against the market-source
pool.  A re-fit is a deliberate decision — the KTC reconciliation test
will fail loudly and must be re-baselined as part of the PR.
