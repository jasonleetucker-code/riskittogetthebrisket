#!/usr/bin/env python3
"""READ-ONLY live probe of Manager Intelligence career / archetypes / compare (Batch E).

Runs ``build_manager_career`` (and, with ``--compare``, the comparison and
optionally ``--league`` the league percentile) against REAL Sleeper and prints
a short summary: chain coverage per league, every season row, the totals with
the seasons each covers, and the archetypes with their evidence.  Not a test
and never run in CI — the deterministic, fixture-based tests are
``tests/intel/test_manager_career.py``.  The workstream requires one such probe
per batch, recorded in the PR.

It only issues GETs against Sleeper's public API.  Values (portfolio summary,
pick values) are priced from a local contract export when one is passed
(``--contract``); archetypes do not depend on values.

    python scripts/probe_manager_career.py jnesselhauf
    python scripts/probe_manager_career.py jnesselhauf --compare Aguilar315
    python scripts/probe_manager_career.py jnesselhauf --league 1180290534131900416
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.intel import (  # noqa: E402
    manager_activity,
    manager_career,
    manager_compare,
    manager_league,
    manager_portfolio,
)

sys.path.insert(0, str(ROOT / "scripts"))
from probe_manager_activity import _load_contract  # noqa: E402


def _cov_text(n: dict) -> str:
    return f"{n.get('count')} of {n.get('seasonsCovered')}"


def _print_career(out: dict) -> None:
    if out.get("status") not in ("ok", "partial"):
        print(f"status: {out.get('status')}")
        return
    m = out["manager"]
    cov = out["coverage"]
    print(f"== {m['displayName']} (@{m['username']}) — career, scope {out['scope']}")
    print(
        f"status {out['status']} · leagues {cov['leaguesInScope']} · calls "
        f"{cov['callsSpent']}/{cov['callBudget']} · budgetExhausted {cov['budgetExhausted']} · "
        f"chains incomplete {len(cov['chainsIncomplete'])} truncated {len(cov['chainsTruncated'])}"
    )
    for lg in out["leagues"]:
        ch = lg["chain"]
        print(
            f"  league {lg['name']!r}: walked {lg['seasonsWalked']} "
            f"chain={ch['state']}{'/' + ch['reason'] if ch.get('reason') else ''} "
            f"held {lg['seasonsHeld']} · not held {lg['notHeldSeasons']}"
        )
    print("  seasons:")
    for s in out["seasons"]:
        rec = s.get("record") or {}
        print(
            f"    {s.get('season')} {str(s.get('leagueName'))[:30]:30} "
            f"held={s.get('held')}{' co' if s.get('coOwned') else ''} "
            f"{rec.get('wins')}-{rec.get('losses')}-{rec.get('ties')} "
            f"PF {rec.get('pointsFor')} share {s.get('pointsForShare')} "
            f"finish={s.get('finish')}{'/' + s['finishReason'] if s.get('finishReason') else ''} "
            f"counts={s.get('countsTowardTotals')} cov={s.get('coverageState')}"
        )
    t = out["totals"]
    print(
        f"  totals: seasons {t['seasons']} (counted {t['countedSeasons']}, years "
        f"{t['distinctYears']}, leagues {t['leagues']}) · titles {_cov_text(t['titles'])} · "
        f"runner-up {_cov_text(t['runnerUps'])} · playoffs {_cov_text(t['playoffAppearances'])} · "
        f"record {t['record']['wins']}-{t['record']['losses']}-{t['record']['ties']} "
        f"win% {t['record']['winPct']} over {t['record']['seasonsCovered']} · "
        f"PF index {t['pointsForIndex']['mean']} over {t['pointsForIndex']['seasonsCovered']} · "
        f"excluded {t['excluded']} · unknown finishes {t['unknownFinishes']}"
    )
    arch = out.get("archetypes") or {}
    print(f"  archetypes (sources {arch.get('sources')}): suggested {arch.get('suggested')}")
    for item in arch.get("items") or []:
        print(f"    [{item['state']}] {item['label']}: {item['statement']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--compare", default=None, help="second username")
    parser.add_argument("--league", default=None, help="league id for the percentile view")
    parser.add_argument("--scope", default="dynasty", choices=manager_portfolio.SCOPES)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--json", action="store_true", help="dump the whole payload")
    args = parser.parse_args()
    contract = _load_contract(args.contract)

    def career(username: str, **kw):
        return manager_career.build_manager_career(
            username,
            contract=contract,
            scope=args.scope,
            profile_provider=manager_portfolio.build_manager_profile,
            activity_provider=manager_activity.build_manager_activity,
            **kw,
        )

    if args.compare:
        out = manager_compare.build_manager_comparison(
            args.username,
            args.compare,
            contract=contract,
            scope=args.scope,
            profile_provider=manager_portfolio.build_manager_profile,
            activity_provider=manager_activity.build_manager_activity,
            career_provider=lambda u, **kw: manager_career.build_manager_career(u, **kw),
        )
        if args.json:
            print(json.dumps(out, indent=2, default=str))
            return 0
        print(f"== compare {args.username} vs {args.compare}: status {out.get('status')}")
        if out.get("status") in ("ok", "partial"):
            print(f"   same manager {out['sameManager']} · shared leagues {out['sharedLeagueIds']}")
            for name in ("a", "b"):
                side = out[name]
                t = side.get("career") or {}
                td = side.get("tendencies") or {}
                dc = side.get("draftCapital") or {}
                pf = side.get("portfolio") or {}
                print(
                    f"   [{name}] {side['manager']['username']}: sources {side['sources']} · "
                    f"leagues {side['leagueCount']} · seasons {t.get('seasons')} titles "
                    f"{(t.get('titles') or {}).get('count')} playoffs "
                    f"{(t.get('playoffAppearances') or {}).get('count')}/"
                    f"{(t.get('playoffAppearances') or {}).get('seasonsCovered')} win% "
                    f"{(t.get('record') or {}).get('winPct')} · trades {td.get('tradeCount')} · "
                    f"picks held {dc.get('picksHeld')} · players {pf.get('uniquePlayers')} "
                    f"age {pf.get('ageMean')} · archetypes "
                    f"{(side.get('archetypes') or {}).get('suggested')}"
                )
    else:
        out = career(args.username)
        if args.json:
            print(json.dumps(out, indent=2, default=str))
            return 0
        _print_career(out)

    if args.league:
        pct = manager_compare.build_league_percentile(
            args.username,
            args.league,
            contract=contract,
            window="season",
            league_provider=manager_league.build_league_scouting,
        )
        print(f"== league percentile: status {pct.get('status')}")
        if pct.get("status") in ("ok", "partial"):
            print(
                f"   {pct['league'].get('name')!r} · in league {pct['managerInLeague']} · "
                f"teams {pct['teamCount']}"
            )
            for m in pct["metrics"]:
                print(
                    f"   {m['label']:32} value {m['value']} median {m['leagueMedian']} "
                    f"pct {m['percentile']} (of {m['teamsWithValue']}) "
                    f"{m['reason'] or ''}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
