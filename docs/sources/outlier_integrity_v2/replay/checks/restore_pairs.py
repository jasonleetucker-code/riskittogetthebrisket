"""Directive §6 on every V / I board: incumbent drops a DLF restoration causes, and V2's fate for each.

Usage: python restore_pairs.py data/oiv2_replay/stage4 OUT.json   (records of scripts/oiv2_replay.py run)
"""

import json
import gzip
import glob
import collections
import sys


def nv(e):
    return (
        dict(e.get("nv") or {})
        if "obs" not in e
        else {k: v[2] for k, v in e["obs"].items() if v[2] != "voting"}
    )


out = {"boards": [], "totals": collections.Counter()}
for f in sorted(glob.glob(sys.argv[1] + "/dynasty_export_*.json.gz")):
    r = json.load(gzip.open(f))
    B = r["builds"]
    inc = B["inc"]["rows"]
    res = {"archive": r["board"]["archive"]}
    for tag, (bcfg, ccfg, ac, own) in {
        "dlfIdp": ("B", "C", "idp", ("dlfIdp", "dlfRookieIdp")),
        "d4": ("Bp", "Cp", "offense", ("dlfValuesSfTep",)),
        "both": ("Bpp", "Cpp", None, ("dlfIdp", "dlfRookieIdp", "dlfValuesSfTep")),
    }.items():
        pairs = []
        kept = 0
        lost = []
        for name, e in B[bcfg]["rows"].items():
            a = inc.get(name)
            if a is None:
                continue
            if ac and a.get("ac") != ac:
                continue
            if a.get("ac") == "pick":
                continue
            newly = set(e.get("dr") or []) - set(a.get("dr") or []) - set(own)
            for s in newly:
                pairs.append((name, s))
                c = B[ccfg]["rows"].get(name) or {}
                st = nv(c).get(s, "voting")
                if st in ("voting",):
                    kept += 1
                else:
                    lost.append((name, s, st))
        res[tag] = {
            "newlyDroppedByIncumbent": len(pairs),
            "retainedByV2": kept,
            "notRetained": lost[:20],
        }
        out["totals"][tag + "_pairs"] += len(pairs)
        out["totals"][tag + "_kept"] += kept
    out["boards"].append(res)
out["totals"] = dict(out["totals"])
json.dump(out, open(sys.argv[2], "w"), indent=1)
print(out["totals"])
print(
    [
        (
            b["archive"][16:31],
            b["dlfIdp"]["newlyDroppedByIncumbent"],
            b["dlfIdp"]["retainedByV2"],
            b["d4"]["newlyDroppedByIncumbent"],
            b["d4"]["retainedByV2"],
        )
        for b in out["boards"]
    ][-8:]
)
nr = [
    (b["archive"][16:31], x)
    for b in out["boards"]
    for t in ("dlfIdp", "d4", "both")
    for x in b[t]["notRetained"]
]
print(len(nr), nr[:15])
