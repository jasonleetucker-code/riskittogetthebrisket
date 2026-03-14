# /src Overview

Modular architecture for the new canonical dynasty engine.

- `adapters/` — source ingestion modules. Each adapter outputs raw snapshot rows (`raw_source_snapshots`, `raw_source_asset_values`).
- `identity/` — master player/pick identity mapping utilities.
- `canonical/` — percentile transforms, curve logic, source blending, snapshot versioning.
- `league/` — league settings parser, scarcity calculations, replacement baselines, pick discount logic.
- `api/` — API data contract builder and validator (`data_contract.py`). API service routes remain in `server.py` until the new engine replaces the legacy data path.
- `data_models/` — Pydantic/BaseModel schemas shared across layers.
- `utils/` — shared helpers (logging, config loading, persistence).

Each module will expose both CLI entrypoints (for Jenkins) and callable functions for the API layer.
