# Live Value Pipeline Trace

Codified from the 2026-04-20 pipeline audit.  This is a reference for
what actually runs in production, not a design document.  When the
pipeline changes, update this doc.  When this doc drifts from the
code, trust the code.

**Verified against the tree on 2026-08-05.**  "Trust the code" was the
only defence this file had, and it is not one — the doc had drifted far
enough to describe a removed pipeline stage as live and to advertise an
auto-commit path ADR-008 deleted, and nothing measured the gap.
`tests/docs/test_pipeline_trace_matches_tree.py` now does: it diffs the
source table against `_RANKING_SOURCES` and fails on any repo path this
file cites that does not exist.

One thing it deliberately does **not** check: the `Lnnnn` line
references throughout.  They were accurate on 2026-04-20 and `main`
has moved several hundred commits since, so treat them as approximate
pointers to a section, never as addresses.  Pinning them would fail on
every unrelated edit and teach people to re-baseline the guard.

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
what `data_contract.py` imports from `player_valuation.py`:

- `percentile_to_value` + the eight `HILL_*_PERCENTILE_C/S` scope
  masters — step 2→3 of the blend,
- `detect_tiers` (returning `TierBoundary`) — tier ids,
- `rank_to_value` / `rank_to_value_for_scope` — used **only** by the
  reconstruction fallbacks in `terminal.py` and `rank_history.py`, not
  by the blend.

> **Corrected 2026-07-29 audit.** This paragraph used to name
> "`run_valuation`, the engine used by the data contract" as one of the
> three live imports. That was never true of the current pipeline —
> `data_contract.py` contains zero references to `run_valuation` — and
> the function has now been deleted along with the rest of the retired
> offline engine (it had no production importer at all). Do not confuse
> it with the live, unrelated `src/bdvm/service.py::run_valuation`.

The offline canonical-build pipeline (`scripts/canonical_build.py`,
`src/canonical/transform.py`, `src/canonical/pipeline.py`) and the
`CANONICAL_DATA_MODE` env var were retired in PR #173 (2026-04-20);
trade suggestions read the live contract directly via
`build_asset_pool_from_contract`.

## Data sources (live)

Declared in `_RANKING_SOURCES` at `src/api/data_contract.py:674`.
Each source stamps `sourceRanks[source_key]` and
`canonicalSiteValues[source_key]` on every matched player row.

Regenerated from the registry on 2026-08-05.  The table this replaced
listed 16 sources against a registry of 21: it invented three
(`ktc`, `footballGuysSf`, `footballGuysIdp` — none are registry keys),
omitted eight including the **anchor** `ktcSfTep`, and gave
`idpTradeCalc` a weight of **2.0** when every registry weight is 1.0 by
policy.  Pinned against the registry by
`tests/docs/test_pipeline_trace_matches_tree.py`.

| Key | Scope | Weight | Depth | Flags |
|---|---|---|---|---|
| `dlfIdp` | overall_idp | 1.0 | 185 | `rank_signal`, `shared_market_translation`, `excludes_rookies` |
| `dlfRookieIdp` | overall_idp | 1.0 | 50 | `rank_signal` |
| `draftSharksIdp` | overall_idp | 1.0 | 400 | — |
| `fantasyProsIdp` | overall_idp | 1.0 | 100 | `rank_signal`, `shared_market_translation`, `excludes_rookies` |
| `idpShowCombined` | overall_idp (+ overall_offense) | 1.0 | 450 | `rank_signal` |
| `idpTradeCalc` | overall_idp (+ overall_offense) | 1.0 | — | `backbone`, `tep_premium` |
| `dlfRookieSf` | overall_offense | 1.0 | 50 | `rank_signal` |
| `dlfSf` | overall_offense | 1.0 | 280 | `rank_signal` |
| `draftSharks` | overall_offense | 1.0 | 500 | `tep_premium` |
| `dynastyDaddySf` | overall_offense | 1.0 | 320 | `rank_signal` |
| `dynastyNerdsSfTep` | overall_offense | 1.0 | 300 | `tep_premium`, `rank_signal` |
| `fantasyCalc` | overall_offense | 1.0 | 450 | `rank_signal` |
| `fantasyNavigatorSf` | overall_offense | 1.0 | 460 | `rank_signal` |
| `fantasyProsFitzmaurice` | overall_offense | 1.0 | 350 | `tep_premium`, `rank_signal` |
| `fantasyProsSf` | overall_offense | 1.0 | 250 | `rank_signal` |
| `flockFantasySf` | overall_offense | 1.0 | 370 | `rank_signal` |
| `flockFantasySfRookies` | overall_offense | 1.0 | 50 | `rank_signal` |
| `ktcSfTep` | overall_offense | 1.0 | — | `retail`, `tep_premium` |
| `otcffbSf` | overall_offense | 1.0 | 460 | `rank_signal` |
| `pfkDynasty` | overall_offense | 1.0 | 460 | `rank_signal` |
| `yahooBoone` | overall_offense | 1.0 | 500 | `tep_premium`, `rank_signal` |

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

Constants are refit **weekly** (Tue 06:17 UTC) by
`.github/workflows/refit-hill-curves.yml`, which produces a CHALLENGER
and stops — see "Re-tuning the constants" below.  It does not write
`src/canonical/player_valuation.py`.

TEP application on TE rows only.  The flat ``value *= 1.15`` this
section used to describe was replaced on 2026-07-27 by ADR-015
(`docs/league-intelligence/DECISIONS.md`): non-TEP TE rows are lifted
onto the board's basis through
``src/league_intel/te_premium.convert_te_value``, KTC's own measured
uplift (1.209 at the top of the board, rising toward 2.05 down it).
- ``isTepPremium=False``: measured base -> tepp conversion.
- ``isTepPremium=True``: TEP-native, keeps the flat 1.10 nudge.
- ``ktc`` / ``ktcSfTep``: exempt — the anchor IS the TE++ board.
Rollback: ``RISKIT_FEATURE_TE_BASIS_CONVERSION=0``.

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
λ·MAD on top was a duplicate penalty on the same signal.  The
diagnostic statistic itself (mean absolute deviation of per-source
value contributions around the trimmed center) is still stamped on
every multi-source row as ``sourceSpread`` (renamed from
``sourceMAD`` 2026-04-20 for clarity) and surfaced in the frontend
value-chain panel, but it never subtracts from ``rankDerivedValue``.

The result of Phase 3 is a pre-discount ``blended_value`` that then
enters Phase 3a (pick year discount) and Phase 4 (global sort).

### Phase 3a — Pick year discount (L4739)

Multiplicative future-year discount applied to pick rows only.  Config
at `config/weights/pick_year_discount.json` — this doc said
`config/promotion/...`, a directory that does not exist.

### Phase 4 — Global sort + stamp (L4744-4983)

Sort descending by blended value, tiebreak by name.  Assign
`canonicalConsensusRank`.  Stamp all value, rank, confidence, and
audit fields.

### Phase 4b — Pre-calibration snapshot (L4999-5012)

Snapshot `rankDerivedValue` into `rankDerivedValueUncalibrated` and
`canonicalConsensusRank` into `canonicalConsensusRankUncalibrated`.

### Phase 4c — IDP calibration (REMOVED)

**This stage does not exist.**  `_apply_idp_calibration_post_pass` is
not in the tree, nor is `config/idp_calibration.json`,
`src/idp_calibration/`, or `tests/idp_calibration/`.  CLAUDE.md records
the removal ("the Phase 4c: removed note in `data_contract.py`");
this doc kept describing the stage as live, with line numbers, stamped
fields and a regression test — the most convincing possible account of
a thing that isn't there.

`rankDerivedValue` is the canonical-pipeline output with **no
post-blend IDP adjustment**.

Phase 4b's `rankDerivedValueUncalibrated` /
`canonicalConsensusRankUncalibrated` snapshot is therefore a copy of
values nothing subsequently calibrates.

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
- `tests/api/test_pick_refinement.py::TestPlayerRankingsUnchanged` —
  invariant bands on 10 offense + 6 IDP anchor players.

## Re-tuning the constants

The four scope-level master Hill curves (GLOBAL / OFFENSE / IDP /
ROOKIE) are refit weekly by `.github/workflows/refit-hill-curves.yml`
(cron `17 6 * * 2`, plus manual dispatch).

**The refit does not ship anything.**  `scripts/auto_refit_hill_curves.py`
fits a CHALLENGER, scores champion and challenger on dynasty boards the
fit never reads (`src/model_registry/holdout.py`), records the verdict
in `config/model_registry/`, and exits — 0 champion stands, 1
challenger is promotable, 3 regression alarm.  Production constants
move only via `scripts/model_registry.py promote` + `apply`, run by a
human.

This section previously described the opposite: that the workflow
"rewrites the constants in `src/canonical/player_valuation.py`, and
rebaselines the KTC reconciliation test pins when max drift exceeds 50
RMSE points".  That is precisely the auto-commit path **ADR-008
(`docs/roster-trade-intelligence/DECISIONS.md`) removed** — an
automation that edits production constants *and* re-baselines its own
guard has no adversary left.  A reader trusting this paragraph would
have concluded the promotion gate they are about to bypass does not
exist.  (Cite ADR-008 with its file: the numbering collides with a
different ADR-008 in `docs/league-intelligence/DECISIONS.md`.)

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
(An entry for the IDP calibration `family_scale` clamp used to sit
here, pointing at `src/idp_calibration/` and `config/idp_calibration.json`.
Neither path exists — see Phase 4c above.)
