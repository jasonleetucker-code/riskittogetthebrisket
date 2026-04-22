#!/usr/bin/env python3
"""Audit per-player Hampel outlier rejections in the live contract.

The per-player Hampel filter in ``src/api/data_contract.py`` drops
source values that sit more than ``_HAMPEL_K`` MADs from the median of
a player's other source values (with a 500 Hill-point absolute floor).
Each affected row stamps ``droppedSources: [...]``.

This script surveys those stamps across the whole board and answers
three diagnostic questions:

  1. How often does Hampel fire at all? (total affected rows,
     distribution of dropped-count per row)
  2. Which sources get dropped most? A source that's dropped on >10%
     of the rows it *could* rank is a candidate for re-ingestion rules,
     a global weight reduction, or adapter-level investigation — its
     disagreement isn't random, it's systemic.
  3. Which individual players carry the largest dropped-source sets?
     Those are the worthwhile spot-check cases: either genuine outlier
     rejections we can verify, or surprise rejections that indicate a
     join-hygiene problem we haven't caught yet.

Run this after a scrape (or any time after the contract has been
rebuilt) to see whether the filter is doing useful work or whether K
/ min_threshold should be retuned.

Usage:
    python scripts/audit_dropped_sources.py [--json-path PATH]
                                            [--top N]
                                            [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _load_payload(json_path: str | None) -> dict:
    """Locate and load the latest contract payload.

    Mirrors ``scripts/audit_identity.py::_load_payload`` — prefer an
    explicit ``--json-path`` override, otherwise fall back to the
    standard latest-build locations.
    """
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
            print(
                "ERROR: No data file found. Pass --json-path explicitly.",
                file=sys.stderr,
            )
            sys.exit(1)

    # Print the load status to stderr so ``--json`` output on stdout
    # stays valid JSON that can be piped straight into ``jq`` without
    # having to strip a leading progress line.
    print(f"Loading: {p}", file=sys.stderr)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _players_array(payload: dict) -> list[dict[str, Any]]:
    """Find the players array inside the contract payload.

    The API response wraps the contract under ``data``; the exports
    build writes it at the top level.
    """
    if isinstance(payload.get("data"), dict):
        arr = payload["data"].get("playersArray")
        if isinstance(arr, list):
            return arr
    arr = payload.get("playersArray")
    return arr if isinstance(arr, list) else []


def _eligible_rows_per_source(
    players: list[dict[str, Any]],
) -> dict[str, int]:
    """Count how many rows each source actually ranked.

    The denominator for "how often is this source Hampel-dropped?"
    must be the set of rows where the source contributed in the first
    place — not the whole board — otherwise a source that covers only
    IDPs looks artificially stable relative to one that covers the
    full offense pool.

    Union of ``sourceRanks.keys()`` and ``droppedSources`` per row: the
    current backend keeps dropped keys in ``sourceRanks`` so the union
    is a no-op, but if a future change strips Hampel-rejected keys out
    of ``sourceRanks`` entirely the dropped occurrences would vanish
    from the denominator and a chronically-dropped source would show
    as ``0 / 0`` instead of ``N / N`` — inverting the elevated-source
    diagnosis.  Union-ing is cheap insurance against that.
    """
    counts: Counter[str] = Counter()
    for row in players:
        keys: set[str] = set()
        ranks = row.get("sourceRanks") or {}
        if isinstance(ranks, dict):
            keys.update(str(k) for k in ranks.keys())
        dropped = row.get("droppedSources") or []
        if isinstance(dropped, list):
            keys.update(str(k) for k in dropped)
        for key in keys:
            counts[key] += 1
    return dict(counts)


def _summarise(players: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = _eligible_rows_per_source(players)

    total_rows = len(players)
    rows_with_drops = 0
    drop_count_histogram: Counter[int] = Counter()
    dropped_by_source: Counter[str] = Counter()
    dropped_by_position: Counter[str] = Counter()
    biggest_offenders: list[dict[str, Any]] = []

    for row in players:
        dropped = row.get("droppedSources") or []
        if not isinstance(dropped, list) or not dropped:
            continue
        rows_with_drops += 1
        drop_count_histogram[len(dropped)] += 1
        for sk in dropped:
            dropped_by_source[str(sk)] += 1
        pos = str(row.get("position") or "?").upper()
        dropped_by_position[pos] += 1
        biggest_offenders.append(
            {
                "rank": row.get("canonicalConsensusRank"),
                "name": row.get("displayName") or row.get("canonicalName") or "?",
                "position": pos,
                "dropped": list(dropped),
                "sourceCount": row.get("sourceCount") or 0,
                "spread": row.get("sourceRankPercentileSpread"),
            }
        )

    biggest_offenders.sort(
        key=lambda o: (-len(o["dropped"]), o["rank"] or 1_000_000)
    )

    return {
        "total_rows": total_rows,
        "rows_with_drops": rows_with_drops,
        "drop_count_histogram": dict(sorted(drop_count_histogram.items())),
        "dropped_by_source": dict(
            sorted(dropped_by_source.items(), key=lambda kv: -kv[1])
        ),
        "eligible_rows_per_source": eligible,
        "dropped_by_position": dict(
            sorted(dropped_by_position.items(), key=lambda kv: -kv[1])
        ),
        "biggest_offenders": biggest_offenders,
    }


def _print_report(summary: dict[str, Any], *, top: int) -> None:
    total = summary["total_rows"]
    hit = summary["rows_with_drops"]
    pct = (100.0 * hit / total) if total else 0.0
    print(f"\n{'=' * 70}")
    print(f"  Hampel drop summary ({total} rows)")
    print(f"{'=' * 70}")
    print(f"Rows with >=1 dropped source: {hit} ({pct:.1f}%)")

    hist = summary["drop_count_histogram"]
    if hist:
        print("\nDrops-per-row distribution:")
        for k in sorted(hist.keys()):
            print(f"  {k} dropped: {hist[k]:>4d} rows")

    print(f"\n{'=' * 70}")
    print("  Drop rate per source")
    print(f"{'=' * 70}")
    print("(dropped / eligible = percentage of this source's rows that were rejected)")
    print()
    src_drops = summary["dropped_by_source"]
    eligible = summary["eligible_rows_per_source"]
    keys = sorted(
        set(src_drops) | set(eligible),
        key=lambda k: (-src_drops.get(k, 0), k),
    )
    print(f"  {'source':<28s} {'dropped':>8s} {'eligible':>10s} {'rate':>8s}")
    for key in keys:
        d = src_drops.get(key, 0)
        e = eligible.get(key, 0)
        rate = (100.0 * d / e) if e else 0.0
        flag = "  <-- elevated" if rate >= 10.0 and e >= 20 else ""
        print(f"  {key:<28s} {d:>8d} {e:>10d} {rate:>7.1f}%{flag}")

    pos_drops = summary["dropped_by_position"]
    if pos_drops:
        print(f"\n{'=' * 70}")
        print("  Drops by position")
        print(f"{'=' * 70}")
        for pos, n in pos_drops.items():
            print(f"  {pos:<5s} {n:>4d}")

    offenders = summary["biggest_offenders"][:top]
    if offenders:
        print(f"\n{'=' * 70}")
        print(f"  Top {len(offenders)} rows by dropped-source count")
        print(f"{'=' * 70}")
        print(
            f"  {'rank':>5s}  {'name':<30s} {'pos':<5s} "
            f"{'#drop':>6s} {'#src':>5s} {'spread':>8s}  dropped"
        )
        for o in offenders:
            rank = str(o["rank"]) if o["rank"] is not None else "-"
            spread = (
                f"{o['spread']:.3f}" if isinstance(o["spread"], (int, float)) else "-"
            )
            dropped = ", ".join(o["dropped"])
            print(
                f"  {rank:>5s}  {o['name']:<30s} {o['position']:<5s} "
                f"{len(o['dropped']):>6d} {o['sourceCount']:>5d} {spread:>8s}  {dropped}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json-path",
        default=None,
        help="Explicit path to a contract JSON snapshot (overrides autodiscovery).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of biggest-offender rows to list (default 20).",
    )
    parser.add_argument(
        "--json",
        dest="emit_json",
        action="store_true",
        help="Emit the summary as JSON on stdout instead of a text report.",
    )
    args = parser.parse_args()

    payload = _load_payload(args.json_path)
    players = _players_array(payload)
    if not players:
        print("ERROR: no playersArray found in the payload.", file=sys.stderr)
        return 1

    summary = _summarise(players)

    if args.emit_json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        _print_report(summary, top=args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
