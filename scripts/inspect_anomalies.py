#!/usr/bin/env python3
"""Inspect anomaly flags and confidence buckets in the current data contract.

Usage:
    python scripts/inspect_anomalies.py [--json-path PATH]

Without --json-path, loads the latest data file from the default pipeline
location.  With --json-path, loads a specific JSON contract file.

Output:
    1. Anomaly summary (total flagged, per-flag counts)
    2. Confidence bucket distribution
    3. Top flagged players with their anomaly details
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract


def _load_payload(json_path: str | None) -> dict:
    """Load a raw payload for contract building."""
    if json_path:
        p = Path(json_path)
    else:
        # Default: look for latest data export
        candidates = [
            REPO / "data" / "latest.json",
            REPO / "exports" / "latest" / "dynasty_data.json",
            REPO / "data" / "dynasty_data.json",
        ]
        p = None
        for c in candidates:
            if c.exists():
                p = c
                break
        if p is None:
            print("ERROR: No data file found. Pass --json-path explicitly.", file=sys.stderr)
            print(f"Searched: {[str(c) for c in candidates]}", file=sys.stderr)
            sys.exit(1)

    print(f"Loading: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect anomaly flags in data contract")
    parser.add_argument("--json-path", help="Path to a JSON contract/payload file")
    args = parser.parse_args()

    raw = _load_payload(args.json_path)

    # Build the contract to get computed fields
    contract = build_api_data_contract(raw)
    players = contract.get("playersArray", [])

    # ── Anomaly Summary ──
    _print_section("ANOMALY SUMMARY")
    summary = contract.get("anomalySummary", {})
    total_flagged = summary.get("totalFlagged", 0)
    flag_counts = summary.get("flagCounts", {})
    total_players = len(players)
    ranked = sum(1 for p in players if p.get("canonicalConsensusRank"))

    print(f"Total players:   {total_players}")
    print(f"Ranked players:  {ranked}")
    print(f"Flagged players: {total_flagged}")
    if flag_counts:
        print("\nPer-flag counts:")
        for flag, count in sorted(flag_counts.items(), key=lambda x: -x[1]):
            print(f"  {flag:35s} {count:>4d}")
    else:
        print("  (no anomalies detected)")

    # ── Confidence Bucket Distribution ──
    _print_section("CONFIDENCE BUCKET DISTRIBUTION")
    bucket_counts: dict[str, int] = {}
    for p in players:
        bucket = p.get("confidenceBucket", "none")
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    for bucket in ["high", "medium", "low", "none"]:
        count = bucket_counts.get(bucket, 0)
        pct = (count / total_players * 100) if total_players else 0
        bar = "#" * int(pct / 2)
        print(f"  {bucket:8s} {count:>5d}  ({pct:5.1f}%)  {bar}")

    # ── Top Flagged Players ──
    _print_section("FLAGGED PLAYERS (up to 50)")
    flagged = [
        p for p in players
        if p.get("anomalyFlags")
    ]
    flagged.sort(key=lambda p: p.get("canonicalConsensusRank") or 9999)

    if not flagged:
        print("  (none)")
    else:
        for p in flagged[:50]:
            rank = p.get("canonicalConsensusRank") or "-"
            name = p.get("displayName") or p.get("canonicalName") or "?"
            pos = p.get("position") or "?"
            flags = ", ".join(p.get("anomalyFlags", []))
            bucket = p.get("confidenceBucket", "?")
            print(f"  #{str(rank):>4s}  {name:30s} {pos:5s}  [{bucket:6s}]  {flags}")

    # ── Source Disagreement Players ──
    _print_section("SOURCE DISAGREEMENT (top 20 by spread)")
    disagreed = [
        p for p in players
        if p.get("hasSourceDisagreement")
    ]
    disagreed.sort(key=lambda p: p.get("sourceRankSpread") or 0, reverse=True)

    if not disagreed:
        print("  (none)")
    else:
        for p in disagreed[:20]:
            rank = p.get("canonicalConsensusRank") or "-"
            name = p.get("displayName") or p.get("canonicalName") or "?"
            spread = p.get("sourceRankSpread") or "?"
            direction = p.get("marketGapDirection") or "?"
            print(f"  #{str(rank):>4s}  {name:30s}  spread={spread}  gap={direction}")

    print()


if __name__ == "__main__":
    main()
