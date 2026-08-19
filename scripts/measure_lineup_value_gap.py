#!/usr/bin/env python3
"""Phase A: how much does the unweighted-sum objective overstate a big plan?

``docs/perfect-draft.md`` §9 says roster value is an **unweighted sum of market
values**, so a 58-man roster that starts 21 still books bench player #40 at full
market value.  That is the stated reason the optimizer prefers very large plans
— fixing the replacement term moved the recommendation only 35 → 34.

The honest fix is lineup-aware roster value, and it is expensive: it is
set-dependent, so it breaks the cardinality decomposition the whole solver rests
on (ADR-010 amendment 2).  Before trading exactness away for it, measure whether
the distortion is real.

**The measurement.** Both objectives agree on what a roster contains; they
disagree on what it is worth.  So walk ``k = 0..N`` rookies added to a real
roster and compare, at each step:

* ``naive`` — Σ board value over every player, which is what the solver credits.
  The marginal value of rookie ``k`` is simply his own board value.
* ``lineup`` — Σ board value over the players the league's own starting slots
  can actually field, from the real solver
  (``src/ros/lineup.py::solve_optimal_assignment``).  The marginal value of
  rookie ``k`` is whatever he adds to the *startable* total, which is zero once
  better players already hold every slot he is eligible for.

The ratio of those two marginals is the distortion.  If it collapses to zero
after a handful of rookies, the naive objective is crediting the rest with value
they do not add, and Phase B is justified.  If it stays near 1, it is not.

**Why board value and not ``ros_value``.**  ``solve_optimal_assignment``
maximizes whatever weight it is handed, and ``RosterAsset.ros_value`` is
explicitly documented as "lineup feasibility ONLY — never cost arithmetic".
The question here is a *valuation* one — what is the startable market value —
so the weight passed in is board value.  Slot eligibility is untouched, which
is the part of the solver that matters.

Usage::

    ALLOW_DEFAULT_LOGIN_DEV=1 python scripts/measure_lineup_value_gap.py
    ALLOW_DEFAULT_LOGIN_DEV=1 python scripts/measure_lineup_value_gap.py \\
        --team "Team Name" --max-k 40 --json out.json

Exit codes follow the repo convention: 0 success, 1 error, 2 skipped (no
contract to measure against — never 0, so "no data" cannot read as "measured").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SKIPPED = 2


def _startable_value(assets: list[Any], slots: list[str]) -> float:
    """Board value of the best lineup this pool can field.

    Weight is board value, so the matching answers "which players give the most
    startable market value", which is the quantity the objective is arguing
    about.  Unpriced players carry 0 — they cannot be credited with value the
    board never gave them.
    """
    from src.ros.lineup import solve_optimal_assignment  # noqa: PLC0415

    pool = []
    for a in assets:
        lp = a.to_lineup_player()
        # ``ros_value`` is the solver's weight field; re-point it at board value
        # for this question only.  Eligibility (position / fantasy_positions) is
        # untouched, which is the part that encodes the league's lineup rules.
        pool.append(
            type(lp)(
                player_id=lp.player_id,
                canonical_name=lp.canonical_name,
                position=lp.position,
                ros_value=float(a.board_value or 0.0),
                injured=lp.injured,
                bye=lp.bye,
                fantasy_positions=lp.fantasy_positions,
            )
        )
    assignment = solve_optimal_assignment(pool, list(slots))
    return sum(float(p.ros_value or 0.0) for p in assignment.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--team", default=None, help="team name (default: first team)")
    ap.add_argument("--max-k", type=int, default=40, help="how many rookies to walk")
    ap.add_argument("--json", default=None, help="also write the series here")
    args = ap.parse_args(argv)

    try:
        import server  # noqa: PLC0415

        from src.draft.context import (  # noqa: PLC0415
            index_contract_rows,
            contract_teams,
            build_roster_assets,
        )
        from src.draft.displacement import RosterAsset  # noqa: PLC0415
        from src.ros.lineup import load_league_starter_slots  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not import the app ({exc})", file=sys.stderr)
        return EXIT_ERROR

    contract = getattr(server, "latest_contract_data", None)
    if not contract:
        # Same hydration the snapshot capture uses: the global is only populated
        # inside the FastAPI lifespan, so a cold shell has to prime it.
        server._prime_latest_payload(server.load_from_disk())  # noqa: SLF001
        contract = getattr(server, "latest_contract_data", None)
    if not contract:
        print("SKIPPED: no contract cached on disk — run a scrape first.", file=sys.stderr)
        return EXIT_SKIPPED

    league_key = (contract.get("meta") or {}).get("leagueKey")
    teams = contract_teams(contract)
    if not teams:
        print("SKIPPED: contract carries no rosters.", file=sys.stderr)
        return EXIT_SKIPPED
    team = next((t for t in teams if t.get("name") == args.team), None) if args.team else teams[0]
    if team is None:
        print(f"ERROR: no team named {args.team!r}.", file=sys.stderr)
        return EXIT_ERROR

    by_id, by_name = index_contract_rows(contract)
    assets, _unmatched = build_roster_assets(team, by_name, by_id)
    slots = load_league_starter_slots(league_key)

    pool = server._our_rookie_pool(server._KTC_TOTAL_PICKS)  # noqa: SLF001
    if not pool:
        print("SKIPPED: contract carries no rookie pool.", file=sys.stderr)
        return EXIT_SKIPPED

    rookies = [
        RosterAsset(
            player_id=f"rookie::{r.get('name')}",
            name=str(r.get("name")),
            position=str(r.get("pos") or "").strip().upper(),
            board_value=float(r.get("value") or 0.0),
            ros_value=float(r.get("value") or 0.0),
            fantasy_positions=(str(r.get("pos") or "").strip().upper(),),
        )
        for r in pool
    ]
    rookies.sort(key=lambda a: -(a.board_value or 0.0))
    max_k = max(0, min(args.max_k, len(rookies)))

    base_naive = sum(float(a.board_value or 0.0) for a in assets)
    base_lineup = _startable_value(assets, slots)

    rows: list[dict[str, Any]] = []
    prev_lineup = base_lineup
    for k in range(1, max_k + 1):
        added = rookies[:k]
        naive = base_naive + sum(float(a.board_value or 0.0) for a in added)
        lineup = _startable_value(list(assets) + added, slots)
        rows.append(
            {
                "k": k,
                "rookie": added[-1].name,
                "pos": added[-1].position,
                "boardValue": round(float(added[-1].board_value or 0.0), 1),
                "naiveMarginal": round(float(added[-1].board_value or 0.0), 1),
                "lineupMarginal": round(lineup - prev_lineup, 1),
                "naiveTotal": round(naive, 1),
                "lineupTotal": round(lineup, 1),
            }
        )
        prev_lineup = lineup

    print(f"league={league_key} team={team.get('name')!r} roster={len(assets)} slots={len(slots)}")
    print(f"baseline: naive={base_naive:,.0f}  startable={base_lineup:,.0f}")
    print()
    print(f"{'k':>3} {'rookie':<24} {'pos':<4} {'naive Δ':>9} {'lineup Δ':>9} {'credited':>9}")
    for r in rows:
        share = (r["lineupMarginal"] / r["naiveMarginal"]) if r["naiveMarginal"] else 0.0
        print(
            f"{r['k']:>3} {r['rookie'][:24]:<24} {r['pos']:<4} "
            f"{r['naiveMarginal']:>9,.0f} {r['lineupMarginal']:>9,.0f} {share:>8.0%}"
        )

    if rows:
        total_naive = sum(r["naiveMarginal"] for r in rows)
        total_lineup = sum(r["lineupMarginal"] for r in rows)
        dead = [r["k"] for r in rows if r["lineupMarginal"] <= 0]
        print()
        print(
            f"over k=1..{max_k}: naive credits {total_naive:,.0f}, "
            f"lineup credits {total_lineup:,.0f} "
            f"({(total_lineup / total_naive if total_naive else 0):.1%})"
        )
        if dead:
            print(f"first rookie adding NO startable value: k={dead[0]} ({len(dead)} of {max_k})")
        else:
            print("every rookie in this range adds startable value")

    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "leagueKey": league_key,
                    "team": team.get("name"),
                    "slots": len(slots),
                    "baselineNaive": base_naive,
                    "baselineLineup": base_lineup,
                    "series": rows,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
