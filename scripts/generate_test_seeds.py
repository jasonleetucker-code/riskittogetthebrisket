#!/usr/bin/env python3
"""Generate test seed CSVs for sources that lack real scraper exports.

Creates realistic but synthetic CSVs for KTC and DynastyDaddy using FantasyCalc
player data as a reference. These seeds allow the pipeline to be tested end-to-end
with multi-source blending before the legacy scraper produces real exports.

The seeds are placed in data/test_seeds/ (NOT exports/latest/site_raw/) to avoid
being confused with real production data. Tests can copy them to the expected
location for pipeline validation.

Usage:
    python scripts/generate_test_seeds.py
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_fantasycalc_players(repo: Path) -> list[tuple[str, int]]:
    """Load real FantasyCalc players as a reference."""
    fc_path = repo / "exports" / "latest" / "site_raw" / "fantasyCalc.csv"
    if not fc_path.exists():
        return []
    players = []
    with fc_path.open("r", encoding="utf-8-sig") as f:
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
    """Generate KTC-like values from FantasyCalc reference with realistic variation.

    KTC values are crowdsourced and tend to be correlated with but not identical
    to FantasyCalc. We add controlled noise (±5-15%) to simulate this.
    """
    rng = random.Random(seed)
    out = []
    for name, fc_val in players:
        # KTC tends to slightly inflate elite QBs and value young WRs more
        noise_pct = rng.uniform(-0.12, 0.15)
        ktc_val = max(100, int(round(fc_val * (1.0 + noise_pct))))
        out.append((name, ktc_val))
    return out


def generate_dynastydaddy_seed(players: list[tuple[str, int]], seed: int = 123) -> list[tuple[str, int]]:
    """Generate DynastyDaddy-like values from FantasyCalc reference.

    DynastyDaddy is API-based and tends to have broader coverage but slightly
    different top-end valuations. We use moderate noise (±8-18%).
    """
    rng = random.Random(seed)
    out = []
    # DynastyDaddy typically has broader player coverage
    for name, fc_val in players:
        noise_pct = rng.uniform(-0.15, 0.12)
        dd_val = max(50, int(round(fc_val * (1.0 + noise_pct))))
        out.append((name, dd_val))
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
    players = load_fantasycalc_players(repo)
    if not players:
        print("[generate_test_seeds] No FantasyCalc data to derive from.")
        return 1

    print(f"[generate_test_seeds] Reference: {len(players)} FantasyCalc players")

    seed_dir = repo / "data" / "test_seeds"

    # KTC seed
    ktc = generate_ktc_seed(players)
    ktc_path = seed_dir / "ktc.csv"
    write_csv(ktc_path, ktc)
    print(f"[generate_test_seeds] KTC seed: {len(ktc)} players → {ktc_path}")

    # DynastyDaddy seed
    dd = generate_dynastydaddy_seed(players)
    dd_path = seed_dir / "dynastyDaddy.csv"
    write_csv(dd_path, dd)
    print(f"[generate_test_seeds] DynastyDaddy seed: {len(dd)} players → {dd_path}")

    # Metadata
    meta = {
        "generated_by": "scripts/generate_test_seeds.py",
        "purpose": "Test seed data for pipeline validation. NOT production data.",
        "reference_source": "FantasyCalc player values with controlled noise",
        "player_count": len(players),
        "seeds": {
            "ktc": {"file": str(ktc_path), "rows": len(ktc), "random_seed": 42},
            "dynastyDaddy": {"file": str(dd_path), "rows": len(dd), "random_seed": 123},
        },
    }
    meta_path = seed_dir / "README.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"[generate_test_seeds] Metadata: {meta_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
