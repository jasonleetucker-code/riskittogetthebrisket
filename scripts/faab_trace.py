#!/usr/bin/env python3
"""faab_trace.py — end-to-end diagnostic trace for one waiver claim.

Answers "why does the /waivers page say $X for this player, for this
team, right now?" by running the exact same production code path
(``src/trade/waiver.py::find_waiver_targets`` plus a direct
``src/trade/faab_engine.py::recommend`` call for the fields the list
endpoint doesn't carry) against a real contract payload, and printing
every field named in the FAAB redesign follow-up report: resolved
owner id, ``bidMethodology``, canonical value, objective ceiling, team
ceiling, clearing price (band), recommended bid, rival count,
historical market evidence, and the shadow Live Waiver Opportunity
value when ``RISKIT_FEATURE_WAIVER_LIVE_OPPORTUNITY=1`` is set.

Usage::

    python scripts/faab_trace.py \\
        --contract exports/latest/dynasty_data_2026-09-01.json \\
        --team-name Collin \\
        --player "Cyrus Allen"

    python scripts/faab_trace.py --contract ... --team-name Collin --board

``--board`` traces every player named in a fixed diagnostic list
(overridable with ``--players``) instead of one name — used for the
September 1 board sanity check.  Diagnostic only: this script never
writes to ``data/`` and never mutates the input contract.

Exit codes: 0 ok, 1 player/team not resolvable, 2 contract load failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SEPT_1_DIAGNOSTIC_BOARD = [
    "Aaron Donald",
    "George Holani",
    "Jacob Saylors",
    "Kamren Kinchens",
    "Seth McGowan",
    "Barion Brown",
    "Derrick Moore",
    "Jonas Sanker",
    "Justice Hill",
    "Carson Wentz",
    "Malik Benson",
    "Dohnte Meyers",
    "Jer'Zhan Newton",
]


def _load_contract(path: Path) -> dict[str, Any]:
    from src.api.data_contract import build_api_data_contract

    raw = json.loads(path.read_text(encoding="utf-8"))
    # A raw scraper export has no ``playersArray`` (that's derived) —
    # a full contract shape has one already.  Build only when needed,
    # so this script also accepts an already-built /api/data dump.
    if isinstance(raw.get("playersArray"), list) and raw["playersArray"]:
        return raw
    return build_api_data_contract(raw)


def _resolve_owner_id(
    sleeper_teams: list[dict[str, Any]], *, name: str | None, owner_id: str | None
) -> str | None:
    if owner_id:
        return owner_id
    if not name:
        return None
    needle = name.strip().lower()
    for t in sleeper_teams:
        if isinstance(t, dict) and str(t.get("name") or "").strip().lower() == needle:
            return str(t.get("ownerId") or "") or None
    return None


def _find_row(contract: dict[str, Any], player_name: str) -> dict[str, Any] | None:
    needle = player_name.strip().lower()
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        nm = str(row.get("displayName") or row.get("name") or "").strip().lower()
        if nm == needle:
            return row
    return None


def trace_one(
    *,
    contract: dict[str, Any],
    sleeper_teams: list[dict[str, Any]],
    owner_id: str,
    player_name: str,
    league_budget: int,
    team_count: int,
    starters_per_team: int,
    roster_settings: dict[str, Any],
    roster_size: int | None,
    market_priors: Any,
) -> dict[str, Any]:
    from src.trade import faab_engine as _engine
    from src.trade import faab_recommender as _recommender
    from src.trade import waiver as _waiver

    row = _find_row(contract, player_name)
    result: dict[str, Any] = {"player": player_name, "found": row is not None}
    if row is None:
        result["error"] = "player not found on canonical board (unresolvable identity or off-board)"
        return result

    canonical_value = row.get("rankDerivedValue")
    result["canonicalValue"] = canonical_value
    result["position"] = row.get("position")

    # Same call the /api/waiver/suggestions handler makes, so
    # bidMethodology + the new per-candidate fields are the REAL
    # production answer, not a hand-reimplementation of it.
    suggestions = _waiver.find_waiver_targets(
        contract,
        sleeper_teams,
        min_value=0,
        include_kicker_def=True,
        league_budget=league_budget,
        team_count=team_count,
        starters_per_team=starters_per_team,
        team_owner_id=owner_id,
        starters=roster_settings.get("starters") or {},
        roster_size=roster_size,
        market_priors=market_priors,
    )
    result["bidMethodology"] = suggestions.get("bidMethodology")
    result["resolvedOwnerId"] = owner_id

    candidate = None
    for items in (suggestions.get("by_position") or {}).values():
        for c in items:
            if str(c.get("name") or "").strip().lower() == player_name.strip().lower():
                candidate = c
                break
        if candidate:
            break
    result["suggestionsCandidate"] = candidate

    # Rival count + team ceiling + factors: recompute the same rivals
    # find_waiver_targets built internally (that function doesn't
    # return them), so the trace can show what actually fed the engine.
    own_team_row = next(
        (t for t in sleeper_teams if str(t.get("ownerId") or "") == str(owner_id)), None
    )
    if own_team_row is not None and candidate is not None:
        board_values = [
            r.get("rankDerivedValue")
            for r in contract.get("playersArray") or []
            if isinstance(r, dict) and isinstance(r.get("rankDerivedValue"), (int, float))
        ]
        league_ctx = _engine.LeagueContext(
            original_budget=league_budget,
            team_count=team_count,
            starters_per_team=starters_per_team,
        )
        anchors = _engine.resolve_anchors(board_values, league_ctx)
        opponents = [t for t in sleeper_teams if str(t.get("ownerId") or "") != str(owner_id)]
        rivals = _recommender.build_rivals(
            opponents,
            position=row.get("position"),
            market_priors=market_priors,
            roster_size=roster_size,
            anchors=anchors,
            starters=roster_settings.get("starters") or {},
        )
        result["rivalCount"] = len(rivals)
        result["rivalsWithKnownBalance"] = sum(1 for r in rivals if r.faab_remaining is not None)

        own_players = own_team_row.get("players") or []
        open_spots = max(0, int(roster_size) - len(own_players)) if roster_size else 0
        team_ctx = _engine.TeamContext(
            owner_id=str(owner_id),
            faab_remaining=own_team_row.get("faabRemaining"),
            open_roster_spots=open_spots,
            need_level="depth",
            competitive_status="bubble",
            risk_posture="balanced",
        )
        # NOTE: this second call uses a simplified need_level ("depth")
        # rather than find_waiver_targets's real per-position
        # _need_level(own_players, ...) — the objective ceiling's need
        # multiplier means this call's objectiveDollars/teamCeiling can
        # differ from suggestionsCandidate's REAL production numbers
        # above. Only teamCeilingDollars/winProbability/rivalCount (not
        # returned by find_waiver_targets) are taken from it; the
        # dollar figures the report should quote are the ones already
        # on suggestionsCandidate.
        rec = _engine.recommend(
            _engine.PlayerInput(
                name=player_name, value=float(canonical_value or 0), position=row.get("position")
            ),
            league_ctx,
            team_ctx,
            anchors=anchors,
            rivals=rivals,
        )
        result["teamCeilingDollars"] = rec["teamCeilingDollars"]
        result["winProbability"] = rec["winProbability"]
        result["objectiveDollars"] = candidate.get("objectiveDollars") if candidate else None
        result["clearing"] = candidate.get("clearing") if candidate else None
        result["clearingLow"] = candidate.get("clearingLow") if candidate else None
        result["clearingHigh"] = candidate.get("clearingHigh") if candidate else None
        result["recommendedBid"] = candidate.get("bid", {}).get("reasonable") if candidate else None
        result["maxRational"] = candidate.get("maxRational") if candidate else None
        result["confidence"] = candidate.get("confidence") if candidate else None

    result["historicalMarketEvidence"] = {
        "sampleSize": getattr(market_priors, "sample_size", None),
        "zeroBidShare": getattr(market_priors, "zero_bid_share", None),
    }

    # Shadow Live Waiver Opportunity value — never affects the numbers
    # above; reported separately per the champion/challenger boundary.
    try:
        from src.api import feature_flags as _ff

        if _ff.is_enabled("waiver_live_opportunity"):
            from src.trade import faab_opportunity as _fo

            sleeper_id = None
            idx = (contract.get("sleeper") or {}).get("idToPlayer") or {}
            for pid, nm in idx.items():
                if str(nm).strip().lower() == player_name.strip().lower():
                    sleeper_id = pid
                    break
            opp = _fo.opportunity_value(
                float(canonical_value or 0), sleeper_id=sleeper_id, player_name=player_name
            )
            result["liveOpportunityValue"] = opp
        else:
            result["liveOpportunityValue"] = "flag off — shadow layer not computed"
    except Exception as exc:  # noqa: BLE001 — diagnostic script, never crash the trace
        result["liveOpportunityValueError"] = str(exc)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract", required=True, help="Path to a raw scrape export or built contract JSON."
    )
    parser.add_argument("--team-name", help="Sleeper team display name (e.g. 'Collin').")
    parser.add_argument(
        "--team-owner-id", help="Sleeper owner id, if known — overrides --team-name."
    )
    parser.add_argument("--player", help="Player display name to trace.")
    parser.add_argument(
        "--board",
        action="store_true",
        help="Trace the fixed September 1 diagnostic board instead of --player.",
    )
    parser.add_argument(
        "--players",
        nargs="*",
        help="Explicit list of players to trace (overrides --board's default list).",
    )
    parser.add_argument(
        "--league-budget",
        type=int,
        default=None,
        help="Override the league's original FAAB budget.",
    )
    parser.add_argument("--team-count", type=int, default=None)
    parser.add_argument("--starters-per-team", type=int, default=20)
    parser.add_argument("--roster-size", type=int, default=None)
    args = parser.parse_args()

    contract_path = Path(args.contract)
    if not contract_path.exists():
        print(f"error: contract file not found: {contract_path}", file=sys.stderr)
        return 2
    try:
        contract = _load_contract(contract_path)
    except Exception as exc:  # noqa: BLE001
        print(f"error: failed to load/build contract: {exc}", file=sys.stderr)
        return 2

    sleeper = contract.get("sleeper") or {}
    sleeper_teams = sleeper.get("teams") or []
    if not sleeper_teams:
        print(
            "error: contract has no sleeper.teams block — cannot resolve a team.", file=sys.stderr
        )
        return 2

    owner_id = _resolve_owner_id(sleeper_teams, name=args.team_name, owner_id=args.team_owner_id)
    if not owner_id:
        print(
            f"error: could not resolve team (--team-name={args.team_name!r}, "
            f"--team-owner-id={args.team_owner_id!r}) against sleeper.teams "
            f"(names available: {[t.get('name') for t in sleeper_teams]})",
            file=sys.stderr,
        )
        return 1

    league_budget = args.league_budget
    if league_budget is None:
        league_budget = next(
            (
                t["faabBudget"]
                for t in sleeper_teams
                if isinstance(t.get("faabBudget"), int) and t["faabBudget"] > 0
            ),
            100,
        )
    team_count = args.team_count or len(sleeper_teams)

    from src.trade.faab_history import load_bid_history, summarize_bid_history

    league_key = None  # trace script works off a raw file, not a resolved league key
    try:
        market_priors = summarize_bid_history(load_bid_history(league_key))
    except Exception:  # noqa: BLE001
        market_priors = summarize_bid_history([])

    players = (
        args.players
        if args.players
        else (SEPT_1_DIAGNOSTIC_BOARD if args.board else ([args.player] if args.player else []))
    )
    if not players:
        print("error: nothing to trace — pass --player, --players, or --board.", file=sys.stderr)
        return 1

    all_ok = True
    for name in players:
        result = trace_one(
            contract=contract,
            sleeper_teams=sleeper_teams,
            owner_id=owner_id,
            player_name=name,
            league_budget=league_budget,
            team_count=team_count,
            starters_per_team=args.starters_per_team,
            roster_settings={},
            roster_size=args.roster_size,
            market_priors=market_priors,
        )
        if not result.get("found"):
            all_ok = False
        print(json.dumps(result, indent=2, default=str))
        print("-" * 72)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
