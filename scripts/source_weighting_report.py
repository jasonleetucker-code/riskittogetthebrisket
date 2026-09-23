#!/usr/bin/env python3
"""Print the source weighting table (and optional player breakdowns).

The same view ``GET /api/sources/weighting`` and
``GET /api/players/{id}/value-explain`` serve, built locally from a raw
payload through the canonical pipeline — nothing is recomputed outside it.

Usage:
    python scripts/source_weighting_report.py                     # latest export
    python scripts/source_weighting_report.py --player "Jack Campbell" --player "Josh Allen"
    python scripts/source_weighting_report.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api.data_contract import build_api_data_contract  # noqa: E402
from src.api.source_weighting_explain import (  # noqa: E402
    find_row,
    player_explain,
    source_table,
)


def _latest_payload() -> Path:
    candidates = sorted((REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
    if not candidates:
        raise SystemExit("no exports/latest/dynasty_data_*.json payload")
    return candidates[-1]


def _fetch_stamps(state_dir: Path) -> dict[str, dict]:
    """``{key: {lastFetched}}`` from ``<key>_last_success`` epoch stamps — the
    infrastructure clock only, shown beside (never instead of) data age."""
    out: dict[str, dict] = {}
    for stamp in state_dir.glob("*_last_success"):
        try:
            epoch = float(stamp.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            continue
        at = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out[stamp.name[: -len("_last_success")]] = {"lastFetched": at}
    return out


def _fmt(v, width, prec=2):
    if v is None:
        return "—".rjust(width)
    if isinstance(v, float):
        return f"{v:.{prec}f}".rjust(width)
    return str(v).rjust(width)


def print_table(table: dict) -> None:
    print(f"as of {table['asOf']}  curve {table['curve']}  applied={table['applied']}")
    print(f"formula: {table['formula']}")
    print(f"row states: {table['rowStates']}")
    hdr = (
        f"{'SOURCE':24s} {'SUBSET':7s} {'ROLE':9s} {'STYLE':12s} {'EXP_h':>7s} {'LAST FETCH':>17s} "
        f"{'LAST ANY':>17s} {'LAST BROAD':>17s} {'AGE_h':>7s} {'r':>5s} {'FRESH':>6s} "
        f"{'HLTH':>5s} {'COV':>5s} {'BASE':>5s} {'EFF':>6s} {'SHARE':>6s} STATE"
    )
    print(hdr)
    for r in table["sources"]:
        print(
            f"{r['source']:24s} {str(r.get('subset')):7s} {str(r.get('role'))[:9]:9s} "
            f"{str(r.get('publicationStyle'))[:12]:12s} {_fmt(r.get('expectedCadenceHours'), 7, 1)} "
            f"{str(r.get('lastFetchedAt'))[:16]:>17s} "
            f"{str(r.get('lastAnyMeaningfulChangeAt'))[:16]:>17s} "
            f"{str(r.get('lastBroadDatasetChangeAt'))[:16]:>17s} "
            f"{_fmt(r.get('ageHours'), 7, 1)} {_fmt(r.get('ageOverExpected'), 5)} "
            f"{_fmt(r.get('freshness'), 6, 3)} {_fmt(r.get('healthFactor'), 5)} "
            f"{_fmt(r.get('coverageFactor'), 5)} {_fmt(r.get('baseWeight'), 5)} "
            f"{_fmt(r.get('effectiveWeight'), 6, 3)} {_fmt(r.get('meanVoteShare'), 6, 3)} "
            f"{r.get('state')}"
        )


def print_player(ex: dict) -> None:
    print(
        f"\nPLAYER: {ex['player']} ({ex['position']})  model {ex['modelValue']} "
        f"rank {ex['modelRank']}  state {ex['sourceWeightState']} "
        f"retained {ex['retainedAuthority']}  confidence {ex['confidence']}"
    )
    print("  MODEL SOURCES")
    for s in ex["modelSources"]:
        print(
            f"    {s['source']:24s} raw {_fmt(s['rawValue'], 7, 0)} rk {_fmt(s['rawRank'], 5, 0)} norm "
            f"{_fmt(s['normalizedValue'], 5, 0)} age {_fmt(s['ageHours'], 6, 1)}h "
            f"exp {_fmt(s['expectedCadenceHours'], 6, 1)}h fresh {_fmt(s['freshness'], 5, 3)} "
            f"hlth {_fmt(s['healthFactor'], 4)} base {_fmt(s['baseWeight'], 4)} "
            f"eff {_fmt(s['effectiveWeight'], 5, 3)} share {_fmt(s['voteShare'], 5, 3)} "
            f"contrib {_fmt(s['contribution'], 7, 1)}  {s['status']}"
        )
    m = ex["ktcMarketBenchmark"]
    print(
        f"  KTC MARKET  crowd {m['ktcCrowdComponent']}  trades {m['ktcTradesComponent']}  "
        f"market {m['ktcMarketValue']} (norm {m['ktcMarketNormalizedValue']})  "
        f"freshness/confidence {m['marketDataState']}"
    )
    d = ex["modelVsKtcMarket"]
    print(
        f"  MODEL VS KTC MARKET  abs {d['absoluteDifference']}  pct {d['percentDifference']}  "
        f"normalized {d['normalizedDifference']}  direction {d['direction']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--payload", type=Path, default=None)
    parser.add_argument("--player", action="append", default=[])
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    payload_path = args.payload or _latest_payload()
    contract = build_api_data_contract(json.loads(payload_path.read_text(encoding="utf-8")))
    table = source_table(contract, _fetch_stamps(REPO_ROOT / "data" / "scrape_state"))
    print_table(table)
    explained = []
    for name in args.player:
        row = find_row(contract, name)
        if row is None:
            print(f"\nPLAYER: {name} — not on the board")
            continue
        ex = player_explain(contract, row)
        explained.append(ex)
        print_player(ex)
    if args.json:
        args.json.write_text(json.dumps({"table": table, "players": explained}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
