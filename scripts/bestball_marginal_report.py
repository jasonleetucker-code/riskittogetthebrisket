#!/usr/bin/env python3
"""Offline report: marginal best-ball utility per player on a fixture roster.

Runs :func:`src.bestball.marginal.marginal_bestball_utility_for_roster` over
one team of the SYNTHETIC dynasty_main-shaped league
(``tests/fixtures/bestball/synthetic_league.py``) and prints, per player:
the marginal (``deltaPpg``), its Monte-Carlo standard error, whether that
estimate is precise relative to the materiality band, the replacement chosen,
how many rosters were simulated (1 before + K candidate afters) and the
wall-clock cost.  The point is the COST MEASUREMENT with candidates included,
so a later precompute can be sized from evidence rather than a guess.

Offline only: no network, no live board, no league resolution, nothing served.
The numbers are synthetic and describe the method's cost and behaviour, not
any real roster.

Before-side reuse: ``evaluate_trade_utility``'s content-addressed before-roster
cache (``cache_scope``, landed with release train 12) is used by default, so
the before roster is simulated once per team.  ``--no-reuse`` measures the
cost without it.  The report states which mode ran and the measured
computed / reused counts.

Exit codes: 0 report printed; 2 bad arguments.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.bestball import marginal as marginal_mod  # noqa: E402
from src.bestball.params import load_marginal_params, with_overrides  # noqa: E402
from src.bestball.replacement import waiver_candidates  # noqa: E402
from src.league_intel.sim_calibration import PointsModel  # noqa: E402
from src.roster_intel import best_ball_utility as bbu  # noqa: E402
from tests.fixtures.bestball.synthetic_league import (  # noqa: E402
    SEASON,
    build_league,
    ppg_lookup_for,
    roster_for,
    rostered_ids,
)


def _reuse_supported() -> bool:
    params = inspect.signature(bbu.evaluate_trade_utility).parameters
    return "cache_scope" in params and hasattr(bbu, "clear_before_side_cache")


def build_report(
    *,
    team_index: int = 0,
    draws: int | None = None,
    max_players: int | None = None,
    candidates: int | None = None,
    reuse: bool = True,
) -> dict:
    params = load_marginal_params()
    overrides = {}
    if draws is not None:
        overrides["draws"] = int(draws)
    if candidates is not None:
        overrides["candidatesPerSlotFamily"] = int(candidates)
    if overrides:
        params = with_overrides(params, **overrides)

    league = build_league()
    pool = waiver_candidates(
        league["contract"],
        rostered_ids(league),
        season=SEASON,
        scoring_settings={},
        params=params,
        ppg_lookup=ppg_lookup_for(league["ppg"]),
    )
    roster = roster_for(league, team_index)
    owner_id = league["contract"]["sleeper"]["teams"][team_index]["ownerId"]
    reuse_supported = _reuse_supported()
    if reuse_supported:
        bbu.clear_before_side_cache()

    started = time.perf_counter()
    if reuse and reuse_supported:
        result = marginal_mod.marginal_bestball_utility_for_roster(
            roster,
            league["slots"],
            waiver_pool=pool,
            params=params,
            max_players=max_players,
            points_model=PointsModel(),
            owner_id=owner_id,
        )
        entries = list(result.entries)
        runs = result.runs
    else:
        projected = sorted(
            (p for p in roster if p.ppg is not None), key=lambda p: (-float(p.ppg), p.player_id)
        )
        if max_players is not None:
            projected = projected[: max(0, int(max_players))]
        entries = [
            marginal_mod.marginal_bestball_utility(
                roster,
                p.player_id,
                league["slots"],
                waiver_pool=pool,
                params=params,
                points_model=PointsModel(),
                owner_id=owner_id,
                cache_scope=None,
            )
            for p in projected
        ]
        runs = sum(int(e.basis.get("afterRuns", 0)) for e in entries)
    elapsed = time.perf_counter() - started

    by_id = {p.player_id: p for p in roster}
    rows = []
    for e in entries:
        p = by_id.get(e.player_id)
        rows.append(
            {
                "playerId": e.player_id,
                "position": None if p is None else p.position,
                "ppg": None if p is None else p.ppg,
                "deltaPpg": e.delta_ppg,
                "mcStandardError": e.mc_standard_error,
                "precisionOk": e.precision_ok,
                "replacementKind": e.replacement.kind,
                "replacementId": e.replacement.player_id,
                "simulatedRosters": e.basis.get("simulatedRosters"),
                "afterRuns": e.basis.get("afterRuns"),
                "beforeSide": e.basis.get("beforeSide"),
                "elapsedS": e.basis.get("elapsedS"),
                "state": e.state,
                "reason": e.reason,
            }
        )
    simulated = [r for r in rows if r["afterRuns"]]
    return {
        "fixture": "tests/fixtures/bestball/synthetic_league.py (synthetic, not live data)",
        "ownerId": owner_id,
        "rosterSize": len(roster),
        "slots": league["slots"],
        "paramSetId": params["paramSetId"],
        "draws": params["draws"],
        "seed": params["seed"],
        "candidatesPerSlotFamily": params["candidatesPerSlotFamily"],
        "materialityPpg": params["materialityPpg"],
        "waiverPool": {
            "state": pool.state,
            "candidates": len(pool.candidates),
            "unpriced": len(pool.unpriced_ids),
            "auctionLotsExcluded": len(pool.excluded_auction_lot_ids),
        },
        "beforeSideReuse": {
            "supportedOnThisTree": reuse_supported,
            "used": bool(reuse and reuse_supported),
            "note": (
                "before roster simulated once per team and reused (best_ball_utility cache_scope)"
                if reuse and reuse_supported
                else "before roster re-simulated for every candidate run"
                if reuse_supported
                else "before-side reuse unavailable on this tree; every run simulates both sides"
            ),
        },
        "totals": {
            "playersSimulated": len(simulated),
            "afterRuns": runs,
            "simulatedRostersIncludingBefore": sum(r["simulatedRosters"] or 0 for r in simulated),
            "elapsedS": round(elapsed, 3),
            "meanSecondsPerPlayer": round(elapsed / len(simulated), 3) if simulated else None,
            "meanSecondsPerAfterRun": round(elapsed / runs, 4) if runs else None,
        },
        "players": rows,
    }


def _print_table(report: dict) -> None:
    print(
        f"Marginal best-ball utility — {report['ownerId']} ({report['rosterSize']} players, "
        f"{len(report['slots'])} slots), draws={report['draws']} seed={report['seed']} "
        f"K/family={report['candidatesPerSlotFamily']} band={report['materialityPpg']} ppg "
        f"paramSetId={report['paramSetId']}"
    )
    print(f"fixture: {report['fixture']}")
    print(f"before-side reuse: {report['beforeSideReuse']['note']}")
    pool = report["waiverPool"]
    print(
        f"waiver pool: {pool['state']}, {pool['candidates']} priced, {pool['unpriced']} unpriced, "
        f"{pool['auctionLotsExcluded']} auction lots excluded"
    )
    print()
    header = f"{'player':<10}{'pos':<5}{'ppg':>7}{'delta':>8}{'SE':>8}{'prec':>6}  {'replacement':<28}{'rosters':>8}{'sec':>8}"
    print(header)
    print("-" * len(header))
    for r in report["players"]:
        repl = r["replacementKind"] + ("" if not r["replacementId"] else f":{r['replacementId']}")
        if r["state"] == "unavailable":
            print(
                f"{r['playerId']:<10}{r['position'] or '':<5}{'—':>7}  unavailable: {r['reason']}"
            )
            continue
        print(
            f"{r['playerId']:<10}{r['position']:<5}{r['ppg']:>7.2f}{r['deltaPpg']:>8.2f}"
            f"{r['mcStandardError']:>8.3f}{('yes' if r['precisionOk'] else 'no'):>6}  "
            f"{repl:<28}{r['simulatedRosters']:>8}{r['elapsedS']:>8.3f}"
        )
    t = report["totals"]
    print()
    print(
        f"totals: {t['playersSimulated']} players, {t['afterRuns']} after-runs "
        f"({t['simulatedRostersIncludingBefore']} rosters incl. before), {t['elapsedS']} s, "
        f"{t['meanSecondsPerPlayer']} s/player, {t['meanSecondsPerAfterRun']} s/after-run"
    )
    print(
        "precision_ok is mcStandardError <= band/2: a statement about this estimate's "
        "precision, not a probability."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--team-index", type=int, default=0)
    ap.add_argument("--draws", type=int, default=None, help="override draws (default: config)")
    ap.add_argument("--max-players", type=int, default=None)
    ap.add_argument("--candidates", type=int, default=None, help="candidates per slot family")
    ap.add_argument("--no-reuse", action="store_true", help="disable before-side reuse")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)
    if not 0 <= args.team_index < 12:
        print("--team-index must be 0-11", file=sys.stderr)
        return 2
    if args.draws is not None and args.draws < 2:
        print("--draws must be >= 2", file=sys.stderr)
        return 2
    report = build_report(
        team_index=args.team_index,
        draws=args.draws,
        max_players=args.max_players,
        candidates=args.candidates,
        reuse=not args.no_reuse,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
