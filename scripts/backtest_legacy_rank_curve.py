#!/usr/bin/env python3
"""Backtest the legacy rank-form Hill curve against the live board.

WHY THIS EXISTS
===============
Two live code paths convert a board RANK back into a VALUE using the
legacy rank-form Hill curve in ``src/canonical/player_valuation.py``:

  * ``src/api/terminal.py::_row_value`` — falls back to
    ``rank_to_value(canonicalConsensusRank)`` when a row carries a rank
    but no ``rankDerivedValue`` / ``values.full``.
  * ``src/api/rank_history.py::_value_for_rank`` — reconstructs a value
    for historical snapshots that persisted a rank but not a value,
    scope-aware (``IDP_HILL_*`` for IDP rows, ``HILL_*`` otherwise).

Those constants (``HILL_MIDPOINT`` 48.44 / ``HILL_SLOPE`` 1.149,
``IDP_HILL_MIDPOINT`` 69.50 / ``IDP_HILL_SLOPE`` 0.945) are NOT in the
model registry's ``CONSTANT_NAMES`` and are refit by a different script
(``scripts/fit_hill_curve_from_market.py``) than the percentile-form
scope masters the live board actually blends with
(``scripts/fit_hill_curve_percentile.py`` + the weekly registry refit).
So the two families drift independently, and a fallback can disagree
with the board it is standing in for.

THE QUESTION THIS ANSWERS
=========================
This is a CONSISTENCY test, not a predictive-accuracy test.  The board
(``rankDerivedValue``) is the authority on what a player is worth.  A
rank→value fallback exists to answer "what would the board have said
for this rank?", so the right metric is simply: how closely does each
candidate curve reproduce the live board from rank alone?

Candidates compared:
  1. legacy_offense    — rank_to_value with HILL_MIDPOINT/HILL_SLOPE
                         (what terminal.py uses for EVERY row today)
  2. legacy_scope      — legacy constants, IDP rows use IDP_HILL_*
                         (what rank_history.py does today)
  3. percentile_offense— the live OFFENSE master (c, s) evaluated at
                         p = (rank-1)/(referenceN-1)
  4. percentile_scope  — live scope masters, IDP rows use the IDP master
  5. percentile_global — the live GLOBAL master for every row
  6. refit_rank_form   — a rank-form curve fit to THIS board, reported
                         as the achievable floor so the gaps above can
                         be read against what is actually possible

Reported overall, by asset class, and by rank band, as RMSE / MAE /
median absolute error, all on the 1–9999 display scale.

USAGE
=====
    python scripts/backtest_legacy_rank_curve.py
    python scripts/backtest_legacy_rank_curve.py --payload path/to.json
    python scripts/backtest_legacy_rank_curve.py --out docs/measurements/x.json

Exit codes: 0 success, 1 error (missing payload / no rows).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.canonical.player_valuation import (  # noqa: E402
    HILL_MIDPOINT,
    HILL_SLOPE,
    HILL_GLOBAL_PERCENTILE_C,
    HILL_GLOBAL_PERCENTILE_S,
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    IDP_HILL_MIDPOINT,
    IDP_HILL_SLOPE,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    percentile_to_value,
    rank_to_value,
)

_IDP_POSITIONS = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "OLB", "ILB", "MLB", "DB", "CB", "S", "FS", "SS"}
)

RANK_BANDS: tuple[tuple[str, int, int], ...] = (
    ("1-24", 1, 24),
    ("25-60", 25, 60),
    ("61-120", 61, 120),
    ("121-250", 121, 250),
    ("251-500", 251, 500),
    ("501+", 501, 10**9),
)


def _scope_of(row: dict[str, Any]) -> str:
    """offense | idp | pick — mirrors rank_history.py's scope split."""
    if row.get("assetClass") == "pick":
        return "pick"
    pos = str(row.get("position") or "").strip().upper()
    return "idp" if pos in _IDP_POSITIONS else "offense"


def _default_payload_path() -> Path | None:
    latest = REPO_ROOT / "exports" / "latest"
    if not latest.is_dir():
        return None
    candidates = sorted(latest.glob("dynasty_data_*.json"))
    return candidates[-1] if candidates else None


def _load_rows(payload_path: Path) -> list[dict[str, Any]]:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    payload = json.loads(payload_path.read_text())
    contract = build_api_data_contract(payload)
    rows: list[dict[str, Any]] = []
    for row in contract.get("playersArray") or []:
        rank = row.get("canonicalConsensusRank")
        value = row.get("rankDerivedValue")
        if not isinstance(rank, (int, float)) or rank <= 0:
            continue
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        rows.append(
            {
                "name": row.get("displayName") or row.get("canonicalName"),
                "rank": float(rank),
                "value": float(value),
                "scope": _scope_of(row),
            }
        )
    return rows


# ── Candidate curves ────────────────────────────────────────────────────
# Each takes (rank, scope) and returns a value on the 1-9999 scale.


def _percentile_at(rank: float, ref_n: int) -> float:
    denom = max(1, ref_n - 1)
    return max(0.0, min(1.0, (rank - 1.0) / denom))


def _build_candidates(ref_n: int) -> dict[str, Callable[[float, str], float]]:
    def legacy_offense(rank: float, _scope: str) -> float:
        return float(rank_to_value(rank))

    def legacy_scope(rank: float, scope: str) -> float:
        if scope == "idp":
            return float(rank_to_value(rank, midpoint=IDP_HILL_MIDPOINT, slope=IDP_HILL_SLOPE))
        return float(rank_to_value(rank, midpoint=HILL_MIDPOINT, slope=HILL_SLOPE))

    def percentile_offense(rank: float, _scope: str) -> float:
        p = _percentile_at(rank, ref_n)
        return float(percentile_to_value(p, midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S))

    def percentile_scope(rank: float, scope: str) -> float:
        p = _percentile_at(rank, ref_n)
        if scope == "idp":
            return float(
                percentile_to_value(p, midpoint=IDP_HILL_PERCENTILE_C, slope=IDP_HILL_PERCENTILE_S)
            )
        return float(percentile_to_value(p, midpoint=HILL_PERCENTILE_C, slope=HILL_PERCENTILE_S))

    def percentile_global(rank: float, _scope: str) -> float:
        p = _percentile_at(rank, ref_n)
        return float(
            percentile_to_value(
                p, midpoint=HILL_GLOBAL_PERCENTILE_C, slope=HILL_GLOBAL_PERCENTILE_S
            )
        )

    return {
        "legacy_offense": legacy_offense,
        "legacy_scope": legacy_scope,
        "percentile_offense": percentile_offense,
        "percentile_scope": percentile_scope,
        "percentile_global": percentile_global,
    }


def _fit_rank_form(rows: list[dict[str, Any]]) -> tuple[float, float]:
    """Coarse grid + refine fit of a rank-form Hill curve to the board.

    Reported as the achievable floor.  Deliberately a simple search —
    this is a reference point for reading the other candidates' gaps,
    not a production fit routine.
    """
    best = (float("inf"), HILL_MIDPOINT, HILL_SLOPE)
    ranks = [r["rank"] for r in rows]
    values = [r["value"] for r in rows]

    def rmse_for(mid: float, slope: float) -> float:
        total = 0.0
        for rank, actual in zip(ranks, values):
            pred = 1.0 + 9998.0 / (1.0 + ((max(1.0, rank) - 1.0) / mid) ** slope)
            total += (pred - actual) ** 2
        return math.sqrt(total / len(ranks))

    for mid_i in range(10, 201, 5):
        for slope_i in range(50, 251, 5):
            mid = float(mid_i)
            slope = slope_i / 100.0
            err = rmse_for(mid, slope)
            if err < best[0]:
                best = (err, mid, slope)
    _, mid0, slope0 = best
    for mid_i in range(int((mid0 - 5) * 10), int((mid0 + 5) * 10) + 1, 2):
        for slope_i in range(int((slope0 - 0.05) * 1000), int((slope0 + 0.05) * 1000) + 1, 5):
            mid = mid_i / 10.0
            slope = slope_i / 1000.0
            if mid <= 0 or slope <= 0:
                continue
            err = rmse_for(mid, slope)
            if err < best[0]:
                best = (err, mid, slope)
    return round(best[1], 4), round(best[2], 4)


def _fit_rank_form_per_scope(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Fit a separate rank-form curve per scope.

    The live code carries TWO pairs (``HILL_*`` and ``IDP_HILL_*``) and
    ``rank_history.py`` routes by scope, so the honest question is whether
    the scopes actually WANT different curves.  They largely do not, and
    the reason is structural: ``canonicalConsensusRank`` is a single
    GLOBAL ordinal over the whole board, so offense, IDP and pick rows all
    lie on one rank→value relation by construction.  Splitting the fit
    measures how much the sub-populations deviate from it, not two
    genuinely different economies.

    ``pick`` is fit and reported for completeness; no live path routes
    picks to their own rank-form pair.
    """
    out: dict[str, dict[str, float]] = {}
    for scope in sorted({r["scope"] for r in rows}):
        subset = [r for r in rows if r["scope"] == scope]
        if len(subset) < 20:
            continue
        mid, slope = _fit_rank_form(subset)
        out[scope] = {"midpoint": mid, "slope": slope, "n": len(subset)}
    return out


def _metrics(errors: list[float]) -> dict[str, float | int]:
    if not errors:
        return {"n": 0}
    abs_err = [abs(e) for e in errors]
    return {
        "n": len(errors),
        "rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 1),
        "mae": round(sum(abs_err) / len(abs_err), 1),
        "medianAbsErr": round(statistics.median(abs_err), 1),
        "maxAbsErr": round(max(abs_err), 1),
        "meanSignedErr": round(sum(errors) / len(errors), 1),
    }


def _evaluate(rows: list[dict[str, Any]], fn: Callable[[float, str], float]) -> dict[str, Any]:
    overall: list[float] = []
    by_scope: dict[str, list[float]] = {}
    by_band: dict[str, list[float]] = {}
    for row in rows:
        err = fn(row["rank"], row["scope"]) - row["value"]
        overall.append(err)
        by_scope.setdefault(row["scope"], []).append(err)
        for label, lo, hi in RANK_BANDS:
            if lo <= row["rank"] <= hi:
                by_band.setdefault(label, []).append(err)
                break
    return {
        "overall": _metrics(overall),
        "byScope": {k: _metrics(v) for k, v in sorted(by_scope.items())},
        "byRankBand": {
            label: _metrics(by_band[label]) for label, _, _ in RANK_BANDS if label in by_band
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, default=None, help="raw scraper payload JSON")
    parser.add_argument("--out", type=Path, default=None, help="write results JSON here")
    parser.add_argument("--skip-fit", action="store_true", help="skip the refit reference curve")
    args = parser.parse_args()

    payload_path = args.payload or _default_payload_path()
    if payload_path is None or not payload_path.is_file():
        print(f"ERROR: no payload found (looked for {payload_path})", file=sys.stderr)
        return 1

    from src.api.data_contract import _PERCENTILE_REFERENCE_N  # noqa: PLC0415

    rows = _load_rows(payload_path)
    if not rows:
        print("ERROR: payload produced no ranked+valued rows", file=sys.stderr)
        return 1

    candidates = _build_candidates(_PERCENTILE_REFERENCE_N)
    results: dict[str, Any] = {name: _evaluate(rows, fn) for name, fn in candidates.items()}

    refit: dict[str, Any] | None = None
    refit_scope: dict[str, dict[str, float]] | None = None
    if not args.skip_fit:
        mid, slope = _fit_rank_form(rows)
        refit = {"midpoint": mid, "slope": slope}
        results["refit_rank_form"] = _evaluate(
            rows, lambda r, _s, m=mid, sl=slope: float(rank_to_value(r, midpoint=m, slope=sl))
        )

        refit_scope = _fit_rank_form_per_scope(rows)
        if refit_scope:

            def _per_scope(rank: float, scope: str) -> float:
                pair = refit_scope.get(scope) or {"midpoint": mid, "slope": slope}
                return float(rank_to_value(rank, midpoint=pair["midpoint"], slope=pair["slope"]))

            results["refit_rank_form_per_scope"] = _evaluate(rows, _per_scope)

    payload_out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        # ``--payload`` may point outside the repo (e.g. a snapshot
        # extracted to a temp dir for a stability sweep), so
        # ``relative_to`` is best-effort rather than assumed.
        "payload": str(
            payload_path.relative_to(REPO_ROOT)
            if payload_path.is_relative_to(REPO_ROOT)
            else payload_path
        ),
        "rowCount": len(rows),
        "scopeCounts": {
            scope: sum(1 for r in rows if r["scope"] == scope)
            for scope in sorted({r["scope"] for r in rows})
        },
        "percentileReferenceN": _PERCENTILE_REFERENCE_N,
        "liveConstants": {
            "legacyOffense": {"midpoint": HILL_MIDPOINT, "slope": HILL_SLOPE},
            "legacyIdp": {"midpoint": IDP_HILL_MIDPOINT, "slope": IDP_HILL_SLOPE},
            "percentileOffense": {"c": HILL_PERCENTILE_C, "s": HILL_PERCENTILE_S},
            "percentileIdp": {"c": IDP_HILL_PERCENTILE_C, "s": IDP_HILL_PERCENTILE_S},
            "percentileGlobal": {"c": HILL_GLOBAL_PERCENTILE_C, "s": HILL_GLOBAL_PERCENTILE_S},
        },
        "refitRankForm": refit,
        "refitRankFormPerScope": refit_scope,
        "results": results,
    }

    ranked = sorted(
        ((name, res["overall"].get("rmse", float("inf"))) for name, res in results.items()),
        key=lambda kv: kv[1],
    )
    print(f"Rows: {len(rows)}  ({payload_out['scopeCounts']})")
    print(f"Percentile reference N: {_PERCENTILE_REFERENCE_N}")
    if refit:
        print(f"Best-fit rank-form curve on this board: {refit}")
    if refit_scope:
        print("Best-fit rank-form curve per scope:")
        for scope, pair in refit_scope.items():
            print(
                f"  {scope:8s} midpoint={pair['midpoint']:8.4f} "
                f"slope={pair['slope']:6.4f}  (n={int(pair['n'])})"
            )
    print("\nOverall RMSE (lower = reproduces the live board more closely):")
    for name, rmse in ranked:
        overall = results[name]["overall"]
        print(
            f"  {name:22s} rmse={rmse:8.1f}  mae={overall['mae']:8.1f}  "
            f"medAbs={overall['medianAbsErr']:8.1f}  meanSigned={overall['meanSignedErr']:+9.1f}"
        )
    print("\nBy scope (RMSE):")
    scopes = sorted({r["scope"] for r in rows})
    header = "  " + " " * 22 + "".join(f"{s:>12s}" for s in scopes)
    print(header)
    for name, _ in ranked:
        cells = "".join(
            f"{results[name]['byScope'].get(s, {}).get('rmse', float('nan')):>12.1f}"
            for s in scopes
        )
        print(f"  {name:22s}{cells}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload_out, indent=2) + "\n")
        print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
