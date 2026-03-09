# Raw Ingestion Layout

This directory is the canonical raw-ingestion store.

## Folder convention

Use explicit source/season/snapshot folders:

`data/raw/<source>/<season>/<snapshot_id>/`

Example:

`data/raw/dlf_sf/2026/dlf_sf_2026_20260309T113000Z/`

Each snapshot folder must include:

- `manifest.json`
- `parse_log.json`
- raw source file (for manual CSV fallback, keep original filename)
- `assets.normalized.jsonl` (adapter output records)

## Manifest schema (required)

Each manual or automated ingest must provide:

- `source`
- `snapshot_id`
- `pulled_at_utc`
- `season`
- `scoring_context`
- `universe`
- `ingest_method`
- `ingest_type`
- `source_url`
- `format_key`
- `raw_file_path`
- `raw_storage_path`
- `record_count`
- `hash`
- `notes`
- `adapter_version`
- `inserted_by`

## Manual CSV ingestion rules

Manual fallback is approved, but never undocumented.

For every manual CSV:

- place source file in the snapshot folder
- generate `manifest.json` with provenance
- include checksum/hash
- include parser warnings in `parse_log.json`
- write normalized rows to `assets.normalized.jsonl`

No mystery files in `data/raw/`.
