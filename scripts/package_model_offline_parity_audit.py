#!/usr/bin/env python3
"""Offline-parity audit for the production market-ledger evaluation (research only).

The production run (``package_model_phase2_research.py --market-ledger-only``)
rebuilt every archived board under the read-only guard, which refused the one
network call ``build_api_data_contract`` makes:
``data_contract._resolve_league_context`` (Sleeper ``total_rosters`` +
``scoring_settings.bonus_rec_te``).  The build then used its fallback
``{roster_count: 12, bonus_rec_te: 0.0, fetched_from_sleeper: False}``.

This audit rebuilds every archived board in the evaluation window three times,
with the league context pinned (no network in any variant):

* ``fallback``   — exactly what the guarded production run used;
* ``live``       — what the live call returns for the registry league today
                   (12 rosters, ``bonus_rec_te`` 0.0, fetched);
* ``ctx2025``    — sensitivity only: the 2025 season-league's context
                   (10 rosters, ``bonus_rec_te`` 0.35), to show how much a
                   DIFFERENT league context would have moved values.

and reports, per variant pair, how many canonical values (players and pick rows)
differ.  Aggregates only.  Nothing is written outside ``--out``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

VARIANTS = {
    "fallback": {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": False},
    "live": {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": True},
    "ctx2025": {"roster_count": 10, "bonus_rec_te": 0.35, "fetched_from_sleeper": True},
}


def _boards(first: date, last: date) -> list[tuple[date, Path, str]]:
    out = []
    for path in sorted((REPO / "exports" / "archive").glob("dynasty_export_*.zip")):
        with zipfile.ZipFile(path) as zf:
            name = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        d = datetime.strptime(name[len("dynasty_data_") : -len(".json")], "%Y-%m-%d").date()
        if first <= d <= last:
            out.append((d, path, name))
    return sorted(out)


def _values(contract: dict) -> dict[str, float]:
    out = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        key = (
            f"pick:{row.get('displayName')}"
            if row.get("assetClass") == "pick"
            else f"p:{row.get('playerId') or row.get('displayName')}"
        )
        v = row.get("rankDerivedValue")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v)
    return out


def _diff(a: dict, b: dict) -> dict:
    keys = set(a) | set(b)
    changed = [k for k in keys if a.get(k) != b.get(k)]
    deltas = [abs(a[k] - b[k]) for k in changed if k in a and k in b]
    return {
        "rows": len(keys),
        "changed": len(changed),
        "onlyInOne": sum(1 for k in changed if (k in a) != (k in b)),
        "maxAbsDelta": round(max(deltas), 3) if deltas else 0.0,
        "changedPicks": sum(1 for k in changed if k.startswith("pick:")),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--first", default="2026-07-14")
    ap.add_argument("--last", default="2026-10-18")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from src.api import data_contract as dc  # noqa: PLC0415

    boards = _boards(date.fromisoformat(args.first), date.fromisoformat(args.last))
    per_board = []
    t0 = time.time()
    for d, path, name in boards:
        with zipfile.ZipFile(path) as zf:
            raw = json.loads(zf.read(name))
        vals = {}
        for vname, ctx in VARIANTS.items():
            dc._LEAGUE_CONTEXT_CACHE.clear()
            dc._resolve_league_context = lambda *_a, _c=ctx, **_k: dict(_c)  # noqa: E731
            vals[vname] = _values(dc.build_api_data_contract(raw))
        per_board.append({
            "boardDate": d.isoformat(),
            "fallback_vs_live": _diff(vals["fallback"], vals["live"]),
            "fallback_vs_ctx2025": _diff(vals["fallback"], vals["ctx2025"]),
        })  # fmt: skip
        print(f"{d} {per_board[-1]['fallback_vs_live']} {per_board[-1]['fallback_vs_ctx2025']}"
              f" ({time.time() - t0:.0f}s)", flush=True)  # fmt: skip

    def total(key):
        return {
            "boards": len(per_board),
            "boardsWithAnyChange": sum(1 for b in per_board if b[key]["changed"]),
            "rowsCompared": sum(b[key]["rows"] for b in per_board),
            "rowsChanged": sum(b[key]["changed"] for b in per_board),
            "maxAbsDelta": max((b[key]["maxAbsDelta"] for b in per_board), default=0.0),
        }

    result = {
        "purpose": "Offline-parity audit of the guarded production ledger evaluation (research only)",
        "window": [args.first, args.last],
        "variants": VARIANTS,
        "fallbackVsLive": total("fallback_vs_live"),
        "fallbackVsCtx2025Sensitivity": total("fallback_vs_ctx2025"),
        "perBoard": per_board,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "perBoard"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
