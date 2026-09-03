#!/usr/bin/env python3
"""Capture pregame Game Day prediction snapshots (C5-GD-02).

Calls ``src.ros.game_day_archive.record_snapshot`` once per (league,
team) so the perishable pre-kickoff state -- roster composition, the
lineup-eligible pool, the league's scoring/slot identity, and a real
wall-clock timestamp -- is not silently lost. That module is a pure
append-only store; this script is its first real caller, closing the
"zero callers anywhere" gap named in
``docs/season-launch/2026_SEASON_LAUNCH_STATUS.md``.

WHAT THIS DOES NOT DO, STATED EXPLICITLY
-----------------------------------------
Every captured ``PlayerPointEstimate`` carries ``point_estimate=None,
estimate_source=None``. This is not a placeholder to be filled in
later by this script -- it is the only honest choice available today:
a repo-wide check (this unit's own design pass, 2026-09-03) found no
per-week point-projection source anywhere in this codebase. BDVM
(``src/bdvm/``) produces a season-long/ROS per-game RATE (``fpg``,
itself frequently a backward-looking proxy) and a dynasty ASSET VALUE
(``rankDerivedValue``) -- neither is a specific upcoming week's
expected score, and treating either as one would be exactly the
fabrication ``game_day_archive.py``'s own docstring says is not its
job. ``PlayerPointEstimate`` is explicitly designed to support and
require this "no source" state (see its ``__post_init__``). When a
real per-week projection source lands, it plugs in as this script's
``estimate_source`` -- the capture cadence and roster resolution below
do not change.

``is_lineup_eligible`` uses the SIMPLER of two readings the design
pass identified: "is this player's position legal in at least one of
the league's resolved starter slots" (pure positional eligibility),
not "does this player win a slot in an optimal lineup" (which would
need a priced pool -- see ``src/ros/lineup.py::assign_lineup`` -- and
BDVM's dynasty value is not the same currency as a weekly lineup
decision). Documented here because nothing else in the codebase
defines this term for a scripted, unpriced capture.

CADENCE -- AN OPERATIONAL CHOICE, NOT A SPEC REQUIREMENT
-----------------------------------------------------------
``docs/GAME_DAY_PROBABILITY_SPEC.md`` Sec5 requires archiving pregame
snapshots but is silent on exactly how far before kickoff. This
script is meant to run once per NFL week, early on the Thursday the
week turns over (matching ``current_nfl_week()``'s own Thursday
boundary) and before that week's first game -- see
``deploy/systemd/dynasty-game-day-snapshots.timer.template`` for the
chosen time and its stated rationale. Re-running within the same week
is safe: ``record_snapshot`` refuses an exact-duplicate
(league, season, week, team, capture_kind) tuple rather than
overwriting it, so this script logs and skips those rather than
failing.

Exit codes (repo convention -- see scripts/refresh_playerctx.py):
    0 - at least one snapshot recorded (or --dry-run resolved cleanly)
    1 - soft failure (not in season, no leagues, no roster data)
    2 - hard/structural error (no contract export, registry unreadable)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api import league_registry  # noqa: E402
from src.bdvm.actuals import current_nfl_season  # noqa: E402
from src.ros import game_day_archive  # noqa: E402
from src.ros.lineup import resolve_starter_slots, slot_eligible_positions  # noqa: E402
from src.trade.faab_engine import current_nfl_week  # noqa: E402


def log(msg: str) -> None:
    print(f"[game-day-capture] {msg}", flush=True)


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "riskittogetthebrisket/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _load_contract() -> dict | None:
    """The live contract, same discovery order as scripts/snapshot_board.py.

    Only ``sleeper.idToPlayer`` and ``sleeper.positions`` are read from it
    (both NFL-wide, per CLAUDE.md) -- per-league roster composition below
    comes straight from Sleeper, since the shared contract's own
    ``sleeper`` block is stamped for one league only (the scoring-
    profile/leagueKey split) and this script must capture every active
    league, not just whichever one happened to be loaded when the export
    was built. Position lookup is a two-step chain, confirmed against a
    real export rather than assumed from the field name alone:
    ``sleeper.idToPlayer`` maps playerId -> canonical name, and
    ``sleeper.positions`` maps that name -> position; there is no
    playerId -> position map directly.
    """
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    for directory in (REPO / "exports" / "latest", REPO / "data"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("dynasty_data*.json"), reverse=True):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                log(f"skip {path.name}: {exc}")
                continue
            if not isinstance(raw, dict):
                continue
            log(f"building contract from {path.relative_to(REPO)}")
            return build_api_data_contract(raw)
    return None


def _position_map_from_contract(contract: dict[str, Any]) -> dict[str, str]:
    """``playerId -> position`` chained through the contract's own two
    NFL-wide maps -- there is no direct playerId -> position map.
    ``sleeper.idToPlayer`` gives ``playerId -> canonical name``;
    ``sleeper.positions`` gives ``name -> position``. A name present in
    one but not the other is dropped rather than guessed.
    """
    sleeper_block = contract.get("sleeper") or {}
    id_to_player = sleeper_block.get("idToPlayer") or {}
    positions_by_name = sleeper_block.get("positions") or {}
    return {
        pid: positions_by_name[name]
        for pid, name in id_to_player.items()
        if name in positions_by_name
    }


def _capture_league(
    cfg: league_registry.LeagueConfig,
    *,
    position_map: dict[str, Any],
    season: int,
    week: int,
    capture_kind: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Capture every team's snapshot for one league. Returns (written, skipped)."""
    fingerprint = league_registry.scoring_fingerprint_for_league(cfg)
    if not fingerprint:
        # Fail closed, per this repo's own invariant: scoring_config_id is
        # a required field on the snapshot, and a PROVEN-CURRENT identity
        # is exactly what scoring_fingerprint_for_league refuses to
        # fabricate when its evidence is stale or missing. An unverified
        # id would be a silent wrongness baked into permanent evidence.
        log(
            f"  {cfg.key}: scoring evidence not fresh/available -- refusing this league (fails closed)"
        )
        return 0, 0

    try:
        live_league = _fetch_json(f"https://api.sleeper.app/v1/league/{cfg.sleeper_league_id}")
        rosters = _fetch_json(f"https://api.sleeper.app/v1/league/{cfg.sleeper_league_id}/rosters")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log(f"  {cfg.key}: could not fetch Sleeper league/roster data ({exc}) -- skipping")
        return 0, 0

    if not isinstance(rosters, list) or not rosters:
        log(f"  {cfg.key}: no rosters returned from Sleeper -- skipping")
        return 0, 0

    slots, slot_source = resolve_starter_slots(
        roster_positions=(live_league or {}).get("roster_positions"),
        roster_settings=cfg.roster_settings,
    )
    if not slots:
        log(f"  {cfg.key}: no starter slots resolved (neither live host nor registry) -- refusing")
        return 0, 0

    eligible_position_union: set[str] = set()
    for slot in slots:
        eligible_position_union |= slot_eligible_positions(slot)

    written = 0
    skipped = 0
    for roster in rosters:
        owner_id = roster.get("owner_id")
        roster_id = roster.get("roster_id")
        team_id = str(owner_id or f"roster_{roster_id}")
        player_ids = [str(p) for p in (roster.get("players") or [])]
        if not player_ids:
            log(
                f"  {cfg.key}/{team_id}: empty roster -- skipping (a snapshot with nobody on it is not evidence)"
            )
            skipped += 1
            continue

        estimates = []
        for pid in player_ids:
            position = str(position_map.get(pid) or "").upper()
            is_eligible = bool(position) and position in eligible_position_union
            estimates.append(
                game_day_archive.PlayerPointEstimate(
                    player_id=pid,
                    position=position or "UNKNOWN",
                    is_lineup_eligible=is_eligible,
                    point_estimate=None,
                    estimate_source=None,
                )
            )

        if dry_run:
            log(
                f"  {cfg.key}/{team_id}: would capture {len(estimates)} players (dry-run, not written)"
            )
            written += 1
            continue

        try:
            game_day_archive.record_snapshot(
                league_key=cfg.key,
                season=season,
                week=week,
                team_id=team_id,
                capture_kind=capture_kind,
                scoring_config_id=fingerprint,
                starter_slots=tuple(slots),
                roster=tuple(estimates),
                run_id=f"capture_game_day_snapshots:{slot_source}",
            )
            log(f"  {cfg.key}/{team_id}: captured {len(estimates)} players")
            written += 1
        except game_day_archive.GameDayArchiveError as exc:
            # Already captured this (league, season, week, team, kind) --
            # append-only refusal, not a failure. Re-running this script
            # within the same week must be a safe no-op.
            log(f"  {cfg.key}/{team_id}: {exc}")
            skipped += 1

    return written, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--league", help="only this league key (default: every active league)")
    parser.add_argument(
        "--capture-kind",
        default="pregame",
        choices=sorted(game_day_archive.CAPTURE_KINDS),
        help="which capture_kind to record (default: pregame)",
    )
    parser.add_argument("--dry-run", action="store_true", help="resolve and report, write nothing")
    args = parser.parse_args(argv)

    season = current_nfl_season()
    if season is None:
        log("not in the NFL season window (current_nfl_season() is None) -- nothing to capture")
        return 1

    week, in_season = current_nfl_week()
    if not in_season or week is None:
        log("not in the NFL regular-season week window (current_nfl_week()) -- nothing to capture")
        return 1

    contract = _load_contract()
    if contract is None:
        log("error: no dynasty_data export found under exports/latest/ or data/")
        return 2
    position_map = _position_map_from_contract(contract)
    if not position_map:
        log(
            "warning: could not build a playerId -> position map from "
            "sleeper.idToPlayer + sleeper.positions -- every player will "
            "be captured as position UNKNOWN"
        )

    try:
        leagues = league_registry.active_leagues()
    except Exception as exc:  # noqa: BLE001 -- a recording job reports, it never crashes the box
        log(f"error: could not read league registry: {exc}")
        return 2

    if args.league:
        leagues = [cfg for cfg in leagues if cfg.key == args.league]

    if not leagues:
        log("error: no matching active leagues")
        return 2

    total_written = 0
    total_skipped = 0
    for cfg in leagues:
        log(f"-> {cfg.key} season={season} week={week} kind={args.capture_kind}")
        try:
            written, skipped = _capture_league(
                cfg,
                position_map=position_map,
                season=season,
                week=week,
                capture_kind=args.capture_kind,
                dry_run=args.dry_run,
            )
        except Exception as exc:  # noqa: BLE001 -- a recording job reports, it never crashes the box
            log(f"  {cfg.key}: unexpected error ({exc}) -- skipping this league")
            continue
        total_written += written
        total_skipped += skipped

    log(f"done: {total_written} snapshot(s) recorded, {total_skipped} skipped")
    return 0 if total_written > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
