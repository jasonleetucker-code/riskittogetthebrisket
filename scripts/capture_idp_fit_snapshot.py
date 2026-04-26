"""Capture a point-in-time snapshot of IDP scoring-fit values.

Designed to run quarterly (or before each major scrape) so we can do a
real historical backtest down the road — "would this lens have flagged
the right buy-lows entering 2024?" — instead of the current sanity-
check that uses CURRENT consensus values to backtest PRIOR seasons.

Snapshot shape (one JSON file per run, keyed by date):

    data/idp_fit_snapshots/{YYYY-MM-DD}.json

    {
      "captured_at": "2026-04-26T17:00:00Z",
      "season": 2026,
      "scoring_fit_weight": 0.30,
      "players": [
        {
          "name": "Micah Parsons",
          "position": "LB",
          "consensus": 8500,
          "delta": 3200,
          "adjusted": 9460,
          "tier": "elite",
          "confidence": "high",
          "synthetic": false
        },
        ...
      ]
    }

Usage:

    python3 scripts/capture_idp_fit_snapshot.py
    python3 scripts/capture_idp_fit_snapshot.py --dry-run

Run this BEFORE flipping the scoring-fit feature flag to capture a
baseline.  Re-run quarterly thereafter.  Backtest scripts can then
compare a captured snapshot's lens output against subsequent realized
production to evaluate the lens's predictive power.

No production behavior is modified — read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Force the flag ON for the duration of this build so the snapshot
# captures lens output regardless of the live env-var state.
os.environ["RISKIT_FEATURE_IDP_SCORING_FIT"] = "1"

from src.api import data_contract as DC  # noqa: E402
from src.api import feature_flags as FF  # noqa: E402


def _idp_position(p: str) -> bool:
    return str(p or "").upper() in {
        "DL", "DT", "DE", "EDGE", "NT",
        "LB", "ILB", "OLB", "MLB",
        "DB", "CB", "S", "FS", "SS",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Build the snapshot but don't write to disk")
    parser.add_argument("--output-dir", default=None,
                        help="Override default snapshot directory")
    args = parser.parse_args()

    FF.reload()
    print(f"flag idp_scoring_fit: {FF.is_enabled('idp_scoring_fit')}")

    # Load the latest raw payload + build the canonical contract.
    exports = _REPO_ROOT / "exports" / "latest"
    snapshots = sorted(exports.glob("dynasty_data_*.json"))
    if not snapshots:
        print("ERROR: no raw payload in exports/latest/", file=sys.stderr)
        return 2
    raw_path = snapshots[-1]
    print(f"reading raw payload from: {raw_path.name}")
    raw = json.loads(raw_path.read_text())

    contract = DC.build_api_data_contract(raw)
    arr = contract.get("playersArray") or []

    captured_at = datetime.now(timezone.utc).isoformat()
    season = (datetime.now(timezone.utc).year
              if datetime.now(timezone.utc).month >= 9
              else datetime.now(timezone.utc).year - 1)

    players_out = []
    for row in arr:
        if not isinstance(row, dict):
            continue
        pos = str(row.get("position") or "").upper()
        if not _idp_position(pos):
            continue
        delta = row.get("idpScoringFitDelta")
        if not isinstance(delta, (int, float)):
            continue
        players_out.append({
            "name": row.get("displayName"),
            "position": pos,
            "playerId": row.get("playerId"),
            "consensus": row.get("rankDerivedValue"),
            "delta": float(delta),
            "adjusted": row.get("idpScoringFitAdjustedValue"),
            "tier": row.get("idpScoringFitTier"),
            "confidence": row.get("idpScoringFitConfidence"),
            "synthetic": bool(row.get("idpScoringFitSynthetic")),
            "draft_round": row.get("idpScoringFitDraftRound"),
            "weighted_ppg": row.get("idpScoringFitWeightedPpg"),
            "games_used": row.get("idpScoringFitGamesUsed"),
        })

    snapshot = {
        "captured_at": captured_at,
        "season": season,
        "scoring_fit_weight": 0.30,
        "source_payload": raw_path.name,
        "player_count": len(players_out),
        "players": players_out,
    }

    print(f"captured {len(players_out)} IDPs with deltas")

    if args.dry_run:
        print("dry-run: skipping write")
        # Print a tiny summary instead.
        positives = [p for p in players_out if p["delta"] > 0]
        negatives = [p for p in players_out if p["delta"] < 0]
        print(f"  positive delta: {len(positives)} players")
        print(f"  negative delta: {len(negatives)} players")
        print(f"  synthetic rookies: {sum(1 for p in players_out if p['synthetic'])}")
        return 0

    out_dir = Path(args.output_dir) if args.output_dir else _REPO_ROOT / "data" / "idp_fit_snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = out_dir / f"{today}.json"
    out_path.write_text(json.dumps(snapshot, indent=2))
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
