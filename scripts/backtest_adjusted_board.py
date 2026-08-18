"""Decide whether the league-adjusted board should replace the market board.

    python3 scripts/backtest_adjusted_board.py
    python3 scripts/backtest_adjusted_board.py --season 2025 --json out.json

The question
────────────
``/api/valuation/league-adjusted`` multiplies the consensus board by
measured per-position and per-player tilts — IDP positional scoring fit,
reception-distance banding, structural scarcity.  Every one of those was
argued from mechanism.  None was ever scored against an outcome.

This scores it: both boards are ranked against what players ACTUALLY
scored under this league's exact rules, and
:func:`src.model_registry.board_holdout.compare_boards` reports whether
the difference survives a paired bootstrap.

Three things about the target that are not incidental
─────────────────────────────────────────────────────
**1. Banded receptions must be in the target, or the test is rigged
against the adjustment.**  This league pays by catch distance —
``rec_0_4`` 0.17 through ``rec_40p`` 1.92.  Those keys are UNSCORABLE
from weekly box scores (``src.nfl_data.scoring_coverage``); only
play-by-play carries them.  So the weekly-stats engine alone produces a
target with the reception-distance component *missing* — and reception
fit is one of the two live axes in the adjustment.  Scoring the
adjustment against a target that omits the thing it corrects for would
guarantee it loses for a reason that has nothing to do with whether it
is right.  Season band counts from
``data/nfl_data/actuals/reception_depth_{season}.jsonl`` are added on
top of the flat ``rec`` rate the weekly engine already applied.

**2. Regular season only.**  Postseason points are real, but who plays
19 games is a fact about a player's TEAM.  Both arms would eat that
confound identically, so it would not flip a verdict — it would just add
variance to a target that has little enough signal already.

**3. Picks leave the population.**  They have no realized points, and
:func:`src.league_intel.replacement.compute_scarcity` has no ``PICK``
key so the adjustment never moves them anyway.  Nothing to measure.

What this can and cannot conclude
─────────────────────────────────
The board is current; the season is finished.  So this is NOT a forecast
test — see :mod:`src.model_registry.board_holdout` for why the
comparison is still sound (any lookahead is common-mode and cancels in
the difference) and for the claim it does not support.

Exit codes
──────────
``0`` verdict produced, ``1`` inputs unusable, ``2`` too few players
joined to decide anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.model_registry.board_holdout import compare_boards  # noqa: E402
from src.utils.name_clean import resolve_canonical_name  # noqa: E402

#: Board rows below this rank are excluded from the focused cut. The
#: board's practical use is the top few hundred assets; past that most
#: realized totals are zero-ish and ordering them is a task neither
#: board is trying to do. Reported ALONGSIDE the full population rather
#: than instead of it — a verdict that only holds at one cut is a
#: verdict about the cut.
FOCUS_TOP_N = 300


def _latest_export(exports_dir: Path) -> Path | None:
    candidates = sorted(exports_dir.glob("dynasty_data_*.json"))
    return candidates[-1] if candidates else None


def _load_league_scoring() -> tuple[str, dict[str, Any], int | None]:
    from src.league_comparison.service import _load_config
    from src.league_comparison.sleeper_scoring import fetch_league_scoring

    cfg = _load_config()
    league_id = str((cfg.get("my_league") or {}).get("id") or "")
    seasons = [int(s) for s in (cfg.get("seasons") or []) if str(s).isdigit()]
    if not league_id:
        return "", {}, None
    return (
        league_id,
        fetch_league_scoring(league_id).scoring_settings or {},
        (max(seasons) if seasons else None),
    )


def _realized_points(
    season: int, scoring: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Season totals per GSIS id under this league's exact rules.

    Returns ``(by_gsis, weekly_row_count, pbp_player_count)`` — the two
    counts so a silently missing play-by-play artifact shows up in the run
    log rather than as an unexplained shift in the verdict. A zero there
    means the ten play-by-play rules scored nothing and the verdict is
    about a different quantity than the one it claims.
    """
    from src.league_comparison.scoring_engine import compute_player_season_scores
    from src.nfl_data.ingest import fetch_weekly_stats
    from src.nfl_data.pbp_weekly import SeasonPbpIndex

    rows = [
        r
        for r in (fetch_weekly_stats([season]) or [])
        if str(r.get("season_type") or "REG").upper() == "REG"
    ]
    # The bands used to be bolted on here from the SEASON depth histogram,
    # which made this script a second owner of "what a band is worth" —
    # and it carried none of the special-teams rules or the pick-six
    # penalty at all.  The canonical supplement carries all ten, per week,
    # and excludes the flat ``rec`` rate structurally rather than by the
    # caller remembering to.
    stats = SeasonPbpIndex().for_season(season)
    scores = compute_player_season_scores(
        rows, scoring, season=season, pbp_for_season=lambda _s: stats
    )

    out: dict[str, dict[str, Any]] = {}
    for s in scores:
        out[str(s.player_id)] = {
            "name": s.player_name,
            "position": s.position,
            "games": s.games_played,
            "points": float(s.total_points),
        }
    return out, len(rows), (stats.player_count if stats is not None else 0)


def _build_population(
    board_rows: list[dict[str, Any]],
    factors: dict[str, float],
    realized: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Join board -> adjusted -> realized, by canonical name.

    Canonical name and not GSIS because the overlay itself is keyed by
    ``displayName`` (``src.league_intel.publish``) — joining the two
    arms on different keys would let a name that resolves for one and
    not the other silently drop out of one arm only.
    """
    by_name: dict[str, dict[str, Any]] = {}
    for entry in realized.values():
        key = resolve_canonical_name(entry["name"])
        if key and key not in by_name:
            by_name[key] = entry

    population: list[dict[str, Any]] = []
    stats = {"boardRows": len(board_rows), "picks": 0, "unpriced": 0, "unjoined": 0}
    for row in board_rows:
        name = str(row.get("displayName") or "").strip()
        if str(row.get("position") or "").upper() == "PICK" or row.get("assetClass") == "pick":
            stats["picks"] += 1
            continue
        value = row.get("rankDerivedValue")
        if not isinstance(value, (int, float)) or value <= 0:
            stats["unpriced"] += 1
            continue
        entry = by_name.get(resolve_canonical_name(name))
        if entry is None:
            stats["unjoined"] += 1
            continue
        factor = float(factors.get(name, 1.0))
        population.append(
            {
                "name": name,
                "position": str(row.get("position") or entry["position"] or "?").upper(),
                "boardRank": row.get("canonicalConsensusRank"),
                "market": float(value),
                "adjusted": float(value) * factor,
                "actual": entry["points"],
                "actualPerGame": (entry["points"] / entry["games"]) if entry["games"] else None,
                "games": entry["games"],
            }
        )
    return population, stats


def replacement_baselines(
    population: list[dict[str, Any]], roster_settings: dict[str, Any]
) -> dict[str, float]:
    """Realized points of the last startable player at each position.

    WHY THIS TARGET EXISTS AT ALL.  Raw points are not comparable across
    positions — a QB outscores every DB in this league by construction,
    and the board correctly does not rank him above all of them.  So a
    cross-position rank correlation against raw points scores the board
    on a question it is not trying to answer, and it penalises exactly
    the thing the adjustment does: re-pricing whole positions against
    each other.  Over-replacement is the standard fantasy answer to
    that, and it is an outside convention rather than something invented
    here to flatter the result.

    Baselines come from REALIZED points and the league's roster
    settings, never from :mod:`src.league_intel.replacement` — that
    module is part of the thing under test, and deriving the target from
    it would let the adjustment grade its own paper.

    Flex slots are deliberately NOT allocated.  Distributing FLEX and
    SFLEX across eligible positions is an optimisation whose answer
    depends on the values being tested.  Dedicated slots only means
    every flex-eligible position's baseline sits somewhat too shallow —
    identically in both arms, so it cannot flip the comparison.
    """
    teams = int(roster_settings.get("teamCount") or 12)
    starters = roster_settings.get("starters") or {}
    by_pos: dict[str, list[float]] = {}
    for row in population:
        by_pos.setdefault(row["position"], []).append(float(row["actual"]))

    out: dict[str, float] = {}
    for pos, values in by_pos.items():
        slots = int(starters.get(pos) or 0) * teams
        if slots <= 0:
            continue
        values.sort(reverse=True)
        out[pos] = values[min(slots, len(values)) - 1]
    return out


def factor_shape(board_rows: list[dict[str, Any]], factors: dict[str, float]) -> dict[str, Any]:
    """How the adjustment varies WITHIN each position.

    This is the table that makes the per-position deltas readable.  Four
    of the seven positions get a single scalar — every DL is multiplied
    by the same 1.083 — and a constant multiplier cannot change ranks
    within its own position, so those deltas are exactly ``0.0000`` by
    construction rather than because the harness failed to see anything.
    Only ``distinct > 1`` positions are testable within-position at all.
    """
    from collections import defaultdict

    position_of = {
        str(r.get("displayName") or ""): str(r.get("position") or "?").upper() for r in board_rows
    }
    grouped: dict[str, list[float]] = defaultdict(list)
    for name, value in factors.items():
        grouped[position_of.get(name, "?")].append(float(value))

    import statistics

    return {
        pos: {
            "n": len(values),
            "distinct": len(set(values)),
            "min": round(min(values), 6),
            "median": round(statistics.median(values), 6),
            "max": round(max(values), 6),
        }
        for pos, values in sorted(grouped.items())
    }


def _score(
    population: list[dict[str, Any]], roster_settings: dict[str, Any], iterations: int
) -> dict[str, Any]:
    """Every target and cut, reported together, so a verdict that only
    survives one framing is visible as exactly that."""
    focused = [
        p for p in population if isinstance(p["boardRank"], int) and p["boardRank"] <= FOCUS_TOP_N
    ]
    per_game = [dict(p, actual=p["actualPerGame"]) for p in population if p["games"]]

    baselines = replacement_baselines(population, roster_settings)
    over_replacement = [
        dict(p, actual=p["actual"] - baselines[p["position"]])
        for p in population
        if p["position"] in baselines
    ]

    return {
        "fullBoard": compare_boards(population, iterations=iterations).to_dict(),
        f"top{FOCUS_TOP_N}": compare_boards(focused, iterations=iterations).to_dict(),
        "perGame": compare_boards(per_game, iterations=iterations).to_dict(),
        "overReplacement": compare_boards(over_replacement, iterations=iterations).to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season", type=int, default=None, help="target season (default: league config)"
    )
    parser.add_argument("--export", type=Path, default=None, help="contract export json")
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--json", type=Path, default=None, help="write the full result here")
    args = parser.parse_args(argv)

    from src.api import gameplan, league_registry
    from src.api.data_contract import build_api_data_contract

    league_id, scoring, config_season = _load_league_scoring()
    season = args.season or config_season
    if not scoring or not season:
        print(
            "[backtest] no league scoring settings or season; cannot score anything",
            file=sys.stderr,
        )
        return 1

    export = args.export or _latest_export(_REPO_ROOT / "exports" / "latest")
    if not export or not export.exists():
        print(f"[backtest] no contract export found at {export}", file=sys.stderr)
        return 1
    print(f"[backtest] board  : {export.name}")

    contract = build_api_data_contract(json.loads(export.read_text(encoding="utf-8")))
    board_rows = contract.get("playersArray") or []

    league_key = league_registry.default_league_key()
    overlay = gameplan.get_league_adjusted_values(
        league_key, league_registry.get_scoring_profile(league_key), contract
    )
    factors = overlay.get("factors") or {}
    inactive = overlay.get("inactiveAxes") or []
    print(f"[backtest] league : {league_key}  factors={len(factors)}  inactiveAxes={inactive}")
    if not factors:
        print(
            "[backtest] the overlay moved nobody — with every axis absent this "
            "compares a board against itself.  Nothing to decide.",
            file=sys.stderr,
        )
        return 2

    realized, weekly_rows, pbp_players = _realized_points(season, scoring)
    print(
        f"[backtest] actuals: season={season} weeklyRows={weekly_rows} "
        f"scoredPlayers={len(realized)} pbpPlayers={pbp_players}"
    )

    population, join_stats = _build_population(board_rows, factors, realized)
    print(f"[backtest] joined : {len(population)}  {join_stats}")

    roster_settings = league_registry.get_league_roster_settings(league_key)
    results = _score(population, roster_settings, args.iterations)
    payload = {
        "season": season,
        "leagueKey": league_key,
        "board": export.name,
        "contractVersion": contract.get("contractVersion"),
        "adjustmentModelVersion": overlay.get("adjustmentModelVersion"),
        "inactiveAxes": inactive,
        "factorsApplied": len(factors),
        "factorShape": factor_shape(board_rows, factors),
        "join": join_stats,
        "results": results,
    }
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"[backtest] wrote {args.json}")

    print()
    print("── adjustment shape (a constant factor cannot re-rank within its position) ──")
    for pos, shape in payload["factorShape"].items():
        flag = "  scalar only" if shape["distinct"] <= 1 else ""
        print(
            f"   {pos:<4} n={shape['n']:<4} distinct={shape['distinct']:<4} "
            f"[{shape['min']:.4f} .. {shape['median']:.4f} .. {shape['max']:.4f}]{flag}"
        )
    print()
    for label, res in results.items():
        print(f"── {label} " + "─" * (58 - len(label)))
        print(
            f"   n={res['n']:<5} movers={res['movers']:<5} "
            f"market rho={res['marketRho']:+.4f}  adjusted rho={res['adjustedRho']:+.4f}  "
            f"delta={res['delta']:+.4f}"
        )
        print(
            f"   win rate={res['winRate']:.3f}  95% CI on delta="
            f"[{res['ci95'][0]:+.4f}, {res['ci95'][1]:+.4f}]"
        )
        print(f"   {res['verdict']}")
        for pos, row in res["byPosition"].items():
            print(
                f"      {pos:<4} n={int(row['n']):<4} market={row['marketRho']:+.4f} "
                f"adjusted={row['adjustedRho']:+.4f} delta={row['delta']:+.4f}"
            )
        print()

    if all(r["verdict"].startswith("too few") for r in results.values()):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
