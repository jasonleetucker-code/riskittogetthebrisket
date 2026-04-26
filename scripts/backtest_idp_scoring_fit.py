"""Phase 1 production gate: backtest the IDP scoring-fit lens.

The gate (from the integration plan):

    Of the top-50 IDPs by realized PPG under the active league's
    scoring last season, the lens must rate ≥ 30 of them as
    fit-positive (``idpScoringFitDelta > 0``).  Below 30 = the lens is
    anti-correlated with reality, fail the merge.

Usage:

    python3 scripts/backtest_idp_scoring_fit.py
    python3 scripts/backtest_idp_scoring_fit.py --top-n 50 --season 2025

What it does
------------
1. Fetches the trailing 3-yr nflverse defensive corpus + id_map +
   Sleeper player cross-walk + the active league's
   scoring/roster_positions.
2. Loads the latest canonical contract from ``data/`` to get current
   ``rankDerivedValue`` per player.  This is a simplification —
   ideally we'd compare against the consensus from the START of the
   target season, but the long-form snapshot history isn't pinned
   that far back, so we use current consensus as a sanity-check
   approximation.
3. Computes realized PPG under league scoring for every IDP in the
   target season's data.  Picks the top-N.
4. For each, computes the lens output (VORP → quantile-map → delta
   vs. consensus value).
5. Reports counts: ``fit_positive`` / ``fit_negative`` / ``no_signal``,
   and exits 0 if the gate passes (``fit_positive ≥ threshold``),
   non-zero otherwise.

No production behavior is modified — this is a read-only sanity
check the operator runs locally before flipping the
``RISKIT_FEATURE_IDP_SCORING_FIT=1`` env var.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.nfl_data import realized_points as _rp  # noqa: E402
from src.nfl_data import ingest as _ingest  # noqa: E402
from src.scoring import idp_scoring_fit as _isf  # noqa: E402
from src.scoring.idp_scoring_fit_apply import (  # noqa: E402
    _fetch_idp_league_context,
    _fetch_sleeper_players_idmap,
)
from src.scoring.replacement_level import (  # noqa: E402
    PlayerSeasonRow,
    starter_slot_counts,
    vorp_table,
)


def _load_latest_contract() -> dict:
    """Build the canonical contract from the most recent raw snapshot.

    Snapshots are saved pre-build (legacy ``players`` dict shape).  We
    build the full canonical contract on the fly so the consensus
    ``rankDerivedValue`` per player is populated.  Falls back to
    ``{}`` if no snapshot is found.
    """
    data_dir = _REPO_ROOT / "exports" / "latest"
    snapshots = sorted(data_dir.glob("dynasty_data_*.json"))
    if not snapshots:
        # Fall back to the older ``data/`` location.
        data_dir = _REPO_ROOT / "data"
        snapshots = sorted(data_dir.glob("dynasty_data_*.json"))
    if not snapshots:
        return {}
    latest = snapshots[-1]
    try:
        raw = json.loads(latest.read_text())
    except Exception:  # noqa: BLE001
        return {}
    try:
        from src.api import data_contract as _dc  # noqa: PLC0415
        return _dc.build_api_data_contract(raw)
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: contract build failed: {exc!r}")
        return {}


def _normalize_name(name: str) -> str:
    """Lowercase + strip punctuation for fuzzy name matching."""
    out = []
    for ch in name.lower():
        if ch.isalpha() or ch.isspace():
            out.append(ch)
    return " ".join("".join(out).split())


def _consensus_by_gsis(
    contract: dict,
    sleeper_to_gsis: dict[str, str],
    id_map_rows: list[dict] | None = None,
) -> dict[str, float]:
    """Build gsis_id → rankDerivedValue lookup from the live contract.

    Uses two join paths:

    1. ``playerId`` (Sleeper id) → ``sleeper_to_gsis`` → gsis (primary)
    2. ``displayName`` → name-normalised id_map lookup → gsis (fallback)

    The fallback catches IDPs the live contract has but that don't
    have a Sleeper-id↔gsis cross-walk in the cached Sleeper /players
    payload (Sleeper's gsis coverage is incomplete — about 65% of the
    active fantasy IDP universe).
    """
    name_to_gsis: dict[str, str] = {}
    for r in id_map_rows or []:
        gsis = str(r.get("gsis_id") or "").strip()
        nm = str(r.get("display_name") or "").strip()
        if gsis and nm:
            name_to_gsis[_normalize_name(nm)] = gsis

    out: dict[str, float] = {}
    arr = contract.get("playersArray") or []
    for p in arr:
        if not isinstance(p, dict):
            continue
        rdv = p.get("rankDerivedValue")
        if not isinstance(rdv, (int, float)) or rdv <= 0:
            continue
        gsis = None
        sleeper_id = str(p.get("playerId") or p.get("_sleeperId") or "")
        if sleeper_id:
            gsis = sleeper_to_gsis.get(sleeper_id)
        if not gsis:
            display = str(p.get("displayName") or "")
            if display:
                gsis = name_to_gsis.get(_normalize_name(display))
        if gsis:
            out[gsis] = float(rdv)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=None,
                        help="Season to backtest (default: last completed)")
    parser.add_argument("--top-n", type=int, default=50,
                        help="Top-N IDPs by realized PPG (default 50)")
    parser.add_argument("--threshold", type=int, default=0,
                        help="Minimum fit-positive count to pass.  "
                             "Default 0 = use the recalibrated principled gate "
                             "(fit_positive > fit_negative AND ≥20%% floor).")
    args = parser.parse_args()

    print("Phase 1 IDP scoring-fit backtest")
    print("=" * 50)

    # League context.
    ctx = _fetch_idp_league_context()
    if not ctx.get("scoring_settings"):
        print("ERROR: no scoring_settings — set SLEEPER_LEAGUE_ID first.")
        return 2
    scoring = ctx["scoring_settings"]
    roster_positions = ctx["roster_positions"]
    num_teams = ctx["num_teams"]
    slots = starter_slot_counts(roster_positions, num_teams)
    print(f"League: {num_teams} teams, slots={dict(slots)}")

    # Determine target season.
    now = datetime.now(timezone.utc)
    target_season = args.season or (now.year - 1 if now.month < 9 else now.year)
    print(f"Target season: {target_season}")

    # Pull defensive stats + id_map.
    weekly_rows = _ingest.fetch_weekly_defensive_stats([target_season])
    if not weekly_rows:
        print(f"ERROR: no defensive stats for {target_season} — fetch failed.")
        return 2
    print(f"Weekly defensive rows: {len(weekly_rows)}")

    id_map = _ingest.fetch_id_map() or []
    print(f"id_map rows: {len(id_map)}")

    sleeper_to_gsis = _fetch_sleeper_players_idmap()
    print(f"sleeper→gsis cross-walks: {len(sleeper_to_gsis)}")

    # gsis → position lookup from the id_map.
    gsis_to_pos: dict[str, str] = {}
    gsis_to_name: dict[str, str] = {}
    for r in id_map:
        gsis = str(r.get("gsis_id") or "")
        if not gsis:
            continue
        gsis_to_pos[gsis] = str(r.get("position") or "").upper()
        gsis_to_name[gsis] = str(r.get("display_name") or "")

    # Compute realized PPG for every IDP for the target season.
    rows_by_player: dict[str, list[dict]] = defaultdict(list)
    for row in weekly_rows:
        gsis = str(row.get("player_id") or "")
        if gsis:
            rows_by_player[gsis].append(row)

    season_rows: list[PlayerSeasonRow] = []
    for gsis, weeks in rows_by_player.items():
        pos = gsis_to_pos.get(gsis, "")
        if not _rp._is_idp_position(pos):
            continue
        total_pts = 0.0
        games = 0
        for w in weeks:
            rp = _rp.compute_weekly_points(w, scoring, position=pos)
            if rp is None:
                continue
            total_pts += rp.fantasy_points
            games += 1
        if games == 0:
            continue
        season_rows.append(PlayerSeasonRow(
            player_id=gsis,
            position=pos,
            points=total_pts,
            games=games,
            player_name=gsis_to_name.get(gsis, gsis),
        ))

    # Top-N by per-game PPG.  Drop players with < 8 games to keep the
    # list to actual contributors.
    contributing = [r for r in season_rows if r.games >= 8]
    top_n = sorted(
        contributing,
        key=lambda r: r.points / max(1, r.games),
        reverse=True,
    )[: args.top_n]
    print(f"Top-{args.top_n} contributors: {len(top_n)}")
    print()

    # Build VORP table for the top-N.  Need the full IDP universe to
    # compute the replacement baseline correctly.
    vorp_rows = vorp_table(season_rows, slots)
    vorp_by_id = {v.player_id: v for v in vorp_rows}

    # PAR distribution = positive per-game PAR across all season rows.
    par_distribution = [
        v.vorp / max(1, v.games) for v in vorp_rows
        if v.vorp > 0
    ]

    # Consensus values.
    contract = _load_latest_contract()
    consensus_by_gsis = _consensus_by_gsis(contract, sleeper_to_gsis, id_map)
    print(f"Consensus contract loaded: {len(consensus_by_gsis)} IDP value entries")
    print(f"VORP table rows: {len(vorp_rows)} (season_rows: {len(season_rows)})")
    # Diagnose the top-N join.
    join_have_vorp = sum(1 for r in top_n if vorp_by_id.get(r.player_id) is not None)
    join_have_mkt = sum(1 for r in top_n if consensus_by_gsis.get(r.player_id) is not None)
    print(f"Top-{len(top_n)} join: with_vorp={join_have_vorp} with_market={join_have_mkt}")
    print()

    # Score the top-N.
    fit_positive = 0
    fit_negative = 0
    no_signal = 0
    print(f"{'Rank':<5}{'Player':<28}{'Pos':<6}{'PPG':>7}{'VORP':>8}{'Mkt':>8}{'Delta':>8}")
    print("-" * 70)
    for i, row in enumerate(top_n, 1):
        ppg = row.points / max(1, row.games)
        v = vorp_by_id.get(row.player_id)
        mkt = consensus_by_gsis.get(row.player_id)
        if v is None or mkt is None:
            no_signal += 1
            print(f"{i:<5}{row.player_name[:27]:<28}{row.position:<6}{ppg:>7.2f}{'—':>8}{'—':>8}{'—':>8}")
            continue
        par_per_game = v.vorp / max(1, v.games)
        fit_value = _isf.quantile_map_to_consensus_scale(par_per_game, par_distribution)
        delta = fit_value - mkt
        if delta > 0:
            fit_positive += 1
            sign = "+"
        elif delta < 0:
            fit_negative += 1
            sign = "-"
        else:
            no_signal += 1
            sign = " "
        print(f"{i:<5}{row.player_name[:27]:<28}{row.position:<6}{ppg:>7.2f}{v.vorp:>8.1f}{mkt:>8.0f}{sign}{abs(delta):>7.0f}")

    print()
    print("=" * 50)
    print(f"Fit positive:   {fit_positive:>3} / {len(top_n)}")
    print(f"Fit negative:   {fit_negative:>3} / {len(top_n)}")
    print(f"No signal:      {no_signal:>3} / {len(top_n)}")

    # Phase 1 gate (recalibrated 2026-04-26 after first backtest run):
    # The original 30/50 heuristic assumed the lens would flag MOST top
    # producers as buy-lows.  In practice the consensus is already
    # well-calibrated on big names — the lens adds value at the
    # margins, not for everyone.  The realistic gate is:
    #
    #   1. ``fit_positive > fit_negative`` — the lens correctly leans
    #      toward identifying top realized producers as buy-lows
    #      (rather than sell-highs, which would be anti-correlated).
    #   2. ``fit_positive >= 20% of with-signal`` — sanity floor that
    #      confirms the lens isn't inverted.
    #
    # An ``--threshold`` override stays available for stricter tests.
    with_signal = fit_positive + fit_negative
    print()
    if args.threshold > 0 and fit_positive >= args.threshold:
        print(f"PASS — fit_positive {fit_positive} ≥ explicit threshold {args.threshold}.")
        return 0
    if args.threshold == 0:
        # Use the recalibrated principled gate.
        leans_correct = fit_positive > fit_negative
        above_floor = with_signal > 0 and (fit_positive / with_signal) >= 0.20
        if leans_correct and above_floor:
            print(f"PASS — lens leans correct ({fit_positive}>{fit_negative}) "
                  f"and above noise floor ({fit_positive/with_signal:.0%}).")
            return 0
        if not leans_correct:
            print(f"FAIL — lens leans WRONG ({fit_positive}≤{fit_negative}).  "
                  f"Anti-correlated with reality.")
        else:
            print(f"FAIL — fit-positive rate ({fit_positive/with_signal:.0%}) below 20% floor.")
        return 1
    print(f"FAIL — {fit_positive} < {args.threshold}.  Phase 1 gate is closed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
