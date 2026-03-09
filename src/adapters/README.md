# Adapter Contract

This file is the frozen adapter contract for the canonical pipeline scaffold.

## Snapshot Contract (required fields)

Each adapter run must generate a snapshot object with:

- `source`
- `snapshot_id`
- `pulled_at_utc`
- `season`
- `format_key`
- `universe`
- `ingest_type` (`api`, `scrape`, `manual_csv`)
- `source_url`
- `raw_storage_path`
- `record_count`
- `adapter_version`

Additional provenance required by this repo:

- `scoring_context`
- `ingest_method`
- `raw_file_path`
- `hash`
- `notes`

## Asset Record Contract (required fields)

Every adapter emits the same normalized asset format, even when some fields are null:

- `source`
- `snapshot_id`
- `asset_type` (`player` or `pick`)
- `external_asset_id`
- `external_name`
- `display_name`
- `team_raw`
- `position_raw`
- `age_raw`
- `rookie_flag_raw`
- `rank_raw`
- `value_raw`
- `tier_raw`
- `universe`
- `format_key`
- `is_idp`
- `is_offense`
- `source_notes`
- `metadata_json`

## Normalized helper fields (recommended)

- `name_normalized_guess`
- `team_normalized_guess`
- `position_normalized_guess`
- `pick_round_guess`
- `pick_slot_guess`
- `pick_year_guess`

These are helper hints only. Identity resolution remains authoritative.

## Example player row

```json
{
  "source": "DLF_SF",
  "snapshot_id": "dlf_sf_2026_20260309T113000Z",
  "asset_type": "player",
  "external_asset_id": "",
  "external_name": "Josh Allen",
  "display_name": "Josh Allen",
  "team_raw": "BUF",
  "position_raw": "QB1",
  "age_raw": "29",
  "rookie_flag_raw": "",
  "rank_raw": 1.0,
  "value_raw": null,
  "tier_raw": "1",
  "universe": "offense_vet",
  "format_key": "dynasty_sf",
  "is_idp": false,
  "is_offense": true,
  "source_notes": "DLF Avg rank import",
  "metadata_json": {"profile_source": "dlf_superflex.csv"},
  "name_normalized_guess": "josh allen",
  "team_normalized_guess": "BUF",
  "position_normalized_guess": "QB",
  "pick_round_guess": null,
  "pick_slot_guess": "",
  "pick_year_guess": null
}
```

## Example pick row

```json
{
  "source": "KTC_PICKS",
  "snapshot_id": "ktc_picks_2026_20260309T113000Z",
  "asset_type": "pick",
  "external_asset_id": "2027_mid_1st",
  "external_name": "2027 Mid 1st",
  "display_name": "2027 Mid 1st",
  "team_raw": "",
  "position_raw": "",
  "age_raw": "",
  "rookie_flag_raw": "",
  "rank_raw": null,
  "value_raw": 4255.0,
  "tier_raw": "",
  "universe": "picks",
  "format_key": "dynasty_sf",
  "is_idp": false,
  "is_offense": false,
  "source_notes": "KTC pick value import",
  "metadata_json": {"bucket": "mid"},
  "name_normalized_guess": "2027 mid 1st",
  "team_normalized_guess": "",
  "position_normalized_guess": "",
  "pick_round_guess": 1,
  "pick_slot_guess": "MID",
  "pick_year_guess": 2027
}
```

