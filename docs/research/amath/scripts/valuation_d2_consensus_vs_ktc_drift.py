"""AMATH VALUATION diagnostic D2 (read-only): who moves toward whom?

gap_t0 = median log-rank of non-KTC families - KTC log-rank (offense, >=4 non-KTC
sources).  Measures Spearman(gap_t0, KTC revision over 28d) and
Spearman(-gap_t0, non-KTC consensus revision).  Positive = that side moves toward
the other.  Same committed-CSV substrate and date limits as D1.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import date, timedelta

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
import amath_val_d1 as m  # noqa: E402

NONKTC = [k for k in m.SOURCES if k != "ktcSfTep"]


def main() -> None:
    out = []
    for i in range(9):
        t0 = date(2026, 7, 20) + timedelta(days=7 * i)
        t1 = t0 + timedelta(days=28)
        b0 = {k: m.board(k, t0) for k in m.SOURCES}
        b1 = {k: m.board(k, t1) for k in m.SOURCES}
        g, rk, rc = [], [], []
        for nm, r0 in b0["ktcSfTep"].items():
            if nm not in b1["ktcSfTep"] or r0 > 300:
                continue
            ks = [k for k in NONKTC if b0[k] and b1[k] and nm in b0[k] and nm in b1[k]]
            if len(ks) < 4:
                continue
            c0 = statistics.median(math.log(b0[k][nm]) for k in ks)
            c1 = statistics.median(math.log(b1[k][nm]) for k in ks)
            k0, k1 = math.log(r0), math.log(b1["ktcSfTep"][nm])
            g.append(c0 - k0)
            rk.append(k1 - k0)
            rc.append(c1 - c0)
        out.append(
            {
                "t0": t0.isoformat(),
                "n": len(g),
                "spearman_gap_vs_ktc_revision": round(m.spearman(g, rk), 3),
                "spearman_neg_gap_vs_consensus_revision": round(m.spearman([-x for x in g], rc), 3),
            }
        )
    s = {
        "median_ktc_toward_consensus": statistics.median(
            o["spearman_gap_vs_ktc_revision"] for o in out
        ),
        "median_consensus_toward_ktc": statistics.median(
            o["spearman_neg_gap_vs_consensus_revision"] for o in out
        ),
    }
    json.dump({"windows": out, "summary": s}, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
