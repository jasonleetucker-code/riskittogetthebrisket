"""Regenerate W19 numeric evidence: erased franchises, streaks, trade-grade zeros."""

import collections
import json
import sys
import urllib.request

sys.path.insert(0, "/home/user/riskittogetthebrisket")

OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/numeric-proof.json"
LEAGUE_2024 = "1090320428817592320"
RETIRED_RIDS = {9, 10}
PUB = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/public-league-full.json"
PRIV = "/tmp/w19_contract_full.json"


def sleeper(path):
    return json.loads(
        urllib.request.urlopen(f"https://api.sleeper.app/v1{path}", timeout=25).read()
    )


def main():
    pub = json.load(open(PUB))
    out = {}

    rosters = sleeper(f"/league/{LEAGUE_2024}/rosters")
    out["sleeper2024RosterCount"] = len(rosters)
    hist24 = [s for s in pub["sections"]["history"]["seasons"] if s["season"] == "2024"][0]
    out["publicHistory2024"] = {
        "numTeams": hist24["numTeams"],
        "standingsRows": len(hist24["standings"]),
    }

    results = collections.defaultdict(list)
    for wk in range(1, 18):
        for entry in sleeper(f"/league/{LEAGUE_2024}/matchups/{wk}"):
            if entry.get("points") is None:
                continue
            results[entry["matchup_id"]].append((wk, entry))
    seq = collections.defaultdict(list)
    for pairs in results.values():
        by_week = collections.defaultdict(list)
        for wk, entry in pairs:
            by_week[wk].append(entry)
        for wk, two in by_week.items():
            if len(two) != 2:
                continue
            a, b = two
            pa, pb = float(a["points"]), float(b["points"])
            if pa <= 0 and pb <= 0:
                continue
            seq[a["roster_id"]].append((wk, "W" if pa > pb else ("T" if pa == pb else "L")))
            seq[b["roster_id"]].append((wk, "W" if pb > pa else ("T" if pb == pa else "L")))

    def longest(rows, ch):
        best = cur = 0
        for _, res in sorted(rows):
            cur = cur + 1 if res == ch else 0
            best = max(best, cur)
        return best

    out["streaks2024ByRoster"] = {
        str(rid): {
            "longestWin": longest(rows, "W"),
            "longestLoss": longest(rows, "L"),
            "retiredOwner": rid in RETIRED_RIDS,
        }
        for rid, rows in sorted(seq.items())
    }
    out["publishedLongestLossStreak"] = pub["sections"]["records"]["longestLossStreaks"][0]
    out["publishedLongestWinStreaks"] = [
        (r["displayName"], r["length"]) for r in pub["sections"]["records"]["longestWinStreaks"][:3]
    ]

    from src.api.public_activity_valuation import build_valuation_from_contract

    val = build_valuation_from_contract(json.load(open(PRIV)))
    zero_kind = collections.Counter()
    total_kind = collections.Counter()
    zero_pick_labels = collections.Counter()
    sides_with_zero = trades_with_zero = total_sides = 0
    for tx in pub["sections"]["activity"]["feed"]:
        hit_tx = False
        for side in tx["sides"]:
            total_sides += 1
            hit_side = False
            for key in ("receivedAssets", "sentAssets"):
                for asset in side.get(key) or []:
                    total_kind[asset["kind"]] += 1
                    if (val(asset) or 0.0) <= 0:
                        zero_kind[asset["kind"]] += 1
                        hit_side = hit_tx = True
                        if asset["kind"] == "pick":
                            zero_pick_labels[f"{asset.get('season')} R{asset.get('round')}"] += 1
            sides_with_zero += 1 if hit_side else 0
        trades_with_zero += 1 if hit_tx else 0
    out["tradeGradeZeroPricedAssets"] = {
        "totalByKind": dict(total_kind),
        "zeroByKind": dict(zero_kind),
        "zeroPickLabels": dict(sorted(zero_pick_labels.items())),
        "tradesAffected": trades_with_zero,
        "tradesTotal": len(pub["sections"]["activity"]["feed"]),
        "sidesAffected": sides_with_zero,
        "sidesTotal": total_sides,
    }

    out["awards2026"] = [
        {"key": a["key"], "displayName": a["displayName"], "value": a["value"]}
        for a in [s for s in pub["sections"]["awards"]["bySeason"] if s["season"] == "2026"][0][
            "awards"
        ]
        if a["key"] in {"points_king", "regular_season_crown", "league_mvp"}
    ]
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)
    print(json.dumps(out, indent=1)[:2200])


main()
