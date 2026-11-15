#!/usr/bin/env python3
"""Read-only reconciliation of dynasty_main pick ownership against Sleeper (Batch G).

For every owned pick identity on the served draft-capital board (3 classes x
12 teams x 6 rounds = 216 for ``dynasty_main``), compare the board's owner with
Sleeper's own public data: the league's rosters and users, and
``/traded_picks``.  GET requests only; nothing is written except the optional
``--out`` report.  NEVER run in CI (it reads live third-party data); the unit
test drives it with saved copies (``--sleeper-dir``).

Run isolated, so nothing from the repository is imported::

    python3 -I scripts/reconcile_draft_capital_sleeper.py \\
        [--url https://chaseupside.com/api/draft-capital?leagueKey=dynasty_main | --payload board.json] \\
        [--sleeper-dir DIR] [--out report.json]

``--sleeper-dir`` holds ``league.json``, ``rosters.json``, ``users.json`` and
``traded_picks.json`` saved from Sleeper; without it the four are fetched.

Checks:

1. shape — Sleeper says 12 rosters (ids 1..12) and 6 rookie rounds; the board
   names three classes;
2. identities — exactly 216 unique ``assetId``s, equal to the identities this
   script folds from Sleeper (season x round x origin roster);
3. owners — every pick's ``currentOwnerRosterId`` equals this script's fold of
   ``/traded_picks`` (a traded pick's holder is Sleeper's ``owner_id``; an
   untraded pick stays with its origin roster);
4. origin — ``originRosterId`` is the identity's origin roster;
5. traded flag — ``isTraded`` is true exactly when the holder differs from
   the origin;
6. names — each pick's ``currentOwner`` / ``originalOwner`` display name is
   Sleeper's team name for that roster (team_name, else display_name);
7. ownership observed — no team publishes ``pickOwnershipState:
   "unavailable"``.

Exit codes: 0 every check PASS; 1 a check FAILED; 2 BLOCKED (the board or
Sleeper could not be read — no result is fabricated).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

LEAGUE_KEY = "dynasty_main"
SLEEPER_LEAGUE_ID = "1312006700437352448"
SLEEPER = "https://api.sleeper.app/v1"
DEFAULT_URL = "https://chaseupside.com/api/draft-capital?leagueKey=dynasty_main"
TEAMS, ROUNDS, CLASSES = 12, 6, 3

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"status": "PASS" if ok else "FAIL", "check": name, "detail": detail})
    return ok


def _get(url: str):
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "riskit-reconcile/1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — fixed hosts, GET only
        return json.loads(resp.read())


def load_sleeper(sleeper_dir: str | None) -> dict:
    names = ("league", "rosters", "users", "traded_picks")
    if sleeper_dir:
        d = Path(sleeper_dir)
        return {n: json.loads((d / f"{n}.json").read_text(encoding="utf-8")) for n in names}
    base = f"{SLEEPER}/league/{SLEEPER_LEAGUE_ID}"
    return {
        "league": _get(base),
        "rosters": _get(f"{base}/rosters"),
        "users": _get(f"{base}/users"),
        "traded_picks": _get(f"{base}/traded_picks"),
    }


def team_names(rosters, users) -> dict[int, str]:
    by_user = {}
    for u in users or []:
        meta = u.get("metadata") or {}
        by_user[str(u.get("user_id"))] = meta.get("team_name") or u.get("display_name")
    out = {}
    for r in rosters or []:
        rid = int(r["roster_id"])
        out[rid] = by_user.get(str(r.get("owner_id"))) or f"Team {rid}"
    return out


def reconcile(board: dict, sleeper: dict) -> int:
    league, rosters = sleeper["league"], sleeper["rosters"]
    rids = sorted(int(r["roster_id"]) for r in rosters)
    rounds = int(((league or {}).get("settings") or {}).get("draft_rounds") or 0)
    check(
        "Sleeper league shape 12 rosters x 6 rounds",
        rids == list(range(1, TEAMS + 1)) and rounds == ROUNDS,
        f"{len(rids)} rosters, {rounds} rounds",
    )
    classes = sorted(int(y) for y in board.get("availableYears") or [])
    check("board names three classes", len(classes) == CLASSES, str(classes))

    fold: dict[str, int] = {}
    for season in classes:
        for rnd in range(1, rounds + 1):
            for origin in rids:
                fold[f"pick:{LEAGUE_KEY}:{season}:r{rnd}:o{origin}"] = origin
    traded = sleeper["traded_picks"]
    if not check("Sleeper /traded_picks is an observation (a list)", isinstance(traded, list)):
        return 1
    for t in traded:
        aid = f"pick:{LEAGUE_KEY}:{int(t['season'])}:r{int(t['round'])}:o{int(t['roster_id'])}"
        if aid in fold:
            fold[aid] = int(t["owner_id"])

    every = list(board.get("picks") or []) + list(board.get("additionalClassPicks") or [])
    ids = [p.get("assetId") for p in every]
    dupes = [a for a, n in Counter(ids).items() if n > 1]
    check(
        "216 unique identities on the board",
        len(ids) == TEAMS * ROUNDS * CLASSES and not dupes and None not in ids,
        f"{len(ids)} rows, {len(set(ids))} unique, duplicates {dupes[:3]}",
    )
    check(
        "board identities = Sleeper fold",
        set(ids) == set(fold),
        f"missing {sorted(set(fold) - set(ids))[:3]}, extra {sorted(set(ids) - set(fold))[:3]}",
    )
    wrong_owner = [
        f"{p['assetId']}: board {p.get('currentOwnerRosterId')} vs Sleeper {fold.get(p['assetId'])}"
        for p in every
        if p.get("assetId") in fold and p.get("currentOwnerRosterId") != fold[p["assetId"]]
    ]
    check("every current owner = Sleeper fold", not wrong_owner, "; ".join(wrong_owner[:5]))
    wrong_origin = [
        p["assetId"]
        for p in every
        if p.get("assetId") and p.get("originRosterId") != int(p["assetId"].rsplit(":o", 1)[1])
    ]
    check("every origin roster = the identity's origin", not wrong_origin, str(wrong_origin[:5]))
    wrong_flag = [
        p["assetId"]
        for p in every
        if p.get("assetId") in fold
        and bool(p.get("isTraded")) != (fold[p["assetId"]] != p.get("originRosterId"))
    ]
    check("isTraded = holder differs from origin", not wrong_flag, str(wrong_flag[:5]))
    names = team_names(rosters, sleeper["users"])
    wrong_name = [
        f"{p['assetId']}: {p.get('currentOwner')!r} vs {names.get(p.get('currentOwnerRosterId'))!r}"
        for p in every
        if p.get("currentOwner") != names.get(p.get("currentOwnerRosterId"))
        or p.get("originalOwner") != names.get(p.get("originRosterId"))
    ]
    check("owner names = Sleeper team names", not wrong_name, "; ".join(wrong_name[:5]))
    unobserved = [
        t.get("team")
        for rows in (board.get("teamTotalsByYear") or {}).values()
        for t in rows
        if t.get("pickOwnershipState") == "unavailable"
    ] + [
        t.get("team")
        for t in board.get("teamTotals") or []
        if t.get("pickOwnershipState") == "unavailable"
    ]
    check("no team publishes unavailable pick ownership", not unobserved, str(unobserved[:5]))
    traded_count = sum(
        1
        for p in every
        if p.get("assetId") in fold and fold[p["assetId"]] != p.get("originRosterId")
    )
    RESULTS.append(
        {
            "status": "INFO",
            "check": "summary",
            "detail": f"classes {classes}; {len(ids)} picks; {traded_count} held by a non-origin roster",
        }
    )
    return 1 if any(r["status"] == "FAIL" for r in RESULTS) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--url", default=None, help=f"served board URL (default {DEFAULT_URL})")
    src.add_argument("--payload", help="a saved board JSON instead of fetching it")
    ap.add_argument("--sleeper-dir")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        board = (
            json.loads(Path(args.payload).read_text(encoding="utf-8"))
            if args.payload
            else _get(args.url or DEFAULT_URL)
        )
        sleeper = load_sleeper(args.sleeper_dir)
    except Exception as exc:  # noqa: BLE001 — unreachable is BLOCKED, never a result
        print(f"BLOCKED: could not read the board or Sleeper ({type(exc).__name__}: {exc})")
        return 2
    if isinstance(board, dict) and board.get("error"):
        print(f"BLOCKED: the board was refused ({board.get('error')}: {board.get('message')})")
        return 2
    code = reconcile(board, sleeper)
    print("Draft-capital ownership vs Sleeper (read-only, GET only)")
    for r in RESULTS:
        line = f"  {r['status']}  {r['check']}"
        if r["detail"] and r["status"] != "PASS":
            line += f"  [{r['detail']}]"
        print(line)
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    print(f"\n{passed} PASS, {failed} FAIL")
    if args.out:
        Path(args.out).write_text(
            json.dumps({"results": RESULTS, "pass": passed, "fail": failed}, indent=1) + "\n",
            encoding="utf-8",
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
