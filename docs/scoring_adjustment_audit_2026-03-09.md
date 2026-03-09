# Scoring-Adjustment Audit (Pre-Refactor) — 2026-03-09

## Scope audited
- `/Users/jason/OneDrive/Desktop/Trade Calculator/Dynasty Scraper.py`
- `/Users/jason/OneDrive/Desktop/Trade Calculator/Static/index.html`

## Findings
1. **Baseline and custom IDs are hardcoded in backend**
   - `SLEEPER_LEAGUE_ID = "1312006700437352448"`
   - `BASELINE_LEAGUE_ID = "1328545898812170240"`
   - `LAM_SEASONS = [2025, 2024, 2023]`

2. **Sleeper scoring ingestion exists but is function-local and not modular**
   - `compute_empirical_lam(...)` fetches league objects and scoring settings internally.
   - Scoring settings extraction and stat scoring helper logic are nested functions.

3. **Player-level format-fit outputs are already generated**
   - `_formatFitPPGTest`, `_formatFitPPGCustom`, `_formatFitRaw`, `_formatFitShrunk`, `_formatFitFinal`,
     `_formatFitProductionMultiplier`, `_formatFitConfidence`, `_formatFitSource`, `_formatFitArchetype`,
     `_formatFitScoringTags`, and related debug fields are written to player payloads.

4. **Adjustment architecture is still mostly multiplier-centric**
   - Uses bucket fallback + per-player fit with capped effective multiplier.
   - Legacy fields (`_rawLeagueMultiplier`, `_shrunkLeagueMultiplier`, `_effectiveMultiplier`, `_leagueAdjusted`) are still core compatibility outputs.

5. **Frontend consumes both empirical-fit and fallback LAM paths**
   - `index.html` reads many `_formatFit*` and multiplier fields.
   - `initLAM()` and fallback bucket compute logic still exist client-side.

6. **Main issue to fix**
   - Scoring translation logic is powerful but monolithic and not cleanly versioned/configured as standalone modules (baseline config, normalized league config, delta map, model output, validation artifacts).

## Refactor approach chosen
- Keep the existing market/dynasty composite engine intact.
- Keep existing frontend field contracts intact.
- Introduce modular scoring components under `src/scoring/`.
- Wire modular config/normalization/delta/model outputs into existing empirical LAM flow.
- Preserve backward-compatible legacy fields while adding cleaner structured scoring outputs.
