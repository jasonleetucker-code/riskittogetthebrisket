"""B1 / W30-F008 — measure the fit-vs-serve percentile denominator gap.

READ-ONLY. Changes no constant, fits nothing, promotes nothing. It
reports the CURRENT inconsistency and pins the inputs that produced the
number, so a later challenger-vs-champion comparison can be attributed
to model code rather than to the scraper.

Why the pinning matters here specifically: `main` receives automated
source refreshes roughly every two hours, and those commits rewrite the
very CSVs the fit reads (`CSVs/site_raw/*.csv`). Between the Phase A
branch point and 2026-08-11 that was 5 commits touching 6 of the fit's
own inputs. A model measurement taken across that movement cannot
separate a code effect from a data effect.

The defect being measured
-------------------------
The fit maps a source's row ``i`` to a percentile using the length of
the list it was handed:

    _percentile_pairs(values)  ->  p = i / (len(values) - 1)

and the call sites truncate FIRST (`values[:400]`) — but not uniformly:
OFFENSE and GLOBAL truncate, the IDP slice does not, and that slice is
only ~370 rows anyway.

Serving maps rank to a percentile against a fixed reference pool:

    p = (rank - 1) / (_PERCENTILE_REFERENCE_N - 1)   # 499

Since V(p) = 9999 / (1 + (p/c)^s) decreases in p, and the serve
percentile is SMALLER than the fit percentile for the same ordinal,
every scope serves values ABOVE anything the fit was scored against —
and by a different amount per scope, which is the part that matters:
it is a non-uniform, scope-dependent stretch of the value ladder, not a
constant offset that would cancel out.

Usage:
    .venv/bin/python docs/master-site-audit/evidence/W30/b1_denominator_measure.py
    .venv/bin/python docs/master-site-audit/evidence/W30/b1_denominator_measure.py --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

REPRESENTATIVE_RANKS = (25, 50, 100, 200, 400)

# Every material input to the B1 fit/holdout comparison. Fit sources and
# holdout sources are listed separately because contamination between
# them is the thing the holdout exists to prevent.
FIT_SOURCE_FILES = (
    "CSVs/site_raw/ktc.csv",
    "CSVs/site_raw/dynastyDaddySf.csv",
    "CSVs/site_raw/dynastyNerdsSfTep.csv",
    "CSVs/site_raw/idpTradeCalc.csv",
    "CSVs/site_raw/draftSharksIdp.csv",
)
HOLDOUT_SOURCE_FILES = (
    "CSVs/site_raw/fantasyCalc.csv",
    "CSVs/site_raw/otcffbSf.csv",
    "CSVs/site_raw/pfkDynasty.csv",
    "CSVs/site_raw/fantasyNavigatorSf.csv",
)
MODEL_CODE_FILES = (
    "src/canonical/player_valuation.py",
    "src/model_registry/holdout.py",
    "scripts/fit_hill_curve_percentile.py",
    "src/api/data_contract.py",
)


def _sha256(path: Path) -> str:
    if not path.exists():
        return "ABSENT"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return "UNKNOWN"


def pin_inputs() -> dict:
    """A durable identity for everything the measurement depends on."""
    files = {}
    for rel in (*FIT_SOURCE_FILES, *HOLDOUT_SOURCE_FILES, *MODEL_CODE_FILES):
        p = ROOT / rel
        files[rel] = {
            "sha256_16": _sha256(p),
            "bytes": p.stat().st_size if p.exists() else 0,
            "gitBlob": _git("rev-parse", f"HEAD:{rel}")[:12],
        }
    return {
        "commit": _git("rev-parse", "HEAD")[:12],
        "commitISO": _git("log", "-1", "--format=%cI"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "treeDirty": bool(_git("status", "--porcelain")),
        "files": files,
    }


def hill(p: float, c: float, s: float) -> float:
    p = max(0.0, min(1.0, float(p)))
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def measure() -> dict:
    """Serve-vs-fit error per scope, on the champion constants."""
    from src.api.data_contract import _PERCENTILE_REFERENCE_N
    from src.canonical import player_valuation as pv

    serve_denominator = _PERCENTILE_REFERENCE_N - 1

    # Fit-side pool sizes, measured rather than assumed.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fitmod", ROOT / "scripts/fit_hill_curve_percentile.py"
    )
    fitmod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(fitmod)
    except SystemExit:
        pass

    fit_top_n = 400  # holdout.FIT_TOP_N, and the literal at the fit call sites
    try:
        idp_rows = len(fitmod._load_idptc_idp_values())
    except Exception as exc:  # noqa: BLE001
        idp_rows = 0
        print(f"warning: could not load the IDP slice: {exc}", file=sys.stderr)

    scopes = {
        "OFFENSE": {
            "c": pv.HILL_PERCENTILE_C,
            "s": pv.HILL_PERCENTILE_S,
            # Truncated at the call site: values[:400]
            "fitRows": fit_top_n,
            "truncated": True,
        },
        "GLOBAL": {
            "c": pv.HILL_GLOBAL_PERCENTILE_C,
            "s": pv.HILL_GLOBAL_PERCENTILE_S,
            "fitRows": fit_top_n,
            "truncated": True,
        },
        "IDP": {
            "c": pv.IDP_HILL_PERCENTILE_C,
            "s": pv.IDP_HILL_PERCENTILE_S,
            # NOT truncated — _percentile_pairs(idp_values) is called with
            # the whole slice, which is smaller than the 400 cap anyway.
            "fitRows": idp_rows,
            "truncated": False,
        },
    }

    out = {}
    for name, cfg in scopes.items():
        fit_denominator = max(1, int(cfg["fitRows"]) - 1)
        errors = {}
        for r in REPRESENTATIVE_RANKS:
            v_fit = hill((r - 1) / fit_denominator, cfg["c"], cfg["s"])
            v_serve = hill((r - 1) / serve_denominator, cfg["c"], cfg["s"])
            errors[f"rank{r}"] = round((v_serve / v_fit - 1) * 100, 1)
        out[name] = {
            "championC": round(float(cfg["c"]), 4),
            "championS": round(float(cfg["s"]), 3),
            "fitPoolRows": int(cfg["fitRows"]),
            "fitDenominator": fit_denominator,
            "servePoolRows": _PERCENTILE_REFERENCE_N,
            "serveDenominator": serve_denominator,
            "truncatedAtCallSite": cfg["truncated"],
            "servePercentileAsFractionOfFit": round(fit_denominator / serve_denominator, 4),
            "servedAbovefitPct": errors,
        }
    return {"servePoolRows": _PERCENTILE_REFERENCE_N, "scopes": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit the full record as JSON")
    args = ap.parse_args()

    # Holdout contamination check. The holdout exists to score a
    # candidate curve against boards the fit never read; an overlap
    # would make its verdict self-congratulatory.
    overlap = sorted(set(FIT_SOURCE_FILES) & set(HOLDOUT_SOURCE_FILES))
    record = {
        "pinnedInputs": pin_inputs(),
        "measurement": measure(),
        "holdoutContamination": {
            "fitSources": list(FIT_SOURCE_FILES),
            "holdoutSources": list(HOLDOUT_SOURCE_FILES),
            "overlap": overlap,
            "clean": not overlap,
        },
    }

    if args.json:
        print(json.dumps(record, indent=1))
        return

    pin = record["pinnedInputs"]
    print(f"PINNED INPUT SNAPSHOT  commit={pin['commit']}  dirty={pin['treeDirty']}")
    print(f"  {pin['commitISO']}  branch={pin['branch']}")
    print("\n  fit sources:")
    for rel in FIT_SOURCE_FILES:
        f = pin["files"][rel]
        print(f"    {rel:44s} sha256:{f['sha256_16']}  {f['bytes']:>9,}B")
    print("  holdout sources (must not overlap the fit set):")
    for rel in HOLDOUT_SOURCE_FILES:
        f = pin["files"][rel]
        print(f"    {rel:44s} sha256:{f['sha256_16']}  {f['bytes']:>9,}B")
    print("  model code:")
    for rel in MODEL_CODE_FILES:
        f = pin["files"][rel]
        print(f"    {rel:44s} sha256:{f['sha256_16']}")

    m = record["measurement"]
    print(f"\nSERVE POOL: {m['servePoolRows']} rows (denominator {m['servePoolRows'] - 1})\n")
    hdr = "  ".join(f"r={r:<4}" for r in REPRESENTATIVE_RANKS)
    print(f"{'scope':8} {'c':>7} {'s':>6} {'fitRows':>8} {'trunc':>6}   {hdr}")
    for name, sc in m["scopes"].items():
        errs = "  ".join(
            f"{sc['servedAbovefitPct'][f'rank{r}']:+6.1f}%" for r in REPRESENTATIVE_RANKS
        )
        print(
            f"{name:8} {sc['championC']:7.4f} {sc['championS']:6.3f} "
            f"{sc['fitPoolRows']:8d} {str(sc['truncatedAtCallSite']):>6}   {errs}"
        )
    print("\nPositive = served ABOVE anything the fit was scored against.")
    print("The per-scope spread is the defect: a constant offset would cancel.")

    hc = record["holdoutContamination"]
    verdict = (
        "CLEAN — no source is on both sides" if hc["clean"] else f"CONTAMINATED: {hc['overlap']}"
    )
    print(f"\nHoldout contamination: {verdict}")


if __name__ == "__main__":
    main()
