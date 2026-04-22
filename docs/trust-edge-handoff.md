# Trust & Edge Layer — Implementation Handoff

Last updated: 2026-04-13

## Overview

The rankings board now exposes trust diagnostics, confidence signals, anomaly detection, identity validation, and actionable edge analysis across three surfaces: Rankings, Edge, and Finder.

Every signal traces to measurable properties of the ranking data. Nothing is predicted or editorialized.

Two IDP sources contribute today: **IDP Trade Calculator** (the shared-market
backbone — prices offense + IDP on one 0-9999 scale) and **Dynasty League
Football IDP** (a 185-player expert consensus that covers DL/LB/DB in an IDP-
only pool). The ranking pipeline treats them very differently: IDPTC pass-
through feeds the Hill curve directly, while DLF is *crosswalked* through the
shared-market IDP ladder before feeding the Hill curve. This prevents DLF
rank 1 from behaving like shared-market rank 1 (and being mapped to Hill
value 9999 as if it beat every offense player) — see "IDP Shared-Market
Crosswalk" below.

---

## Contract Fields (per player)

Source of truth: `src/api/data_contract.py` (`_compute_unified_rankings` + `_validate_and_quarantine_rows`)

Frontend consumer: `frontend/lib/dynasty-data.js` (`buildRows` + `computeUnifiedRanks`)

| Field | Type | Description |
|---|---|---|
| `confidenceBucket` | `"high"` \| `"medium"` \| `"low"` \| `"none"` | Trust tier for this ranking |
| `confidenceLabel` | string | Human-readable explanation |
| `anomalyFlags` | string[] | Machine-readable data quality flags |
| `isSingleSource` | boolean | Only one ranking source contributed |
| `hasSourceDisagreement` | boolean | Sources diverge by >80 ordinal ranks |
| `sourceRankSpread` | number \| null | Max minus min source rank (null if 1 source) |
| `blendedSourceRank` | number \| null | Mean of per-source ordinal ranks |
| `marketGapDirection` | `"retail_premium"` \| `"consensus_premium"` \| `"none"` | Retail (sources flagged `is_retail` in the registry — today just KTC) vs mean rank of non-retail sources (expert consensus). Adding a second retail source is a pure registry change. |
| `marketGapMagnitude` | number \| null | Absolute ordinal rank difference between KTC and consensus mean |
| `identityConfidence` | float 0.0-1.0 | How confident we are this is the right entity |
| `identityMethod` | string | Method used: `canonical_id`, `position_source_aligned`, `partial_evidence`, `name_only` |
| `quarantined` | boolean | Row flagged by identity/data-quality validation |
| `droppedSources` | string[] | Source keys whose values were rejected by the per-player Hampel outlier filter (K=2.75, n>=4, 500 Hill-point absolute floor). Empty for rows where no source was dropped. |
| `effectiveSourceRanks` | object | `sourceRanks` minus any keys present in `droppedSources`. Frontend display helpers (`marketEdge`, `marketGapLabel`) read this so retail-vs-consensus edge labels stay in lockstep with backend `marketGapDirection`/`confidence`/`anomalyFlags`, all of which use the post-Hampel set. Falls back to `sourceRanks` on legacy payloads that pre-date the field. |

### Confidence Bucket Logic

Evaluated top-to-bottom, first match wins:

1. **high** — 2+ sources AND sourceRankSpread <= 30
2. **medium** — 2+ sources AND sourceRankSpread <= 80
3. **low** — single source OR sourceRankSpread > 80
4. **none** — player did not receive a unified rank

Constants: `_CONFIDENCE_SPREAD_HIGH = 30`, `_CONFIDENCE_SPREAD_MEDIUM = 80`

### Anomaly Flags

Ranking-phase flags:
- `offense_as_idp` — offense player with only IDP source values
- `idp_as_offense` — IDP player with only offense source values
- `missing_position` — position is null, empty, or "?"
- `retired_or_invalid_name` — name matches invalid patterns
- `ol_contamination` — OL/OT/OG/C position leaked into rankings
- `suspicious_disagreement` — surviving sources disagree by >20% percentile spread (or >150 ordinal ranks for legacy callers). Computed on the *post-Hampel* set: any source dropped by the per-player outlier filter (see `droppedSources`) is excluded from the spread calculation, so a single rogue value cannot trip the flag if the rest of the field agrees.
- `missing_source_distortion` — single source when dual expected
- `impossible_value` — rankDerivedValue <= 0 despite having a rank

Identity-validation flags (trigger quarantine):
- `name_collision_cross_universe` — same normalized name in offense + IDP
- `position_source_contradiction` — position disagrees with source evidence
- `near_name_value_mismatch` — same surname, different universes, wild value gap
- `unsupported_position` — not in QB/RB/WR/TE/DL/LB/DB/PICK
- `no_valid_source_values` — no sources > 0 but has derived value
- `orphan_csv_graft` — value from CSV enrichment for wrong entity

### Quarantine

Any flag in `_QUARANTINE_FLAGS` set triggers `quarantined = true` and degrades `confidenceBucket` to `"low"`. Quarantined rows remain in the dataset — they are dimmed in the UI, not removed.

### `OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS`

A narrow override list for verified cross-universe name collisions where
the same display name legitimately refers to two different people across
the offense and IDP universes (e.g. "Josh Johnson" — retired QB vs draftable
DB prospect).

**The exception is conditional**: it only suppresses
`position_source_contradiction` on a row that has *also* tripped
`name_collision_cross_universe` in Check 1. A false-positive contradiction
on a non-colliding name will still fire as before — the exception list
cannot mask genuine data-quality errors anymore. Before adding a new
entry, verify the contradiction survives a full rebuild with the
normalised `_canonical_match_key` join in place: historical
contradictions were almost entirely punctuation join artefacts
(`T.J. Watt` vs `TJ Watt`) and do not reproduce after the hygiene fix.

### IDP Shared-Market Crosswalk

IDPTradeCalc prices offense + IDP on a single 0-9999 scale, so its
ordinal rank is computed over the full combined pool. Its #1 IDP might
sit at combined-pool rank ~40 because 39 offense players out-price it
in the backbone source. That's the correct behaviour — feeding that 40
into the Hill curve gives the right relative value for the best IDP on
the shared offense+IDP economy.

DLF, in contrast, only ranks IDPs. Its raw board ordinal says "best IDP
= rank 1", which — fed directly to the Hill curve — would produce value
9999 as if the best IDP were also the best asset in the whole dynasty
market. That's the bug the crosswalk fixes.

The crosswalk is built in `src/canonical/idp_backbone.py` as a
`shared_market_idp_ladder`: the i-th entry is the combined-pool rank of
the i-th best IDP in the backbone source. The builder activates the
ladder only when the caller supplies `offense_positions` to
`build_backbone_from_rows`, which the contract builder does automatically
when the backbone source declares `overall_offense` in its `extra_scopes`.

Any source flagged `needs_shared_market_translation=True` in
`_RANKING_SOURCES` (today: `dlfIdp`) has its raw IDP ordinal rank
translated through this ladder via `translate_position_rank(raw_rank,
shared_market_ladder)`. DLF rank 1 becomes the combined-pool rank of the
best IDP in IDPTC (~44 in live data), which is what actually gets fed
to the Hill curve.

- Backbone source (`idpTradeCalc`): pass-through, `method=direct`,
  `sharedMarketTranslated=false`.
- DLF (`dlfIdp`): crosswalked, `method=exact` (or
  `extrapolated` past the ladder tail), `sharedMarketTranslated=true`.
- Frontend mirror: `buildIdpBackbone(rows, sourceKey, includeSharedMarket)`
  and the `sharedMarketTranslated` meta field in
  `frontend/lib/dynasty-data.js` keep the browser-side fallback in lock
  step with the backend.

### Name join normalisation

All cross-source name joins go through `_canonical_match_key` which
wraps `src/utils/name_clean.py::normalize_player_name`. The normaliser
ASCII-folds diacritics, lowercases, strips generational suffixes
(Jr/Sr/II-VI), collapses non-alphanumerics to whitespace, and collapses
adjacent single-letter initials. The result is a single key that
treats `T.J. Watt` and `TJ Watt` as the same player, `D.J. Moore` and
`DJ Moore` as the same player, and `Marvin Harrison Jr.` and
`Marvin Harrison` as the same player.

Before this fix, `_enrich_from_source_csvs` used a suffix-strip-only
key and silently lost every player whose spelling drifted between the
scraper payload and the committed CSVs — T.J. Watt was the canonical
example (present in both DLF and IDPTC, but landed on the board as a
1-src ghost because the join failed on the period). The frontend
mirror `normalizePlayerName` in `frontend/lib/dynasty-data.js` uses the
same rules so offline fallbacks reproduce the backend join semantics.

---

## UI Surfaces

### Rankings (`/rankings`)

- **Trust bar**: aggregate stats (high/medium/low confidence, multi-source count, quarantine count)
- **Lens system**: 5 views (Consensus, Disagreements, Inefficiencies, Safest, Fragile)
- **Edge rail**: collapsible summary with top KTC/Consensus premiums, consensus assets, flagged players
- **Signal column**: per-row action labels (Market premium, Consensus asset) and stackable caution labels
- **Tier grouping**: backend canonical tiers with rank-based fallback
- **Fast-scan chips**: R (rookie), 1-src, ! (flagged), ~ (disagreement)
- **Methodology panel**: expandable 8-step explanation of ranking pipeline

### Edge (`/edge`)

Source agreement dashboard. 6 sections in a 2-column grid:
1. Consensus Assets — high confidence, multi-source, tight agreement
2. Biggest Disagreements — highest source rank spread
3. Retail Premium (today shown as "KTC Premium") — players the retail market values much higher than the expert consensus. Section title is resolved dynamically from `getRetailLabel()` in `frontend/lib/dynasty-data.js`; adding a second `isRetail` source flips the title to "Retail Premium" automatically.
4. Consensus Premium — players the expert consensus values much higher than the retail market (inverse of #3)
5. Flagged Anomalies — data quality flags in top 300
6. Single-Source Players — valued by only one source

### Finder (`/finder`)

Filter-driven player discovery with 5 preset workflows:
1. WR Gaps — WR position + source disagreement
2. Stable IDP — high confidence IDP assets
3. 1-Source Risk — single-source players
4. Rookie Spread — rookies with notable disagreement
5. All Players — custom filter exploration

Each workflow layers with position, confidence, and search filters.

---

## Shared Helper Modules

| Module | Purpose | Tests |
|---|---|---|
| `frontend/lib/edge-helpers.js` | Lens definitions, edge summary, action/caution labels | `__tests__/edge-helpers.test.js` (30 tests) |
| `frontend/lib/rankings-helpers.js` | Tier labels, value bands, fast-scan chips | `__tests__/rankings-helpers.test.js` (17 tests) |
| `frontend/lib/display-helpers.js` | Shared badge CSS classes, confidence labels, market gap labels | `__tests__/display-helpers.test.js` (18 tests) |
| `frontend/lib/dynasty-data.js` | Row building, unified ranking, rank-to-value | `__tests__/dynasty-data.test.js` + `__tests__/trust-fields.test.js` |

---

## Local Verification

### Backend tests

```bash
cd /path/to/riskittogetthebrisket
python -m pytest tests/ -q
# Trust-specific:
python -m pytest tests/api/test_trust_confidence.py -v
python -m pytest tests/api/test_identity_validation.py -v
python -m pytest tests/api/test_data_contract.py -v
```

### Frontend tests

```bash
cd frontend
npx vitest run --reporter=verbose
# Specific suites:
npx vitest run __tests__/edge-helpers.test.js
npx vitest run __tests__/trust-fields.test.js
npx vitest run __tests__/display-helpers.test.js
npx vitest run __tests__/rankings-helpers.test.js
```

### Running locally

```bash
# Terminal 1: backend
python server.py
# Terminal 2: frontend
cd frontend && npm run dev
# Visit http://localhost:3000/rankings, /edge, /finder
```

### Anomaly audit

```bash
# Check for anomaly flags in live data:
curl -s http://localhost:8000/api/data | python -c "
import json, sys
data = json.load(sys.stdin)
for p in data.get('playersArray', []):
    flags = p.get('anomalyFlags', [])
    if flags:
        print(f\"{p['canonicalName']:30} {p.get('position','?'):4} {', '.join(flags)}\")
"
```

---

## Known Pre-existing Issues

- 2 JS test failures in `dynasty-data.test.js` (`computedConsensusRank` tests) — pre-existing before trust/edge work, related to IDP rank offset calculation in the test fixture, not in production code.

## Known Data Quality Issues (current as of 2026-04-13)

### Fixed

- **T.J. Watt / T.J. Edwards / D.J. Moore / C.J. Stroud et al.** — every
  player whose scraper payload spelling differed in punctuation from the
  CSV exports was previously dropped by the enrichment join. T.J. Watt
  was the headline case: he appeared in both `exports/latest/site_raw/dlfIdp.csv`
  and `exports/latest/site_raw/idpTradeCalc.csv` as `TJ Watt`, but the
  scraper payload key was `T.J. Watt`, so the legacy
  `_strip_name_suffix(name).lower()` join produced `t.j. watt` vs
  `tj watt` and the match failed silently. Fixed by routing every join
  through `_canonical_match_key` (wrapping `normalize_player_name`),
  which collapses periods and initials consistently with the
  identity and adapter layers. The frontend mirror is
  `normalizePlayerName` in `frontend/lib/dynasty-data.js`. Regression
  tests live in `tests/api/test_name_join_hygiene.py`.
- **DLF IDP overweighting** — DLF was registered as `overall_idp`,
  which passed its raw IDP ordinal rank directly to the Hill curve as
  if it were a combined offense+IDP rank. DLF rank 1 → value 9999 inflated
  every elite IDP. Fixed by building a
  `shared_market_idp_ladder` in `src/canonical/idp_backbone.py` from the
  backbone source's combined offense+IDP ordering and translating any
  source flagged `needs_shared_market_translation` (today: DLF) through
  it via `translate_position_rank`. Top IDPs now land at consensus rank
  ~44 and below — behind offense starters who out-price them on the
  retail market — while still occupying the same top-tier value band they
  deserve within the IDP pool. Regression tests:
  `tests/canonical/test_idp_backbone.py::TestSharedMarketIdpLadder` and
  `tests/api/test_dlf_source.py::TestDlfParticipatesInUnifiedRankings::test_dlf_rank_is_mapped_through_shared_market_when_offense_present`.
- **Stale `sourceCount` on out-of-limit rows** — rows that used to land
  inside the top-800 cap and carried their (enriched) sourceCount only
  because Phase 4 stamped it. Rows past the cap retained the stale
  pre-enrichment count from `_derive_player_row`. Fixed by splitting
  Phase 4 into two sub-phases: 4a refreshes `sourceCount`,
  `isSingleSource`, and `sourcePresence` for *every* ranked row (so the
  counts always reflect post-enrichment reality), and 4b still caps the
  `canonicalConsensusRank` / value stamping at `OVERALL_RANK_LIMIT`.
- **`OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS` is now conditional** — the
  set only overrides `position_source_contradiction` on rows that also
  carry `name_collision_cross_universe` from Check 1. A false-positive
  contradiction on a non-colliding name (the old class of join
  artefact) will now fire as before. The set has been pruned to the
  single verified case (Josh Johnson: QB vs S).
- **Elijah Mitchell (DB)** — IDP DB with only KTC (offense) data. Was incorrectly excepted from `position_source_contradiction` quarantine via `OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS`. Removed from exception set so Check 2 now quarantines him correctly.
- **Bobby Brown (DL)** — IDP DL with only KTC data. Already quarantined via `near_name_value_mismatch` (Check 3).
- **Unsupported positions (OL/OT/OG/C/G/T/P/LS)** — blocked from ranking pipeline via `_RANKABLE_POSITIONS` allowlist. Frontend excludes via `classifyPos("excluded")`. Players like Nick Martin (OL) and Brandon Knight (OT) are correctly quarantined and unranked.

### Accepted / Working as Intended

- **IDP players with DLF + IDPTC both present** now carry `sourceCount=2` and
  medium/high confidence. Rows where DLF recognised a player but IDPTC did not
  remain single-source by design.
- **Will Anderson (DL)** and other elite IDPs sit around consensus rank 44 on
  the unified board — behind the top offense starters but still at a high
  Hill value (~5100). Correct behaviour: DLF rank 1 is crosswalked to the
  combined-pool rank of the best IDP, not treated as overall rank 1.
- **Travis Hunter (WR, rank ~52)** — spread=69, medium confidence, expert consensus ranks higher than KTC. Correct behavior: shows "Market premium: Consensus" signal. Market gap label is accurate.
- **~36 empty-position rows** — players with no position string. Not in any rankable set, receive no unified rank, invisible on all frontend surfaces (Rankings, Edge, Finder). Harmless.
- **126 picks** — all clean, no anomaly flags. Correctly excluded from ranking board (PICK not in `_RANKABLE_POSITIONS`) but present in data for trade calculator.

### Requires Later Data/Modeling Pass

- **Cross-universe name collisions** — when both an offense and IDP player share the same name (e.g., "James Williams"), Check 1 flags both. The scraper's name-based matching cannot distinguish them. Needs canonical player IDs (Sleeper ID, etc.) to resolve.
- **Age field** — scaffolded in contract but null for most players. Requires scraper bridge to supply age.
- **Single-source IDPs outside DLF's 185-entry board** — DLF's top-185 cap
  means any IDP deeper than DLF rank 185 is crosswalked via
  `TRANSLATION_EXTRAPOLATED`. This is safer than the old DIRECT pass-
  through but extrapolated ranks carry less confidence than exact-anchor
  ranks. A deeper DLF board would tighten this.
- **Bryan Bresee-style players with `pos=None` in the scraper** — their
  position is currently backfilled from the Sleeper positions map. When
  the scraper misses a row, we rely on the name-based Sleeper join
  remaining stable across releases.

## Intentionally Deferred

1. **League-specific trade finder** — old Finder used Sleeper rosters + `/api/trade/finder` API. Deferred until league sync is built.
2. **Percentile projection engine** — `frontend/lib/edge-detection.js` was removed (dead code, no imports). Can be rebuilt from git history if needed.
3. **Per-section filtering on Edge page** — sections show fixed top-N lists. Could add interactive filtering later.
4. **Export/copy on Edge and Finder** — available on Rankings page only.
5. **Canonical engine mode** — `CANONICAL_DATA_MODE` env var exists for gradual rollout but the canonical 6-step pipeline (`--engine canonical`) is not the default engine.
6. **Multi-source overlap** — current sources (KTC + IDPTC) cover non-overlapping pools. When overlap occurs, blended averaging is ready but untested in production.
