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
| `marketGapDirection` | `"ktc_higher"` \| `"idptc_higher"` \| `"none"` | Which source ranks the player higher |
| `marketGapMagnitude` | number \| null | Absolute ordinal rank difference |
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
- **Edge rail**: collapsible summary with top KTC/IDPTC premiums, consensus assets, flagged players
- **Signal column**: per-row action labels (Market premium, Consensus asset) and stackable caution labels
- **Tier grouping**: backend canonical tiers with rank-based fallback
- **Fast-scan chips**: R (rookie), 1-src, ! (flagged), ~ (disagreement)
- **Methodology panel**: expandable 8-step explanation of ranking pipeline

### Edge (`/edge`)

Source agreement dashboard. 6 sections in a 2-column grid:
1. Consensus Assets — high confidence, multi-source, tight agreement
2. Biggest Disagreements — highest source rank spread
3. KTC Premium — players KTC values much higher
4. IDPTC Premium — players IDPTC values much higher
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

- 2 JS test failures in `dynasty-data.test.js` (`computedConsensusRank` tests) — pre-existing before this work, related to IDP rank offset calculation in the test fixture, not in production code.

## Intentionally Deferred

1. **League-specific trade finder** — old Finder used Sleeper rosters + `/api/trade/finder` API. Deferred until league sync is built.
2. **Percentile projection engine** — `frontend/lib/edge-detection.js` still exists but is no longer imported by any page. Kept for potential future use; migration test still asserts its existence.
3. **Per-section filtering on Edge page** — sections show fixed top-N lists. Could add interactive filtering later.
4. **Export/copy on Edge and Finder** — available on Rankings page only.
5. **Age field population** — scaffolded in contract (`age` field) but null for most players since the scraper bridge does not supply age.
6. **Canonical engine mode** — `CANONICAL_DATA_MODE` env var exists for gradual rollout but the canonical 6-step pipeline (`--engine canonical`) is not the default engine.
7. **Multi-source overlap** — current sources (KTC + IDPTC) cover non-overlapping pools. When overlap occurs, blended averaging is ready but untested in production.
