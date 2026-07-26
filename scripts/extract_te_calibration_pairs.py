#!/usr/bin/env python3
"""Extract paired TE-premium boards into the calibration cache (LI-6).

**Calibration only.** Nothing this script writes is a ranking source:
it does not touch ``_RANKING_SOURCES``, ``_SOURCE_CSV_PATHS``, or
``data_contract.py``, and the blend never reads
``data/calibration/te_pairs/``. The output exists so
``src/league_intel/calibration.py`` can measure a publisher's TE
premium from two variants of that publisher's own board.

Dynasty Nerds
-------------
DN publishes its whole rankings dataset inline in the page HTML::

    window.DR_DATA = { PPR: [...], SFLEX: [...], STD: [...],
                       SFLEXTEP: [...], _meta: {...} }

``scripts/fetch_dynasty_nerds.py`` already downloads that payload every
refresh and extracts **only** ``SFLEXTEP``. ``SFLEX`` is the same board
without the TE premium — the paired variant, from the same publisher,
in bytes we were already fetching and discarding.

So this script costs **zero additional HTTP against DN**: it reuses the
existing fetcher's ``_fetch_html`` / ``_extract_dr_data`` / ``_build_rows``
(the last is already parameterized by key) and pulls every variant out
of one response. The fetcher itself is imported, never modified.

Usage::

    python3 scripts/extract_te_calibration_pairs.py
    python3 scripts/extract_te_calibration_pairs.py --html-file page.html
    python3 scripts/extract_te_calibration_pairs.py --measure

Exit codes:
    0 — pairs written
    1 — soft failure (fetch/parse error, or a variant missing)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.fetch_dynasty_nerds import (  # noqa: E402
    DN_URL,
    _build_rows,
    _extract_dr_data,
    _fetch_html,
)

OUT_DIR = _REPO_ROOT / "data" / "calibration" / "te_pairs"

#: DR_DATA keys → the variant filenames we cache. ``SFLEX`` vs
#: ``SFLEXTEP`` is the TE pair; ``PPR``/``STD`` are captured too so the
#: scoring-format contrast can be checked rather than assumed.
DN_VARIANTS: dict[str, str] = {
    "SFLEX": "dynastyNerds_sflex",
    "SFLEXTEP": "dynastyNerds_sflextep",
    "PPR": "dynastyNerds_ppr",
    "STD": "dynastyNerds_std",
}

FIELDS = ["Name", "Rank", "Value", "SleeperId", "Pos", "Team"]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in FIELDS})


def extract_dynasty_nerds(html: str) -> dict[str, list[dict]]:
    """Pull every cached variant out of one DR_DATA payload."""
    data = _extract_dr_data(html)
    out: dict[str, list[dict]] = {}
    for key in DN_VARIANTS:
        if key not in data:
            print(f"[te-pairs] WARNING: DR_DATA missing {key!r} — skipped", file=sys.stderr)
            continue
        out[key] = _build_rows(data, key=key)
    return out


def build_paired_rows(
    base_rows: list[dict],
    premium_rows: list[dict],
) -> list[dict]:
    """Join two variants into the row shape ``calibration.py`` expects.

    Output rows carry ``position`` plus a ``canonicalSiteValues`` map
    keyed by variant, which is exactly what
    ``measure_paired_te_premium`` reads. Joined on SleeperId when both
    sides have one (collision-proof), else on name.
    """

    def key_of(r: dict) -> str:
        sid = str(r.get("SleeperId") or "").strip()
        return f"sid:{sid}" if sid else f"nm:{str(r.get('Name') or '').strip().lower()}"

    base_by = {key_of(r): r for r in base_rows}
    out: list[dict] = []
    for pr in premium_rows:
        br = base_by.get(key_of(pr))
        if br is None:
            continue
        out.append(
            {
                "displayName": pr.get("Name"),
                "position": (pr.get("Pos") or "").upper(),
                "team": pr.get("Team"),
                "sleeperId": pr.get("SleeperId"),
                "canonicalSiteValues": {
                    "base": br.get("Value"),
                    "premium": pr.get("Value"),
                },
                "baseRank": br.get("Rank"),
                "premiumRank": pr.get("Rank"),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DN_URL)
    ap.add_argument("--html-file", help="parse a saved page instead of fetching")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--measure", action="store_true", help="run calibration and print it")
    args = ap.parse_args(argv)

    try:
        if args.html_file:
            html = Path(args.html_file).read_text(encoding="utf-8")
        else:
            html = _fetch_html(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"[te-pairs] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        variants = extract_dynasty_nerds(html)
    except Exception as exc:  # noqa: BLE001
        print(f"[te-pairs] parse failed: {exc}", file=sys.stderr)
        return 1

    if "SFLEX" not in variants or "SFLEXTEP" not in variants:
        print("[te-pairs] DN pair incomplete — SFLEX and SFLEXTEP both required", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    for key, stem in DN_VARIANTS.items():
        rows = variants.get(key)
        if not rows:
            continue
        _write(out_dir / f"{stem}.csv", rows)
        print(f"[te-pairs] {key}: {len(rows)} rows → {stem}.csv")

    paired = build_paired_rows(variants["SFLEX"], variants["SFLEXTEP"])
    (out_dir / "dynastyNerds_paired.json").write_text(
        json.dumps(
            {
                "publisher": "dynastyNerds",
                "baseVariant": "SFLEX",
                "premiumVariant": "SFLEXTEP",
                "source": args.url,
                "extractedAt": datetime.now(timezone.utc).isoformat(),
                "note": (
                    "Both variants come from ONE DR_DATA payload the "
                    "existing fetcher already downloads; SFLEX was "
                    "previously parsed and discarded. Zero extra HTTP."
                ),
                "rows": paired,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[te-pairs] paired rows: {len(paired)} → dynastyNerds_paired.json")

    if args.measure:
        from src.league_intel.calibration import measure_paired_te_premium

        result = measure_paired_te_premium(paired, "base", "premium")
        print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
