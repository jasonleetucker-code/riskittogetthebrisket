"""Derive per-source row-count floors from git-tracked CSV history (W05-F004).

Evidence source: every distinct committed version (unique blob) of each
registered source's CSV in git history.  Raw usable rows are counted with the
contract's OWN parser (``_parse_source_csv_cached``), so "row" means exactly
what the board build means by it.

Floor rule (recorded in ``docs/sources/SOURCE_ROW_FLOORS.md``):

    robust_min = min of historical observations NOT collapsed
                 (a collapsed observation is < 50% of the history median: a
                 degraded scrape, the very event a floor must catch)
    ratio      = min(1, built board count / raw usable rows) on the reference board
                 (the floor is compared with MATCHED board rows, not raw rows)
    fraction   = 0.8, or 0.5 for class-phase (rookie) sources whose population
                 legitimately changes with the draft calendar
    floor      = floor(fraction * ratio * robust_min)

    ceiling    = 2 * raw max   (report-only ``source_above_expected``)

Usage:  python scripts/derive_source_row_floors.py [--keys a,b] [--json out.json] [--write-config]
Read-only unless ``--json`` / ``--write-config`` is given.  ``--write-config`` adds floors for
sources that declare none and sets their ceilings in config/weights/source_row_floors.json.
It also prints the reference board (archive name + sha256) the match ratios were measured on.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CLASS_PHASE_SOURCES = {"dlfRookieSf", "dlfRookieIdp", "flockFantasySfRookies"}
COLLAPSE_FRACTION = 0.5
FLOOR_FRACTION = 0.8
CLASS_PHASE_FRACTION = 0.5


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def history_counts(csv_rel: str, source_key: str, signal: str) -> list[int]:
    from src.api import data_contract as dc

    shas = _git("log", "--format=%H", "--", csv_rel).decode().split()
    blobs: dict[str, None] = {}
    for sha in shas:
        try:
            blobs[_git("rev-parse", f"{sha}:{csv_rel}").decode().strip()] = None
        except subprocess.CalledProcessError:
            continue  # deletion commit
    counts: list[int] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, blob in enumerate(blobs):
            p = Path(tmp) / f"{i}.csv"
            p.write_bytes(_git("cat-file", "blob", blob))
            lookup, err = dc._parse_source_csv_cached(p, source_key, signal, csv_rel)
            counts.append(0 if err else sum(len(v) for v in lookup.values()))
    return counts


def reference_board() -> tuple[str | None, str | None]:
    """(archive file name, sha256) of the board the match ratios use."""
    import hashlib

    sys.path.insert(0, str(REPO / "tests"))
    from archive_fixtures import ARCHIVE, newest_complete_raw_payload

    _, name = newest_complete_raw_payload()
    if not name:
        return None, None
    return name, hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest()


def reference_ratio(keys: list[str]) -> dict[str, tuple[int, int]]:
    """(built, raw) on the newest complete archived board, current repo CSVs."""
    sys.path.insert(0, str(REPO / "tests"))
    from archive_fixtures import newest_complete_raw_payload

    from src.api import data_contract as dc

    payload, _ = newest_complete_raw_payload()
    contract = dc.build_api_data_contract(payload)
    built = {k: 0 for k in keys}
    for row in contract["playersArray"]:
        sites = row.get("canonicalSiteValues") or {}
        for k in keys:
            try:
                if float(sites.get(k) or 0) > 0:
                    built[k] += 1
            except (TypeError, ValueError):
                pass
    out = {}
    for k in keys:
        cfg = dc._SOURCE_CSV_PATHS[k]
        rel, sig = (
            (cfg, "value") if isinstance(cfg, str) else (cfg["path"], cfg.get("signal", "value"))
        )
        lookup, _ = dc._parse_source_csv_cached(REPO / rel, k, str(sig).lower(), rel)
        out[k] = (built[k], sum(len(v) for v in lookup.values()))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--write-config", action="store_true")
    args = ap.parse_args()
    from src.api import data_contract as dc

    declared = dc._load_source_row_floors()
    keys = [k for k in args.keys.split(",") if k] or sorted(
        set(dc.get_ranking_source_keys()) - set(declared)
    )
    ratios = reference_ratio(keys)
    report: dict[str, dict] = {}
    for k in keys:
        cfg = dc._SOURCE_CSV_PATHS[k]
        rel, sig = (
            (cfg, "value") if isinstance(cfg, str) else (cfg["path"], cfg.get("signal", "value"))
        )
        counts = history_counts(rel, k, str(sig).lower())
        if not counts:
            report[k] = {"error": "no history"}
            continue
        median = statistics.median(counts)
        kept = [c for c in counts if c >= COLLAPSE_FRACTION * median]
        built, raw = ratios[k]
        ratio = min(1.0, built / raw) if raw else 0.0
        frac = CLASS_PHASE_FRACTION if k in CLASS_PHASE_SOURCES else FLOOR_FRACTION
        robust_min = min(kept)
        report[k] = {
            "versions": len(counts),
            "rawMin": min(counts),
            "rawMedian": median,
            "rawMax": max(counts),
            "collapsedVersions": len(counts) - len(kept),
            "robustMin": robust_min,
            "referenceBuilt": built,
            "referenceRaw": raw,
            "matchRatio": round(ratio, 4),
            "fraction": frac,
            "floor": int(frac * ratio * robust_min),
            "ceiling": 2 * max(counts),
        }
        print(k, json.dumps(report[k]))
    board_name, board_sha = reference_board()
    print(f"reference board: {board_name} sha256={board_sha}")
    if args.write_config:
        cfg_path = REPO / "config" / "weights" / "source_row_floors.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for k, v in report.items():
            if "floor" in v:
                cfg["floors"].setdefault(k, v["floor"])
                cfg.setdefault("ceilings", {})[k] = v["ceiling"]
        cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
