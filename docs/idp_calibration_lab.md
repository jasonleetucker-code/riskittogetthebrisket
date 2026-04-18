# IDP Calibration Lab

Internal tooling for calibrating how DL / LB / DB values are scaled in the
live trade calculator. The lab takes two Sleeper league IDs, walks each one
back through `previous_league_id`, rescores a common IDP player universe
under both scoring systems for 2022-2025, and produces per-position
per-bucket multipliers plus anchor curves. Nothing reaches production
until you click **Promote to production**.

**Location:** `/tools/idp-calibration` (auth-gated, hidden from the public).

## Data sources

### From Sleeper (authoritative)
- League metadata (name, season, total rosters)
- `scoring_settings` — normalised via `src/scoring/sleeper_ingest.py::KEY_ALIASES`
- `roster_positions` — parsed into lineup demand by `src/idp_calibration/lineup.py`
- `previous_league_id` — walked by `src/idp_calibration/sleeper_client.fetch_league_chain`
- Global NFL players map (for ID -> name / position in the stats adapter)

### From the historical stats adapter layer
The lab never hardcodes a "Sleeper only" assumption for historical stats
because Sleeper's season stats endpoint is undocumented. The adapter
interface lives at `src/idp_calibration/stats_adapter.py`. Adapters:

1. `SleeperStatsAdapter` — probes `https://api.sleeper.app/v1/stats/nfl/regular/{season}`.
   Skipped by default unless `IDP_CALIBRATION_ALLOW_NETWORK=1` is set.
2. `LocalCSVStatsAdapter` — reads `data/idp_calibration/stats/{season}.csv`.
   Header must include `player_id`, `name`, `position`, and any subset of
   the canonical IDP stat columns (`idp_tkl_solo`, `idp_tkl_ast`,
   `idp_tkl_loss`, `idp_sack`, `idp_hit`, `idp_int`, `idp_pd`, `idp_ff`,
   `idp_fum_rec`, `idp_def_td`), plus optional `games`.
3. `ManualFallbackAdapter` — returns an empty list and surfaces a warning
   so the UI can flag that no stats source was reachable.

The factory `get_stats_adapter(season)` picks the first usable adapter.
Whichever adapter is used, the **same player universe is rescored under
both league scoring systems** so the comparison is apples to apples.

## How to run an analysis

1. Start backend + frontend: `python server.py` + `npm run dev -w frontend`.
2. Sign in, then visit `/tools/idp-calibration`.
3. Paste the test-league (market) ID and your-league ID.
4. (Optional) Open **Advanced settings** to tweak seasons, replacement
   mode, blend weights, year recency weights, bucket edges, or universe
   filters. Defaults:
   - Seasons: 2022-2025
   - Replacement: `starter_plus_buffer` with 15% team-count buffer
   - Blend: 75% intrinsic / 25% market
   - Year weights: 2025=0.40, 2024=0.30, 2023=0.20, 2022=0.10
   - Buckets: 1-6, 7-12, 13-24, 25-36, 37-60, 61-100
5. Click **Analyze**. The run is saved to
   `data/idp_calibration/runs/{run_id}.json` and the latest pointer is
   written to `data/idp_calibration/latest.json`.
6. Inspect the dashboard sections — league verification, demand, VOR by
   season, multi-year multipliers, anchor curves, recommendation.
7. Use the export buttons for JSON / bucket CSV / anchor CSV if you want
   an artefact outside the app.

## Promotion flow

Promotion is always manual.

1. Open a run you like.
2. Pick an `active_mode` — `blended` (default), `intrinsic_only`, or
   `market_only`.
3. Click **Promote to production** (it's a two-click confirm).

On promote:

- If `config/idp_calibration.json` already exists, it is copied to
  `config/idp_calibration.backups/{iso_timestamp}.json` first.
- The approved calibration output (multipliers + anchors + metadata) is
  written to `config/idp_calibration.json`.
- The live valuation pipeline picks up the new config within one request
  thanks to an mtime-keyed cache in `src/idp_calibration/production.py`.
  No server restart is required.

### Promoted config schema

```json
{
  "version": 1,
  "promoted_at": "...",
  "source_run_id": "...",
  "promoted_by": "...",
  "league_ids": {"test": "...", "mine": "..."},
  "year_coverage": [2022, 2023, 2024, 2025],
  "blend_weights": {"intrinsic": 0.75, "market": 0.25},
  "replacement_settings": {"mode": "starter_plus_buffer", "buffer_pct": 0.15},
  "active_mode": "blended",
  "bucket_edges": [[1,6],[7,12],[13,24],[25,36],[37,60],[61,100]],
  "multipliers": {
    "DL": {"position": "DL", "buckets": [{"label": "1-6", "intrinsic": 1.0, "market": 1.0, "final": 1.0, "count": 24}, ...]},
    "LB": {...},
    "DB": {...}
  },
  "anchors": {
    "intrinsic": {"DL": [{"rank": 1, "value": 1.0}, ...], ...},
    "market":    {"DL": [...], ...},
    "final":     {"DL": [...], ...}
  }
}
```

## How the production calculator consumes the config

1. `src/api/data_contract.py` imports
   `src.idp_calibration.production`.
2. After Phase 4 of `_compute_unified_rankings`, the helper
   `_apply_idp_calibration_post_pass(players_array, players_by_name)`
   runs.
3. The helper calls `production.load_production_config()`. If no
   promoted config exists, it returns immediately (strict no-op).
4. When a config exists, IDP rows are grouped into DL/LB/DB, sorted by
   their current `rankDerivedValue`, and each row's value is multiplied
   by `production.get_idp_bucket_multiplier(position, pos_rank,
   mode=active_mode)`. The new value is mirrored into the legacy
   `players_by_name` dict so runtime views stay in sync.
5. Offense and pick rows are untouched. Picks are renormalised later in
   Phase 5 exactly as before.
6. Downstream consumers (trade suggestions, finder, rankings page) read
   the updated `rankDerivedValue` without any additional change.

The promoted config is the **single** entry point. There is no parallel
code path — if the file is deleted, every IDP multiplier is 1.0 again.

## Stats network access

`SleeperStatsAdapter` probes an undocumented Sleeper endpoint, so we
keep its behaviour predictable:

* **Production server (no pytest in `sys.modules`)** → network
  **enabled by default**. The adapter factory tries Sleeper first,
  falls through to `LocalCSVStatsAdapter`
  (`data/idp_calibration/stats/{season}.csv`), then
  `ManualFallbackAdapter`.
* **pytest** → network **disabled by default** so the unit suite never
  touches a live endpoint.

No operator setup is required on a fresh deploy. If you want to
override the default, set `IDP_CALIBRATION_ALLOW_NETWORK` in
`__APP_DIR__/.env` and restart the service — `"1"` / `"true"` /
`"yes"` / `"on"` enable, `"0"` / `"false"` / `"no"` / `"off"`
disable. Explicit caller arguments to `get_stats_adapter()` always win
over both.

If the Sleeper endpoint is unreachable from your VPS even with network
enabled, drop CSVs at `data/idp_calibration/stats/{season}.csv` with
the header documented above — the factory uses them in preference
order `sleeper → local_csv → manual_fallback`.

## Known limitations

- The Sleeper stats endpoint is undocumented. When it fails, the lab
  defaults to `LocalCSVStatsAdapter` (see above) or loudly warns via
  `ManualFallbackAdapter`. Populate
  `data/idp_calibration/stats/{season}.csv` for deterministic runs.
- The player universe is defined per season (all valid DL/LB/DB with
  usable stats). Changing the universe between analyses changes the
  multiplier curve shape, so compare like-for-like settings.
- Bucket counts below `min_bucket_size` (default 3) are merged into the
  neighbouring lower-rank bucket, and the merge is reported both in the
  UI and in the saved run artefact. Don't over-read the multiplier when
  the bucket is small or merged.
- The market curve is Test League scoring only. It is treated as a
  prior, not ground truth — bump the `blend.intrinsic` weight toward
  1.0 if you want the promoted config to lean on your own league
  economics more heavily.
- Promotion has no granular RBAC beyond the existing session auth gate.
  Any authenticated user can promote.
- IDP rookie / veteran split from `src/canonical/calibration.py` is
  preserved — the lab's multipliers apply on top of whichever universe
  scale the canonical engine already picked.

## Tests

`pytest tests/idp_calibration/ -q`

| File | Covers |
|---|---|
| `test_season_chain.py` | `previous_league_id` walk, missing-season warnings |
| `test_scoring.py` | Sleeper `scoring_settings` -> canonical weight map |
| `test_replacement.py` | Replacement-level math (strict / buffer / manual) |
| `test_vor_buckets.py` | Common-universe invariant, bucket blended-center, merge logic |
| `test_translation_anchors.py` | Multi-year multipliers, monotonic anchors |
| `test_storage_promotion.py` | Run save / load, promote + backup |
| `test_api.py` | Endpoint validation, run lookup, promote flow |
| `test_production_integration.py` | Promoted config scales IDP rows only |
