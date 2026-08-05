#!/usr/bin/env python3
"""Capture a canonical snapshot of every user-facing number on the board.

WHY THIS EXISTS
---------------
The 2026-08-04 decision-intelligence audit
(``docs/audits/decision-intelligence-audit-2026-08-04.md``) found 43
Critical and 130 High findings, and its Part B remediation plan opens with
a blocking prerequisite: **nothing else starts until a board change is
measurable.**  Several of the fixes deliberately move values — the IDP
re-fit, the pick-year discount gate, the TE-premium default — and several
others must move *nothing*.  Without a baseline those two cases are
indistinguishable, and a regression reads exactly like an intended repricing.

This script builds the real contract through the real entry point
(``build_api_data_contract``) from a pinned input export, and serializes
the decision-bearing fields to a stable, diffable JSON.  Pair it with
``scripts/board_diff.py``.

USAGE
-----
    # capture the pre-change baseline
    python scripts/golden_board.py --out tests/fixtures/golden/baseline.json

    # after a change
    python scripts/golden_board.py --out /tmp/after.json
    python scripts/board_diff.py tests/fixtures/golden/baseline.json /tmp/after.json

THE CONTRACT HAS **TWO** INPUTS, AND BOTH MOVE
-----------------------------------------------
This originally defaulted to ``exports/latest/dynasty_data_2026-08-04.json``
and called that pinned.  It is not: the filename carries only the DATE,
and ``scheduled-refresh.yml`` runs every two hours, so same-day refreshes
overwrite it in place.  Measured — that file was rewritten SIX times in
two days, and rebasing this batch onto main silently moved the capture's
input from the 18:20 scrape to the 20:14 one (two players in, one out).

So the export is now a committed, gzipped fixture — immutable by
construction, 92 KB.

**That was only half of it, and the half-fix was worse than none**
because it came with a claim of pinning.  ``build_api_data_contract``
also reads the per-source boards from ``CSVs/site_raw/*.csv`` at build
time, and those are TRACKED files the same refresh rewrites — nine
times in one day.  Measured after a rebase onto a main that had not
touched ``data_contract.py`` or ``src/canonical/`` at all: **290 values
moved, 266 ranks changed, 664 tiers flipped and 11 rows voted
differently**, entirely from CSV churn, and the capture reported it as
though the code had done it.  A harness that attributes data drift to
your diff is the exact failure it exists to prevent.

Both inputs are therefore hashed into every capture, and
``board_diff.py`` refuses to compare captures whose inputs differ.  The
committed baseline is a reference for the last merged tree state, not a
timeless constant: when the refresh lands, re-capture rather than
diffing across it.  Within a batch — capture, change, capture — both
inputs are identical and the diff is pure code effect, which is the
comparison that actually matters.

``--input`` still accepts a live export for deliberate use.

Exit codes: 0 success, 1 nothing built, 2 error.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_INPUT = REPO_ROOT / "tests" / "fixtures" / "golden" / "input_export.json.gz"

# The fields that constitute a user-facing decision.  Deliberately NOT
# every field on the row: diagnostics that carry a timestamp or a
# build-order artifact would make every capture differ from every other
# and the diff would be useless.
_ROW_FIELDS = (
    "assetClass",
    "position",
    "rankDerivedValue",
    "canonicalConsensusRank",
    "canonicalTierId",
    "confidenceBucket",
    "confidenceLabel",
    "marketGapDirection",
    "marketGapMagnitude",
    "sourceRankSpread",
    "isSingleSource",
    "hasSourceDisagreement",
    "quarantined",
    "pickYearDiscount",
    "anchorValue",
    "alphaShrinkage",
)


def _num(v):
    """Round floats so float noise is not reported as a board change."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return round(v, 6)
    return v


def _read_export(path: Path) -> tuple[dict, str]:
    """Load an export (plain or gzipped) and hash its CONTENT.

    Hashing the decompressed bytes, not the file: the frozen fixture is
    gzipped and the live export is not, so a file-level hash reports
    two byte-identical inputs as different.  A check that cries wolf
    teaches people to pass ``--allow-input-change`` without reading it,
    which is how the check stops existing.
    """
    blob = path.read_bytes()
    if path.suffix == ".gz":
        blob = gzip.decompress(blob)
    return json.loads(blob.decode("utf-8")), hashlib.sha256(blob).hexdigest()


SOURCE_CSV_DIR = REPO_ROOT / "CSVs" / "site_raw"


def _source_csv_digest() -> tuple[str, int]:
    """Hash the per-source boards the contract build reads from disk.

    The second input.  ``data_contract`` resolves these against the repo
    root with no override, so a capture cannot be isolated from them —
    it can only be honest about which ones it saw.  Name and content
    both go into the hash: a source file appearing or disappearing
    changes the blend as surely as its rows changing.
    """
    h = hashlib.sha256()
    count = 0
    if SOURCE_CSV_DIR.is_dir():
        for path in sorted(SOURCE_CSV_DIR.glob("*.csv")):
            h.update(path.name.encode("utf-8"))
            h.update(path.read_bytes())
            count += 1
    return h.hexdigest(), count


def capture(input_path: Path) -> dict:
    from src.api.data_contract import build_api_data_contract

    raw, input_sha = _read_export(input_path)
    source_sha, source_count = _source_csv_digest()
    contract = build_api_data_contract(raw)
    arr = contract.get("playersArray") or []

    rows: dict[str, dict] = {}
    for r in arr:
        if not isinstance(r, dict):
            continue
        key = str(r.get("displayName") or r.get("canonicalName") or "").strip()
        if not key:
            continue
        rows[key] = {f: _num(r.get(f)) for f in _ROW_FIELDS}
        # source coverage drives confidence and the single-source haircut,
        # so a change in WHICH sources voted is a board change even when
        # the resulting value happens to land the same.
        eff = r.get("effectiveSourceRanks") or {}
        rows[key]["_sourceKeys"] = sorted(eff) if isinstance(eff, dict) else []

    ranked = [r for r in arr if r.get("canonicalConsensusRank")]
    return {
        "inputExport": input_path.name,
        "inputSha256": input_sha,
        "sourceCsvSha256": source_sha,
        "sourceCsvCount": source_count,
        "scrapeTimestamp": (raw.get("scrapeTimestamp") or raw.get("date")),
        "totals": {
            "rows": len(arr),
            "ranked": len(ranked),
            "priced": sum(1 for r in arr if r.get("rankDerivedValue") is not None),
            "picks": sum(1 for r in arr if r.get("assetClass") == "pick"),
            "idp": sum(1 for r in arr if r.get("assetClass") == "idp"),
        },
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if not args.input.exists():
        print(f"error: input export not found: {args.input}", file=sys.stderr)
        return 2
    try:
        snap = capture(args.input)
    except Exception as exc:  # noqa: BLE001 — the harness must report, not crash
        print(f"error: contract build failed: {exc}", file=sys.stderr)
        return 2

    if not snap["rows"]:
        print("error: contract produced zero rows", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
    t = snap["totals"]
    print(
        f"captured {t['rows']} rows ({t['ranked']} ranked, {t['priced']} priced, "
        f"{t['picks']} picks, {t['idp']} idp) -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
