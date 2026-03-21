# Mike Clay Value Integration (Offseason)

## Live Authority Path

Mike Clay now affects live adjusted values through the same contract authority used by rankings and trade:

1. `Dynasty Scraper.py` produces base market fields (`_rawComposite`, `_scoringAdjusted`, `_scarcityAdjusted`, `_finalAdjusted`).
2. `src/api/data_contract.py` builds `valueBundle` for every player.
3. In that same path, an offseason Mike Clay overlay is applied to `fullValue` when active.
4. `/api/data` returns the adjusted values consumed by rankings and trade calculator.

No display-only side path was added.

## Code Locations

- Runtime context + dataset loading + signal math + gating:
  - `src/offseason/mike_clay/integration.py`
- Full value layer integration:
  - `src/api/data_contract.py` (`_authoritative_value_bundle`)
- Ingestion pipeline used by integration:
  - `src/offseason/mike_clay/pipeline.py`

## Seasonal Gating

Config source:
- `config/mike_clay_integration.json`

Required yearly window config (single source of truth):
- `seasonWindowsByYear.<guide_year>.offseasonStartDate`
- `seasonWindowsByYear.<guide_year>.week1StartDate`
- `seasonWindowsByYear.<guide_year>.week1EndDate`

Example:

```json
{
  "enabled": true,
  "seasonWindowsByYear": {
    "2026": {
      "offseasonStartDate": "2026-01-15",
      "week1StartDate": "2026-09-10",
      "week1EndDate": "2026-09-14"
    }
  }
}
```

Fail-safe behavior:
- Missing year entry or malformed dates => seasonal gate is disabled (`season_window_invalid`), no Clay overlay.
- No hidden Jan/Sep fallback dates are used.
- Clay can only be active in the configured offseason window (`offseasonStartDate <= now < week1StartDate`).
- Week 1 and in-season phases are deterministically inactive.

Optional env overrides:
- `MIKE_CLAY_ENABLED=0|1`
- `MIKE_CLAY_INTEGRATION_CONFIG=/abs/path/to/config.json`
- `MIKE_CLAY_IMPORT_LATEST_PATH=/abs/path/to/mike_clay_import_latest.json`
- `MIKE_CLAY_FORCE_PHASE=offseason|week1|post_week1_decay|in_season_inactive`
- `MIKE_CLAY_FORCE_WEIGHT=<float>`

Operational annual rollover:
1. Add next season under `seasonWindowsByYear` (do not edit code defaults).
2. Set exact `offseasonStartDate`, `week1StartDate`, `week1EndDate`.
3. Restart runtime and confirm `/api/data` -> `offseasonClayStatus`:
   - `seasonalGatingConfigured=true`
   - `cutoverWindow.policy=explicit_yearly_window`
   - `cutoverWindow.guideYear=<new year>`
4. Confirm `seasonalGatingReason` is expected for current calendar date.

## Formula Summary

For matched players with eligible confidence/status:

1. Compute Clay signals (`0..1`) by position family:
   - Offensive: production, opportunity, durability/games, TD expectation, team environment, schedule, role certainty, starter confidence
   - IDP: IDP production, IDP opportunity, durability, team environment, schedule, role certainty, starter confidence
2. Build centered signal:
   - `centered = overallSignal - positionBaseline`
3. Convert to raw delta:
   - `rawDeltaPct = centered * 0.30 * positionInfluence`
4. Apply gates:
   - seasonal weight, match-status multiplier, match-confidence gate, source-count gate, durability gate, role gate
5. Apply low-games / uncertain-role damping:
   - low projected games reduce upside and can add downside pressure
6. Clamp to per-position cap and scale:
   - `deltaPct ∈ [-positionCap, +positionCap]`
   - adjusted value clamped to canonical range `1..9999`

## Guardrails

- No Mike Clay row match => no value change.
- Inactive phase or missing dataset => no value change.
- Unsupported asset classes (picks, non-player positions) => no value change.
- Low match confidence / low parse confidence => excluded.
- Per-position max delta caps prevent single-source takeover.
- Source-count gate reduces effect on thin market coverage assets.

## Diagnostics and Auditability

Exposed in `/api/data`:
- `valueAuthority.offseasonClay`:
  - enabled/active status
  - import data readiness (`importDataReady`, `datasetLoaded`)
  - seasonal gate state (`seasonalGatingActive`, `seasonalGatingConfigured`, `seasonalGatingReason`, `seasonalGatingErrors`)
  - season phase
  - current weight
  - config path used
  - guide version/year
  - import timestamp
  - unresolved/ambiguous/low-confidence counts
  - explicit cutover window (`cutoverWindow`) with configured dates and validity
- `valueResolverDiagnostics.offseasonClayDiagnostics`:
  - top 50 before vs after
  - risers/fallers
  - biggest disagreement cases
  - biggest offense/IDP impact
  - strong-support / weak-current cases
  - strong-current / weak-support cases
  - games/role penalty cases
  - excluded/unresolved impact summary

## Known Limitations

- Accuracy depends on canonical match coverage in the imported Clay dataset.
- Unresolved guide players are counted and surfaced but not auto-forced into values.
- A missing yearly season window intentionally disables Clay until fixed (fail-safe by design).
