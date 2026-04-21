#!/usr/bin/env python3
"""Fit scope-level master Hill curves per the updated Final Framework.

Framework update (2026-04-20): value-based sources are the training
set for the rank-to-value conversion system.  Methodology:

  Step 1: For each value-based source j, fit its own implied
          rank-to-value curve f_j(p) where p = (r - 1) / (N_j - 1).
  Step 2: For each scope (global, offense, IDP), combine the per-
          source fits into a master curve V*_scope(p) by trimmed
          mean-median across the percentile grid.
  Step 3: Emit the master (c*, s*) for each scope.

Scope assignments (current registry, expanded 2026-04-21):

  - GLOBAL:   IDPTradeCalc + DraftSharks-Combined
              (both publish offense + IDP on a single cross-universe
              value scale — IDPTC natively; DS via the offense-combined
              page that serves every position from one shared ``3D
              Value +`` scale.  DS is concat-loaded from its SF + IDP
              CSVs so the concatenated pool's top value anchors 9999.)
  - OFFENSE:  KTC, DynastyDaddy, DynastyNerds, YahooBoone,
              FantasyPros-Fitzmaurice, DraftSharks-SF
              (offense-only value distributions; Boone/Fitzmaurice are
              SF-TEP-native, DraftSharks-SF is the league-synced slice
              from the combined board).
  - IDP:      IDPTradeCalc's IDP slice + DraftSharks-IDP
              (IDPTC IDP slice via snapshot position filter; DS IDP
              directly from its IDP-filtered CSV).
  - ROOKIE:   KTC + IDPTC rookie slices (unchanged — rookies-only
              slicing is value-source-agnostic, but we add Boone /
              Fitzmaurice / DraftSharks rookie slices too when they
              have ≥10 rookies with values in the latest snapshot).

Replaces the previous "pooled fit" which weighted sources by their
data-point count.  Per-source-then-combine gives each source equal
voice, matching the framework's intent.

Usage:
    python3 scripts/fit_hill_curve_percentile.py
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Value-based sources grouped by scope.  Each entry: (csv_path,
# value_col, label).  The IDPTC IDP scope contribution is still
# handled specially via _load_idptc_idp_values() because the IDPTC
# CSV mixes positions and needs a snapshot-backed position filter;
# DS IDP has its own pre-filtered CSV so it just rides _load_values.
GLOBAL_SOURCES: dict[str, tuple[str, str]] = {
    "IDPTradeCalc": ("CSVs/site_raw/idpTradeCalc.csv", "value"),
}
OFFENSE_SOURCES: dict[str, tuple[str, str]] = {
    "KTC":          ("CSVs/site_raw/ktc.csv",                    "value"),
    "DynastyDaddy": ("CSVs/site_raw/dynastyDaddySf.csv",         "value"),
    "DynastyNerds": ("CSVs/site_raw/dynastyNerdsSfTep.csv",      "Value"),
    # Added 2026-04-21: three more value-based offense sources that
    # went live in the April source expansion.  Each is SF-TEP-native
    # (Boone pulls 2QB + TE-Prem columns; Fitzmaurice uses SF Value +
    # TEP Value; DraftSharks is league-synced via its WebAssembly
    # scoring worker).  Tops are ~141 (Boone), ~101 (Fitzmaurice),
    # ~100 (DS SF) — all normalize to 9999 at the curve's anchor.
    "YahooBoone":   ("CSVs/site_raw/yahooBoone.csv",             "boone_value"),
    "Fitzmaurice":  ("CSVs/site_raw/fantasyProsFitzmaurice.csv", "value"),
    "DraftSharks":  ("CSVs/site_raw/draftSharksSf.csv",          "3D Value +"),
}
# IDP value sources that have pre-filtered per-position CSVs.  IDPTC
# is NOT in this dict because its CSV is all positions mixed —
# _load_idptc_idp_values() handles IDPTC's IDP slice via a snapshot
# position filter instead.
IDP_CSV_SOURCES: dict[str, tuple[str, str]] = {
    # DraftSharks IDP slice: every value is on DS's cross-universe
    # scale (Schwesinger at 44 reflects his cross-universe rank ~36,
    # not an IDP-only rescale).  Training against the IDP slice
    # normalizes the slice top to 9999 — same pattern as IDPTC-IDP.
    "DraftSharks-IDP": ("CSVs/site_raw/draftSharksIdp.csv", "3D Value +"),
}

_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB",
     "DB", "CB", "S", "SS", "FS"}
)


def _load_values(path: Path, col: str) -> list[float]:
    vs: list[float] = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            raw = r.get(col)
            try:
                v = float(raw) if raw else 0.0
            except (TypeError, ValueError):
                continue
            if v > 0:
                vs.append(v)
    vs.sort(reverse=True)
    return vs


def _latest_snapshot() -> "Path | None":
    """Return the newest ``dynasty_data_*.json`` snapshot path, or None.

    Prefers ``data/`` (dev machine) but falls back to
    ``exports/latest/`` (which is checked into the repo, so CI runs can
    still fit IDP / rookie scopes off the most recent committed board).
    """
    for sub in ("data", "exports/latest"):
        candidates = sorted(
            (REPO / sub).glob("dynasty_data_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def _load_idptc_idp_values() -> list[float]:
    """IDPTC's IDP-slice values in descending order."""
    import json

    snapshot = _latest_snapshot()
    if snapshot is None:
        return []
    candidates = [snapshot]
    with candidates[0].open() as f:
        raw = json.load(f)
    positions = (raw.get("sleeper") or {}).get("positions") or {}
    vs: list[float] = []
    for name, p in (raw.get("players") or {}).items():
        pos = str(positions.get(name, "")).strip().upper()
        if pos not in _IDP_POSITIONS:
            continue
        v = (p or {}).get("idpTradeCalc")
        try:
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            continue
        if vf > 0:
            vs.append(vf)
    vs.sort(reverse=True)
    return vs


def _load_draftsharks_combined_values() -> list[float]:
    """DraftSharks offense + IDP combined pool, descending.

    DraftSharks publishes every player on a single cross-universe
    ``3D Value +`` scale (Josh Allen at 100 and Schwesinger at 44 are
    comparable on the same 0-100 range).  The scraper writes the
    offense and IDP slices into separate CSVs for downstream scope
    filtering, but for GLOBAL training we recover the original pool
    by concatenating both files before normalizing — preserving DS's
    native cross-universe top anchor (Allen at 100) so the resulting
    Hill curve matches IDPTC's combined-pool semantics.
    """
    sf = _load_values(REPO / "CSVs" / "site_raw" / "draftSharksSf.csv", "3D Value +")
    idp = _load_values(REPO / "CSVs" / "site_raw" / "draftSharksIdp.csv", "3D Value +")
    combined = sf + idp
    combined.sort(reverse=True)
    return combined


def _load_rookie_values(source_key: str) -> list[float]:
    """Rookie-only values for the given value-based source.

    Filters the latest snapshot to rookies and pulls the source's
    value from each rookie's ``_canonicalSiteValues`` dict.  Returns
    descending-sorted values.  Used to build the ROOKIE scope master
    curve.
    """
    import json

    snapshot = _latest_snapshot()
    if snapshot is None:
        return []
    candidates = [snapshot]
    with candidates[0].open() as f:
        raw = json.load(f)
    vs: list[float] = []
    for _name, p in (raw.get("players") or {}).items():
        if not (p.get("_isRookie") or p.get("_formatFitRookie")):
            continue
        site_values = (p or {}).get("_canonicalSiteValues") or {}
        v = site_values.get(source_key)
        try:
            vf = float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            continue
        if vf > 0:
            vs.append(vf)
    vs.sort(reverse=True)
    return vs


def _percentile_pairs(values: list[float]) -> list[tuple[float, float]]:
    """Return [(p, normalized_v)] where normalized_v has top = 9999."""
    if len(values) < 2:
        return []
    top = values[0]
    n = len(values)
    return [((i) / (n - 1), values[i] / top * 9999.0) for i in range(n)]


def _hill(p: float, c: float, s: float) -> float:
    p = max(0.0, min(1.0, float(p)))
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def _fit(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Grid-search + refine (c, s) against the pairs."""
    best: tuple[float, float, float] | None = None
    c_grid = [0.005 + 0.005 * i for i in range(100)]  # 0.005..0.5
    s_grid = [0.4 + 0.02 * i for i in range(106)]     # 0.4..2.5
    for c in c_grid:
        for s in s_grid:
            err = sum((v - _hill(p, c, s)) ** 2 for p, v in pairs)
            if best is None or err < best[0]:
                best = (err, c, s)
    assert best is not None
    err0, c0, s0 = best
    for dc in (-0.002, -0.001, 0.0, 0.001, 0.002):
        for ds in (-0.01, -0.005, 0.0, 0.005, 0.01):
            c = c0 + dc
            s = s0 + ds
            if c <= 0 or s <= 0:
                continue
            err = sum((v - _hill(p, c, s)) ** 2 for p, v in pairs)
            if err < best[0]:
                best = (err, c, s)
    return best[1], best[2], best[0] / len(pairs)


def _trimmed_mean_median(values: list[float]) -> float:
    """Framework's step 9 blend: drop max+min, mean of (trimmed_mean,
    trimmed_median).  For n=2 returns mean; for n=1 returns passthrough.
    """
    if not values:
        return 0.0
    vs = sorted(values)
    n = len(vs)
    if n >= 3:
        t = vs[1:-1]
        t_mean = sum(t) / len(t)
        m = len(t)
        t_median = (
            float(t[m // 2])
            if m % 2 == 1
            else (t[m // 2 - 1] + t[m // 2]) / 2.0
        )
        return (t_mean + t_median) / 2.0
    if n == 2:
        return (vs[0] + vs[1]) / 2.0
    return vs[0]


def _fit_scope_master(
    scope_label: str,
    per_source_fits: list[tuple[str, float, float]],  # (label, c, s)
) -> tuple[float, float, float] | None:
    """Build a scope master curve from per-source fits.

    Framework step 5 combines per-source fitted curves into a
    "weighted market target" — the framework does not prescribe a
    specific aggregation rule for this step (the trimmed mean-median
    is for step 9, the subgroup combining).  We use the unweighted
    mean of per-source V_j(p) values at each percentile p.

    The mean (rather than trimmed mean-median) is the right rule
    here because:
      - With n=3 sources, trimmed mean-median degenerates to the
        middle source — it's not a blend, it's a single-source pick.
      - The mean treats every source equally, matching the framework's
        "weighted market target" intent.
      - Outlier curves can't skew the master very far because the
        Hill family is constrained.

    Rule:
      1. Generate a fine percentile grid.
      2. For each percentile, compute V_j(p) for every source in scope.
      3. V*(p) = mean(V_j(p)).
      4. Fit a single Hill against the (p, V*(p)) curve.
      5. Emit master (c*, s*).
    """
    if not per_source_fits:
        return None
    grid: list[float] = []
    for i in range(1, 50):
        grid.append(i / 2000.0)  # fine top-of-curve sampling
    for i in range(1, 200):
        grid.append(i / 200.0)   # linear mid-to-tail sampling
    grid = sorted(set(round(p, 6) for p in grid))

    master_pairs: list[tuple[float, float]] = []
    for p in grid:
        vals = [_hill(p, c, s) for _, c, s in per_source_fits]
        master_pairs.append((p, sum(vals) / len(vals)))

    c, s, mse = _fit(master_pairs)
    return c, s, mse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--print-old-style",
        action="store_true",
        help="Also print the legacy pooled fit for comparison",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help=(
            "Also write fitted constants to this path as a JSON dict "
            "keyed by HILL_*_C/S name.  Consumed by "
            "scripts/auto_refit_hill_curves.py."
        ),
    )
    args = parser.parse_args()

    def _fit_sources(
        sources: dict[str, tuple[str, str]],
        label_prefix: str = "",
    ) -> list[tuple[str, float, float]]:
        out: list[tuple[str, float, float]] = []
        for label, (rel_path, col) in sources.items():
            values = _load_values(REPO / rel_path, col)
            if not values:
                print(f"  {label_prefix}{label}: no values found")
                continue
            pairs = _percentile_pairs(values[:400])
            c, s, mse = _fit(pairs)
            out.append((label, c, s))
            print(
                f"  {label_prefix}{label:18s}  n={len(pairs):4d}  "
                f"c={c:.4f}  s={s:.3f}  rmse={mse ** 0.5:.1f}"
            )
        return out

    print("Per-source Hill fits:\n")
    print("OFFENSE scope (offense-only value sources):")
    offense_fits = _fit_sources(OFFENSE_SOURCES, "")

    print("\nGLOBAL scope (combined offense + IDP value sources):")
    global_fits = _fit_sources(GLOBAL_SOURCES, "")
    # Add DraftSharks as a combined-pool entry alongside IDPTC.  DS
    # natively cross-universe → concatenate SF + IDP CSVs, sort
    # descending, percentile-fit.  Labeled DraftSharks-Combined for
    # parity with the IDPTradeCalc entry shown above.
    ds_combined = _load_draftsharks_combined_values()
    if len(ds_combined) >= 20:
        pairs = _percentile_pairs(ds_combined[:400])
        c, s, mse = _fit(pairs)
        global_fits.append(("DraftSharks-Combined", c, s))
        print(
            f"  DraftSharks-Combined  n={len(pairs):4d}  "
            f"c={c:.4f}  s={s:.3f}  rmse={mse ** 0.5:.1f}"
        )
    else:
        print(
            f"  DraftSharks-Combined  (only {len(ds_combined)} total "
            f"values; skipping)"
        )

    print("\nIDP scope (IDP value sources):")
    idp_values = _load_idptc_idp_values()
    idp_fits: list[tuple[str, float, float]] = []
    if idp_values:
        pairs = _percentile_pairs(idp_values)
        c, s, mse = _fit(pairs)
        idp_fits.append(("IDPTradeCalc-IDP", c, s))
        print(
            f"  IDPTradeCalc-IDP    n={len(pairs):4d}  c={c:.4f}  "
            f"s={s:.3f}  rmse={mse ** 0.5:.1f}"
        )
    else:
        print("  IDPTradeCalc-IDP    (no snapshot available)")
    # Any additional IDP value sources whose CSVs are pre-filtered
    # to IDP positions (e.g. DraftSharks-IDP) are fit alongside the
    # IDPTC IDP slice; _fit_scope_master averages them into the IDP
    # master curve.
    idp_fits.extend(_fit_sources(IDP_CSV_SOURCES, "  "))

    print("\nROOKIE scope (rookie slices of value-based sources):")
    rookie_fits: list[tuple[str, float, float]] = []
    for label, src_key in (
        ("KTC-Rookie",          "ktc"),
        ("IDPTC-Rookie",        "idpTradeCalc"),
        # Added 2026-04-21: rookie slices from the newly-wired
        # value sources.  Each rookie slice is normalized so the
        # slice's top contributes 9999, same as KTC / IDPTC.
        # Small rookie classes with <10 rookies in a snapshot are
        # auto-skipped so a sparse source doesn't wreck the master.
        ("Boone-Rookie",        "yahooBoone"),
        ("Fitzmaurice-Rookie",  "fantasyProsFitzmaurice"),
        ("DraftSharks-Rookie",  "draftSharks"),
    ):
        rv = _load_rookie_values(src_key)
        if len(rv) < 10:
            print(
                f"  {label:22s}  (only {len(rv)} rookies with values; skipping)"
            )
            continue
        pairs = _percentile_pairs(rv)
        c, s, mse = _fit(pairs)
        rookie_fits.append((label, c, s))
        print(
            f"  {label:22s}  n={len(pairs):4d}  c={c:.4f}  "
            f"s={s:.3f}  rmse={mse ** 0.5:.1f}"
        )

    print("\nScope-level master curves (trimmed mean-median across per-source fits):")
    for scope_label, fits in (
        ("GLOBAL", global_fits),
        ("OFFENSE", offense_fits),
        ("IDP", idp_fits),
        ("ROOKIE", rookie_fits),
    ):
        result = _fit_scope_master(scope_label, fits)
        if result is None:
            print(f"  {scope_label:8s}  (no per-source fits)")
            continue
        c, s, mse = result
        print(
            f"  {scope_label:8s}  c*={c:.4f}  s*={s:.3f}  "
            f"master-fit rmse={mse ** 0.5:.1f}"
        )

    print()
    print("Value at key percentiles for each scope master:")
    ps = (0.0, 0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
    print("  " + "scope".ljust(8) + "".join(f"{p:>9.3f}" for p in ps))
    for scope_label, fits in (
        ("GLOBAL", global_fits),
        ("OFFENSE", offense_fits),
        ("IDP", idp_fits),
        ("ROOKIE", rookie_fits),
    ):
        result = _fit_scope_master(scope_label, fits)
        if result is None:
            continue
        c, s, _ = result
        row = "".join(f"{int(_hill(p, c, s)):>9}" for p in ps)
        print(f"  {scope_label:<8}" + row)

    print()
    print("Suggested constants (src/canonical/player_valuation.py):")
    out_constants: dict[str, float] = {}
    for scope_label, fits in (
        ("GLOBAL", global_fits),
        ("OFFENSE", offense_fits),
        ("IDP", idp_fits),
        ("ROOKIE", rookie_fits),
    ):
        result = _fit_scope_master(scope_label, fits)
        if result is None:
            continue
        c, s, _ = result
        if scope_label == "OFFENSE":
            c_name, s_name = "HILL_PERCENTILE_C", "HILL_PERCENTILE_S"
        elif scope_label == "IDP":
            c_name, s_name = "IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"
        elif scope_label == "ROOKIE":
            c_name, s_name = "HILL_ROOKIE_PERCENTILE_C", "HILL_ROOKIE_PERCENTILE_S"
        else:
            c_name, s_name = "HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"
        print(f"{c_name}: float = {c:.4f}")
        print(f"{s_name}: float = {s:.3f}")
        out_constants[c_name] = round(c, 4)
        out_constants[s_name] = round(s, 3)

    if args.json_out is not None:
        import json as _json
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(_json.dumps(out_constants, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
