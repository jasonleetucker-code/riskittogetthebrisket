"""OFF vs ON diff of two build_board.py summaries.  usage: diff_boards.py <off.rows.json> <on.rows.json>"""

from __future__ import annotations

import json
import sys

off = json.load(open(sys.argv[1], encoding="utf-8"))
on = json.load(open(sys.argv[2], encoding="utf-8"))
ro, rn = off["rows"], on["rows"]
print("currentDraftYear", off["currentDraftYear"], on["currentDraftYear"])
print("health OFF", off["health"]["ok"], off["health"]["errors"])
print("health ON ", on["health"]["ok"], on["health"]["errors"], on["health"]["structuralErrors"])
print("guard stamp", json.dumps(on["pickClassTetherGuard"], indent=1))
assert set(ro) == set(rn), set(ro) ^ set(rn)


def cls(p):
    return (p or {}).get("class")


moved = []
nonpick_moved = []
rank_moved = []
prov_changed = []
for name in ro:
    a, b = ro[name], rn[name]
    if a["value"] != b["value"]:
        (moved if a["assetClass"] == "pick" else nonpick_moved).append(name)
    if a["rank"] != b["rank"] or a["tier"] != b["tier"]:
        rank_moved.append(name)
    if a["prov"] != b["prov"] and a["value"] == b["value"]:
        prov_changed.append(name)

print("pick rows moved:", len(moved))
print("non-pick rows moved:", len(nonpick_moved), nonpick_moved[:10])
print("rows whose rank/tier changed:", len(rank_moved), rank_moved[:10])
print("pick rows with provenance-only change:", len(prov_changed), prov_changed[:5])


def topn(rows, n):
    ranked = sorted((r["rank"], k) for k, r in rows.items() if isinstance(r["rank"], int))
    return {k for _, k in ranked[:n]}


for n in (50, 100, 200):
    a, b = topn(ro, n), topn(rn, n)
    print(f"top-{n} membership change: -{sorted(a - b)} +{sorted(b - a)}")

deltas = []
for name in moved:
    a, b = ro[name]["value"], rn[name]["value"]
    d = (b or 0) - (a or 0)
    pct = None if not a else 100.0 * d / a
    deltas.append((name, a, b, d, pct))


def key(t):
    import re

    m = re.match(r"(\d{4}) Pick (\d)\.(\d\d)", t[0])
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (9999, 0, 0)


deltas.sort(key=key)
if deltas:
    mx = max(deltas, key=lambda t: abs(t[3]))
    mxp = max(deltas, key=lambda t: abs(t[4] or 0))
    print("max abs movement:", mx)
    print("max pct movement:", mxp)
    ups = sum(1 for t in deltas if t[3] > 0)
    print("up", ups, "down", len(deltas) - ups)

print()
print("| Pick | OFF | ON | Δ | Δ% | provenance OFF | provenance ON | KTC Crowd / Trades | IDPTC |")
print("|---|---:|---:|---:|---:|---|---|---|---|")
for name, a, b, d, pct in deltas:
    po, pn = ro[name]["prov"] or {}, rn[name]["prov"] or {}
    s = rn[name]["sites"]
    ktc = "/".join(
        str(int(round(s[k]))) if isinstance(s.get(k), (int, float)) else "–"
        for k in ("ktcCrowdSfTep", "ktcTradesSfTep")
    )
    idptc = s.get("idpTradeCalc")
    idptc = str(int(round(idptc))) if isinstance(idptc, (int, float)) else "–"
    off_desc = f"{cls(po)} ({ro[name]['anchor']})" if ro[name]["anchor"] else cls(po)
    on_desc = cls(pn)
    if pn.get("class") == "derived_round_step":
        on_desc += f" from {pn.get('basis')}"
    print(
        f"| {name} | {a} | {b} | {d:+d} | {pct:+.1f}% | {off_desc} | {on_desc} | {ktc} | {idptc} |"
    )
