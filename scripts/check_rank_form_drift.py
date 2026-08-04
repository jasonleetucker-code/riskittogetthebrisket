#!/usr/bin/env python3
"""Alarm when the legacy rank-form Hill constants drift off the board.

WHAT DRIFTS, AND WHY IT IS SILENT
=================================
``HILL_MIDPOINT`` / ``HILL_SLOPE`` and ``IDP_HILL_MIDPOINT`` /
``IDP_HILL_SLOPE`` in ``src/canonical/player_valuation.py`` reconstruct a
value from a rank.  Two live paths use them — ``terminal.py``'s value
fallback and ``rank_history.py``'s historical backfill — plus the
frontend mirror in ``value-history.js``.

Nothing fails when they stop matching the board.  A reconstruction path
returning a wrong-but-plausible number produces a chart that renders
fine, and that is exactly how the pre-2026-07-30 pair went unnoticed at
RMSE 821.8 on offense rows against a floor of 89.8 — a ~9x error on
every reconstructed offense value.

WHAT MOVES THEM
===============
Not market churn.  16 archived snapshots spanning 2026-07-16 → 07-30 all
refit to offense 65.4 / 0.910 and IDP 64.4-64.6 / 0.900, because the
board's rank→value relation IS a Hill curve — churn only permutes which
player sits at which rank.

What moves them is a **percentile-master promotion**.  The masters are
step 3 of the live pipeline, so promoting a new pair reshapes the board's
rank→value relation and the rank-form approximation of it goes stale.
Measured: the pre-promotion board of 2026-07-29 refit to 68.8 / 0.929,
the post-promotion board to 65.2 / 0.905.  So this check belongs
downstream of ``scripts/model_registry.py apply``, and the workflow that
runs it fires on the same weekly cadence as the refit.

THE METRIC
==========
Parameter delta is the wrong alarm — a curve can move its parameters and
still reproduce the board (the two are partially redundant), and a small
parameter move near a steep optimum can matter more than a large one on
a plateau.  What matters is whether the COMMITTED curve still reproduces
the board, so the metric is:

    excess RMSE = RMSE(committed constants) − RMSE(refit optimum)

per scope, on the served board's ranked rows.  Zero means the committed
curve is optimal; the default threshold of 25.0 (on the 1–9999 display
scale) is the point at which a reconstructed history value is off by
enough to be visible on a chart.  For reference, the committed pair
scored an excess of 0.4 when it was set on 2026-07-30, and the pair it
replaced scored 732.

WHY THIS DOES NOT AUTO-COMMIT
=============================
ADR-008 (``docs/roster-trade-intelligence/DECISIONS.md``) prohibits a
model autonomously rewriting production constants, and its sharpest
finding is worth re-reading before automating anything here: the old
refit path was green **by construction** because it rewrote the very
test that guarded it.

An auto-fix that patched ``player_valuation.py`` *and* re-baselined
``test_rank_form_constants_tripwire.py`` / ``test_player_valuation.py``
would recreate that exact circularity — a PR that cannot fail its own
guard.  So this script computes the fix and hands it over: it prints the
constants to write and the files to write them in, and the workflow opens
an issue.  The human edit then makes the tripwire fail, and updating the
pins is the deliberate, recorded act.  That is the whole design.

USAGE
=====
    python scripts/check_rank_form_drift.py
    python scripts/check_rank_form_drift.py --verbose
    python scripts/check_rank_form_drift.py --threshold 15
    python scripts/check_rank_form_drift.py --json-out /tmp/drift.json

Exit codes:
    0  within tolerance
    1  error (no payload, no ranked rows, unreadable snapshot)
    2  drift detected — a human should act
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.canonical.player_valuation import (  # noqa: E402
    HILL_MIDPOINT,
    HILL_SLOPE,
    IDP_HILL_MIDPOINT,
    IDP_HILL_SLOPE,
)

DEFAULT_THRESHOLD = 25.0

# scope -> (constant name pair, committed values).  ``pick`` is fit and
# reported but has no committed pair: ``rank_to_value_for_scope`` routes
# picks to the offense curve deliberately (the board prices them by
# tethering, not by a rank curve), so a pick-only fit is diagnostic.
_COMMITTED: dict[str, tuple[tuple[str, str], tuple[float, float]]] = {
    "offense": (("HILL_MIDPOINT", "HILL_SLOPE"), (HILL_MIDPOINT, HILL_SLOPE)),
    "idp": (("IDP_HILL_MIDPOINT", "IDP_HILL_SLOPE"), (IDP_HILL_MIDPOINT, IDP_HILL_SLOPE)),
}


def _load_backtest_module() -> ModuleType:
    """Import the backtest script as a module.

    It is a script, not a package member, so this is the same importlib
    pattern ``audit-dropped-sources.yml`` uses.  Reusing it keeps ONE
    grid-search and ONE definition of "which rows count" — duplicating
    either here is how the two would end up disagreeing about drift.
    """
    path = REPO_ROOT / "scripts" / "backtest_legacy_rank_curve.py"
    spec = importlib.util.spec_from_file_location("backtest_legacy_rank_curve", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rmse(rows: list[dict[str, Any]], midpoint: float, slope: float) -> float:
    total = 0.0
    for row in rows:
        rank = max(1.0, float(row["rank"]))
        pred = 1.0 + 9998.0 / (1.0 + ((rank - 1.0) / midpoint) ** slope)
        total += (pred - float(row["value"])) ** 2
    return math.sqrt(total / len(rows))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=None, help="raw scraper payload JSON")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f"excess-RMSE budget per scope before drift is reported (default {DEFAULT_THRESHOLD})",
    )
    parser.add_argument("--json-out", type=Path, default=None, help="write the verdict here")
    parser.add_argument("--verbose", action="store_true", help="print per-scope detail")
    args = parser.parse_args()

    try:
        backtest = _load_backtest_module()
    except Exception as exc:  # pragma: no cover - import-time failure
        print(f"ERROR: could not load the backtest module: {exc}", file=sys.stderr)
        return 1

    payload_path = args.payload or backtest._default_payload_path()
    if payload_path is None or not Path(payload_path).is_file():
        print(f"ERROR: no payload found (looked for {payload_path})", file=sys.stderr)
        return 1

    try:
        rows = backtest._load_rows(Path(payload_path))
    except Exception as exc:
        print(f"ERROR: could not build a contract from {payload_path}: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("ERROR: payload produced no ranked+valued rows", file=sys.stderr)
        return 1

    per_scope = backtest._fit_rank_form_per_scope(rows)

    scopes: dict[str, Any] = {}
    drifted: list[str] = []
    for scope, (names, committed) in _COMMITTED.items():
        subset = [r for r in rows if r["scope"] == scope]
        if not subset:
            scopes[scope] = {"n": 0, "note": "no rows of this scope on the board"}
            continue
        fit = per_scope.get(scope)
        committed_rmse = _rmse(subset, committed[0], committed[1])
        if fit is None:
            scopes[scope] = {
                "n": len(subset),
                "committed": {"midpoint": committed[0], "slope": committed[1]},
                "committedRmse": round(committed_rmse, 1),
                "note": "too few rows to refit; no comparison made",
            }
            continue
        best_rmse = _rmse(subset, fit["midpoint"], fit["slope"])
        excess = committed_rmse - best_rmse
        entry = {
            "n": len(subset),
            "constantNames": list(names),
            "committed": {"midpoint": committed[0], "slope": committed[1]},
            "refit": {"midpoint": fit["midpoint"], "slope": fit["slope"]},
            "committedRmse": round(committed_rmse, 1),
            "refitRmse": round(best_rmse, 1),
            "excessRmse": round(excess, 1),
            "drifted": bool(excess > args.threshold),
        }
        scopes[scope] = entry
        if entry["drifted"]:
            drifted.append(scope)

    verdict = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "payload": Path(payload_path).name,
        "rowCount": len(rows),
        "threshold": args.threshold,
        "scopes": scopes,
        "pickDiagnostic": per_scope.get("pick"),
        "drifted": drifted,
        "status": "drift" if drifted else "ok",
    }

    print(f"payload   : {Path(payload_path).name}  ({len(rows)} ranked rows)")
    print(f"threshold : {args.threshold:.1f} excess RMSE per scope\n")
    for scope, entry in scopes.items():
        if "excessRmse" not in entry:
            print(f"{scope:8s} {entry.get('note')}")
            continue
        flag = "DRIFT" if entry["drifted"] else "ok"
        print(
            f"{scope:8s} {flag:5s} committed "
            f"{entry['committed']['midpoint']:.4g}/{entry['committed']['slope']:.4g} "
            f"rmse={entry['committedRmse']:.1f}   refit "
            f"{entry['refit']['midpoint']:.4g}/{entry['refit']['slope']:.4g} "
            f"rmse={entry['refitRmse']:.1f}   excess={entry['excessRmse']:+.1f}"
        )
    if args.verbose and per_scope.get("pick"):
        pick = per_scope["pick"]
        print(
            f"\npick     (diagnostic only, routed to the offense curve) "
            f"best fit {pick['midpoint']:.4g}/{pick['slope']:.4g} on n={int(pick['n'])}"
        )

    if drifted:
        print("\nDRIFT DETECTED. To fix, edit these THREE places together:\n")
        print("  1. src/canonical/player_valuation.py")
        for scope in drifted:
            entry = scopes[scope]
            mid_name, slope_name = entry["constantNames"]
            print(f"       {mid_name}: float = {entry['refit']['midpoint']}")
            print(f"       {slope_name}: float = {entry['refit']['slope']}")
        if "offense" in drifted:
            off = scopes["offense"]["refit"]
            print("\n  2. frontend/lib/value-history.js — RANK_FORM_CURVE")
            print(f"       midpoint: {off['midpoint']},")
            print(f"       slope: {off['slope']},")
        else:
            print("\n  2. frontend/lib/value-history.js — no change (it mirrors")
            print("     the OFFENSE pair only)")
        print("\n  3. tests/canonical/test_rank_form_constants_tripwire.py — _PINNED")
        print("     and tests/canonical/test_player_valuation.py spot values.")
        print(
            "\nThose two test files are deliberately NOT rewritten by this "
            "script: see the 'WHY THIS DOES NOT AUTO-COMMIT' note in its "
            "docstring, and ADR-008."
        )

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(verdict, indent=2) + "\n")
        print(f"\nWrote {args.json_out}")

    return 2 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
