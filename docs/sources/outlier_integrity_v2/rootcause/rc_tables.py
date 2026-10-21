#!/usr/bin/env python3
"""Render the root-cause (DISCOVER-1) vote tables from rc_analyze / rc_decompose outputs.

usage: rc_tables.py OUT_DIR TAG   (reads OUT_DIR/analysis_TAG.json, OUT_DIR/decompose_TAG.json)
writes OUT_DIR/vote_tables_TAG.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

here = Path(sys.argv[1])
tag = sys.argv[2]
an = json.loads((here / f"analysis_{tag}.json").read_text())
de = json.loads((here / f"decompose_{tag}.json").read_text())
L: list[str] = []
P = L.append
SHORT = {
    "draftSharksIdp": "DS",
    "fantasyProsIdp": "FP",
    "idpTradeCalc": "IDPTC",
    "dlfIdp": "DLF",
    "dlfRookieIdp": "DLFr",
    "idpShowCombined": "IDPShow",
}
ia = an["inputs"]
P(f"# DISCOVER-1 vote tables -- {tag}")
P(f"payload sha256 {ia['A']['payloadSha256']}  scrape {ia['A']['scrapeTimestamp']}")
P(f"A env {ia['A']['env']} holds {ia['A']['policyHoldsInForce']}")
P(f"B env {ia['B']['env']} holds {ia['B']['policyHoldsInForce']}")
P(f"filter constants {ia['A']['constants']}")
P("")
P(
    f"IDP rows reaching the filter: A {an['idpRowsReachingFilter_A']}  B {an['idpRowsReachingFilter_B']}"
)
P(f"IDP voters per row (non-withheld): A {an['idpVotersPerRow_A']}")
P(f"                                   B {an['idpVotersPerRow_B']}")
P(
    f"IDP drops: A {an['idpDrops_A']}  B {an['idpDrops_B']};  offense drops A {an['offenseDrops_A']}  B {an['offenseDrops_B']} (offense drop set unchanged: {not an['offenseDropSetChanged']})"
)
nd = an["newlyDroppedIdp"]
P(
    f"newly dropped IDP votes: {nd['allNewDrops']} = {nd['otherSourceVotesDropped']} other-source on {nd['rows']} rows + DLF's own {nd['dlfOwnVotesDropped']}"
)
P(
    f"  by source {nd['bySource']}  by position {nd['byPosition']}  rows with two drops {nd['rowsWithTwoDrops']}"
)
P("")
P("## The 31 other-source votes the incumbent drops in B (and never in A)")
P(
    "row | n | votes (source value @effRank) | median | MAD | 2.75*MAD | threshold | floor? | dropped (deviation)"
)
cf = {x["row"]: x for x in de["mechanismCounterfactuals"]}
for d in an["newlyDroppedDetail"]:
    b = d["B"]
    votes = ", ".join(
        f"{SHORT.get(v['source'], v['source'])} {v['value']:.0f}@{v['effectiveRank']}"
        for v in b["votes"]
    )
    dropped = ", ".join(
        f"{SHORT.get(v['source'], v['source'])} ({v['deviation']:.0f})"
        for v in b["votes"]
        if v["dropped"]
    )
    P(
        f"{d['row']} | {cf[d['row']]['n']} | {votes} | {b['median']:.1f} | {b['mad']:.1f} | {b['kMad']:.1f} | "
        f"{b['threshold']:.1f} | {'Y' if b['floorBound'] else 'n'} | {dropped}"
    )
P("")
P("## Mechanism counterfactuals (exact re-implementation; diagnostics, not proposals)")
P(json.dumps(de["mechanismSummary"], indent=1))
P("reimplementation mismatches on B: " + str(de["reimplementationMismatchesOnB"]))
P("")
P("## Every IDP move >= 30%: decomposition A -> B(no IDP filter) -> B")
P("row | A | B no-filter | B | total | DLF own vote | filter reaction | dropped in B")
for x in de["movesGe30pct"]:
    P(
        f"{x['row']} | {x['A']} | {x['B_noFilter']} | {x['B']} | {x['total']:+.1%} | {x['dlfOwnVote']:+.1%} | "
        f"{x['filterReaction']:+.1%} | {', '.join(x['droppedInB'])}"
    )
P(f"DLF's own vote across all {de['idpRowsMoved']} moved IDP rows: {de['dlfOwnVote_absRel']}")
P(
    f"every IDP move >= 10% carries a filter drop: {de['movesGe10pctAllHaveFilterDrop']} ({len(de['movesGe10pct'])} rows)"
)
P("")
P("## Focus rows: full vote tables")
for f in an["focus"]:
    P(f"### {f['row']}  (A -> B {f.get('relChange', 0):+.1%})")
    for t in "AB":
        b = f[t]
        P(
            f"{t}: value {b['value']} rank {b['rank']} conf {b['confidence']} filterRan {b['filterRan']} n {b['n']}"
            + (
                f" median {b['median']} MAD {b['mad']:.2f} 2.75*MAD {b['kMad']} threshold {b['threshold']} "
                f"floorBound {b['floorBound']} dropped {b['dropped']}"
                if b["filterRan"]
                else f" freshnessExcluded {b['freshnessExcluded']}"
            )
        )
        P(
            "   source | value | deviation | dropped | path | method | rawRank | effRank | anchor | weight"
        )
        for v in b["votes"]:
            P(
                f"   {v['source']} | {v['value']} | {v.get('deviation')} | {v.get('dropped')} | {v.get('path')} | "
                f"{v.get('method')} | {v.get('rawRank')} | {v.get('effectiveRank')} | {v.get('anchor')} | "
                f"{None if v.get('weight') is None else round(v['weight'], 3)}"
                + (
                    ""
                    if v.get("contributedToBlend") is not False
                    else "  [freshness-withheld, not a vote]"
                )
            )
P("")
P("## Production today: the same statistic inside the B11 lost-evidence replay (A)")
P(json.dumps(de["productionLostEvidenceReplay_idp"], indent=1))
(here / f"vote_tables_{tag}.txt").write_text("\n".join(L) + "\n")
print("\n".join(L))
