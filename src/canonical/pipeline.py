from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.canonical.transform import build_canonical_by_universe, flatten_canonical
from src.data_models import RawAssetRecord
from src.utils import save_json


def write_canonical_snapshot(
    out_path: Path,
    run_id: str,
    source_snapshot_id: str,
    records: list[RawAssetRecord],
    source_weights: dict[str, float],
    exponent: float = 0.65,
) -> dict:
    """
    Deterministic canonical skeleton:
      1) load normalized source assets
      2) split by universe
      3) map rank/value -> percentile -> canonical source score
      4) blend weighted source scores
      5) persist canonical snapshot
    """
    canonical_by_universe = build_canonical_by_universe(
        records=records,
        source_weights=source_weights,
        exponent=exponent,
    )
    all_assets = flatten_canonical(canonical_by_universe)

    payload = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_snapshot_id": source_snapshot_id,
        "asset_count": len(all_assets),
        "asset_count_by_universe": {u: len(v) for u, v in canonical_by_universe.items()},
        "assets_by_universe": {u: [a.to_dict() for a in rows] for u, rows in canonical_by_universe.items()},
        "assets": [a.to_dict() for a in all_assets],
    }
    save_json(out_path, payload)
    return payload

