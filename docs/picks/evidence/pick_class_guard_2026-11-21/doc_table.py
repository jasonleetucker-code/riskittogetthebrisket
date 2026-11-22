"""Markdown diff table for the evidence doc.  usage: doc_table.py <off.rows.json> <on.rows.json>"""

from __future__ import annotations

import json
import sys

off = json.load(open(sys.argv[1], encoding="utf-8"))["rows"]
on = json.load(open(sys.argv[2], encoding="utf-8"))["rows"]


def num(v):
    return str(int(round(v))) if isinstance(v, (int, float)) else "–"


print(
    "| Pick | OFF | ON | Δ | Δ% | OFF provenance (tethered rookie) | ON provenance "
    "| IDPTC slot (votes) | KTC slot, spread from tier (no vote) |"
)
print("|---|---:|---:|---:|---:|---|---|---:|---:|")
for rnd in range(1, 7):
    for slot in range(1, 13):
        name = f"2027 Pick {rnd}.{slot:02d}"
        a, b = off[name], on[name]
        d = b["value"] - a["value"]
        pct = 100.0 * d / a["value"]
        po = f"{(a['prov'] or {}).get('class')} ({a['anchor']})"
        pn = (b["prov"] or {}).get("class")
        if pn == "derived_round_step":
            pn += f" from {b['prov'].get('basis')}"
        print(
            f"| {name} | {a['value']} | {b['value']} | {d:+d} | {pct:+.1f}% | {po} | {pn} "
            f"| {num(b['sites'].get('idpTradeCalc'))} | {num(b['sites'].get('ktc'))} |"
        )
