"""W27 evidence: re-measure the KTC <-> IDPTradeCalc overlap on the LIVE contract.

Reproduces (or refutes) CLAUDE.md's "Cross-market note" claim:
    "475 of KTC's 500 rows also appear on the IDPTC board at a median
     value ratio of 1.000 (p10 0.888, p90 1.054, measured 2026-07-26).
     Both top out at 9999."

Usage:
    curl -s -b /tmp/audit-cookies.txt http://127.0.0.1:8000/api/data > contract.json
    .venv/bin/python docs/master-site-audit/evidence/W27/measure_cross_market.py contract.json
"""

from __future__ import annotations

import collections
import json
import sys


def quantile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    idx = (len(ordered) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def main() -> int:
    contract = json.load(open(sys.argv[1]))
    rows = contract.get("playersArray") or []

    paired: list[tuple[str, str, float, float, float]] = []
    ktc_pos: collections.Counter[str] = collections.Counter()
    idp_pos: collections.Counter[str] = collections.Counter()
    ktc_max = idptc_max = 0.0

    for row in rows:
        sites = row.get("canonicalSiteValues") or {}
        ktc = sites.get("ktcSfTep")
        idptc = sites.get("idpTradeCalc")
        pos = row.get("position") or ("PICK" if row.get("assetClass") == "pick" else "?")
        if ktc:
            ktc_pos[pos] += 1
            ktc_max = max(ktc_max, float(ktc))
        if idptc:
            idp_pos[pos] += 1
            idptc_max = max(idptc_max, float(idptc))
        if ktc and idptc:
            paired.append(
                (
                    row.get("displayName") or "",
                    pos,
                    float(ktc),
                    float(idptc),
                    float(idptc) / float(ktc),
                )
            )

    ratios = [r[4] for r in paired]
    out = {
        "ktcSfTepRows": sum(ktc_pos.values()),
        "idpTradeCalcRows": sum(idp_pos.values()),
        "ktcSfTepByPosition": dict(ktc_pos),
        "idpTradeCalcByPosition": dict(idp_pos),
        "pairedRows": len(paired),
        "pairedShareOfKtc": round(len(paired) / max(sum(ktc_pos.values()), 1), 4),
        "ktcSfTepMax": ktc_max,
        "idpTradeCalcMax": idptc_max,
        "ratioPooled": {
            "n": len(ratios),
            "p10": round(quantile(ratios, 0.10), 4),
            "median": round(quantile(ratios, 0.50), 4),
            "p90": round(quantile(ratios, 0.90), 4),
        },
        "ratioByPosition": {},
        "idpTradeCalcIdpMax": max(
            (
                float((r.get("canonicalSiteValues") or {}).get("idpTradeCalc") or 0)
                for r in rows
                if r.get("position") in {"DL", "LB", "DB"}
            ),
            default=0.0,
        ),
    }
    by_pos: dict[str, list[float]] = collections.defaultdict(list)
    for _, pos, _, _, ratio in paired:
        by_pos[pos].append(ratio)
    for pos, vals in sorted(by_pos.items(), key=lambda kv: -len(kv[1])):
        out["ratioByPosition"][pos] = {
            "n": len(vals),
            "p10": round(quantile(vals, 0.10), 4),
            "median": round(quantile(vals, 0.50), 4),
            "p90": round(quantile(vals, 0.90), 4),
        }
    json.dump(out, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
