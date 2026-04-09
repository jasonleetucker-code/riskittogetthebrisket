#!/usr/bin/env python3
"""Audit identity resolution and data quality in the current data contract.

Reports:
  1. Top suspicious / quarantined players
  2. Cross-universe name collisions
  3. Rows with high source disagreement
  4. Unsupported positions on the board
  5. Rows with no valid source values but non-zero derived values
  6. Near-name value mismatches (same last name, different universes)
  7. Identity confidence distribution

Usage:
    python scripts/audit_identity.py [--json-path PATH]
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
    if json_path:
        p = Path(json_path)
    else:
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
            sys.exit(1)

    print(f"Loading: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _section(title: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def _row_line(row: dict, *, show_flags: bool = True) -> str:
    rank = row.get("canonicalConsensusRank") or "-"
    name = row.get("displayName") or row.get("canonicalName") or "?"
    pos = row.get("position") or "?"
    ac = row.get("assetClass") or "?"
    rdv = row.get("rankDerivedValue") or 0
    bucket = row.get("confidenceBucket") or "?"
    ic = row.get("identityConfidence", 0)
    parts = [
        f"#{str(rank):>4s}",
        f"{name:30s}",
        f"{pos:5s}",
        f"{ac:8s}",
        f"val={rdv:>5d}",
        f"conf={bucket:6s}",
        f"id={ic:.2f}",
    ]
    if show_flags:
        flags = ", ".join(row.get("anomalyFlags") or [])
        if flags:
            parts.append(f"  [{flags}]")
    return "  ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit identity resolution quality")
    parser.add_argument("--json-path", help="Path to a JSON contract/payload file")
    args = parser.parse_args()

    raw = _load_payload(args.json_path)
    contract = build_api_data_contract(raw)
    players = contract.get("playersArray", [])
    validation = contract.get("validationSummary", {})

    total = len(players)
    ranked = sum(1 for p in players if p.get("canonicalConsensusRank"))
    quarantined = [p for p in players if p.get("quarantined")]

    print(f"\nTotal players: {total}")
    print(f"Ranked:        {ranked}")
    print(f"Quarantined:   {len(quarantined)}")

    # ── 1. Quarantined / suspicious players ──
    _section("QUARANTINED PLAYERS (sorted by rank)")
    quarantined.sort(key=lambda p: p.get("canonicalConsensusRank") or 9999)
    if not quarantined:
        print("  (none)")
    else:
        for p in quarantined[:60]:
            print(f"  {_row_line(p)}")

    # ── 2. Cross-universe collisions ──
    _section("CROSS-UNIVERSE NAME COLLISIONS")
    collisions = validation.get("crossUniverseCollisions", [])
    if not collisions:
        print("  (none)")
    else:
        for c in collisions:
            names = ", ".join(c.get("names", []))
            classes = ", ".join(c.get("assetClasses", []))
            print(f"  norm='{c.get('normalizedName', '?')}' → [{classes}]  names: {names}")

    # ── 3. Near-name mismatches ──
    _section("NEAR-NAME VALUE MISMATCHES (same last name, cross-universe)")
    near = validation.get("nearNameMismatches", [])
    if not near:
        print("  (none)")
    else:
        for n in near[:30]:
            print(
                f"  {n.get('lastName', '?'):15s}  "
                f"off={n.get('offenseName', '?'):25s} val={n.get('offenseValue', 0):>5d}  "
                f"idp={n.get('idpName', '?'):25s} val={n.get('idpValue', 0):>5d}  "
                f"ratio={n.get('ratio', 0):.1f}x"
            )

    # ── 4. High source disagreement ──
    _section("HIGH SOURCE DISAGREEMENT (sourceRankSpread > 80)")
    disagreed = [
        p for p in players
        if (p.get("sourceRankSpread") or 0) > 80
    ]
    disagreed.sort(key=lambda p: p.get("sourceRankSpread") or 0, reverse=True)
    if not disagreed:
        print("  (none)")
    else:
        for p in disagreed[:20]:
            spread = p.get("sourceRankSpread") or "?"
            gap = p.get("marketGapDirection") or "?"
            print(f"  {_row_line(p, show_flags=False)}  spread={spread}  gap={gap}")

    # ── 5. Unsupported positions ──
    _section("UNSUPPORTED POSITIONS")
    unsupported = [
        p for p in players
        if "unsupported_position" in (p.get("anomalyFlags") or [])
    ]
    if not unsupported:
        print("  (none)")
    else:
        for p in unsupported[:30]:
            print(f"  {_row_line(p)}")

    # ── 6. No valid source values + non-zero derived value ──
    _section("NO SOURCE VALUES BUT HAS DERIVED VALUE")
    orphans = [
        p for p in players
        if "no_valid_source_values" in (p.get("anomalyFlags") or [])
    ]
    if not orphans:
        print("  (none)")
    else:
        for p in orphans[:30]:
            print(f"  {_row_line(p)}")

    # ── 7. Identity confidence distribution ──
    _section("IDENTITY CONFIDENCE DISTRIBUTION")
    buckets = {"1.00": 0, "0.95": 0, "0.85": 0, "0.70": 0}
    for p in players:
        ic = p.get("identityConfidence", 0)
        if ic >= 1.0:
            buckets["1.00"] += 1
        elif ic >= 0.95:
            buckets["0.95"] += 1
        elif ic >= 0.85:
            buckets["0.85"] += 1
        else:
            buckets["0.70"] += 1

    for level, count in buckets.items():
        pct = (count / total * 100) if total else 0
        bar = "#" * int(pct / 2)
        labels = {
            "1.00": "canonical_id",
            "0.95": "pos+source aligned",
            "0.85": "partial evidence",
            "0.70": "name only",
        }
        print(f"  {level} ({labels[level]:20s}) {count:>5d}  ({pct:5.1f}%)  {bar}")

    # ── 8. Position-source contradictions ──
    _section("POSITION-SOURCE CONTRADICTIONS")
    contradictions = [
        p for p in players
        if "position_source_contradiction" in (p.get("anomalyFlags") or [])
    ]
    if not contradictions:
        print("  (none)")
    else:
        for p in contradictions[:30]:
            sites = p.get("canonicalSiteValues") or {}
            site_str = ", ".join(f"{k}={v}" for k, v in sites.items() if v)
            print(f"  {_row_line(p)}  sources: {site_str}")

    print()


if __name__ == "__main__":
    main()
