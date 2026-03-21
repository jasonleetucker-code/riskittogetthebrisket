# /src Overview

This repo is intentionally in a mixed legacy/new phase. This file documents what
is actually live versus scaffold.

## Runtime authority truth

- `LIVE (authoritative)`:
  - `src/api/data_contract.py` shapes and validates the live `/api/data` contract.
  - `src/scoring/*` is imported by `Dynasty Scraper.py` (when available) for live
    scoring/format-fit math used before contract shaping.
- `SCAFFOLD / NOT authoritative for /api/data`:
  - `src/adapters/*` + `scripts/source_pull.py`
  - `src/identity/*` + `scripts/identity_resolve.py`
  - `src/canonical/*` + `scripts/canonical_build.py`
  - `src/league/*` + `scripts/league_refresh.py`
  - These feed `data/*` scaffold artifacts and `/api/scaffold/*` diagnostics, not
    live rankings/calculator/player-value authority.

## Module map

- `adapters/`: scaffold source-ingest adapters.
- `identity/`: scaffold identity resolution utilities.
- `canonical/`: scaffold percentile/curve/blending pipeline.
- `league/`: scaffold league refresh layer.
- `api/`: contains live contract resolver plus API scaffolding.
- `data_models/`: shared data models used by scaffold scripts.
- `utils/`: shared helpers used by scaffold and live code.
