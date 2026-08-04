#!/usr/bin/env python3
"""Measure KTC's TE-premium as a RANK shift, from KTC's own two boards.

Math audit 2026-07-30, finding C4.

``config/weights/te_premium_curve.json`` (FR-2) measures the same premium
as a VALUE ratio: ``uplift(v) = 1 + a*v^-k``, fitted on 73 TEs appearing on
both ``ktc.csv`` (base SF) and ``ktcSfTep.csv`` (TE++ level 2).  That fit is
sound *in the space it was fitted in* — KTC base-board values.

It is applied somewhere else.  ``_compute_unified_rankings`` multiplies it
into a source's **Hill contribution**, which is derived from that source's
overall RANK, and the two are not the same variable:

    KTC ranks Brock Bowers 8th and VALUES him 8153.
    Hill maps rank 8 to 9076.

The Hill curve is far steeper at the top than KTC's real value
distribution, so a rank-8 TE arrives at the uplift curve as 9076 — outside
the domain the curve was ever measured on (max TE base value 8153).
``9076 * 1.2092 = 10975``, clamped to the 9999 ceiling.  Measured on the
live source CSVs, six sources' top-TE votes all pinned to exactly 9999:
fantasyCalc, pfkDynasty and dynastyDaddySf (rank 8), idpTradeCalc and
dynastyNerdsSfTep (rank 7), otcffbSf (rank 14).  Each therefore cast an
identical vote for a tight end and for the #1 overall player, erasing the
disagreement they actually published.

The same premium measured in RANK space cannot do that, because KTC's own
TE++ board answers the question directly and never approaches the ceiling:

    Bowers   base rank   8  ->  TE++ rank   5
    McBride  base rank  17  ->  TE++ rank   8
    Loveland base rank  28  ->  TE++ rank  12

A rank shift is bounded by construction (rank >= 1), strictly monotone over
the measured pairs (verified), and lands inside the Hill curve's domain by
definition.

What makes this identifiable at all: the two boards are the same publisher,
the same players, the same scrape date, and the TE++ setting is the ONLY
difference — verified here by checking that every non-TE row has a byte-
identical value across the two files.  So the rank movement IS the premium,
with no modelling assumption needed to isolate it.

Output: ``config/weights/te_premium_rank_shift.json``

    python scripts/audit/fit_ktc_te_rank_shift.py            # print
    python scripts/audit/fit_ktc_te_rank_shift.py --write    # write config
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_KTC_BASE = _REPO_ROOT / "CSVs" / "site_raw" / "ktc.csv"
_KTC_TEPP = _REPO_ROOT / "CSVs" / "site_raw" / "ktcSfTep.csv"
_OUT = _REPO_ROOT / "config" / "weights" / "te_premium_rank_shift.json"

# How many knots to keep.  The raw measurement is ~72 pairs; storing every
# one makes the config a data dump and over-fits sampling noise in the
# deep tail.  Sampling evenly in log-rank keeps the shape where it moves
# fastest (the top of the board) and thins the flat tail.
_KNOT_COUNT = 14


def _load_values(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = str(row.get("name") or "").strip()
            try:
                val = float(row.get("value"))
            except (TypeError, ValueError):
                continue
            if name:
                out[name] = val
    return out


def _dense_ranks(values: dict[str, float]) -> dict[str, int]:
    """Rank descending by value, ties broken by name for determinism."""
    ordered = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
    return {name: i + 1 for i, (name, _) in enumerate(ordered)}


def _positions(payload_path: Path) -> dict[str, str]:
    with payload_path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    sleeper = payload.get("sleeper") or {}
    return {
        str(k).strip().lower(): str(v).upper()
        for k, v in (sleeper.get("positions") or {}).items()
    }


def fit(payload_path: Path) -> dict:
    base_vals = _load_values(_KTC_BASE)
    tepp_vals = _load_values(_KTC_TEPP)
    pos = _positions(payload_path)

    base_ranks = _dense_ranks(base_vals)
    tepp_ranks = _dense_ranks(tepp_vals)

    shared = [n for n in base_vals if n in tepp_vals]
    tes = [n for n in shared if pos.get(n.lower()) == "TE"]
    non_tes = [n for n in shared if pos.get(n.lower()) not in (None, "TE")]

    # Identification check — if the TE++ setting moved a non-TE value, the
    # rank movement below is not purely the TE premium and this fit is not
    # identified.  Refuse rather than publish a contaminated curve.
    contaminated = [n for n in non_tes if base_vals[n] != tepp_vals[n]]
    if contaminated:
        raise SystemExit(
            f"NOT IDENTIFIED: {len(contaminated)} non-TE rows differ between the two "
            f"KTC boards (e.g. {contaminated[:3]}). The TE++ setting is not the only "
            "difference, so a rank shift measured here would absorb something else."
        )

    pairs = sorted((base_ranks[n], tepp_ranks[n], n) for n in tes)
    if len(pairs) < 20:
        raise SystemExit(f"only {len(pairs)} paired TEs — too thin to fit")

    # Monotonicity is what makes this usable as an order-preserving map.
    non_mono = [
        (pairs[i][2], pairs[i + 1][2])
        for i in range(len(pairs) - 1)
        if pairs[i + 1][1] < pairs[i][1]
    ]

    # Enforce monotonicity defensively (a tie in base value could otherwise
    # invert a pair), then thin to knots sampled evenly in log-rank.
    running = 0
    cleaned: list[tuple[int, int]] = []
    for base_r, tepp_r, _ in pairs:
        running = max(running, tepp_r)
        cleaned.append((base_r, running))

    step = max(1, len(cleaned) // _KNOT_COUNT)
    knots = cleaned[::step]
    if knots[-1] != cleaned[-1]:
        knots.append(cleaned[-1])

    ratios = [t / b for b, t in cleaned]
    return {
        "_comment": (
            "KTC's TE-premium measured as a RANK shift, base SF -> TE++ level 2. "
            "Consumed by src/league_intel/te_premium.py::convert_te_rank, which the "
            "canonical blend applies BEFORE the Hill curve so the premium cannot "
            "saturate the 9999 ceiling. Fitter: scripts/audit/fit_ktc_te_rank_shift.py. "
            "See docs/audits/math-formula-audit-2026-07-30.md finding C4."
        ),
        "version": "te.rankshift.2026-07-30.v1",
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        "source": "CSVs/site_raw/ktc.csv vs CSVs/site_raw/ktcSfTep.csv",
        "pairedTightEnds": len(pairs),
        "nonTeRowsChecked": len(non_tes),
        "nonTeRowsThatMoved": len(contaminated),
        "monotoneAsMeasured": not non_mono,
        "ratioRange": [round(min(ratios), 4), round(max(ratios), 4)],
        "_knots": "[baseRank, teppRank] pairs, monotone, interpolated in log-rank space",
        "knots": [[b, t] for b, t in knots],
        "_limitation": (
            "Measured within KTC's 500-row board. Applying it to another publisher "
            "assumes their board has comparable depth and shape — the same assumption "
            "te_premium_curve.json already carries, stated here for the same reason."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--payload",
        type=Path,
        default=_REPO_ROOT / "exports" / "latest" / "dynasty_data_2026-07-30.json",
        help="raw payload supplying the name -> position map",
    )
    ap.add_argument("--write", action="store_true", help="write config/weights/te_premium_rank_shift.json")
    args = ap.parse_args(argv)

    result = fit(args.payload)
    print(json.dumps(result, indent=2))
    if args.write:
        _OUT.parent.mkdir(parents=True, exist_ok=True)
        with _OUT.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
        print(f"\nwrote {_OUT.relative_to(_REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
