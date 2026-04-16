"""Regenerate the top-player baseline fixture used by
``tests/api/test_pick_refinement.py::TestPlayerRankingsUnchanged``.

Run this whenever an intentional change to the pick refinement or
ranking blend shifts the known-player ranks in the captured snapshot.
The resulting ``top_player_baseline.json`` is committed to the repo
alongside the test so the invariant the test pins (rank proximity +
value proximity + confidence bucket) is reproducible on any machine.

Usage:
    cd /path/to/trade-calculator
    .venv/bin/python tests/api/fixtures/regen_top_player_baseline.py

The script reads the newest ``dynasty_data_*.json`` under
``exports/latest`` and stamps its player rows into the fixture JSON.
It does NOT require the FastAPI server to be running — it runs the
canonical contract builder directly against the on-disk scrape.

Add or remove target players by editing ``TARGETS`` below.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

# Top-five offense + a few additional anchors so the baseline exercises
# the full top-25 window rather than pinning only the #1-#5 slots.
TARGETS: list[str] = [
    "Josh Allen",
    "Ja'Marr Chase",
    "Bijan Robinson",
    "Drake Maye",
    "Jahmyr Gibbs",
    "Puka Nacua",
    "Brock Bowers",
    "Jayden Daniels",
    "Malik Nabers",
    "Patrick Mahomes",
]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root))

    from src.api.data_contract import build_api_data_contract  # noqa: E402

    data_dir = repo_root / "exports" / "latest"
    scrape_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not scrape_files:
        print(
            f"ERROR: No dynasty_data_*.json under {data_dir}",
            file=sys.stderr,
        )
        return 1

    newest = scrape_files[0]
    raw = json.loads(newest.read_text())
    contract = build_api_data_contract(raw)
    by_name = {
        r["canonicalName"]: r
        for r in contract.get("playersArray") or []
        if r.get("canonicalName")
    }

    players: dict[str, dict[str, object]] = {}
    for target in TARGETS:
        row = by_name.get(target)
        if not row:
            print(f"WARN: {target} not found in current contract", file=sys.stderr)
            continue
        players[target] = {
            "canonicalConsensusRank": int(row.get("canonicalConsensusRank") or 0),
            "rankDerivedValue": int(row.get("rankDerivedValue") or 0),
            "confidenceBucket": str(row.get("confidenceBucket") or ""),
        }

    payload = {
        "capturedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": newest.name,
        "note": (
            "Top-player baseline snapshot for "
            "tests/api/test_pick_refinement.py::TestPlayerRankingsUnchanged. "
            "Regenerate via "
            "tests/api/fixtures/regen_top_player_baseline.py whenever "
            "intentional pick-refinement or blend changes shift the captured "
            "rankings. Day-to-day scrape churn is absorbed by tolerances in "
            "the test itself, so routine scrape drift does NOT require a "
            "regen — only real invariant changes do."
        ),
        "players": dict(sorted(players.items())),
    }

    out_path = Path(__file__).resolve().parent / "top_player_baseline.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {out_path}")
    print(f"  source: {newest.name}")
    print(f"  players: {len(players)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
