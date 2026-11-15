#!/usr/bin/env python3
"""READ-ONLY live probe of Manager Intelligence league scouting (Batch C).

Runs ``build_league_scouting`` against REAL Sleeper for one league id and
prints a short summary: coverage, call budget, and one line per team (value
rank, priced roster total + unpriced count, picks, activity counts,
tendencies source).  Not a test and never run in CI — the deterministic,
fixture-based tests are ``tests/intel/test_manager_league.py``.  The
workstream requires one such probe per batch, recorded in the PR.

It only issues GETs against Sleeper's public API.  Values are priced from a
local contract export when one is passed (``--contract``); otherwise every
value is ``None`` (``board_unavailable``).  For one of OUR registry leagues
the Manager Scout profile is attached from this host's local stores; where
those stores do not exist the scout block says so.

    python scripts/probe_manager_league.py 1312006700437352448 --window 90d
    python scripts/probe_manager_league.py --find "Championship Alleys" --user jnesselhauf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.intel import manager_activity, manager_league  # noqa: E402
from src.public_league import sleeper_client  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from probe_manager_activity import _load_contract  # noqa: E402


def _find_league(username: str, name: str) -> str | None:
    """A league id by name from one user's current-season leagues (read-only)."""
    kind, user = sleeper_client.fetch_user_classified(username)
    if kind != sleeper_client.FETCH_OK:
        print(f"user lookup: {kind}", file=sys.stderr)
        return None
    state = sleeper_client.fetch_nfl_state() or {}
    season = str(state.get("league_season") or state.get("season") or "")
    kind, leagues = sleeper_client.fetch_user_leagues_classified(user["user_id"], season)
    if kind != sleeper_client.FETCH_OK:
        print(f"leagues lookup: {kind}", file=sys.stderr)
        return None
    want = name.strip().lower()
    names = [(str(lg.get("name") or "").strip().lower(), lg) for lg in leagues or []]
    exact = [lg for n, lg in names if n == want]
    partial = [lg for n, lg in names if want in n]
    hit = exact or (partial if len(partial) == 1 else [])
    if hit:
        return str(hit[0]["league_id"])
    print(f"no single league matching {name!r} for {username}", file=sys.stderr)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("league_id", nargs="?")
    parser.add_argument("--find", default=None, help="league name to look up via --user")
    parser.add_argument("--user", default=None)
    parser.add_argument("--window", default="30d", choices=sorted(manager_activity.WINDOWS))
    parser.add_argument("--contract", default=None)
    parser.add_argument("--json", action="store_true", help="dump the whole payload")
    args = parser.parse_args()

    league_id = args.league_id
    if not league_id and args.find and args.user:
        league_id = _find_league(args.user, args.find)
    if not league_id:
        parser.error("pass a league id, or --find NAME --user USERNAME")

    out = manager_league.build_league_scouting(
        league_id, contract=_load_contract(args.contract), window=args.window
    )
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    print(f"status={out.get('status')} query={out.get('query')}")
    if out.get("status") not in ("ok", "partial"):
        return 1
    lg = out["league"]
    cov = out["coverage"]
    fmt = lg.get("format") or {}
    print(
        f"league={lg['name']!r} season={lg['season']} scope={lg['scope']} "
        f"superflex={fmt.get('superflex')} idp={fmt.get('idp')} teams={out['managerCount']} "
        f"registry={lg['registryKey']} window={out['windowApplied']} hasBoard={out['hasBoard']}"
    )
    print(
        f"coverage rosters={cov['rosters']} tx={cov['transactions']} drafts={cov['drafts']} "
        f"tradedPicks={cov['tradedPicks']} users={cov['leagueUsers']} "
        f"weeks ok/failed={cov['weeksFetched']}/{cov['weeksFailed']} legs={cov['legsRequested']}"
    )
    print(
        f"calls={cov['callsSpent']}/{cov['callBudget']} budgetExhausted={cov['budgetExhausted']} "
        f"ranking={ {k: v for k, v in out['ranking'].items() if k in ('rankedRosters', 'withheld')} }"
    )
    scout = out.get("scout")
    if scout is not None:
        print(
            f"scout state={scout.get('state')} reason={scout.get('reason')} "
            f"formerMembersWithHistory={scout.get('formerMembersWithHistory')}"
        )
    for m in out["managers"]:
        r = m["roster"]
        dc = m["draftCapital"]
        picks = (
            "unknown"
            if dc.get("picks") is None and dc.get("available", True)
            else ("earlier-season" if dc.get("available") is False else len(dc["picks"]))
        )
        act = m["activity"]
        tend = m.get("tendencies") or {}
        tsum = (
            f"scout={'yes' if m.get('scout') else 'none'}"
            if m["tendenciesSource"] == "manager_scout"
            else f"trades n={tend.get('tradeCount')} "
            f"sufficient={tend.get('pickPlayer', {}).get('sufficientSample')}"
        )
        print(
            f"  #{m['valueRank'] if m['valueRank'] is not None else '-':<2} "
            f"{(m['displayName'] or ('(open roster)' if m['orphan'] else '?'))!s:22.22} "
            f"players={r['playerCount']} st/bn/taxi/ir={r['starters']}/{r['bench']}/{r['taxi']}/{r['reserve']} "
            f"value={r['pricedValue']} unpriced={r['unpricedCount']} picks={picks} "
            f"pickValue={dc.get('pricedValue')} trades={act['trades']} adds={act['playersAdded']} "
            f"drops={act['playersDropped']} uncertain={act['uncertainAttribution']} {tsum}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
