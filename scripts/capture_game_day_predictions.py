#!/usr/bin/env python3
"""Capture each league's pre-game prediction state into the Game Day archive.

`src/ros/game_day_archive.py` (C5-GD-02) was built specifically because
this observation is PERISHABLE — "once a week is scored, the pre-event
state that produced any prediction is gone unless it was captured before
the outcome was known" — and then shipped with no caller for two weeks.
This script is the caller. `src/ros/game_day_capture.py` holds the
resolution logic; this file owns only fetching, iteration and reporting.

Run it BEFORE a week's first kickoff. It refuses to write a `pregame`
capture once Sleeper is reporting scores for that week (exit 3): a
snapshot reconstructed after the fact and labelled `pregame` is worse
than a missing one, because nothing downstream could tell.

Idempotent: the archive is append-only and refuses a duplicate
(league, season, week, team, capture_kind), which this script reports as
an already-captured skip rather than an error — so a retried cron, or a
second run in the same window, is safe.

Exit codes
    0  every requested league is captured (newly, or already was)
    1  at least one league failed
    2  nothing to do — no leagues configured, or no week resolved
    3  refused — the pregame window has closed for a requested league
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.api import league_registry  # noqa: E402
from src.public_league import sleeper_client  # noqa: E402
from src.ros.game_day_archive import GameDayArchiveError, record_snapshot  # noqa: E402
from src.ros.game_day_capture import (  # noqa: E402
    GameDayCaptureRefusal,
    build_capture,
    estimate_index_from_ensemble,
)


def _resolve_estimates(
    season: int, scoring_settings: dict
) -> tuple[dict, str | None, tuple, tuple]:
    """``(name → fpg, source label, loaded, unavailable)``.

    The only LIVE `PROJECTION_MODEL` sources in the census today are
    `clayProjections` and `idpShowProjections`, both
    `PRESEASON_FULL_SEASON` horizon — there are ZERO live WEEKLY-horizon
    sources (`config/projections/source_capability_census.json`). So the
    per-game figure from a full-season projection is the best available
    Week 1 point estimate, and the label says exactly that rather than
    implying a weekly projection exists.

    Any failure yields no estimates and no label, which the capture
    records as `point_estimate=None` throughout — never 0.0.
    """
    try:
        from src.ros.projection_ensemble import build_ros_full_season_ensemble

        result = build_ros_full_season_ensemble(season=season, scoring_settings=scoring_settings)
    except Exception as exc:  # noqa: BLE001 — a missing snapshot must not lose the roster capture
        print(f"    projections: unavailable ({type(exc).__name__}: {exc})")
        return {}, None, (), ()

    if not result.ensemble:
        print(
            f"    projections: no observations "
            f"(loaded={list(result.sources_loaded)} unavailable={list(result.sources_unavailable)})"
        )
        return {}, None, tuple(result.sources_loaded), tuple(result.sources_unavailable)

    label = f"ros_ensemble:{result.horizon}:equal_family_mean"
    return (
        estimate_index_from_ensemble(result.ensemble),
        label,
        tuple(result.sources_loaded),
        tuple(result.sources_unavailable),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league",
        action="append",
        default=[],
        metavar="KEY",
        help="registry league key; repeatable. Default: every ACTIVE league.",
    )
    parser.add_argument(
        "--capture-kind", default="pregame", choices=["pregame", "in_game", "postgame"]
    )
    parser.add_argument(
        "--season", type=int, default=None, help="override the season Sleeper reports."
    )
    parser.add_argument("--week", type=int, default=None, help="override the week Sleeper reports.")
    parser.add_argument("--run-id", default="", help="ties one batch of captures together.")
    parser.add_argument(
        "--allow-season-type",
        action="append",
        default=None,
        metavar="TYPE",
        help="Sleeper season_type values this run accepts. " "Default: regular, post.",
    )
    parser.add_argument("--dry-run", action="store_true", help="resolve and report, write nothing.")
    args = parser.parse_args()

    if args.league:
        configs = [league_registry.get_league_by_key(k) for k in args.league]
        for key, cfg in zip(args.league, configs):
            if cfg is None:
                print(f"ERROR: unknown league key {key!r}", file=sys.stderr)
        configs = [c for c in configs if c is not None]
    else:
        configs = list(league_registry.active_leagues())

    if not configs:
        print("Nothing to do: no leagues resolved.")
        return 2

    season, week = args.season, args.week
    if season is None or week is None:
        state = sleeper_client.fetch_nfl_state()
        if not state:
            print(
                "ERROR: Sleeper /state/nfl unavailable and no --season/--week given. "
                "Refusing to guess the week.",
                file=sys.stderr,
            )
            return 2
        print(
            f"Sleeper state: season={state.get('season')} week={state.get('week')} "
            f"season_type={state.get('season_type')}"
        )
        # A PRESEASON week 1 is not the regular season's week 1, and the
        # archive keys on (league, season, week, capture_kind) alone —
        # so capturing during the preseason would consume the real Week 1
        # pregame slot with a preseason roster and then REFUSE the genuine
        # capture as a duplicate. The gate is on the host's own
        # season_type rather than a date, and it fails closed.
        allowed = args.allow_season_type or ["regular", "post"]
        season_type = str(state.get("season_type") or "").strip().lower()
        if season_type not in allowed:
            print(
                f"Nothing to do: season_type={season_type!r} is not in {allowed}. "
                "A preseason capture would consume the real week's slot."
            )
            return 2
        if season is None:
            season = int(state.get("season") or 0) or None
        if week is None:
            raw_week = state.get("week")
            week = int(raw_week) if raw_week not in (None, "") else None
    if not season or not week:
        print("Nothing to do: no season/week resolved.")
        return 2

    print(
        f"Capturing {args.capture_kind} for season {season}, week {week} "
        f"across {len(configs)} league(s).{' [DRY RUN]' if args.dry_run else ''}"
    )

    failures = 0
    refusals = 0
    players_meta = sleeper_client.fetch_nfl_players()
    if not players_meta:
        print(
            "ERROR: Sleeper players dump unavailable — positions and eligibility "
            "would be unresolvable.",
            file=sys.stderr,
        )
        return 1

    for cfg in configs:
        key = cfg.key
        print(f"\n  {key}:")
        league_id = league_registry.get_sleeper_league_id(key)
        if not league_id:
            print("    ERROR: no Sleeper league id", file=sys.stderr)
            failures += 1
            continue

        league_payload = sleeper_client.fetch_league(league_id)
        rosters = sleeper_client.fetch_rosters(league_id)
        matchups = sleeper_client.fetch_matchups(league_id, week)
        if not league_payload or not rosters:
            print("    ERROR: Sleeper returned no league payload or no rosters", file=sys.stderr)
            failures += 1
            continue

        estimates, label, loaded, unavailable = _resolve_estimates(
            int(season), dict(league_payload.get("scoring_settings") or {})
        )

        try:
            build = build_capture(
                league_key=key,
                season=int(season),
                week=int(week),
                capture_kind=args.capture_kind,
                league_payload=league_payload,
                rosters=rosters,
                matchups=matchups,
                players_meta=players_meta,
                roster_settings=cfg.roster_settings,
                estimates=estimates,
                estimate_source_label=label,
                sources_loaded=loaded,
                sources_unavailable=unavailable,
            )
        except GameDayCaptureRefusal as exc:
            print(f"    REFUSED: {exc}", file=sys.stderr)
            refusals += 1
            continue
        except ValueError as exc:
            print(f"    ERROR: {exc}", file=sys.stderr)
            failures += 1
            continue

        have, total = build.estimate_coverage
        print(
            f"    teams={len(build.teams)} players={total} "
            f"estimates={have}/{total} slots={len(build.starter_slots)} "
            f"({build.starter_slot_source}) scoring={build.scoring_config_id}"
        )
        for note in build.notes:
            print(f"    note: {note}")
        if args.dry_run:
            continue

        wrote = skipped = 0
        for team in build.teams:
            try:
                record_snapshot(
                    league_key=build.league_key,
                    season=build.season,
                    week=build.week,
                    team_id=team.team_id,
                    capture_kind=build.capture_kind,
                    scoring_config_id=build.scoring_config_id,
                    starter_slots=build.starter_slots,
                    roster=team.roster,
                    run_id=args.run_id,
                )
                wrote += 1
            except GameDayArchiveError:
                # Append-only: this exact tuple is already captured. A
                # retried cron must not overwrite the earlier, EARLIER
                # observation — that one is the better evidence.
                skipped += 1
        print(f"    wrote {wrote} snapshot(s), {skipped} already captured")

    if refusals:
        print(f"\nREFUSED {refusals} league(s): pregame window closed.", file=sys.stderr)
        return 3
    if failures:
        print(f"\nFAILED for {failures} league(s).", file=sys.stderr)
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
