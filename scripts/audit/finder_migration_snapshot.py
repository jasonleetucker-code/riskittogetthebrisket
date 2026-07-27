#!/usr/bin/env python3
"""Snapshot ``/api/trade/finder`` output for every team, for F-6 before/after.

Collaborative audit, finding K (WS-J F-6).  The finder reads
``_finalAdjusted`` — the raw scraper composite — while the rankings the
user sees, and every sibling trade engine, read ``rankDerivedValue``.
Migrating it moves every number the endpoint emits, so the migration
needs a before and an after rather than a code review.

Run this on the pre-migration tree, then on the post-migration tree, then
diff the two JSON files.  Both runs must use the SAME ``--payload`` or the
comparison measures a data refresh instead of a code change.

    python scripts/audit/finder_migration_snapshot.py --out before.json
    # ... apply the migration ...
    python scripts/audit/finder_migration_snapshot.py --out after.json
    python scripts/audit/finder_migration_snapshot.py --diff before.json after.json

What the diff can and cannot say
--------------------------------
It bounds how far the endpoint's behaviour moves.  It does NOT say which
side is more accurate: both values descend from the same scrape, and
there is no ground truth for what a dynasty asset is worth.  The reason
to prefer the post-migration numbers is coherence with the board the
product actually shows, not measured accuracy.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import inspect  # noqa: E402

from src.trade.finder import find_trades  # noqa: E402

_SUPPORTS_CONTRACT = "contract" in inspect.signature(find_trades).parameters


def _latest_payload() -> Path:
    """Newest dated export, so the script does not rot on a hardcoded date."""
    candidates = sorted(
        (REPO / "exports" / "latest").glob("dynasty_data_*.json"),
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        raise SystemExit("no exports/latest/dynasty_data_*.json found; pass --payload explicitly")
    return candidates[0]


def _teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sleeper = payload.get("sleeper") or {}
    teams = sleeper.get("teams")
    return list(teams) if isinstance(teams, list) else []


def snapshot(payload_path: Path) -> dict[str, Any]:
    """Build the contract from the raw payload, then snapshot the finder.

    ``exports/latest/dynasty_data_*.json`` is the RAW scrape, not the
    served contract — it has ``players`` but no ``playersArray``, so the
    board values only exist after ``build_api_data_contract`` runs.  This
    mirrors ``scripts/measure_engine_value_divergence.py``: build the
    contract from the payload, so before and after are compared with the
    input held constant.
    """
    raw = json.loads(payload_path.read_text(encoding="utf-8"))

    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    payload = build_api_data_contract(raw)
    players = payload.get("players") or {}
    teams = _teams(payload) or _teams(raw)
    if not teams:
        raise SystemExit(f"{payload_path.name} carries no sleeper.teams; cannot snapshot")

    names = [str(t.get("teamName") or t.get("name") or "") for t in teams]
    names = [n for n in names if n]

    out: dict[str, Any] = {
        "payload": payload_path.name,
        "playersInDict": len(players),
        "teams": {},
    }

    for me in names:
        opponents = [n for n in names if n != me]
        try:
            res = find_trades(
                players=players,
                my_team=me,
                opponent_teams=opponents,
                sleeper_teams=teams,
                # None on the pre-migration tree (find_trades has no such
                # kwarg there); the post-migration run passes the board.
                **({"contract": payload} if _SUPPORTS_CONTRACT else {}),
            )
        except Exception as exc:  # noqa: BLE001
            out["teams"][me] = {"error": repr(exc)}
            continue

        trades = res.get("trades") or []
        out["teams"][me] = {
            "tradeCount": len(trades),
            "poolSize": (res.get("metadata") or {}).get("assetPoolSize"),
            "marketCoverage": (res.get("metadata") or {}).get("marketCoverage"),
            "valueSource": (res.get("metadata") or {}).get("valueSource", "rawComposite"),
            "assetsUnpricedByBoard": (res.get("metadata") or {}).get("assetsUnpricedByBoard", 0),
            "warnings": res.get("warnings") or [],
            "arbitrageScores": [round(float(t.get("arbitrageScore") or 0), 3) for t in trades],
            "boardDeltas": [int(t.get("boardDelta") or 0) for t in trades],
            "positionMix": _counter(
                a.get("position")
                for t in trades
                for a in list(t.get("give") or []) + list(t.get("receive") or [])
            ),
            "packageShapes": _counter(
                f"{len(t.get('give') or [])}for{len(t.get('receive') or [])}" for t in trades
            ),
            "top5": [
                {
                    "give": [a.get("name") for a in (t.get("give") or [])],
                    "receive": [a.get("name") for a in (t.get("receive") or [])],
                    "boardDelta": t.get("boardDelta"),
                    "arbitrageScore": t.get("arbitrageScore"),
                }
                for t in trades[:5]
            ],
        }
    return out


def _counter(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for it in items:
        key = str(it or "?")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def diff(before: dict[str, Any], after: dict[str, Any]) -> None:
    b_teams, a_teams = before.get("teams", {}), after.get("teams", {})
    print(f"payload before={before.get('payload')}  after={after.get('payload')}")
    if before.get("payload") != after.get("payload"):
        print("  !! DIFFERENT PAYLOADS — this diff measures a data refresh too")
    print()

    b_counts = [v.get("tradeCount", 0) for v in b_teams.values() if "error" not in v]
    a_counts = [v.get("tradeCount", 0) for v in a_teams.values() if "error" not in v]
    print(f"teams snapshotted:  before {len(b_counts)}  after {len(a_counts)}")
    print(f"total trades:       before {sum(b_counts)}  after {sum(a_counts)}")
    if b_counts and a_counts:
        print(
            f"median per team:    before {statistics.median(b_counts):g}  "
            f"after {statistics.median(a_counts):g}"
        )

    b_pool = {v.get("poolSize") for v in b_teams.values() if "error" not in v}
    a_pool = {v.get("poolSize") for v in a_teams.values() if "error" not in v}
    print(
        f"pool size:          before {sorted(x for x in b_pool if x)}  "
        f"after {sorted(x for x in a_pool if x)}"
    )
    print()

    print("per-team trade count and top-1 stability:")
    changed_top1 = 0
    for team in sorted(set(b_teams) | set(a_teams)):
        b, a = b_teams.get(team, {}), a_teams.get(team, {})
        bt, at = b.get("tradeCount", "-"), a.get("tradeCount", "-")
        b1 = (b.get("top5") or [{}])[0].get("receive")
        a1 = (a.get("top5") or [{}])[0].get("receive")
        same = "same" if b1 == a1 else "CHANGED"
        if b1 != a1:
            changed_top1 += 1
        print(f"  {team[:26]:<26} {str(bt):>4} -> {str(at):<4}  top1 {same}")
    print()
    print(f"top recommendation changed for {changed_top1}/{len(set(b_teams) | set(a_teams))} teams")


def main() -> int:
    ap = argparse.ArgumentParser(description="F-6 finder before/after snapshot.")
    ap.add_argument("--payload", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--diff", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()

    if args.diff:
        before = json.loads(args.diff[0].read_text(encoding="utf-8"))
        after = json.loads(args.diff[1].read_text(encoding="utf-8"))
        diff(before, after)
        return 0

    payload_path = args.payload or _latest_payload()
    snap = snapshot(payload_path)
    text = json.dumps(snap, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}  ({len(snap['teams'])} teams, payload {snap['payload']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
