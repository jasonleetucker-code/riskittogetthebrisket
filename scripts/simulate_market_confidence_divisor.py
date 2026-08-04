#!/usr/bin/env python3
"""Simulate changing the ``site_count`` divisor in market confidence.

WHY THIS EXISTS
===============
``Dynasty Scraper.py::_market_confidence`` computes:

    site_score = clamp(site_count / SITE_DIVISOR, 0.20, 1.00)   # 65% weight
    cv_score   = clamp(1 - min(cv,0.35)/0.35, 0.20, 1.00)       # 35% weight
    conf       = clamp(site_score*0.65 + cv_score*0.35, 0.20, 1.00)

``SITE_DIVISOR`` is 8.0.  But ``site_count`` (persisted as ``_sites``)
never exceeds 3 on real payloads, so ``site_score`` is confined to
{0.20, 0.25, 0.375} and confidence is structurally capped at

    0.375*0.65 + 1.00*0.35 = 0.59375

— which is exactly the observed maximum.  The metric can never express
high confidence, so the ``low_conf_unstable`` threshold of 0.35 cannot
be calibrated meaningfully against it.

WHY ``_sites`` MAXES AT 3 (measured 2026-07-30)
===============================================
It is not a registry-coverage count.  The composite loop accumulates
``wNorms`` from the SCRAPER's own per-player dash keys, and the
scraper's ``SITES`` toggle map has exactly two entries enabled — ``KTC``
and ``IDPTradeCalc``, the rest ``False`` and labelled "disabled in scope
reduction".  Those two emit three numeric dash keys between them
(``ktc``, ``ktcSfTep``, ``idpTradeCalc``), so ``len(wNorms) ∈ {1,2,3}``
by construction.  The other 18 registry sources are fetched by
``scripts/fetch_*.py`` and merged downstream in
``src/api/data_contract.py``, which never recomputes ``_sites``.  The
``/ 8.0`` divisor is a fossil of the pre-scope-reduction ~10-site era.

OUTCOME (2026-07-30)
====================
The rule this was measured for is **RETIRED**, because the table this
script prints shows every candidate divisor pushing confidence UP: zero
players fall below 0.35 at divisors 3, 4 or 5, so there is no divisor at
which a "fires below 0.35" rule becomes well-calibrated.  See
``docs/open-modeling-decisions.md`` §3.

The script is kept because the divisor itself is still 8.0 and the
composite-multiplier columns below are the measurement anyone correcting
it will need.  ``--threshold`` now just annotates the output; no live
rule reads it.

WHY THIS DOESN'T NEED THE SCRAPER
=================================
Re-scraping to measure the fix is impractical in a dev environment (no
network, no site credentials) AND unnecessary, because the formula is
INVERTIBLE.  For every player the payload gives us ``_marketConfidence``
and ``_sites``; ``site_score`` follows from ``_sites``, so:

    cv_score = (conf - site_score*0.65) / 0.35

recovers the second input exactly.  With both inputs known we can
recompute confidence under any divisor with no re-scrape and no
approximation.

The four downstream consumers of ``market_conf`` are all LINEAR in it,
so their multiplier shifts are exact too:

    elite_boost      = 1 + (0.09 * span * agreement * conf)   [offense]
    single-source    = 0.55 + (0.82-0.55) * conf
    idp_conf_factor  = 0.60 + (0.40 * conf)
    elite_cap        = cap * (1 + 0.08*conf)  offense / 0.03  IDP

``span`` and ``agreement`` are not in the payload, so ``elite_boost`` is
reported as a per-unit sensitivity rather than an absolute.  The other
three are exact.

WHAT TO READ OFF IT
===================
The question is not "is 8.0 wrong" — it is — but "what does correcting
it do to composite values", because ``market_conf`` feeds the scraper's
composite arithmetic and therefore ``_finalAdjusted``.

USAGE
=====
    python scripts/simulate_market_confidence_divisor.py
    python scripts/simulate_market_confidence_divisor.py --divisors 3 4 5
    python scripts/simulate_market_confidence_divisor.py --out docs/measurements/x.json

Exit codes: 0 success, 1 error.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

LIVE_DIVISOR = 8.0
SITE_WEIGHT = 0.65
CV_WEIGHT = 0.35
FLOOR = 0.20
CEILING = 1.00

# Downstream consumers, all linear in conf.
SINGLE_SOURCE_MIN, SINGLE_SOURCE_MAX = 0.55, 0.82
IDP_CONF_BASE, IDP_CONF_SPAN = 0.60, 0.40
ELITE_CAP_OFFENSE, ELITE_CAP_IDP = 0.08, 0.03
ELITE_BOOST_MAX = 0.09


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _site_score(site_count: float, divisor: float) -> float:
    return _clamp(float(site_count) / divisor, FLOOR, CEILING)


def _conf(site_count: float, cv_score: float, divisor: float) -> float:
    return _clamp(
        _site_score(site_count, divisor) * SITE_WEIGHT + cv_score * CV_WEIGHT, FLOOR, CEILING
    )


def _recover_cv_score(conf: float, site_count: float) -> float:
    """Invert the live formula to recover the agreement term."""
    return _clamp(
        (conf - _site_score(site_count, LIVE_DIVISOR) * SITE_WEIGHT) / CV_WEIGHT, 0.0, 1.0
    )


def _default_payload() -> Path | None:
    latest = REPO_ROOT / "exports" / "latest"
    if not latest.is_dir():
        return None
    cands = sorted(latest.glob("dynasty_data_*.json"))
    return cands[-1] if cands else None


def _pct(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * len(s)))]


def _describe(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {}
    return {
        "n": len(vals),
        "min": round(min(vals), 4),
        "p10": round(_pct(vals, 0.10), 4),
        "median": round(statistics.median(vals), 4),
        "p90": round(_pct(vals, 0.90), 4),
        "max": round(max(vals), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--payload", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--divisors", type=float, nargs="*", default=[3.0, 4.0, 5.0])
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="annotation only — the retired low_conf_unstable rule's threshold",
    )
    args = ap.parse_args()

    path = args.payload or _default_payload()
    if path is None or not path.is_file():
        print(f"ERROR: no payload found ({path})", file=sys.stderr)
        return 1

    payload = json.loads(path.read_text())
    players = payload.get("players") or {}

    rows: list[dict[str, Any]] = []
    for name, p in players.items():
        if not isinstance(p, dict):
            continue
        conf = p.get("_marketConfidence")
        sites = p.get("_sites")
        if not isinstance(conf, (int, float)) or not isinstance(sites, (int, float)):
            continue
        rows.append(
            {
                "name": name,
                "conf": float(conf),
                "sites": float(sites),
                "cvScore": _recover_cv_score(float(conf), float(sites)),
            }
        )

    if not rows:
        print("ERROR: payload carries no _marketConfidence/_sites pairs", file=sys.stderr)
        return 1

    live = [r["conf"] for r in rows]
    site_counts = [r["sites"] for r in rows]
    ceiling_live = _conf(max(site_counts), 1.0, LIVE_DIVISOR)

    print(f"payload            : {path.name}")
    print(f"players with data  : {len(rows)}")
    print(f"observed _sites    : min={min(site_counts):.0f} max={max(site_counts):.0f}")
    print(f"LIVE divisor       : {LIVE_DIVISOR}")
    print(f"  confidence       : {_describe(live)}")
    print(f"  structural ceiling at max _sites : {ceiling_live:.4f}")
    print(f"  below threshold {args.threshold}: {sum(1 for c in live if c < args.threshold)}")
    print()

    results: dict[str, Any] = {"live": {"divisor": LIVE_DIVISOR, "confidence": _describe(live)}}

    for div in args.divisors:
        new = [_conf(r["sites"], r["cvScore"], div) for r in rows]
        deltas = [n - r["conf"] for n, r in zip(new, rows)]
        # Exact downstream shifts (linear consumers).
        ss = [
            (SINGLE_SOURCE_MIN + (SINGLE_SOURCE_MAX - SINGLE_SOURCE_MIN) * n)
            / (SINGLE_SOURCE_MIN + (SINGLE_SOURCE_MAX - SINGLE_SOURCE_MIN) * r["conf"])
            for n, r in zip(new, rows)
        ]
        idpf = [
            (IDP_CONF_BASE + IDP_CONF_SPAN * n) / (IDP_CONF_BASE + IDP_CONF_SPAN * r["conf"])
            for n, r in zip(new, rows)
        ]
        capo = [
            (1 + ELITE_CAP_OFFENSE * n) / (1 + ELITE_CAP_OFFENSE * r["conf"])
            for n, r in zip(new, rows)
        ]
        entry = {
            "divisor": div,
            "confidence": _describe(new),
            "ceilingAtMaxSites": round(_conf(max(site_counts), 1.0, div), 4),
            "meanConfDelta": round(sum(deltas) / len(deltas), 4),
            "maxConfDelta": round(max(deltas), 4),
            "belowThreshold": sum(1 for c in new if c < args.threshold),
            "downstreamMultiplier": {
                "singleSourceDiscount": _describe(ss),
                "idpConfFactor": _describe(idpf),
                "eliteCapOffense": _describe(capo),
            },
        }
        results[f"divisor_{div:g}"] = entry

        print(f"DIVISOR {div:g}")
        print(f"  confidence     : {entry['confidence']}")
        print(f"  ceiling        : {entry['ceilingAtMaxSites']}")
        print(
            f"  mean delta     : {entry['meanConfDelta']:+.4f}   max {entry['maxConfDelta']:+.4f}"
        )
        print(f"  below {args.threshold}     : {entry['belowThreshold']}")
        print(
            f"  composite multipliers (new/old) — "
            f"single-source x{entry['downstreamMultiplier']['singleSourceDiscount']['median']:.4f}, "
            f"idp_conf x{entry['downstreamMultiplier']['idpConfFactor']['median']:.4f}, "
            f"elite_cap x{entry['downstreamMultiplier']['eliteCapOffense']['median']:.4f}"
        )
        print(
            f"  elite_boost sensitivity: up to "
            f"{ELITE_BOOST_MAX * entry['maxConfDelta']:+.4f} on the boost term "
            f"(scaled by span*agreement, both <= 1)"
        )
        print()

    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "payload": path.name,
        "threshold": args.threshold,
        "results": results,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2) + "\n")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
