#!/usr/bin/env python3
"""Export a comprehensive player-position mapping from legacy data.

Produces a stable JSON artifact at data/player_map/player_position_map.json
that the canonical pipeline uses for position enrichment.

Sources of position data (in priority order):
1. _lamBucket from legacy player data (855 players)
2. Sleeper ID cross-reference for future enrichment
3. Universe-based inference for IDP-only sources

Usage:
    python scripts/export_player_map.py [--legacy PATH] [--output PATH]

If paths are not provided, finds the latest available files automatically.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on sys.path for shared imports
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._shared import _repo_root, _latest as _latest_file, _normalize_name


# Common nickname → formal name mappings for fuzzy enrichment
NICKNAME_MAP: dict[str, str] = {
    "cam": "cameron",
    "tj": "t j",
    "cj": "c j",
    "dj": "d j",
    "aj": "a j",
    "jt": "j t",
    "dk": "d k",
    "kj": "k j",
    "pj": "p j",
    "rj": "r j",
}

# Canonical position mapping
POS_MAP: dict[str, str] = {
    "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
    "DL": "DL", "DE": "DL", "DT": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB",
    "DB": "DB", "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB",
    "K": "K", "P": "K",
}


def build_player_map(legacy_path: Path) -> dict:
    """Build comprehensive player-position map from legacy data.

    Returns a dict with:
    - entries: list of player dicts with name, normalized_name, position, sleeper_id
    - lookup: dict of normalized_name → position for fast enrichment
    - nickname_lookup: dict of nickname-expanded name → position
    - stats: summary counts
    """
    data = json.loads(legacy_path.read_text())
    players = data.get("players", {})

    entries = []
    lookup: dict[str, str] = {}
    nickname_lookup: dict[str, str] = {}

    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue

        raw_pos = str(pdata.get("_lamBucket", "")).strip().upper()
        if not raw_pos or raw_pos == "PICK":
            continue

        canonical_pos = POS_MAP.get(raw_pos)
        if not canonical_pos or canonical_pos == "PICK":
            continue

        norm = _normalize_name(name)
        sleeper_id = str(pdata.get("_sleeperId", "")) or None

        entry = {
            "name": name,
            "normalized_name": norm,
            "position": canonical_pos,
            "sleeper_id": sleeper_id,
        }
        entries.append(entry)

        # Primary lookup
        if norm:
            lookup[norm] = canonical_pos

        # Nickname expansion: for names starting with a known nickname,
        # also register the expanded form
        if norm:
            parts = norm.split()
            if len(parts) >= 2:
                first = parts[0]
                rest = " ".join(parts[1:])
                # If first name is a nickname, also register expanded form
                if first in NICKNAME_MAP:
                    expanded = NICKNAME_MAP[first] + " " + rest
                    nickname_lookup[expanded] = canonical_pos
                # If first name could be expanded TO a nickname, register that too
                for nick, formal in NICKNAME_MAP.items():
                    if first == formal.replace(" ", ""):
                        nickname_lookup[nick + " " + rest] = canonical_pos

    return {
        "entries": entries,
        "lookup": lookup,
        "nickname_lookup": nickname_lookup,
        "stats": {
            "total_entries": len(entries),
            "unique_names": len(lookup),
            "nickname_expansions": len(nickname_lookup),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export player-position map from legacy data")
    parser.add_argument("--legacy", help="Path to legacy data JSON")
    parser.add_argument("--output", help="Output path for player map")
    args = parser.parse_args()

    repo = _repo_root()

    if args.legacy:
        legacy_path = Path(args.legacy)
    else:
        legacy_path = _latest_file(repo / "data", "legacy_data_*.json")
    if legacy_path is None or not legacy_path.exists():
        print("[player_map] No legacy data file found.")
        return 1

    player_map = build_player_map(legacy_path)

    out_dir = repo / "data" / "player_map"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = out_dir / "player_position_map.json"

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": legacy_path.name,
        "schema_version": "1.0",
        "stats": player_map["stats"],
        "entries": player_map["entries"],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"[player_map] Exported {player_map['stats']['total_entries']} players → {out_path}")
    print(f"[player_map] {player_map['stats']['unique_names']} unique names, "
          f"{player_map['stats']['nickname_expansions']} nickname expansions")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
