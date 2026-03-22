"""Position enrichment for canonical assets using legacy player data.

The canonical pipeline's source CSVs (exports/latest/site_raw/*.csv) only contain
name and value columns — no position data. DLF adapters extract position from their
rank-suffix format, but all other sources leave position empty.

This module fills the gap by cross-referencing canonical assets against the legacy
player map (data/legacy_data_*.json), which has _lamBucket position data for ~94%
of players.

Position provenance is tracked: each enriched asset records whether its position
came from source data ("adapter") or from this enrichment step ("legacy_enrichment").
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Canonical league positions (maps legacy values to standard forms)
LEGACY_POS_MAP: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
    "K": "K",
    "PICK": "PICK",
}


def _normalize_name(name: str) -> str:
    """Normalize name for matching — same logic as comparison batch."""
    n = name.strip()
    for sfx in (" Jr.", " Sr.", " II", " III", " IV", " V"):
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
    return n.lower().replace(".", "").replace("'", "").replace("\u2019", "")


def _is_pick_asset(name: str) -> bool:
    """Check if asset name looks like a draft pick rather than a player."""
    n = name.lower().strip()
    pick_patterns = [
        r"^\d{4}\s+(pick|early|mid|late)",
        r"^(early|mid|late)\s+\d",
        r"^\d{4}\s+\d+\.\d+",
        r"pick\s+\d+\.\d+",
    ]
    return any(re.search(p, n) for p in pick_patterns)


def build_legacy_position_lookup(legacy_path: Path) -> dict[str, str]:
    """Build a normalized-name → position lookup from legacy player data.

    Args:
        legacy_path: Path to legacy_data_*.json file.

    Returns:
        Dict mapping normalized player name to canonical position string.
    """
    data = json.loads(legacy_path.read_text())
    players = data.get("players", {})
    lookup: dict[str, str] = {}

    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        raw_pos = str(pdata.get("_lamBucket", "")).strip().upper()
        if not raw_pos or raw_pos == "PICK":
            continue
        canonical_pos = LEGACY_POS_MAP.get(raw_pos)
        if not canonical_pos or canonical_pos == "PICK":
            continue

        norm = _normalize_name(name)
        if norm:
            lookup[norm] = canonical_pos

    return lookup


def enrich_positions(
    assets: list[dict[str, Any]],
    legacy_lookup: dict[str, str],
) -> list[dict[str, Any]]:
    """Enrich canonical assets with position data from legacy player map.

    For each asset that lacks position in its metadata:
    1. Skip if it's a pick asset (picks don't have player positions)
    2. Try to match against legacy position lookup by normalized name
    3. If matched, set metadata.position and record provenance

    Assets that already have position from source data are left unchanged
    but get provenance marked as "adapter".

    Args:
        assets: List of canonical asset dicts.
        legacy_lookup: normalized_name → position from build_legacy_position_lookup.

    Returns:
        Same list with enriched metadata. Each asset gets:
        - metadata.position: the position (possibly newly set)
        - metadata.position_source: "adapter" | "legacy_enrichment" | None
    """
    enriched_count = 0
    skipped_picks = 0
    already_had = 0
    unmatched = 0

    for asset in assets:
        meta = asset.setdefault("metadata", {})
        display_name = str(asset.get("display_name", ""))

        # Already has position from source adapter
        if meta.get("position"):
            meta["position_source"] = "adapter"
            already_had += 1
            continue

        # Skip pick assets
        if _is_pick_asset(display_name):
            meta["position_source"] = None
            skipped_picks += 1
            continue

        # Try legacy lookup
        norm = _normalize_name(display_name)
        pos = legacy_lookup.get(norm)
        if pos:
            meta["position"] = pos
            meta["position_source"] = "legacy_enrichment"
            enriched_count += 1
        else:
            meta["position_source"] = None
            unmatched += 1

    return assets, {
        "already_had_position": already_had,
        "enriched_from_legacy": enriched_count,
        "skipped_picks": skipped_picks,
        "unmatched": unmatched,
        "total": len(assets),
        "position_coverage_pct": round(
            (already_had + enriched_count) / len(assets) * 100, 1
        ) if assets else 0,
    }
