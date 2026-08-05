"""W28 — independent recomputation of the Team Assignment section.

Re-derives every (manager -> NFL team) score straight from the Sleeper
snapshot + ``config/team_assignment.json`` and diffs the result against
the live ``/api/public/league/teamAssignment`` payload.  Exits non-zero
on any mismatch.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[4]
EV = REPO / "docs/master-site-audit/evidence/W28"

PLAYERS = json.loads((REPO / "data/public_league/nfl_players.json").read_text())
SNAP = json.loads((REPO / "data/public_league/snapshot.json").read_text())
CFG = json.loads((REPO / "config/team_assignment.json").read_text())

W = CFG["weights"]
THRESHOLD = CFG["thresholds"]["assignmentMinPoints"]
MAX_TEAMS = CFG["limits"]["maxTeamsPerOwner"]
FAVORITES = {k: v for k, v in CFG["favorites"].items() if k != "_doc"}
ALIASES = {k.lower(): v.lower() for k, v in CFG["displayNameAliases"].items() if k != "_doc"}

SKILL = {"RB", "WR", "TE"}
IDP = {"DL", "DE", "DT", "LB", "DB", "CB", "S"}


def score(meta: dict) -> int:
    pos = (meta.get("position") or "").upper()
    if not pos:
        return 0
    raw = meta.get("depth_chart_order")
    try:
        depth = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        depth = None
    pts = 0
    if pos == "QB" and depth == 1:
        pts += W["qbAnchor"]
    if pos in SKILL and depth is not None:
        if depth == 1:
            pts += W["skillStarter"]
        elif depth in (2, 3):
            pts += W["skillCommittee"]
    if int(meta.get("years_exp") or 0) == 0:
        rd = meta.get("draft_round")
        try:
            rd = int(rd) if rd is not None else None
        except (TypeError, ValueError):
            rd = None
        if rd == 1:
            pts += W["rookieRound1"]
        elif rd == 2:
            pts += W["rookieRound2"]
    if pos in IDP and depth == 1:
        pts += W["idpStarter"]
    return pts


def main() -> int:
    season = next(s for s in SNAP["seasons"] if str(s.get("season")) == "2026")
    managers = SNAP["managers"]["byOwnerId"]
    mine: dict[str, list] = {}
    for roster in season["rosters"]:
        owner = str(roster.get("owner_id") or "")
        if not owner:
            continue
        name = (managers.get(owner, {}).get("displayName") or "").strip()
        key = name.lower() if name.lower() in FAVORITES else ALIASES.get(name.lower())
        totals: collections.Counter = collections.Counter()
        for pid in roster.get("players") or []:
            meta = PLAYERS.get(str(pid))
            if not isinstance(meta, dict):
                continue
            team = (meta.get("team") or "").upper()
            pts = score(meta)
            if team and pts > 0:
                totals[team] += pts
        fav = FAVORITES.get(key, {}).get("abbr") if key else None
        out = [(fav, totals.get(fav, 0), True)] if fav else []
        rest = sorted(
            ((a, v) for a, v in totals.items() if a != fav and v >= THRESHOLD),
            key=lambda x: (-x[1], x[0]),
        )
        out += [(a, v, False) for a, v in rest[: max(0, MAX_TEAMS - len(out))]]
        mine[name] = out

    live = json.loads((EV / "team-assignment-live.json").read_text())["data"]["assignments"]
    bad = 0
    for entry in live:
        theirs = [(t["abbr"], t["score"], t["isFavorite"]) for t in entry["nflTeams"]]
        if mine.get(entry["displayName"]) != theirs:
            bad += 1
            print(
                f"MISMATCH {entry['displayName']}: live={theirs} mine={mine.get(entry['displayName'])}"
            )
    print(f"managers compared: {len(live)}  mismatches: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
