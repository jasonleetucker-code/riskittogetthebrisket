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
three imports (`rank_to_value`, Hill constants, and the `run_valuation`
engine used by the data contract).  The offline canonical-build
pipeline (`scripts/canonical_build.py`, `src/canonical/transform.py`,
`src/canonical/pipeline.py`) and the `CANONICAL_DATA_MODE` env var
were retired in PR #173 (2026-04-20); trade suggestions read the live
contract directly via `build_asset_pool_from_contract`.

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

### Phase 3 — Value-based direct votes + rank-only Hill + position-gated blend

For each row with any per-source rank, the blend branches on source
type:

**Step 2 — Per-source contribution.**  Two paths depending on whether
the source publishes real dollar-equivalent values or just ranks.

*Value-based sources* — keys in `_VALUE_BASED_SOURCES` (currently
``ktc``, ``idpTradeCalc``, ``dynastyDaddySf``).  These sources vote
with their raw site value, normalized so each site's top player
contributes 9999 exactly:
```
value = raw / site_max × 9999
```
where ``site_max`` is this source's largest value across the full
``playersArray`` (pre-computed once, not per-row).  Malformed /
missing raw values fall back to the Hill path below as a safety net.
Value votes bypass the Hill curve entirely — this is what the
framework override calls "don't re-model live value-site votes
through Hill."

*Rank-only sources* — ranks mapped to a percentile and then to a
value through the scope-appropriate Hill master:
```
p     = (effective_rank − 1) / denom_for(source)
value = percentile_to_value(p, midpoint=c, slope=s)
      = 9999 / (1 + (p / c)^s)
```
Denominator is ``_PERCENTILE_REFERENCE_N = 500`` for non-rookie
sources (KTC's native scale, the combined-pool coordinate) and the
source's own native pool size N_j (~40-50) for rookie sources.

**Step 2a — DraftSharks combined cross-market rank (Phase 1b).**
DS publishes offense and IDP on one cross-market scale (top offense =
100 3D Value+; top IDP = 44) but splits the CSV by position family;
~50% of rows also have negative values.  Before Phase 2-3, the blend
merges both DS sources' raw values into one sorted list, assigns a
combined rank 1..N (negatives naturally sort to the tail), and
overwrites each row's ``effectiveRank`` for both sources.  Both DS
sources then feed the **GLOBAL** Hill master via the
``ds_combined_rank_partner`` flag in the registry — the same curve
IDPTC's anchor contribution uses.  This preserves DS's native
cross-market ratio and cleanly handles the negative-value tail.

**Step 2b — Scope-master routing for rank-only sources.**

| Scope | Routing | Constants |
|---|---|---|
| GLOBAL | `is_anchor=True` (IDPTC) OR `ds_combined_rank_partner` set (DraftSharks, DraftSharksIdp) | `HILL_GLOBAL_PERCENTILE_C / _S` |
| ROOKIE | `needs_rookie_translation=True` (DLF Rookie SF, DLF Rookie IDP) | `HILL_ROOKIE_PERCENTILE_C / _S` |
| IDP | non-anchor, non-rookie, ``scope=overall_idp`` | `IDP_HILL_PERCENTILE_C / _S` |
| OFFENSE | everything else | `HILL_PERCENTILE_C / _S` |

Constants auto-refit monthly by `.github/workflows/refit-hill-curves.yml`
— see `scripts/auto_refit_hill_curves.py` for the drift threshold
(50 RMSE points on the 0-9999 scale).

TEP application on TE rows only:
- ``is_tep_premium=False`` (most sources): ``value *= 1.15`` fixed boost
- ``is_tep_premium=True`` (Dynasty Nerds SF-TEP, Yahoo Boone's TE-Prem
  column): pass-through unchanged.

**Step 3 — Soft-fallback coverage diagnostic (framework step 9,
post-override).**  For each active source whose scope admits this
player's position but which DIDN'T rank them, increment
``softFallbackCount``.  Pre-override this block injected a
"just-past-the-published-list" Hill value into the blend; that
distorted count-aware trimming when a row had ≥ 2 fallbacks (the n≥5
trim only removes one of them; the remaining fallback(s) dragged the
mean down by several hundred points — Chase at rank #5 with sf=2
lost ~600).  Post-override (2026-04-20) the blend uses covered
sources only; the count is a pure transparency metric.

**Step 4 — Position-gated blend.**  Offense rows vs IDP rows vs pick
rows split here:

- **Offense rows (QB/RB/WR/TE)**: flat count-aware mean-median over
  every covered source (value-direct contributions and rank-Hill
  contributions, equal weight).  No anchor, no α-shrinkage.

- **IDP rows (DL/LB/DB) and pick rows**: hierarchical anchor + α
  shrinkage.
  - Anchor = IDPTC's value for this row (value-direct, GLOBAL-scope).
  - Subgroup = count-aware mean-median of every non-anchor source's
    value (covered sources only).
  - Combined: ``center = anchor + α × (subgroup − anchor)`` with
    ``_ALPHA_SHRINKAGE = 0.10``.  Shrinks the subgroup adjustment
    toward the IDPTC cross-market baseline.

Count-aware blend (shared helper ``count_aware_mean_median_blend``):
- n=1: passthrough.
- n=2: mean.
- n=3-4: untrimmed — ``center = (mean + median) / 2`` over all n.
- n≥5: trimmed — drop 1 max + 1 min, then ``(trimmed_mean +
  trimmed_median) / 2``.

**Step 5 — λ·MAD retired.**  ``_MAD_PENALTY_LAMBDA = 0.0`` as of the
Final Framework override 2026-04-20: count-aware trimming (offense)
and anchor + α-shrinkage (IDP + picks) already damp disagreement;
λ·MAD on top was a duplicate penalty on the same signal.
``sourceMAD`` is still stamped as a diagnostic transparency field
(the frontend value-chain panel displays it as "source spread") but
never subtracts from ``rankDerivedValue``.

The result of Phase 3 is a pre-discount ``blended_value`` that then
enters Phase 3a (pick year discount) and Phase 4 (global sort).

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

Auto-refit is wired up for the four scope-level master Hill curves
(GLOBAL / OFFENSE / IDP / ROOKIE).  The workflow
`.github/workflows/refit-hill-curves.yml` runs on the 1st of every
month via cron (plus manual dispatch); the driver at
`scripts/auto_refit_hill_curves.py` re-fits the masters, computes
per-scope RMSE drift on a percentile grid, rewrites the constants in
`src/canonical/player_valuation.py`, and rebaselines the KTC
reconciliation test pins when max drift exceeds 50 RMSE points on
the 0-9999 scale.

Retired / archived backtest scripts:

- `scripts/archive/backtest_mad_lambda.py` — λ is pinned to 0.0;
  script is kept for historical reference only.

Live constants that are NOT auto-tuned:

- `_ALPHA_SHRINKAGE = 0.10` — IDP/pick hierarchical-blend shrinkage.
  Tuned via `scripts/backtest_alpha_shrinkage.py` (joint α × λ sweep
  in `scripts/backtest_alpha_lambda_joint.py`).
- `_PERCENTILE_REFERENCE_N = 500` — aligned with KTC's pool size.
  Re-tune via `scripts/backtest_percentile_reference_n.py` if the
  retail market's natural depth ever shifts.
- IDP calibration `family_scale` clamp `[0.85, 1.15]` — controlled by
  the IDP calibration lab in `src/idp_calibration/` and promoted via
  `config/idp_calibration.json`.
