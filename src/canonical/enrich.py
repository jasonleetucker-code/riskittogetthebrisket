"""Position enrichment for canonical assets.

Uses multiple strategies to fill missing position metadata:
1. Legacy player map lookup (normalized name matching)
2. Nickname expansion (Cam→Cameron, TJ→T.J., etc.)
3. Universe-based inference (IDP universe assets from IDP-only sources)
4. Source-based inference (IDPTradeCalc → IDP positions)

Position provenance is tracked: each enriched asset records whether its position
came from source data ("adapter"), legacy lookup ("legacy_enrichment"),
nickname matching ("nickname_match"), or universe/source inference ("universe_inferred").
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.utils.name_clean import POSITION_ALIASES as LEGACY_POS_MAP  # noqa: F401
from src.utils.name_clean import resolve_idp_position as _resolve_idp_position
from src.utils.name_clean import NICKNAME_MAP  # noqa: F401

# Sources known to only contain IDP players
IDP_ONLY_SOURCES = {"IDPTRADECALC"}

# Default IDP position when we know a player is IDP but not which specific position
# LB is the most common IDP position; used as safe default when specific position unknown
DEFAULT_IDP_POSITION = "LB"


def _normalize_name(name: str) -> str:
    """Normalize name for matching — same logic as comparison batch."""
    n = name.strip()
    for sfx in (" Jr.", " Jr", " Sr.", " Sr", " II", " III", " IV", " V", " VI"):
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
        r"^\d{4}\s+\d+(st|nd|rd|th)$",
    ]
    return any(re.search(p, n) for p in pick_patterns)


def _nickname_variants(norm_name: str) -> list[str]:
    """Generate nickname-expanded variants of a normalized name."""
    parts = norm_name.split()
    if len(parts) < 2:
        return []

    first = parts[0]
    rest = " ".join(parts[1:])
    variants = []

    # Try expanding nickname → formal
    if first in NICKNAME_MAP:
        variants.append(NICKNAME_MAP[first] + " " + rest)

    # Try reducing formal → nickname
    for nick, formal in NICKNAME_MAP.items():
        formal_clean = formal.replace(" ", "")
        if first == formal_clean:
            variants.append(nick + " " + rest)

    # Handle "Dr" suffix (e.g., "Gervon Dexter Dr" → "Gervon Dexter")
    if parts[-1] in ("dr", "sr", "jr", "i"):
        variants.append(" ".join(parts[:-1]))

    return variants


def _is_idp_asset(asset: dict[str, Any]) -> bool:
    """Check if asset is from an IDP universe or IDP-only sources."""
    universe = str(asset.get("universe", ""))
    if "idp" in universe.lower():
        return True
    sources = set(asset.get("source_values", {}).keys())
    return bool(sources and sources.issubset(IDP_ONLY_SOURCES))


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
        raw_pos = str(pdata.get("position", pdata.get("POS", ""))).strip().upper()
        if not raw_pos or raw_pos == "PICK":
            continue
        # Apply DL > DB > LB priority first so a dual-position IDP
        # (e.g. "DL/LB") resolves the same way every other reader does.
        # Fall back to the legacy alias map for offense/kicker codes.
        canonical_pos = _resolve_idp_position(
            pdata.get("fantasy_positions"), raw_pos
        ) or LEGACY_POS_MAP.get(raw_pos)
        if not canonical_pos or canonical_pos == "PICK":
            continue

        norm = _normalize_name(name)
        if norm:
            lookup[norm] = canonical_pos

    return lookup


def build_player_map_lookup(player_map_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Build lookups from the exported player position map.

    Returns:
        Tuple of (primary_lookup, nickname_lookup) dicts mapping
        normalized name → position.
    """
    data = json.loads(player_map_path.read_text())
    primary: dict[str, str] = {}
    nickname: dict[str, str] = {}

    for entry in data.get("entries", []):
        norm = entry.get("normalized_name", "")
        pos = entry.get("position", "")
        if norm and pos:
            primary[norm] = pos

    # Build nickname variants from primary
    for norm, pos in list(primary.items()):
        for variant in _nickname_variants(norm):
            if variant not in primary:
                nickname[variant] = pos

    return primary, nickname


def enrich_positions(
    assets: list[dict[str, Any]],
    legacy_lookup: dict[str, str],
    nickname_lookup: dict[str, str] | None = None,
    *,
    infer_idp: bool = True,
    supplemental_path: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Enrich canonical assets with position data using multiple strategies.

    Strategies applied in order:
    1. Skip if already has position from source adapter
    2. Skip if it's a pick asset
    3. Try primary legacy lookup by normalized name
    4. Try nickname-expanded variants
    5. Try supplemental position map (curated multi-source players)
    6. If IDP and infer_idp=True, assign default IDP position

    Args:
        assets: List of canonical asset dicts.
        legacy_lookup: normalized_name → position from build_legacy_position_lookup.
        nickname_lookup: nickname_variant → position (optional).
        infer_idp: Whether to infer IDP position from universe/source context.
        supplemental_path: Path to supplemental_positions.json (optional).

    Returns:
        Tuple of (enriched assets, summary dict).
    """
    nickname_lookup = nickname_lookup or {}

    # Load supplemental position map if available
    supplemental_lookup: dict[str, str] = {}
    if supplemental_path and supplemental_path.exists():
        try:
            data = json.loads(supplemental_path.read_text())
            for name, pos in data.get("players", {}).items():
                norm = _normalize_name(name)
                if norm and pos:
                    supplemental_lookup[norm] = pos
        except Exception:
            pass

    counts = {
        "already_had_position": 0,
        "enriched_from_legacy": 0,
        "enriched_from_nickname": 0,
        "enriched_from_supplemental": 0,
        "enriched_from_universe_infer": 0,
        "skipped_picks": 0,
        "unmatched": 0,
    }

    for asset in assets:
        meta = asset.setdefault("metadata", {})
        display_name = str(asset.get("display_name", ""))

        # Already has position from source adapter
        if meta.get("position"):
            meta["position_source"] = "adapter"
            counts["already_had_position"] += 1
            continue

        # Skip pick assets
        if _is_pick_asset(display_name):
            meta["position_source"] = None
            counts["skipped_picks"] += 1
            continue

        # Strategy 1: Primary legacy lookup
        norm = _normalize_name(display_name)
        pos = legacy_lookup.get(norm)
        if pos:
            meta["position"] = pos
            meta["position_source"] = "legacy_enrichment"
            counts["enriched_from_legacy"] += 1
            continue

        # Strategy 2: Nickname variant matching
        for variant in _nickname_variants(norm):
            pos = legacy_lookup.get(variant) or nickname_lookup.get(variant)
            if pos:
                break
        if pos:
            meta["position"] = pos
            meta["position_source"] = "nickname_match"
            counts["enriched_from_nickname"] += 1
            continue

        # Strategy 3: Supplemental position map (curated multi-source players)
        pos = supplemental_lookup.get(norm)
        if pos:
            meta["position"] = pos
            meta["position_source"] = "supplemental_map"
            counts["enriched_from_supplemental"] += 1
            continue

        # Strategy 4: Universe/source-based IDP inference
        if infer_idp and _is_idp_asset(asset):
            meta["position"] = DEFAULT_IDP_POSITION
            meta["position_source"] = "universe_inferred"
            counts["enriched_from_universe_infer"] += 1
            continue

        meta["position_source"] = None
        counts["unmatched"] += 1

    total_with_pos = (
        counts["already_had_position"]
        + counts["enriched_from_legacy"]
        + counts["enriched_from_nickname"]
        + counts["enriched_from_supplemental"]
        + counts["enriched_from_universe_infer"]
    )

    summary = {
        **counts,
        "total": len(assets),
        "position_coverage_pct": round(total_with_pos / len(assets) * 100, 1) if assets else 0,
    }

    return assets, summary
