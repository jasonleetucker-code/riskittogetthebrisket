"""Full diff of public sections with and without the retired-owner filter."""

import json
import sys

sys.path.insert(0, "/home/user/riskittogetthebrisket")

from src.public_league import history, identity, luck, power, records, streaks  # noqa: E402
from src.public_league.snapshot import build_public_snapshot  # noqa: E402

LEAGUE = "1312006700437352448"
OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/retired-owner-diff-full.json"


def build(snap):
    rec = records.build_section(snap)
    hist = history.build_section(snap)
    return {
        "records": rec,
        "historyStandingsRowsBySeason": {s["season"]: len(s["standings"]) for s in hist["seasons"]},
        "hallOfFameRows": len(hist["hallOfFame"]),
        "luckCareerRows": len(luck.build_section(snap)["byOwnerCareer"]),
        "powerCurrentRanking": len(power.build_section(snap)["currentRanking"]),
        "streaksCurrentByOwner": len(streaks.build_section(snap)["currentStreaksByOwner"]),
    }


def main():
    snap = build_public_snapshot(LEAGUE, max_seasons=3)
    shipped = build(snap)
    identity._RETIRED_OWNER_IDS = frozenset()
    full = build(build_public_snapshot(LEAGUE, max_seasons=3))

    cats = [
        "singleWeekHighest",
        "singleWeekLowest",
        "biggestMargin",
        "narrowestVictory",
        "mostPointsInLoss",
        "fewestPointsInWin",
        "mostPointsInSeason",
        "mostPointsAgainstInSeason",
        "longestWinStreaks",
        "longestLossStreaks",
    ]
    diff = {}
    for c in cats:
        a = [
            str(r.get("displayName"))
            + "|"
            + str(r.get("points") or r.get("length") or r.get("totalPoints"))
            for r in shipped["records"][c]
        ]
        b = [
            str(r.get("displayName"))
            + "|"
            + str(r.get("points") or r.get("length") or r.get("totalPoints"))
            for r in full["records"][c]
        ]
        diff[c] = {"shipped": a, "full": b, "changed": a != b}
    out = {
        "recordCategoryDiff": diff,
        "changedCategories": [c for c, v in diff.items() if v["changed"]],
        "historyStandingsRowsShipped": shipped["historyStandingsRowsBySeason"],
        "historyStandingsRowsFull": full["historyStandingsRowsBySeason"],
        "hallOfFame": [shipped["hallOfFameRows"], full["hallOfFameRows"]],
        "luckCareerRows": [shipped["luckCareerRows"], full["luckCareerRows"]],
        "powerCurrentRanking": [shipped["powerCurrentRanking"], full["powerCurrentRanking"]],
        "streaksCurrentByOwner": [shipped["streaksCurrentByOwner"], full["streaksCurrentByOwner"]],
    }
    print(json.dumps({k: v for k, v in out.items() if k != "recordCategoryDiff"}, indent=1))
    for c in out["changedCategories"]:
        print(f"\n-- {c}\n  shipped: {diff[c]['shipped']}\n  full   : {diff[c]['full']}")
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1)


main()
