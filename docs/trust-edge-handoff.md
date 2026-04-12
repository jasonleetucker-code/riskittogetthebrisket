# Trust & Edge Layer — Implementation Handoff

Last updated: 2026-04-09

## Overview

The rankings board now exposes trust diagnostics, confidence signals, anomaly detection, identity validation, and actionable edge analysis across three surfaces: Rankings, Edge, and Finder.

Every signal traces to measurable properties of the ranking data. Nothing is predicted or editorialized.

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
| `marketGapDirection` | `"ktc_premium"` \| `"consensus_premium"` \| `"none"` | KTC (retail) vs mean rank of other sources (expert consensus) |
| `marketGapMagnitude` | number \| null | Absolute ordinal rank difference between KTC and consensus mean |
| `identityConfidence` | float 0.0-1.0 | How confident we are this is the right entity |
| `identityMethod` | string | Method used: `canonical_id`, `position_source_aligned`, `partial_evidence`, `name_only` |
| `quarantined` | boolean | Row flagged by identity/data-quality validation |

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
- `suspicious_disagreement` — sources disagree by >150 ordinal ranks
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
3. KTC Premium — players KTC (retail market) values much higher than the expert consensus
4. Consensus Premium — players the expert consensus values much higher than KTC
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

## Known Data Quality Issues (current as of 2026-04-09)

### Fixed

- **Elijah Mitchell (DB)** — IDP DB with only KTC (offense) data. Was incorrectly excepted from `position_source_contradiction` quarantine via `OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS`. Removed from exception set so Check 2 now quarantines him correctly.
- **Bobby Brown (DL)** — IDP DL with only KTC data. Already quarantined via `near_name_value_mismatch` (Check 3). Also in `OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS` but quarantine fires through another path.
- **Unsupported positions (OL/OT/OG/C/G/T/P/LS)** — blocked from ranking pipeline via `_RANKABLE_POSITIONS` allowlist. Frontend excludes via `classifyPos("excluded")`. Players like Nick Martin (OL) and Brandon Knight (OT) are correctly quarantined and unranked.

### Accepted / Working as Intended

- **All IDP players are single-source / low confidence** — expected since only one IDP source (IDPTradeCalc) currently feeds the pipeline. Will self-correct when a second IDP source is added.
- **Will Anderson (DL, rank ~38)** — single-source IDP with high value. Correct behavior: ranked from IDPTC, low confidence since only one source.
- **Travis Hunter (WR, rank ~52)** — spread=69, medium confidence, expert consensus ranks higher than KTC. Correct behavior: shows "Market premium: Consensus" signal. Market gap label is accurate.
- **~36 empty-position rows** — players with no position string. Not in any rankable set, receive no unified rank, invisible on all frontend surfaces (Rankings, Edge, Finder). Harmless.
- **126 picks** — all clean, no anomaly flags. Correctly excluded from ranking board (PICK not in `_RANKABLE_POSITIONS`) but present in data for trade calculator.

### Requires Later Data/Modeling Pass

- **`OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS` set** — 4 remaining names (Bobby Brown, Cameron Young, Dwight Bentley, Josh Johnson). Only Bobby Brown exists in current data; others are phantom entries. The exception set should ideally be conditional: only apply when both universe versions of a player exist. Currently it's a static name list that may mask future contamination.
- **Cross-universe name collisions** — when both an offense and IDP player share the same name (e.g., "James Williams"), Check 1 flags both. The scraper's name-based matching cannot distinguish them. Needs canonical player IDs (Sleeper ID, etc.) to resolve.
- **Age field** — scaffolded in contract but null for most players. Requires scraper bridge to supply age.
- **Single-source value stability** — single-source players have no spread/agreement signal. Their rank position is entirely determined by one market. No mitigation possible until a second source covers the same pool.

## Intentionally Deferred

1. **League-specific trade finder** — old Finder used Sleeper rosters + `/api/trade/finder` API. Deferred until league sync is built.
2. **Percentile projection engine** — `frontend/lib/edge-detection.js` was removed (dead code, no imports). Can be rebuilt from git history if needed.
3. **Per-section filtering on Edge page** — sections show fixed top-N lists. Could add interactive filtering later.
4. **Export/copy on Edge and Finder** — available on Rankings page only.
5. **Canonical engine mode** — `CANONICAL_DATA_MODE` env var exists for gradual rollout but the canonical 6-step pipeline (`--engine canonical`) is not the default engine.
6. **Multi-source overlap** — current sources (KTC + IDPTC) cover non-overlapping pools. When overlap occurs, blended averaging is ready but untested in production.
