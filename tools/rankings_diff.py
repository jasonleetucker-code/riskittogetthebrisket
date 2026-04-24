#!/usr/bin/env python3
"""A/B ranking-diff tool (upgrade item #9).

Compare two rankings output dumps — typically STATIC weights vs
DYNAMIC weights — side-by-side so you can verify a weight flip
isn't going to surprise users in prod.

Usage
-----
    python3 tools/rankings_diff.py <baseline.json> <candidate.json>

    # Also accepts URL arguments if auth is available:
    python3 tools/rankings_diff.py \\
        https://riskittogetthebrisket.org/api/data?view=delta \\
        https://staging.riskit/api/data?view=delta \\
        --cookie jason_session=...

Output
------
Human-readable summary:
    * # players whose rank moved >N positions (N=1/5/10/25)
    * # players who CROSSED a top-50 / top-100 / top-150 line
    * Top 20 biggest rank drops + top 20 biggest rank climbs
    * Per-position mean absolute rank delta

Exit codes
----------
    0  diff printed
    1  any player moved >50 ranks (flagged as concerning)
    2  file / URL load failed

Pure-Python; no external deps beyond urllib.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_source(src: str, cookie: str | None = None) -> dict[str, Any]:
    """Load a dump from a file path or URL.  Returns parsed JSON."""
    if src.startswith("http://") or src.startswith("https://"):
        req = urllib.request.Request(src)
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            print(f"ERROR loading {src}: {exc}", file=sys.stderr)
            sys.exit(2)
    path = Path(src)
    if not path.exists():
        print(f"ERROR: file not found: {src}", file=sys.stderr)
        sys.exit(2)
    return json.loads(path.read_text(encoding="utf-8"))


def _ranks_by_name(payload: dict[str, Any]) -> dict[str, tuple[int, str]]:
    """Return ``{displayName: (canonicalRank, position)}`` from a
    contract payload.  Uses playersArray if present, else falls
    back to the legacy players dict."""
    out: dict[str, tuple[int, str]] = {}
    arr = payload.get("playersArray")
    if isinstance(arr, list) and arr:
        for p in arr:
            if not isinstance(p, dict):
                continue
            name = str(p.get("displayName") or p.get("canonicalName") or "")
            rank = p.get("canonicalConsensusRank")
            pos = str(p.get("position") or "")
            if name and isinstance(rank, int) and rank > 0:
                out[name] = (rank, pos)
        return out
    players = payload.get("players") or {}
    if isinstance(players, dict):
        for name, p in players.items():
            if not isinstance(p, dict):
                continue
            rank = p.get("_canonicalConsensusRank") or p.get("canonicalConsensusRank")
            pos = str(p.get("position") or "")
            if isinstance(rank, int) and rank > 0:
                out[name] = (rank, pos)
    return out


def _diff(baseline: dict[str, tuple[int, str]], candidate: dict[str, tuple[int, str]]) -> dict[str, Any]:
    """Compute the diff.  Returns a dict with all the stats."""
    common = set(baseline.keys()) & set(candidate.keys())
    only_baseline = set(baseline.keys()) - set(candidate.keys())
    only_candidate = set(candidate.keys()) - set(baseline.keys())

    deltas: list[tuple[str, int, int, int, str]] = []  # (name, base_rank, cand_rank, delta, pos)
    by_pos_abs: dict[str, list[int]] = defaultdict(list)
    for name in common:
        b_rank, pos = baseline[name]
        c_rank, _ = candidate[name]
        delta = c_rank - b_rank
        deltas.append((name, b_rank, c_rank, delta, pos))
        by_pos_abs[pos].append(abs(delta))

    # Buckets of movement size.
    moved = {
        1: sum(1 for d in deltas if abs(d[3]) > 1),
        5: sum(1 for d in deltas if abs(d[3]) > 5),
        10: sum(1 for d in deltas if abs(d[3]) > 10),
        25: sum(1 for d in deltas if abs(d[3]) > 25),
        50: sum(1 for d in deltas if abs(d[3]) > 50),
    }
    # Line crossings.
    crossed = {
        "top50": sum(1 for (_, b, c, _, _) in deltas if (b <= 50) != (c <= 50)),
        "top100": sum(1 for (_, b, c, _, _) in deltas if (b <= 100) != (c <= 100)),
        "top150": sum(1 for (_, b, c, _, _) in deltas if (b <= 150) != (c <= 150)),
    }
    # Sort for top movers.
    deltas.sort(key=lambda d: d[3])
    biggest_drops = deltas[-20:][::-1]  # most negative rank delta = biggest drop in value
    biggest_climbs = deltas[:20]  # most negative delta means they became #1
    # Wait — rank 1 is BETTER.  A climb means rank DECREASED (1 is best).
    # So "delta < 0" = climbed, "delta > 0" = dropped.  Fix sort direction.
    deltas.sort(key=lambda d: d[3])  # ascending = climbs first (negative)
    biggest_climbs = deltas[:20]
    biggest_drops = deltas[-20:][::-1]

    by_pos = {
        pos: round(sum(vals) / len(vals), 2) if vals else 0.0
        for pos, vals in by_pos_abs.items()
    }
    return {
        "commonCount": len(common),
        "onlyBaseline": len(only_baseline),
        "onlyCandidate": len(only_candidate),
        "moved": moved,
        "crossed": crossed,
        "biggestClimbs": biggest_climbs,
        "biggestDrops": biggest_drops,
        "byPosMeanAbs": by_pos,
    }


def _format_report(diff: dict[str, Any]) -> str:
    lines = []
    lines.append(f"Common players compared: {diff['commonCount']}")
    lines.append(f"Only in baseline:        {diff['onlyBaseline']}")
    lines.append(f"Only in candidate:       {diff['onlyCandidate']}")
    lines.append("")
    lines.append("Rank movement distribution:")
    for threshold in (1, 5, 10, 25, 50):
        lines.append(f"  > {threshold:>3} rank change: {diff['moved'][threshold]:>5}")
    lines.append("")
    lines.append("Line crossings (crossed into/out of the top):")
    for line_name, count in diff["crossed"].items():
        lines.append(f"  {line_name:>8}: {count}")
    lines.append("")
    lines.append("Mean |delta| per position:")
    for pos in sorted(diff["byPosMeanAbs"].keys()):
        lines.append(f"  {pos:>5}: {diff['byPosMeanAbs'][pos]:.2f}")
    lines.append("")
    lines.append("Biggest CLIMBS (rank improved most):")
    for (name, b, c, d, pos) in diff["biggestClimbs"]:
        lines.append(f"  {pos:>4} {name[:28]:<28} {b:>4} → {c:<4} ({d:+d})")
    lines.append("")
    lines.append("Biggest DROPS (rank worsened most):")
    for (name, b, c, d, pos) in diff["biggestDrops"]:
        lines.append(f"  {pos:>4} {name[:28]:<28} {b:>4} → {c:<4} ({d:+d})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", help="file path or URL")
    parser.add_argument("candidate", help="file path or URL")
    parser.add_argument("--cookie", help="Cookie header for authed URLs")
    parser.add_argument(
        "--warn-threshold", type=int, default=50,
        help="Exit 1 if any player moves >N ranks (default 50)",
    )
    args = parser.parse_args(argv)

    b = _load_source(args.baseline, args.cookie)
    c = _load_source(args.candidate, args.cookie)
    b_ranks = _ranks_by_name(b)
    c_ranks = _ranks_by_name(c)
    if not b_ranks or not c_ranks:
        print("ERROR: could not extract rank data from both inputs", file=sys.stderr)
        return 2
    diff = _diff(b_ranks, c_ranks)
    print(_format_report(diff))
    if diff["moved"][args.warn_threshold] > 0:
        print(f"\nWARN: {diff['moved'][args.warn_threshold]} players moved >{args.warn_threshold} ranks")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
