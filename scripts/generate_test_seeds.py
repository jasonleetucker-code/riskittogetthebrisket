#!/usr/bin/env python3
"""Generate test seed CSVs for KTC using the real KTC export as reference data.

Creates realistic but synthetic CSVs for KTC by adding controlled noise to
the real KTC values. These seeds allow the pipeline to be tested end-to-end.

The seeds are placed in data/test_seeds/ (NOT exports/latest/site_raw/) to avoid
being confused with real production data.

Usage:
    python scripts/generate_test_seeds.py
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

# Ensure repo root is on sys.path for shared imports
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._shared import _repo_root


def load_ktc_players(repo: Path) -> list[tuple[str, int]]:
    """Load real KTC players as a reference."""
    ktc_path = repo / "exports" / "latest" / "site_raw" / "ktc.csv"
    if not ktc_path.exists():
        return []
    players = []
    with ktc_path.open("r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = str(row.get("name", "")).strip()
            val = str(row.get("value", "")).strip()
            if not name or not val:
                continue
            # Skip picks
            if any(x in name for x in ["Pick", "Early", "Mid", "Late", "1st", "2nd", "3rd", "4th", "5th", "6th"]):
                continue
            try:
                players.append((name, int(val)))
            except ValueError:
                continue
    return sorted(players, key=lambda x: -x[1])


def generate_ktc_seed(players: list[tuple[str, int]], seed: int = 42) -> list[tuple[str, int]]:
    """Generate KTC-like values with controlled noise for testing.

    Adds +-12-15% noise to simulate variation between scrape runs.
    """
    rng = random.Random(seed)
    out = []
    for name, val in players:
        noise_pct = rng.uniform(-0.12, 0.15)
        noisy_val = max(100, int(round(val * (1.0 + noise_pct))))
        out.append((name, noisy_val))
    return out


def write_csv(path: Path, rows: list[tuple[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "value"])
        for name, val in sorted(rows, key=lambda x: x[0].lower()):
            w.writerow([name, val])


def main() -> int:
    repo = _repo_root()
    players = load_ktc_players(repo)
    if not players:
        print("[generate_test_seeds] No KTC data to derive from.")
        return 1

    print(f"[generate_test_seeds] Reference: {len(players)} KTC players")

    seed_dir = repo / "data" / "test_seeds"

    # KTC seed
    ktc = generate_ktc_seed(players)
    ktc_path = seed_dir / "ktc.csv"
    write_csv(ktc_path, ktc)
    print(f"[generate_test_seeds] KTC seed: {len(ktc)} players -> {ktc_path}")

    # Metadata
    meta = {
        "generated_by": "scripts/generate_test_seeds.py",
        "purpose": "Test seed data for pipeline validation. NOT production data.",
        "reference_source": "KTC player values with controlled noise",
        "player_count": len(players),
        "seeds": {
            "ktc": {"file": str(ktc_path), "rows": len(ktc), "random_seed": 42},
        },
    }
    meta_path = seed_dir / "README.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"[generate_test_seeds] Metadata: {meta_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
