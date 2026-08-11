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
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

REPRESENTATIVE_RANKS = (25, 50, 100, 200, 400)


def _fitter():
    """The production fitter module, imported not copied.

    Everything material is DERIVED from its own declarations. An earlier
    version of this script kept a hand-written parallel list and it was
    wrong within a day: it named 3 of the 6 `OFFENSE_SOURCES`, omitting
    yahooBoone, fantasyProsFitzmaurice and draftSharksSf, and it missed
    the DraftSharks-combined pair GLOBAL trains on. A pin set that has to
    be maintained alongside the thing it pins is a pin set that silently
    stops covering it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fit_hill_curve_percentile_pin", ROOT / "scripts/fit_hill_curve_percentile.py"
    )
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def fit_source_files(fitter) -> tuple[str, ...]:
    """Every CSV the OFFENSE / GLOBAL / IDP fits actually read.

    Derived from the fitter's own source dicts plus the DraftSharks
    combined pair, which GLOBAL builds by concatenating the SF and IDP
    slices (`_load_draftsharks_combined_values`) and which therefore
    appears in no source dict at all.
    """
    paths: list[str] = []
    for table in (fitter.OFFENSE_SOURCES, fitter.GLOBAL_SOURCES, fitter.IDP_CSV_SOURCES):
        paths.extend(rel for rel, _col in table.values())
    # GLOBAL's DraftSharks-Combined entry, declared only in code.
    paths.extend(("CSVs/site_raw/draftSharksSf.csv", "CSVs/site_raw/draftSharksIdp.csv"))
    return tuple(sorted(set(paths)))


def holdout_source_files() -> tuple[str, ...]:
    """The holdout set, derived from the registry's own declaration."""
    from src.model_registry.holdout import OFFENSE_HOLDOUT_SOURCES

    return tuple(sorted({rel for rel, _col in OFFENSE_HOLDOUT_SOURCES.values()}))


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


def pin_snapshot(fitter) -> dict:
    """Resolve, identify and hash the board snapshot the fit trains on.

    This is the input the first version of this script missed entirely,
    and it is the one most able to move underneath a comparison:
    `_latest_snapshot()` picks by **mtime** across `data/` then
    `exports/latest/`, so a container that writes a board between two
    runs changes the IDP training data without changing one line of code.

    It is unambiguously material — it supplies the position filter AND
    the per-player IDPTradeCalc values behind the entire IDP scope (and
    the rookie slices behind ROOKIE).
    """
    path = fitter._latest_snapshot()
    if path is None:
        return {
            "resolved": False,
            "reason": "no dynasty_data_*.json found in data/ or exports/latest/",
        }

    try:
        rel = str(path.resolve().relative_to(ROOT))
        tracked_blob = _git("rev-parse", f"HEAD:{rel}")
        tracked = not tracked_blob.startswith("UNKNOWN") and len(tracked_blob) == 40
    except ValueError:  # outside the repo (an explicit pin may be)
        rel = str(path)
        tracked_blob, tracked = "OUTSIDE-REPO", False

    if rel.startswith("data/"):
        origin = "data/ (runtime-written; NOT the committed copy)"
    elif rel.startswith("exports/latest/"):
        origin = "exports/latest/ (committed)"
    else:
        origin = "explicit pin outside the standard search path"

    return {
        "resolved": True,
        "path": rel,
        "origin": origin,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "gitBlob": tracked_blob[:12] if tracked else None,
        "tracked": tracked,
        "pinnedByEnv": bool(os.getenv(fitter.SNAPSHOT_ENV_VAR, "").strip()),
        "pinEnvVar": fitter.SNAPSHOT_ENV_VAR,
    }


def fit_top_n_parity() -> dict:
    """The canonical FIT_TOP_N vs the literals the fitter truncates with.

    `holdout.FIT_TOP_N` is the declared constant, but the fit script
    truncates with bare `values[:400]` literals at its call sites. If
    those ever diverge, the holdout would score a curve trained on a
    different pool than it believes — so this asserts rather than
    assumes, instead of the measurement hardcoding 400 itself.
    """
    from src.model_registry.holdout import FIT_TOP_N

    src = (ROOT / "scripts/fit_hill_curve_percentile.py").read_text()
    literals = sorted({int(n) for n in re.findall(r"\[:(\d+)\]", src)})
    return {
        "canonicalFitTopN": int(FIT_TOP_N),
        "fitterTruncationLiterals": literals,
        "inParity": all(n == int(FIT_TOP_N) for n in literals) and bool(literals),
    }


def pin_inputs(fitter) -> dict:
    """A durable identity for everything the measurement depends on."""
    fit_files = fit_source_files(fitter)
    holdout_files = holdout_source_files()
    files = {}
    for rel in (*fit_files, *holdout_files, *MODEL_CODE_FILES):
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
        "fitSourceFiles": list(fit_files),
        "holdoutSourceFiles": list(holdout_files),
        "snapshot": pin_snapshot(fitter),
        "fitTopNParity": fit_top_n_parity(),
        "files": files,
    }


def hill(p: float, c: float, s: float) -> float:
    p = max(0.0, min(1.0, float(p)))
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def measure(fitmod) -> dict:
    """Serve-vs-fit error per scope, on the champion constants."""
    from src.api.data_contract import _PERCENTILE_REFERENCE_N
    from src.canonical import player_valuation as pv
    from src.model_registry.holdout import FIT_TOP_N

    serve_denominator = _PERCENTILE_REFERENCE_N - 1

    # Canonical, never a local literal — see fit_top_n_parity().
    fit_top_n = int(FIT_TOP_N)
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
    fitter = _fitter()
    fit_files, holdout_files = fit_source_files(fitter), holdout_source_files()
    overlap = sorted(set(fit_files) & set(holdout_files))
    record = {
        "pinnedInputs": pin_inputs(fitter),
        "measurement": measure(fitter),
        "holdoutContamination": {
            "fitSources": list(fit_files),
            "holdoutSources": list(holdout_files),
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
    for rel in pin["fitSourceFiles"]:
        f = pin["files"][rel]
        print(f"    {rel:44s} sha256:{f['sha256_16']}  {f['bytes']:>9,}B")
    print("  holdout sources (must not overlap the fit set):")
    for rel in pin["holdoutSourceFiles"]:
        f = pin["files"][rel]
        print(f"    {rel:44s} sha256:{f['sha256_16']}  {f['bytes']:>9,}B")
    snap = pin["snapshot"]
    print("  board snapshot (position filter + IDPTC values for the IDP scope):")
    if not snap.get("resolved"):
        print(f"    UNRESOLVED — {snap.get('reason')}")
    else:
        print(f"    {snap['path']}")
        print(f"      origin   : {snap['origin']}")
        print(f"      sha256   : {snap['sha256'][:32]}...")
        print(f"      gitBlob  : {snap['gitBlob'] or 'UNTRACKED'}   bytes: {snap['bytes']:,}")
        pinned = "YES" if snap["pinnedByEnv"] else f"no (set ${snap['pinEnvVar']} to force)"
        print(f"      pinned   : {pinned}")
    par = pin["fitTopNParity"]
    flag = "OK" if par["inParity"] else "DIVERGED"
    print(
        f"  FIT_TOP_N parity: canonical={par['canonicalFitTopN']} "
        f"fitter literals={par['fitterTruncationLiterals']} -> {flag}"
    )
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
