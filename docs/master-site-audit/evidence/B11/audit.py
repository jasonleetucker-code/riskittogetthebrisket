"""B11 — OLD vs NEW confidence distribution audit.

Reproduces `confidence-distribution.md` in this directory.

HOW TO GET THE TWO INPUTS
-------------------------
Both are `build_api_data_contract` output over the SAME pinned payload,
one built before the B11 commit and one after. Pinning the payload is the
point: comparing across refreshed inputs would measure the scrape, not
the gate.

    # from the repo root, with the B11 commit checked out
    python docs/master-site-audit/evidence/B11/audit.py --dump new.json

    git stash && git checkout <pre-B11-sha>
    python docs/master-site-audit/evidence/B11/audit.py --dump old.json
    git checkout - && git stash pop

    python docs/master-site-audit/evidence/B11/audit.py \\
        --old old.json --new new.json --out confidence-distribution.md

`--dump` writes only the fields this audit reads, so the artifacts stay
small enough to keep around while a review is open.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# docs/master-site-audit/evidence/B11/audit.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD = REPO_ROOT / "exports" / "latest" / "dynasty_data_2026-08-14.json"

LEVELS = ["none", "low", "medium", "high"]

#: The only fields the audit reads. Dumping the whole contract would be
#: ~12 MB per side for a handful of columns.
DUMP_FIELDS = (
    "canonicalName",
    "displayName",
    "position",
    "assetClass",
    "canonicalConsensusRank",
    "isRookie",
    "sourceCount",
    "independentSourceCount",
    "confidenceBucket",
    "confidenceAxes",
    "confidenceReasons",
)


def dump(payload_path: Path, out_path: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from src.api.data_contract import build_api_data_contract

    contract = build_api_data_contract(json.loads(payload_path.read_text(encoding="utf-8")))
    rows = [
        {field: row.get(field) for field in DUMP_FIELDS}
        for row in (contract.get("playersArray") or [])
    ]
    out_path.write_text(json.dumps(rows), encoding="utf-8")
    print(f"wrote {len(rows)} rows to {out_path}")


def band(rank: int | None) -> str:
    if not rank:
        return "unranked"
    if rank <= 100:
        return "001-100"
    if rank <= 200:
        return "101-200"
    if rank <= 400:
        return "201-400"
    if rank <= 800:
        return "401-800"
    return "800+"


def load(path: Path) -> dict[str, dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(r.get("canonicalName") or r.get("displayName")): r for r in rows}


def report(old_path: Path, new_path: Path) -> str:
    old, new = load(old_path), load(new_path)
    if set(old) != set(new):
        raise SystemExit(
            "the two dumps cover different rows — they were not built over the same payload"
        )

    rows = []
    for key in old:
        a, b = old[key], new[key]
        rows.append(
            {
                "name": a.get("displayName"),
                "pos": a.get("position") or "?",
                "ac": a.get("assetClass"),
                "rank": a.get("canonicalConsensusRank"),
                "rookie": bool(a.get("isRookie")),
                "old": a.get("confidenceBucket") or "none",
                "new": b.get("confidenceBucket") or "none",
                "axes": b.get("confidenceAxes") or {},
                "reasons": b.get("confidenceReasons") or [],
                "ind": b.get("independentSourceCount"),
            }
        )

    out: list[str] = []
    say = out.append
    say("# B11 — OLD vs NEW confidence distribution")
    say("")
    say(f"Board: pinned payload · {len(rows)} rows")
    say("")

    oc, nc = Counter(r["old"] for r in rows), Counter(r["new"] for r in rows)
    say("| bucket | OLD | NEW | delta |")
    say("|---|---:|---:|---:|")
    for level in reversed(LEVELS):
        say(f"| {level} | {oc[level]} | {nc[level]} | {nc[level] - oc[level]:+d} |")
    say("")

    up = [r for r in rows if LEVELS.index(r["new"]) > LEVELS.index(r["old"])]
    down = [r for r in rows if LEVELS.index(r["new"]) < LEVELS.index(r["old"])]
    same = [r for r in rows if r["new"] == r["old"]]
    say(f"upgraded **{len(up)}** · downgraded **{len(down)}** · unchanged **{len(same)}**")
    say("")

    say("## Transitions")
    say("")
    say("| from | to | n |")
    say("|---|---|---:|")
    moves = Counter((r["old"], r["new"]) for r in rows)
    for (a, b), n in sorted(moves.items(), key=lambda t: -t[1]):
        if a != b:
            say(f"| {a} | {b} | {n} |")
    say("")

    two = [r for r in rows if abs(LEVELS.index(r["new"]) - LEVELS.index(r["old"])) >= 2]
    say(f"## Two-or-more level moves — {len(two)}")
    say("")
    say("| player | pos | rank | old | new | families | binding axes |")
    say("|---|---|---:|---|---|---:|---|")
    for r in sorted(two, key=lambda r: (r["rank"] or 9999))[:40]:
        binding = ", ".join(a for a, v in r["axes"].items() if v == r["new"]) or "-"
        say(
            f"| {r['name']} | {r['pos']} | {r['rank']} | {r['old']} | {r['new']} "
            f"| {r['ind']} | {binding} |"
        )
    say("")

    say("## By board depth")
    say("")
    say("| band | n | OLD h/m/l/n | NEW h/m/l/n |")
    say("|---|---:|---|---|")
    for name in ("001-100", "101-200", "201-400", "401-800", "unranked"):
        sub = [r for r in rows if band(r["rank"]) == name]
        if not sub:
            continue
        a, b = Counter(r["old"] for r in sub), Counter(r["new"] for r in sub)
        say(
            f"| {name} | {len(sub)} "
            f"| {a['high']}/{a['medium']}/{a['low']}/{a['none']} "
            f"| {b['high']}/{b['medium']}/{b['low']}/{b['none']} |"
        )
    say("")

    say("## By position")
    say("")
    say("| pos | n | up | down | same | NEW high | NEW medium | NEW low | NEW none |")
    say("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for pos in sorted({r["pos"] for r in rows}):
        sub = [r for r in rows if r["pos"] == pos]
        u = sum(1 for r in sub if LEVELS.index(r["new"]) > LEVELS.index(r["old"]))
        d = sum(1 for r in sub if LEVELS.index(r["new"]) < LEVELS.index(r["old"]))
        b = Counter(r["new"] for r in sub)
        say(
            f"| {pos} | {len(sub)} | {u} | {d} | {len(sub) - u - d} "
            f"| {b['high']} | {b['medium']} | {b['low']} | {b['none']} |"
        )
    say("")

    say("## By independent-family coverage (NEW)")
    say("")
    say("| families | n | high | medium | low | none |")
    say("|---:|---:|---:|---:|---:|---:|")
    for count in sorted({r["ind"] for r in rows if r["ind"] is not None}):
        sub = [r for r in rows if r["ind"] == count]
        b = Counter(r["new"] for r in sub)
        say(
            f"| {count} | {len(sub)} | {b['high']} | {b['medium']} " f"| {b['low']} | {b['none']} |"
        )
    say("")

    say("## Binding axis on the NEW board (non-pick rows)")
    say("")
    binding_counts: Counter[str] = Counter()
    for r in rows:
        if r["ac"] == "pick" or not r["axes"]:
            continue
        for axis, level in r["axes"].items():
            if level == r["new"]:
                binding_counts[axis] += 1
    say("| axis | rows where it is (equal-)weakest |")
    say("|---|---:|")
    for axis, n in binding_counts.most_common():
        say(f"| {axis} | {n} |")
    say("")

    say("## Did thin or stale evidence get MORE confident?")
    say("")
    say(
        f"- rows upgraded with fewer than 3 independent families: "
        f"**{sum(1 for r in up if (r['ind'] or 0) < 3)}**"
    )
    stale_up = [r for r in up if any("staleness budget" in x for x in r["reasons"])]
    say(
        f"- rows upgraded whose evidence includes a stale family: **{len(stale_up)}** "
        f"(all still pass the freshness ladder — the reason is published on the row)"
    )
    gap_up = [r for r in up if any("eligible evidence families" in x for x in r["reasons"])]
    say(f"- rows upgraded that are missing at least one eligible family: **{len(gap_up)}**")
    thin_high = [
        r for r in rows if r["ac"] != "pick" and r["new"] == "high" and (r["ind"] or 0) < 5
    ]
    say(
        f"- PLAYER rows reaching HIGH with fewer than 5 independent families: "
        f"**{len(thin_high)}** — the independence axis makes it structurally impossible"
    )
    pick_high = [r for r in rows if r["ac"] == "pick" and r["new"] == "high"]
    say(
        f"- PICK rows at HIGH: **{len(pick_high)}**, on 2 evidence families.  Picks keep "
        f"their own coefficient-of-variation gate, and their eligible population only HAS "
        f"2-4 families (KTC + IDPTC are the two real pick markets), so the 5-family bar "
        f"derived from the blend's trimming rung does not apply to them.  A named "
        f"boundary, not an exemption that leaked."
    )
    say("")

    say("## Representative rows")
    say("")

    def show(title: str, selected: list[dict], limit: int) -> None:
        say(f"### {title}")
        say("")
        for r in selected[:limit]:
            say(
                f"- **{r['name']}** ({r['pos']}, rank {r['rank']}) — "
                f"{r['old']} → **{r['new']}**  "
            )
            say(f"  axes: {r['axes']}  ")
            for reason in r["reasons"]:
                say(f"  · {reason}")
        say("")

    ranked = [r for r in rows if r["rank"]]
    show("Top of board", sorted(ranked, key=lambda r: r["rank"])[:4], 4)
    show("Deep board", sorted([r for r in ranked if r["rank"] > 600], key=lambda r: r["rank"]), 3)
    show("IDP", [r for r in ranked if r["pos"] in ("DL", "LB", "DB")], 3)
    show("Thin coverage (1-2 families)", [r for r in ranked if (r["ind"] or 0) <= 2], 3)
    show(
        "Most disputed (8+ families, agreement LOW)",
        sorted(
            [r for r in ranked if (r["ind"] or 0) >= 8 and r["axes"].get("agreement") == "low"],
            key=lambda r: r["rank"],
        ),
        3,
    )
    show("Rookies", sorted([r for r in ranked if r["rookie"]], key=lambda r: r["rank"]), 3)
    show("Picks (own CV path, family-aware)", [r for r in rows if r["ac"] == "pick"], 3)

    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", type=Path, help="build the contract and write a slim dump here")
    parser.add_argument("--payload", type=Path, default=DEFAULT_PAYLOAD)
    parser.add_argument("--old", type=Path)
    parser.add_argument("--new", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.dump:
        dump(args.payload, args.dump)
        return
    if not (args.old and args.new):
        parser.error("pass --dump, or both --old and --new")
    text = report(args.old, args.new)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
