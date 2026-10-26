#!/usr/bin/env python3
"""Fit scope-level master Hill curves per the updated Final Framework.

Framework update (2026-04-20): value-based sources are the training
set for the rank-to-value conversion system.  Methodology:

  Step 1: For each value-based source j, fit its own implied
          rank-to-value curve f_j(p) on the canonical percentile coordinate.
  Step 2: For each scope (global, offense, IDP, rookie), combine the per-
          source fits into a master curve V*_scope(p) by the unweighted mean
          across the percentile grid.
  Step 3: Emit the master (c*, s*) for each scope.

Which boards train which scope is NOT declared here (Batch 3 Unit D,
2026-10-01). It is read from the one training manifest,
``src/model_registry/training_manifest.py``, whose paths, signal types and
provider families are derived from the live source registry. Every population
it hands this fit is PLAYERS ONLY — KTC's base board used to train OFFENSE with
36 pick rows inside its top 400 (audit error E3).

``fit_scopes(root=…, snapshot=…)`` is the pure entry point: it reads only files
under ``root`` (the repo by default; a git-materialized tree for a pinned,
point-in-time refit — ``src/model_registry/training_run.py``) and returns the
per-source fits, the scope masters and the eight constants. ``main()`` prints the
human report around it.

Usage:
    python3 scripts/fit_hill_curve_percentile.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.player_valuation import (  # noqa: E402
    PERCENTILE_REFERENCE_N,
    training_percentiles,
)
from src.canonical.tail_policy import clamp_percentile  # noqa: E402
from src.model_registry.training_manifest import (  # noqa: E402
    LOADER_CSV,
    LOADER_CSV_CONCAT,
    LOADER_SNAPSHOT_IDP,
    LOADER_SNAPSHOT_ROOKIE,
    ROLE_TRAIN,
    MissingColumnError,
    TrainingManifest,
    default_manifest,
    load_board_values,
)

# Derived views of the manifest, kept under their historical names because the
# B1 pin instrument, the registry provenance and the DLF gate read them.
_MANIFEST = default_manifest()
GLOBAL_SOURCES: dict[str, tuple[str, str]] = _MANIFEST.csv_table("GLOBAL", ROLE_TRAIN)
OFFENSE_SOURCES: dict[str, tuple[str, str]] = _MANIFEST.csv_table("OFFENSE", ROLE_TRAIN)
IDP_CSV_SOURCES: dict[str, tuple[str, str]] = _MANIFEST.csv_table("IDP", ROLE_TRAIN)

_IDP_POSITIONS: frozenset[str] = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "ILB", "OLB", "MLB", "DB", "CB", "S", "SS", "FS"}
)

SCOPE_CONSTANT_NAMES: dict[str, tuple[str, str]] = {
    "GLOBAL": ("HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"),
    "OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S"),
    "IDP": ("IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"),
    "ROOKIE": ("HILL_ROOKIE_PERCENTILE_C", "HILL_ROOKIE_PERCENTILE_S"),
}

#: Minimum rows before a concatenated or snapshot slice is fitted at all.
MIN_COMBINED_ROWS = 20
MIN_ROOKIE_ROWS = 10


def _load_values(path: Path, col: str) -> list[float]:
    """Players-only positive values, descending — the manifest's population rule."""
    return list(load_board_values(path, col).values)


#: Env var that pins the board snapshot this fit trains against.
#: Set it to an absolute path to force a specific file instead of
#: whichever one happens to be newest on disk.
SNAPSHOT_ENV_VAR = "RISKIT_FIT_SNAPSHOT"


def _latest_snapshot(root: Path | None = None) -> "Path | None":
    """Return the ``dynasty_data_*.json`` snapshot this fit trains on.

    The snapshot is a MATERIAL model input, not a convenience: it
    supplies the position filter AND the IDPTradeCalc per-player values
    behind the IDP scope, and the rookie slices behind ROOKIE. Two runs
    that select different snapshots are not comparable, however identical
    the code.

    Selection order:

    1. ``$RISKIT_FIT_SNAPSHOT`` if set — an explicit pin.
    2. newest ``data/`` snapshot under ``root`` (dev machine),
    3. newest ``exports/latest/`` snapshot under ``root`` (checked in, so CI
       can fit IDP / rookie scopes off the most recent committed board).

    "Newest" is by the DATE IN THE FILENAME, not by mtime: a fresh checkout
    gives every file the same mtime, so mtime order was arbitrary in CI and
    a refit could not be reproduced from its own record.

    A pin that does not exist is fatal rather than a silent fallback —
    quietly training on a different snapshot than the operator named is
    the failure this pin exists to prevent.
    """
    override = os.getenv(SNAPSHOT_ENV_VAR, "").strip()
    if override:
        pinned = Path(override).expanduser()
        if not pinned.is_file():
            raise SystemExit(
                f"{SNAPSHOT_ENV_VAR} points at a file that does not exist: {pinned}\n"
                "Refusing to fall back to whichever snapshot is newest — that would "
                "train on different data than the pin names."
            )
        return pinned
    base = root or REPO
    for sub in ("data", "exports/latest"):
        candidates = sorted((base / sub).glob("dynasty_data_*.json"), key=lambda p: p.name)
        if candidates:
            return candidates[-1]
    return None


def _read_snapshot(snapshot: Path | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    with snapshot.open(encoding="utf-8") as f:
        return json.load(f)


def _load_idptc_idp_values(snapshot: Path | None = None) -> list[float]:
    """IDPTC's IDP-slice values in descending order (players only by construction)."""
    raw = _read_snapshot(snapshot if snapshot is not None else _latest_snapshot())
    if raw is None:
        return []
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


def _load_draftsharks_combined_values(root: Path | None = None) -> list[float]:
    """DraftSharks offense + IDP combined pool, descending.

    DraftSharks publishes every player on a single cross-universe
    ``3D Value +`` scale. The scraper writes the offense and IDP slices into
    separate CSVs; for GLOBAL training the original pool is recovered by
    concatenating both (the manifest's ``DraftSharks-Combined`` board names
    them) before normalizing.
    """
    board = _MANIFEST.board("GLOBAL", "DraftSharks-Combined")
    base = root or REPO
    combined: list[float] = []
    for rel in board.paths:
        combined.extend(_load_values(base / rel, str(board.value_column)))
    combined.sort(reverse=True)
    return combined


def _load_rookie_values(source_key: str, snapshot: Path | None = None) -> list[float]:
    """Rookie-only values for the given value-signal source, descending.

    Reads ``_canonicalSiteValues[source_key]`` of rookie rows. The manifest
    refuses this slice for a RANK-signal source, whose entry there is a
    synthetic rank encoding rather than a value.
    """
    raw = _read_snapshot(snapshot if snapshot is not None else _latest_snapshot())
    if raw is None:
        return []
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
    """Return [(p, normalized_v)] where normalized_v has top = 9999.

    Percentiles come from the canonical coordinate owner, NOT from
    ``len(values)``. Dividing by the caller's list length is what made a
    training row's coordinate depend on how many rows survived
    truncation — /399 here, /369 for the shorter IDP slice, against /499
    at serve time (audit finding W30-F008).

    Truncation still selects which observations train the curve; it just
    no longer redefines the universe they are measured against.
    """
    if len(values) < 2:
        return []
    top = values[0]
    ps = training_percentiles(len(values))
    return [(ps[i], values[i] / top * 9999.0) for i in range(len(values))]


def _hill(p: float, c: float, s: float) -> float:
    # Tail bound from the canonical owner, not a local ``min(1.0, p)``.
    # A fit that capped its own training coordinates would re-learn the
    # saturated shape on every refit and hand production a curve shaped
    # by a tail policy production had already stopped using (W30-F023).
    p = clamp_percentile(p, reference_n=PERCENTILE_REFERENCE_N)
    if p == 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def _fit(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Grid-search + refine (c, s) against the pairs."""
    best: tuple[float, float, float] | None = None
    c_grid = [0.005 + 0.005 * i for i in range(100)]  # 0.005..0.5
    s_grid = [0.4 + 0.02 * i for i in range(106)]  # 0.4..2.5
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
        t_median = float(t[m // 2]) if m % 2 == 1 else (t[m // 2 - 1] + t[m // 2]) / 2.0
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
        grid.append(i / 200.0)  # linear mid-to-tail sampling
    grid = sorted(set(round(p, 6) for p in grid))

    master_pairs: list[tuple[float, float]] = []
    for p in grid:
        vals = [_hill(p, c, s) for _, c, s in per_source_fits]
        master_pairs.append((p, sum(vals) / len(vals)))

    c, s, mse = _fit(master_pairs)
    return c, s, mse


_SCOPE_REPORT_ORDER: tuple[str, ...] = ("OFFENSE", "GLOBAL", "IDP", "ROOKIE")


def _trainer_values(board, root: Path, snapshot: Path | None) -> tuple[list[float], str | None]:
    """The values one manifest trainer contributes, or ``([], reason)`` to skip it.

    A missing trainer CSV is an error, never a skip: a master silently fitted on
    five of six declared boards is a different model wearing the same name.

    A declared value column that is ABSENT from its file (a vendor rename) is a
    skip with reason ``missing_column:<col>`` — never a board of zeros. The
    training run records every skipped declared trainer, and a scope with one is
    NOT promotable (``training_run.tournament_exclusion_reason``), so the master on
    fewer boards still exists as evidence but cannot win a tournament.
    """
    try:
        return _trainer_values_unchecked(board, root, snapshot)
    except MissingColumnError as exc:
        return [], f"missing_column:{exc.column}"


def _trainer_values_unchecked(
    board, root: Path, snapshot: Path | None
) -> tuple[list[float], str | None]:
    if board.loader == LOADER_CSV:
        path = root / board.paths[0]
        if not path.is_file():
            raise FileNotFoundError(f"trainer {board.scope}:{board.label} CSV missing: {path}")
        values = _load_values(path, str(board.value_column))[:400]
        return (values, None) if values else ([], "no values found")
    if board.loader == LOADER_CSV_CONCAT:
        for rel in board.paths:
            if not (root / rel).is_file():
                raise FileNotFoundError(f"trainer {board.scope}:{board.label} CSV missing: {rel}")
        values = _load_draftsharks_combined_values(root)
        if len(values) < MIN_COMBINED_ROWS:
            return [], f"only {len(values)} total values"
        return values[:400], None
    if snapshot is None:
        return [], "no snapshot available"
    if board.loader == LOADER_SNAPSHOT_IDP:
        values = _load_idptc_idp_values(snapshot)
        return (values, None) if values else ([], "no IDP values in snapshot")
    if board.loader == LOADER_SNAPSHOT_ROOKIE:
        values = _load_rookie_values(board.source_key, snapshot)
        if len(values) < MIN_ROOKIE_ROWS:
            return [], f"only {len(values)} rookies with values"
        return values, None
    raise ValueError(f"unknown loader {board.loader!r}")


def fit_scopes(
    *,
    root: Path | None = None,
    snapshot: Path | None = None,
    manifest: TrainingManifest | None = None,
    log: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fit every scope master from the manifest's trainers under ``root``.

    Pure over its inputs: the same files, snapshot and manifest give the same
    result byte for byte (``training_run`` hashes it).
    """
    m = manifest or _MANIFEST
    base = root or REPO
    snap = snapshot if snapshot is not None else _latest_snapshot(base)
    say = log or (lambda _msg: None)

    per_source: dict[str, list[dict[str, Any]]] = {}
    skipped: dict[str, dict[str, str]] = {}
    masters: dict[str, dict[str, float]] = {}
    constants: dict[str, float] = {}
    # Content hash of exactly the values each trainer fed the fit. Two refits
    # whose trainers saw identical values are the SAME evidence, whatever their
    # cutoff, snapshot scrape time or holdout files (training_run.evidence_hash).
    content: dict[str, dict[str, str]] = {}
    for scope in _SCOPE_REPORT_ORDER:
        fits: list[dict[str, Any]] = []
        skipped[scope] = {}
        content[scope] = {}
        say(f"\n{scope} scope:")
        for board in m.trainers(scope):
            values, reason = _trainer_values(board, base, snap)
            pairs = _percentile_pairs(values) if values else []
            if reason or not pairs:
                skipped[scope][board.label] = reason or "no usable percentile pairs"
                say(f"  {board.label:22s}  (skipped: {skipped[scope][board.label]})")
                continue
            content[scope][board.label] = hashlib.sha256(
                json.dumps(values, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            c, s, mse = _fit(pairs)
            fits.append({"label": board.label, "c": c, "s": s, "rmse": mse**0.5, "n": len(pairs)})
            say(
                f"  {board.label:22s}  n={len(pairs):4d}  c={c:.4f}  s={s:.3f}  "
                f"rmse={mse ** 0.5:.1f}"
            )
        per_source[scope] = fits
        result = _fit_scope_master(scope, [(f["label"], f["c"], f["s"]) for f in fits])
        if result is None:
            continue
        c, s, mse = result
        masters[scope] = {"c": c, "s": s, "rmse": mse**0.5}
        c_name, s_name = SCOPE_CONSTANT_NAMES[scope]
        constants[c_name] = round(c, 4)
        constants[s_name] = round(s, 3)
    return {
        "perSource": per_source,
        "skipped": skipped,
        "trainingContent": content,
        "masters": masters,
        "constants": constants,
        "snapshot": str(snap) if snap is not None else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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

    print("Per-source Hill fits (trainers from src/model_registry/training_manifest.py):")
    result = fit_scopes(log=print)

    print("\nScope-level master curves (mean of per-source curves):")
    for scope in _SCOPE_REPORT_ORDER:
        master = result["masters"].get(scope)
        if master is None:
            print(f"  {scope:8s}  (no per-source fits)")
            continue
        print(
            f"  {scope:8s}  c*={master['c']:.4f}  s*={master['s']:.3f}  "
            f"master-fit rmse={master['rmse']:.1f}"
        )

    print()
    print("Value at key percentiles for each scope master:")
    ps = (0.0, 0.001, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9)
    print("  " + "scope".ljust(8) + "".join(f"{p:>9.3f}" for p in ps))
    for scope in _SCOPE_REPORT_ORDER:
        master = result["masters"].get(scope)
        if master is None:
            continue
        row = "".join(f"{int(_hill(p, master['c'], master['s'])):>9}" for p in ps)
        print(f"  {scope:<8}" + row)

    print()
    print("Suggested constants (src/canonical/player_valuation.py) — a CHALLENGER only:")
    for name, value in result["constants"].items():
        literal = f"{value:.4f}" if name.endswith("_C") else f"{value:.3f}"
        print(f"{name}: float = {literal}")

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(result["constants"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
