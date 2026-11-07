#!/usr/bin/env python3
"""Capture each league's pre-game prediction state into the Game Day archive.

`src/ros/game_day_archive.py` (C5-GD-02) was built specifically because
this observation is PERISHABLE — "once a week is scored, the pre-event
state that produced any prediction is gone unless it was captured before
the outcome was known" — and then shipped with no caller for two weeks.
This script is the caller. `src/ros/game_day_capture.py` holds the
resolution logic; this file owns only fetching, iteration and reporting.

Two pre-event capture kinds, each gated on its OWN kickoff from the nflverse
slate (never an assumed weekday), each written to its own immutable file:

* ``pregame``      — inside 30h of the week's FIRST kickoff (usually the
  Wednesday evening before Thursday Night Football).  Refused once Sleeper is
  reporting scores for the week (exit 3): a snapshot reconstructed after the
  fact and labelled `pregame` is worse than a missing one, because nothing
  downstream could tell.
* ``pregame_late`` — inside 12h of the week's first SUNDAY kickoff (owner
  directive 2026-11-07, Part 7), so Sunday/Monday games are archived against
  the post-injury-report, post-weekend-waiver state rather than Wednesday's.
  Thursday's game has scored by then, so the score gate cannot protect it:
  the schedule must PROVE the capture precedes Sunday's first kickoff, and an
  unknown Sunday kickoff is refused (exit 1), never guessed.

The systemd timer runs ``--capture-kind pregame --capture-kind pregame_late``
every 4 hours; each kind decides independently whether this firing is the
right one, and the exit code combines them (3 > 1 > 0 > 2).

Each written snapshot carries ``provenance``: the kickoff it claims to
precede, the deployed code revision, the projection inputs its estimates came
from, and summaries of the run's capture context.  The context itself — the
injury report as known at capture time (`src/nfl_data/injury_history.py`,
full entries + content hash + fetch time, or ``unavailable`` with a reason,
never an empty "no injuries" list) and the identity of the canonical board
current on the host (payload sha256 + scrapeTimestamp; NOT an input to the
estimates) — is written once per run to
``data/game_day/capture_context/<season>/week_<n>/<kind>__<UTC instant>.json``.

Idempotent: the archive is append-only and refuses a duplicate
(league, season, week, team, capture_kind), which this script reports as
an already-captured skip rather than an error — so a retried cron, or a
second run in the same window, is safe.

Exit codes
    0  every requested league is captured (newly, or already was — including
       after kickoff, when the archive already holds every team's snapshot
       of that kind taken before it)
    1  at least one league failed, or a late capture's Sunday kickoff could
       not be resolved
    2  nothing to do — no leagues configured, no week resolved, or outside
       every requested kind's window
    3  refused — a kind's window has closed for a requested league AND its
       observation is missing (or could not be verified)

Operator verification on the box (week N's early AND late snapshots)
    APP_DIR=/home/dynasty/trade-calculator; cd "$APP_DIR"
    PY=/home/dynasty/.venvs/trade-calculator/bin/python

    # 1. Read-only verdict per kind (exit 0 complete, 3 gap, 2 not yet due):
    "$PY" scripts/capture_game_day_predictions.py --verify --season 2026 --week N

    # 2. The files themselves — one <team>_pregame.json AND one
    #    <team>_pregame_late.json per team, per league:
    for L in data/game_day/predictions/2026/*/; do
      echo "$L early=$(ls "$L"week_N/*_pregame.json 2>/dev/null | wc -l)" \
           "late=$(ls "$L"week_N/*_pregame_late.json 2>/dev/null | wc -l)"
    done
    ls -l data/game_day/capture_context/2026/week_N/

    # 3. Each snapshot's captured instant vs the kickoff it claims to precede:
    grep -h -o '"capturedAt": "[^"]*"\\|"precedesKickoffUtc": "[^"]*"' \\
      data/game_day/predictions/2026/dynasty_main/week_N/1_pregame_late.json

    # 4. What the timer did:
    journalctl -u dynasty-game-day-capture.service --since "-7 days" \\
      | grep -E "window:|wrote|REFUSED|Per-kind"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.api import league_registry  # noqa: E402
from src.public_league import sleeper_client  # noqa: E402
from src.ros.game_day_archive import (  # noqa: E402
    GameDayArchiveError,
    load_capture_contexts,
    load_snapshot,
    load_snapshots_for_week,
    record_capture_context,
    record_snapshot,
)
from src.ros.game_day_capture import (  # noqa: E402
    CAPTURE_WINDOW_HOURS,
    LATE_CAPTURE_WINDOW_HOURS,
    PREGAME_KIND,
    PREGAME_KINDS,
    PREGAME_LATE_KIND,
    GameDayCaptureRefusal,
    board_context_from_payload,
    build_capture,
    combine_exit_codes,
    estimate_index_from_ensemble,
    first_kickoff_utc,
    first_sunday_kickoff_utc,
    injury_context_from_as_known,
    late_pregame_window_state,
    pregame_capture_gaps,
    pregame_window_state,
    snapshot_provenance,
    week_one_waiver_guard,
)
from src.ros.game_day_sim import get_cached_league_week_simulation  # noqa: E402
from src.ros.game_day_week import resolve_pregame_week  # noqa: E402


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


def _uncaptured_pregame(
    configs, season: int, week: int, kickoff, capture_kind: str = PREGAME_KIND
) -> list[tuple[str, str]]:
    """``(league_key, reason)`` for every league whose ``capture_kind``
    observation for this week is NOT fully in the archive -- empty means
    nothing was lost.  ``kickoff`` is the instant that kind claims to precede
    (the week's first kickoff for ``pregame``, its first Sunday kickoff for
    ``pregame_late``).

    Fails closed: a league whose roster list cannot be read is reported as a
    gap ("could not verify"), never assumed captured."""
    gaps: list[tuple[str, str]] = []
    for cfg in configs:
        league_id = league_registry.get_sleeper_league_id(cfg.key)
        rosters = sleeper_client.fetch_rosters(league_id) if league_id else None
        rosters = [
            r for r in rosters or () if isinstance(r, dict) and r.get("roster_id") is not None
        ]
        if not rosters:
            gaps.append((cfg.key, "could not verify: no rosters from Sleeper"))
            continue
        # A roster with no players is never captured (build_capture reports it,
        # the archive refuses an empty snapshot), so it cannot be a lost
        # observation -- counting it would page every run until the week rolls.
        expected = [r["roster_id"] for r in rosters if r.get("players")]
        missing = pregame_capture_gaps(
            expected_team_ids=expected,
            snapshots=load_snapshots_for_week(cfg.key, season, week, capture_kind=capture_kind),
            first_kickoff=kickoff,
            capture_kind=capture_kind,
        )
        if missing:
            gaps.append((cfg.key, f"no {capture_kind} snapshot for team(s) {', '.join(missing)}"))
    return gaps


def _load_schedule(season: int) -> tuple[list | None, str | None]:
    """``(nflverse schedule rows, None)`` or ``(None, reason)``.  Read ONCE per
    run: both pregame kinds resolve their kickoff from the same slate."""
    try:
        from src.nfl_data import ingest as _nfl_ingest

        return list(_nfl_ingest.fetch_schedules([int(season)]) or []), None
    except Exception as exc:  # noqa: BLE001 — a schedule outage must not lose a capture
        print(f"  schedule unavailable ({type(exc).__name__}: {exc})")
        return None, f"schedule_unavailable: {type(exc).__name__}"


def _code_revision() -> dict:
    """The deployed commit the capture ran on (``git rev-parse HEAD``), or
    ``None`` with a reason -- never a guess."""
    import subprocess  # noqa: PLC0415

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"sha": None, "reason": f"{type(exc).__name__}: {exc}"}
    sha = out.stdout.strip()
    if out.returncode != 0 or not sha:
        return {"sha": None, "reason": f"git rev-parse exited {out.returncode}"}
    return {"sha": sha, "reason": None}


def _injury_block(at: datetime) -> dict:
    """The injury report as known at ``at``, via its canonical owner."""
    try:
        from src.nfl_data import injury_history

        if not injury_history.store_dir().is_dir():
            return injury_context_from_as_known(None, error="injury_history_store_missing")
        known = injury_history.as_known_at(at)
    except Exception as exc:  # noqa: BLE001 — context must never lose the roster capture
        return injury_context_from_as_known(None, error=f"{type(exc).__name__}: {exc}")
    return injury_context_from_as_known(known)


def _board_block() -> dict:
    """Identity of the canonical board current on this host, via its owner."""
    try:
        from src.api import sparse_evidence_shadow as ses

        found = ses.newest_live_payload(with_bytes=True)
        budget = ses.stale_budget_hours()
    except Exception as exc:  # noqa: BLE001 — context must never lose the roster capture
        return board_context_from_payload(
            None, stale_budget_hours=None, error=f"{type(exc).__name__}: {exc}"
        )
    return board_context_from_payload(found, stale_budget_hours=budget, repo_root=REPO_ROOT)


class _Run:
    """Per-process state shared by every capture kind of one run."""

    def __init__(self, args, configs, season: int, week: int):
        self.args = args
        self.configs = configs
        self.season = season
        self.week = week
        self._schedule: tuple[list | None, str | None] | None = None
        self._players_meta = None
        self._contexts: dict[str, dict] = {}
        self._revision: dict | None = None

    def schedule(self) -> tuple[list | None, str | None]:
        if self._schedule is None:
            self._schedule = _load_schedule(self.season)
        return self._schedule

    def players_meta(self):
        if self._players_meta is None:
            self._players_meta = sleeper_client.fetch_nfl_players() or {}
        return self._players_meta

    def code_revision(self) -> dict:
        if self._revision is None:
            self._revision = _code_revision()
        return self._revision

    def context(self, kind: str) -> dict:
        """This run's capture context for ``kind``, recorded on first use.

        Taken only when a snapshot is actually about to be written, so a run
        whose teams are all already captured records nothing.  A failure is
        returned as ``unavailable`` with its reason: the roster snapshot is
        the perishable evidence and is written regardless.
        """
        if kind in self._contexts:
            return self._contexts[kind]
        injuries = _injury_block(datetime.now(timezone.utc))
        board = _board_block()
        try:
            path, digest, _record = record_capture_context(
                season=self.season,
                week=self.week,
                capture_kind=kind,
                injuries=injuries,
                canonical_board=board,
                run_id=self.args.run_id,
            )
            try:
                rel = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
            except ValueError:
                rel = str(path)
            ref = {"state": "known", "path": rel, "sha256": digest}
        except Exception as exc:  # noqa: BLE001 — see docstring
            ref = {"state": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
        print(
            f"    context ({kind}): injuries={injuries.get('state')} "
            f"board={board.get('state')} file={ref.get('path') or ref.get('reason')}"
        )
        self._contexts[kind] = {"injuries": injuries, "board": board, "ref": ref}
        return self._contexts[kind]


def _resolve_window(run: _Run, kind: str) -> tuple[str, str, object]:
    """``(state, explanation, kickoff)`` for one pregame kind.

    THE CAPTURE WINDOW IS DERIVED FROM THE SCHEDULE, NOT FROM A WEEKDAY.
    The retired timer assumed a Thursday-night opener; Week 1 of 2026 opens
    on a WEDNESDAY (NE @ SEA, 2026-09-09 20:20 ET = 2026-09-10 00:20 UTC), so
    a Thursday-13:00-UTC run would have been ~13 hours late, been correctly
    refused, and lost the observation for good.  The timer fires several
    times a day and THIS decides which of those firings is the right one --
    for ``pregame`` against the week's first kickoff, for ``pregame_late``
    against its first SUNDAY kickoff.
    """
    rows, schedule_error = run.schedule()
    if kind == PREGAME_LATE_KIND:
        if rows is None:
            sunday, reason = None, schedule_error
        else:
            sunday, reason = first_sunday_kickoff_utc(rows, season=run.season, week=run.week)
        state, why = late_pregame_window_state(
            season=run.season,
            week=run.week,
            sunday_kickoff=sunday,
            kickoff_reason=reason,
            window_hours=run.args.late_window_hours,
        )
        return state, why, sunday
    kickoff = None
    if rows is not None:
        kickoff = first_kickoff_utc(rows, season=run.season, week=run.week)
    state, why = pregame_window_state(first_kickoff=kickoff, window_hours=run.args.window_hours)
    return state, why, kickoff


def _capture_kind(run: _Run, kind: str) -> int:
    """Run one capture kind end to end; returns that kind's exit code."""
    args, season, week, configs = run.args, run.season, run.week, run.configs
    kickoff = None
    precedes_basis = "none"
    if kind in PREGAME_KINDS:
        state, why, kickoff = _resolve_window(run, kind)
        label = "Late pregame window" if kind == PREGAME_LATE_KIND else "Pregame window"
        precedes_basis = (
            "first_sunday_kickoff_of_week" if kind == PREGAME_LATE_KIND else "first_kickoff_of_week"
        )
        print(f"{label}: {state} — {why}")
        if state == "not_applicable":
            print(f"Nothing to do: {kind} does not apply to season {season} week {week}.")
            return 2
        if state == "unknown" and kind == PREGAME_LATE_KIND:
            # No score gate can stand in for the schedule here: Thursday's
            # game has already scored by Sunday, so an unprovable late
            # capture is refused rather than labelled pre-Sunday.
            print(
                f"ERROR: {kind} not captured — the first Sunday kickoff is unknown, so "
                "the capture could not be proven to precede it.",
                file=sys.stderr,
            )
            return 1
        if state == "closed":
            # Closed is only a LOST observation if the archive lacks it.  The
            # timer fires every 4h until Sleeper rolls the week (~5 days after
            # a Thursday opener), so a week captured before kickoff must not
            # page as "unrecoverable" on every one of those runs.
            gaps = _uncaptured_pregame(configs, season, week, kickoff, capture_kind=kind)
            if not gaps:
                print(
                    f"Nothing to do: week {week}'s {kind} observation was captured "
                    "before kickoff for every league."
                )
                return 0
            for key, reason in gaps:
                print(f"  {key}: {reason}", file=sys.stderr)
            # The `pregame` wording is byte-identical to before: the journal
            # stage parser (deploy/diagnostics/performance_inventory.py)
            # matches these lines exactly.
            which = "Sunday kickoff" if kind == PREGAME_LATE_KIND else "kickoff"
            print(f"REFUSED: first {which} has passed.", file=sys.stderr)
            return 3
        if args.ignore_window:
            print("  --ignore-window: proceeding (post-kickoff refusal still applies)")
        elif state == "early":
            print(
                "Nothing to do yet: capturing now would consume the append-only "
                f"{kind} slot with a roster waivers will still change."
            )
            return 2

    # Owner's 2026 Week 1 timing overrides the generic 30h timer window.
    # This guard cannot be bypassed with --ignore-window. Dry runs write
    # nothing and remain useful for preparation before Wednesday.
    if kind == PREGAME_KIND and not args.dry_run and (season, week) == (2026, 1):
        owner_league_id = league_registry.get_sleeper_league_id("dynasty_main")
        transactions = (
            sleeper_client.fetch_transactions(owner_league_id, 1) if owner_league_id else []
        )
        allowed, reason = week_one_waiver_guard(season=season, week=week, transactions=transactions)
        print(f"Week 1 owner timing: {reason}")
        if not allowed:
            return 3

    print(
        f"Capturing {kind} for season {season}, week {week} "
        f"across {len(configs)} league(s).{' [DRY RUN]' if args.dry_run else ''}"
    )

    failures = 0
    refusals = 0
    players_meta = run.players_meta()
    if not players_meta:
        print(
            "ERROR: Sleeper players dump unavailable — positions and eligibility "
            "would be unresolvable.",
            file=sys.stderr,
        )
        return 1

    for cfg in configs:
        key = cfg.key
        print(f"\n  {key} ({kind}):")
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
            season, dict(league_payload.get("scoring_settings") or {})
        )

        try:
            build = build_capture(
                league_key=key,
                season=season,
                week=week,
                capture_kind=kind,
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
            # Same rule as the schedule gate above, for the score gate (which
            # is what decides when no kickoff could be resolved): the week
            # having begun is a lost observation only if the archive lacks it.
            if kind == PREGAME_KIND and not _uncaptured_pregame([cfg], season, week, kickoff):
                print(f"    week has begun; pregame already captured for every team ({exc})")
                continue
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

        # Teams this kind still lacks.  Context is recorded only when there is
        # something to write, so a re-run inside the window adds no files.
        pending = [
            t
            for t in build.teams
            if load_snapshot(build.league_key, build.season, build.week, t.team_id, kind) is None
        ]
        skipped = len(build.teams) - len(pending)
        wrote = 0
        provenance = None
        if pending:
            ctx = run.context(kind)
            try:
                # Round-tripped through JSON here so a provenance value that
                # cannot be serialised is caught BEFORE the roster write, not
                # inside it: provenance must never cost the snapshot itself.
                provenance = json.loads(
                    json.dumps(
                        snapshot_provenance(
                            build,
                            precedes_kickoff=kickoff,
                            precedes_basis=precedes_basis,
                            injuries=ctx["injuries"],
                            canonical_board=ctx["board"],
                            capture_context=ctx["ref"],
                            code_revision=run.code_revision(),
                        ),
                        default=str,
                    )
                )
            except Exception as exc:  # noqa: BLE001 — see comment above
                provenance = {"state": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
        for team in pending:
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
                    provenance=provenance,
                )
                wrote += 1
            except GameDayArchiveError:
                # Append-only: this exact tuple is already captured. A
                # retried cron must not overwrite the earlier, EARLIER
                # observation — that one is the better evidence.
                skipped += 1
        print(f"    wrote {wrote} snapshot(s), {skipped} already captured")

        # Warm the Game Day simulation cache so the pregame window's
        # FIRST real request (any manager checking their matchup) reuses
        # this instead of paying the full draws x teams x lineup-solve
        # cost live. Best-effort: `build_capture` already proved the
        # pregame window is open for this league (same `week_has_begun`
        # gate `resolve_pregame_week` uses below), so a failure here is
        # this league's projections/roster shape, not a stale window —
        # and either way it must never turn THIS script's exit code into
        # a false failure, since the archive write above is its real job.
        # `pregame` only: by Sunday the week HAS begun, so the resolver
        # would refuse a late warm by design.
        if have > 0 and kind == PREGAME_KIND:
            try:
                resolution = resolve_pregame_week(
                    league_key=key,
                    league_payload=league_payload,
                    rosters=rosters,
                    matchups=matchups,
                    players_meta=players_meta,
                    starter_slots=build.starter_slots,
                    estimates=estimates,
                    estimate_source=label,
                )
                sim = get_cached_league_week_simulation(
                    rules=resolution.rules,
                    teams=resolution.teams,
                    opponents=resolution.opponents,
                    season=season,
                    week=week,
                )
                print(f"    sim cache: warmed (already cached={sim.cached})")
            except Exception as exc:  # noqa: BLE001 — see comment above
                print(f"    sim cache: warm skipped ({type(exc).__name__}: {exc})")

    if refusals:
        print(f"\nREFUSED {refusals} league(s): {kind} window closed.", file=sys.stderr)
        return 3
    if failures:
        print(f"\nFAILED for {failures} league(s).", file=sys.stderr)
        return 1
    print("\nDone.")
    return 0


def _verify(run: _Run, kinds: list[str]) -> int:
    """Read-only: does the archive hold each pregame kind for every team,
    captured before the kickoff it claims to precede?  Writes nothing."""
    codes: list[int] = []
    for kind in kinds:
        if kind not in PREGAME_KINDS:
            print(f"{kind}: --verify checks pregame kinds only; skipped")
            continue
        state, why, kickoff = _resolve_window(run, kind)
        print(f"{kind}: window {state} — {why}")
        if state == "not_applicable":
            codes.append(2)
            continue
        for cfg in run.configs:
            snaps = load_snapshots_for_week(cfg.key, run.season, run.week, capture_kind=kind)
            stamps = sorted(s.captured_at for s in snaps)
            print(
                f"  {cfg.key}: {len(snaps)} snapshot(s)"
                + (f", captured {stamps[0]} .. {stamps[-1]}" if stamps else "")
            )
        contexts = load_capture_contexts(run.season, run.week, capture_kind=kind)
        print(f"  capture-context files: {len(contexts)}")
        gaps = _uncaptured_pregame(run.configs, run.season, run.week, kickoff, capture_kind=kind)
        for key, reason in gaps:
            print(f"  GAP {key}: {reason}")
        if gaps:
            codes.append(3)
        elif state in ("early", "open") and not any(
            load_snapshots_for_week(c.key, run.season, run.week, capture_kind=kind)
            for c in run.configs
        ):
            codes.append(2)  # window not yet passed and nothing captured yet
        else:
            codes.append(0)
    return combine_exit_codes(codes)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--league",
        action="append",
        default=[],
        metavar="KEY",
        help="registry league key; repeatable. Default: every ACTIVE league.",
    )
    parser.add_argument(
        "--capture-kind",
        action="append",
        default=None,
        choices=["pregame", "pregame_late", "in_game", "postgame"],
        help="repeatable; each kind is gated and reported independently. Default: pregame.",
    )
    parser.add_argument(
        "--season", type=int, default=None, help="override the season Sleeper reports."
    )
    parser.add_argument("--week", type=int, default=None, help="override the week Sleeper reports.")
    parser.add_argument("--run-id", default="", help="ties one batch of captures together.")
    parser.add_argument(
        "--ignore-window",
        action="store_true",
        help="capture regardless of how far off kickoff is. For an owner-authorized "
        "manual capture; the post-kickoff refusal still applies and is not bypassable.",
    )
    parser.add_argument(
        "--window-hours",
        type=float,
        default=CAPTURE_WINDOW_HOURS,
        help="hours before the week's first kickoff that the pregame window opens "
        f"(default {CAPTURE_WINDOW_HOURS:g}).",
    )
    parser.add_argument(
        "--late-window-hours",
        type=float,
        default=LATE_CAPTURE_WINDOW_HOURS,
        help="hours before the week's first SUNDAY kickoff that the pregame_late window "
        f"opens (default {LATE_CAPTURE_WINDOW_HOURS:g}).",
    )
    parser.add_argument(
        "--allow-season-type",
        action="append",
        default=None,
        metavar="TYPE",
        help="Sleeper season_type values this run accepts. " "Default: regular, post.",
    )
    parser.add_argument("--dry-run", action="store_true", help="resolve and report, write nothing.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="read-only: report whether each pregame kind is archived for every team "
        "before its kickoff (exit 0 complete, 3 gap, 2 not yet due). Writes nothing.",
    )
    args = parser.parse_args()
    # Order-preserving de-duplication: `--capture-kind pregame` twice is one kind.
    kinds = list(dict.fromkeys(args.capture_kind or [PREGAME_KIND]))
    if args.verify and args.capture_kind is None:
        kinds = list(PREGAME_KINDS)

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

    run = _Run(args, configs, int(season), int(week))
    if args.verify:
        return _verify(run, kinds)

    codes: dict[str, int] = {}
    for kind in kinds:
        if len(kinds) > 1:
            print(f"\n=== {kind} ===")
        codes[kind] = _capture_kind(run, kind)
    if len(kinds) > 1:
        print("\nPer-kind exit codes: " + ", ".join(f"{k}={c}" for k, c in codes.items()))
    return combine_exit_codes(list(codes.values()))


if __name__ == "__main__":
    raise SystemExit(main())
