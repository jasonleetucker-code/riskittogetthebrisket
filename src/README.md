# /src Overview

Modular architecture for the new canonical dynasty engine.

- `adapters/` — source ingestion modules. Each adapter outputs raw snapshot rows (`raw_source_snapshots`, `raw_source_asset_values`).
- `identity/` — master player/pick identity mapping utilities.
- `canonical/` — percentile transforms, curve logic, source blending, snapshot versioning.
- `league/` — league settings parser, scarcity calculations, replacement baselines, pick discount logic.
- `api/` — FastAPI/Starlette services for calculator, rankings, roster endpoints.
- `data_models/` — Pydantic/BaseModel schemas shared across layers.
- `utils/` — shared helpers (logging, config loading, persistence).

Each module exposes both CLI entrypoints (for CI pipelines) and callable functions for the API layer.
