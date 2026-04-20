#!/usr/bin/env python3
"""Auto-refit the Hill scope masters and apply if drift exceeds threshold.

Reads the committed Hill constants from
``src/canonical/player_valuation.py``, runs the framework-faithful
fit via ``scripts/fit_hill_curve_percentile.py``, computes curve-shape
drift between committed and newly-fit masters, and applies the new
constants (rewriting ``player_valuation.py`` and re-baselining the
KTC reconciliation test pins) when drift exceeds the threshold.

Drift metric: RMSE of V_new(p) − V_old(p) over the percentile grid
{0.01, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.90} for each scope
master.  The max RMSE across all four scopes is compared to the
threshold.

Threshold (``DRIFT_RMSE_THRESHOLD``): **50 points** on the 0–9999
scale (~0.5% of scale).  Well above grid-search fit noise (~5 pts)
and well below typical market-shift curve drift (~100–500 pts).

Exit codes:
    0   no drift — no changes made
    1   drift applied — files modified, ready to commit
    2   error — fit or file rewrite failed

Usage:
    python3 scripts/auto_refit_hill_curves.py
    python3 scripts/auto_refit_hill_curves.py --dry-run
    python3 scripts/auto_refit_hill_curves.py --threshold 100
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAYER_VALUATION = REPO / "src" / "canonical" / "player_valuation.py"
KTC_RECONCILIATION_TEST = (
    REPO / "tests" / "canonical" / "test_ktc_reconciliation.py"
)
FIT_SCRIPT = REPO / "scripts" / "fit_hill_curve_percentile.py"
KTC_CSV = REPO / "CSVs" / "site_raw" / "ktc.csv"

CONSTANT_NAMES: tuple[str, ...] = (
    "HILL_GLOBAL_PERCENTILE_C",
    "HILL_GLOBAL_PERCENTILE_S",
    "HILL_PERCENTILE_C",
    "HILL_PERCENTILE_S",
    "IDP_HILL_PERCENTILE_C",
    "IDP_HILL_PERCENTILE_S",
    "HILL_ROOKIE_PERCENTILE_C",
    "HILL_ROOKIE_PERCENTILE_S",
)

SCOPE_TO_CS = {
    "GLOBAL":  ("HILL_GLOBAL_PERCENTILE_C",  "HILL_GLOBAL_PERCENTILE_S"),
    "OFFENSE": ("HILL_PERCENTILE_C",         "HILL_PERCENTILE_S"),
    "IDP":     ("IDP_HILL_PERCENTILE_C",     "IDP_HILL_PERCENTILE_S"),
    "ROOKIE":  ("HILL_ROOKIE_PERCENTILE_C",  "HILL_ROOKIE_PERCENTILE_S"),
}

DRIFT_RMSE_THRESHOLD: float = 50.0
DRIFT_GRID: tuple[float, ...] = (0.01, 0.05, 0.10, 0.20, 0.30, 0.50, 0.70, 0.90)


def _hill(p: float, c: float, s: float) -> float:
    """Pure Hill eval — must match ``percentile_to_value`` at p>0."""
    if p <= 0.0:
        return 9999.0
    if p >= 1.0:
        p = 1.0
    return 9999.0 / (1.0 + (p / c) ** s)


def read_committed_constants() -> dict[str, float]:
    """Parse the committed constants from player_valuation.py."""
    text = PLAYER_VALUATION.read_text()
    out: dict[str, float] = {}
    for name in CONSTANT_NAMES:
        # Match lines like ``NAME: float = 0.1100``.
        m = re.search(
            rf"^{re.escape(name)}:\s*float\s*=\s*([0-9.]+)\s*$",
            text,
            re.MULTILINE,
        )
        if not m:
            raise RuntimeError(
                f"Could not find constant {name!r} in "
                f"{PLAYER_VALUATION}.  Did the file format change?"
            )
        out[name] = float(m.group(1))
    return out


def run_fit_with_json() -> dict[str, float]:
    """Run the fit script, capture JSON output, return constants dict."""
    with tempfile.NamedTemporaryFile(
        mode="w+", suffix=".json", delete=False
    ) as tmp:
        json_path = Path(tmp.name)
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(FIT_SCRIPT),
                "--json-out",
                str(json_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO),
            check=True,
        )
        data = json.loads(json_path.read_text())
        return {str(k): float(v) for k, v in data.items()}
    finally:
        try:
            json_path.unlink()
        except FileNotFoundError:
            pass


def compute_scope_drift(
    committed: dict[str, float], fitted: dict[str, float]
) -> dict[str, float]:
    """Return per-scope RMSE of V_new(p) − V_old(p) over DRIFT_GRID."""
    out: dict[str, float] = {}
    for scope, (c_name, s_name) in SCOPE_TO_CS.items():
        c_old, s_old = committed[c_name], committed[s_name]
        c_new, s_new = fitted[c_name], fitted[s_name]
        sq_diffs = [
            (_hill(p, c_new, s_new) - _hill(p, c_old, s_old)) ** 2
            for p in DRIFT_GRID
        ]
        rmse = (sum(sq_diffs) / len(sq_diffs)) ** 0.5
        out[scope] = rmse
    return out


def rewrite_player_valuation(fitted: dict[str, float]) -> None:
    """Update the 8 Hill constants in player_valuation.py in place."""
    text = PLAYER_VALUATION.read_text()
    for name, new_val in fitted.items():
        # Preserve formatting — c stays 4 decimals, s stays 3 decimals.
        if name.endswith("_C"):
            new_literal = f"{new_val:.4f}"
        else:
            new_literal = f"{new_val:.3f}"
        pattern = rf"^({re.escape(name)}:\s*float\s*=\s*)[0-9.]+(\s*)$"
        text, n = re.subn(
            pattern,
            rf"\g<1>{new_literal}\g<2>",
            text,
            flags=re.MULTILINE,
        )
        if n != 1:
            raise RuntimeError(
                f"Expected exactly 1 match for {name!r} in "
                f"{PLAYER_VALUATION}, got {n}"
            )
    PLAYER_VALUATION.write_text(text)


def rebaseline_ktc_reconciliation(fitted: dict[str, float]) -> None:
    """Recompute PINNED_DELTAS in test_ktc_reconciliation.py from the
    new OFFENSE master's output at each pinned rank, using the
    CURRENT KTC CSV as the reference denominator.
    """
    import csv

    # Load KTC values (same filter as the test).
    pick_re = re.compile(r"^\d{4}\s+(Early|Mid|Late)\s+\d", re.IGNORECASE)
    rows: list[tuple[str, int]] = []
    with KTC_CSV.open() as f:
        for r in csv.DictReader(f):
            name = (r.get("name") or "").strip()
            val = (r.get("value") or "").strip()
            if not name or not val or pick_re.match(name):
                continue
            try:
                rows.append((name, int(val)))
            except ValueError:
                continue
    rows.sort(key=lambda t: -t[1])

    # Percentile reference N is read from data_contract.py to stay in
    # sync.  Parsing inline is cheaper than importing the module.
    data_contract_text = (
        REPO / "src" / "api" / "data_contract.py"
    ).read_text()
    ref_n_match = re.search(
        r"_PERCENTILE_REFERENCE_N:\s*int\s*=\s*(\d+)",
        data_contract_text,
    )
    if not ref_n_match:
        raise RuntimeError("Could not find _PERCENTILE_REFERENCE_N")
    ref_n = int(ref_n_match.group(1))

    c_off = fitted["HILL_PERCENTILE_C"]
    s_off = fitted["HILL_PERCENTILE_S"]

    # Build the new PINNED_DELTAS list.  Preserve the existing
    # tolerance bands per rank.
    test_text = KTC_RECONCILIATION_TEST.read_text()
    existing_tolerances: dict[int, float] = {}
    for m in re.finditer(
        r"\(\s*(\d+),\s*\d+,\s*-?\d+\.\d+,\s*(-?\d+\.\d+)\s*\)",
        test_text,
    ):
        rank = int(m.group(1))
        tol = float(m.group(2))
        existing_tolerances[rank] = tol

    # Ranks pinned in the test.  Keep the order as-is.
    new_entries: list[tuple[int, int, float, float]] = []
    for rank in sorted(existing_tolerances.keys()):
        if rank - 1 >= len(rows):
            continue
        _, ktc = rows[rank - 1]
        p = (rank - 1) / max(1.0, float(ref_n - 1))
        p = max(0.0, min(1.0, p))
        ours = int(round(_hill(p, c_off, s_off)))
        pct_diff = 100.0 * (ours - ktc) / ktc
        tol = existing_tolerances[rank]
        new_entries.append((rank, ours, round(pct_diff, 1), tol))

    # Rewrite PINNED_DELTAS in the test file.
    new_block_lines = ["PINNED_DELTAS: list[tuple[int, int, float, float]] = ["]
    for rank, ours, pct, tol in new_entries:
        sign = "" if pct >= 0 else ""
        new_block_lines.append(
            f"    ({rank:>3}, {ours:>4}, {pct:>5}, {tol:>4}),"
        )
    new_block_lines.append("]")
    new_block = "\n".join(new_block_lines)

    test_text_new = re.sub(
        r"PINNED_DELTAS:\s*list\[tuple\[int, int, float, float\]\] = \[[^\]]*\]",
        new_block,
        test_text,
        flags=re.DOTALL,
        count=1,
    )
    if test_text_new == test_text:
        raise RuntimeError("Failed to rewrite PINNED_DELTAS in test file")
    KTC_RECONCILIATION_TEST.write_text(test_text_new)


def format_drift_report(
    committed: dict[str, float],
    fitted: dict[str, float],
    drift: dict[str, float],
    threshold: float,
) -> str:
    lines: list[str] = []
    lines.append("Hill scope master drift report")
    lines.append("=" * 50)
    lines.append(f"Threshold: {threshold:.1f} RMSE points")
    lines.append("")
    lines.append(f"{'scope':<10}{'c_old':>10}{'c_new':>10}{'s_old':>10}{'s_new':>10}{'RMSE':>10}")
    for scope, (c_name, s_name) in SCOPE_TO_CS.items():
        c_old = committed[c_name]
        s_old = committed[s_name]
        c_new = fitted[c_name]
        s_new = fitted[s_name]
        rmse = drift[scope]
        marker = " ★" if rmse > threshold else ""
        lines.append(
            f"{scope:<10}{c_old:>10.4f}{c_new:>10.4f}"
            f"{s_old:>10.3f}{s_new:>10.3f}{rmse:>10.2f}{marker}"
        )
    lines.append("")
    max_scope = max(drift.items(), key=lambda kv: kv[1])
    lines.append(
        f"Max drift: {max_scope[0]} @ RMSE={max_scope[1]:.2f} "
        f"({'APPLY' if max_scope[1] > threshold else 'no-op'})"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--threshold",
        type=float,
        default=DRIFT_RMSE_THRESHOLD,
        help="RMSE drift threshold (default: %(default).1f pts).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Report drift but do not rewrite files.",
    )
    args = ap.parse_args()

    try:
        committed = read_committed_constants()
    except Exception as exc:
        print(f"ERROR reading committed constants: {exc}", file=sys.stderr)
        return 2

    try:
        fitted = run_fit_with_json()
    except subprocess.CalledProcessError as exc:
        print(f"ERROR running fit:\n{exc.stderr}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR running fit: {exc}", file=sys.stderr)
        return 2

    drift = compute_scope_drift(committed, fitted)
    report = format_drift_report(committed, fitted, drift, args.threshold)
    print(report)

    max_drift = max(drift.values())
    if max_drift <= args.threshold:
        print("\nNo drift beyond threshold — no changes made.")
        return 0

    if args.dry_run:
        print("\nDry-run mode — would apply constants but leaving files untouched.")
        return 1

    try:
        rewrite_player_valuation(fitted)
        rebaseline_ktc_reconciliation(fitted)
    except Exception as exc:
        print(f"ERROR applying drift: {exc}", file=sys.stderr)
        return 2

    print("\nApplied new constants to:")
    print(f"  {PLAYER_VALUATION.relative_to(REPO)}")
    print(f"  {KTC_RECONCILIATION_TEST.relative_to(REPO)}")
    print("Run the full test suite to confirm before committing.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
