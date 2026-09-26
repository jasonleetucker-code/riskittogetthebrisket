"""Game Day U7 — real ``/api/matchup/intel`` payloads for the UI, from the U4 replay.

The Game Day UI is a pure renderer of the matchup payload, so its component
tests (and the /game-day E2E spec) must read what the backend ACTUALLY
emits rather than a hand-written approximation of it.  This module drives
the PRODUCTION path end to end over the captured replay inputs in
``tests/fixtures/game_day/replay/``:

1. the U5 shared collector (``src.ros.game_day_live.run_tick``) ticks with
   only its network clients replaced by the captures — the same
   ``FixtureWorld`` the collector suite uses — and writes a versioned
   generation to a private temporary ``LIVE_ROOT``;
2. ``src.api.matchup_intel.build_matchup_intel`` then SERVES that generation
   (its request-path network seam raises, so nothing is recomputed) with the
   collector's ``freshness`` block, exactly as ``GET /api/matchup/intel``
   would.

Output: ``frontend/__tests__/fixtures/game-day/*.json``.
``test_game_day_ui_fixtures.py`` regenerates every scenario and requires
byte equality, so a backend change to anything the UI reads fails there
until the fixtures (and therefore the UI tests) are regenerated with it::

    python -m tests.game_day.ui_payloads

Labelling.  Team names are replay labels (``Team 8``), never real managers.
Every non-capture input is named in each fixture's ``_fixture.description``.
The wall clock is pinned to the scenario's own clock throughout (collector
tick, simulation cache stamp, freshness ages), so the output is
deterministic; the local pregame archive is normalized to "not captured".
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.api import matchup_intel
from src.ros import game_day_live as live
from src.ros import game_day_sim
from tests.game_day.test_game_day_live_collector import (
    LEAGUES,
    TNF_KICKOFF,
    FixtureWorld,
    _pregame_espn,
    _replay_seams,
)
from tests.game_day.test_game_day_replay import (
    PLAYERS,
    REAL_FETCH,
    SEASON,
    WEEK,
    _scenario,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "__tests__" / "fixtures" / "game-day"
#: Enough draws for stable leverage rows (production serves 2000).
DRAWS = 400
SEED = game_day_sim.DEFAULT_SEED
#: Roster 8 vs 10 is the closest real matchup in the capture (~80/20 at halftime).
ROSTER = 8
#: Roster 8's scheduled opponent in the capture: the team-switcher scenario
#: serves the same generation from this side.
OPPONENT_ROSTER = 10
#: A served payload is read this long after the tick that produced it.
SERVE_LAG_SECONDS = 20.0
#: The weekly-projection fetch every scenario's pre-kickoff collector tick
#: sees: the REAL 00:58Z fetch re-stamped as observed 00:10Z (LABELLED
#: SYNTHETIC — no capture predates the TNF kickoff; the same caveat as
#: ``projections_synthetic_pre_kickoff.json``, applied to every game so the
#: Sunday players hold a baseline, as a collector running all week would).
PRE_KICKOFF_WEEKLY = replace(REAL_FETCH, observed_at="2026-09-25T00:10:00+00:00")

#: name -> (scenario dir, options, description)
SCENARIOS: dict[str, tuple[str, dict, str]] = {
    "pregame": (
        "real_end_q1",
        {"pregame": True},
        "SYNTHETIC CLOCK over real inputs: collector tick at 2026-09-25T00:12Z "
        "(before GB@ATL kickoff), every ESPN game rewritten to scheduled, no points "
        "banked, and the REAL 00:58Z weekly projection fetch re-stamped as observed "
        "00:11Z so a full pre-kickoff board exists.",
    ),
    "halftime": (
        "real_halftime",
        {},
        "REAL capture: GB@ATL halftime.  Collector ticked once pre-kickoff and once "
        "at capture (see PRE_KICKOFF_WEEKLY).",
    ),
    "overtime": (
        "synthetic_overtime",
        {},
        "SYNTHETIC: real halftime capture with GB@ATL rewritten to overtime.",
    ),
    "final": (
        "real_final",
        {},
        "REAL capture: GB@ATL final; the rest of the week is unplayed, so the "
        "matchup is still live (Sunday games scheduled).",
    ),
    "mixed-slate": (
        "synthetic_mixed_slate",
        {},
        "SYNTHETIC: real TNF final + Sunday 1pm games at every stage.",
    ),
    "week-final": (
        "real_final",
        {"week_final": True},
        "SYNTHETIC: real TNF final capture with every other game of the week rewritten "
        "to STATUS_FINAL at a synthetic now of 2026-09-29T12:00Z; players of those games "
        "get deterministic synthetic points (pid%17 x 0.75, -1.25 when pid%13==0, the "
        "mixed-slate rule) and each host team total is set to the canonical best-ball "
        "total of those points (two-pass build).",
    ),
    "halftime-opponent": (
        "real_halftime",
        {"roster": OPPONENT_ROSTER},
        "REAL capture: GB@ATL halftime served from the OPPONENT's perspective "
        "(roster 10, the scheduled opponent of the default fixture's roster 8) "
        "out of the same collector generation — the Game Day team switcher.",
    ),
    "live-feed-down": (
        "real_halftime",
        {"espn_error": "http_error:403"},
        "REAL halftime capture with every ESPN scoreboard read refused (HTTP 403, as "
        "observed from at least one location on 2026-09-25) — partial live state.",
    ),
    "pending": (
        "real_halftime",
        {"cold": True},
        "REAL halftime capture served cold: no collector generation exists, so the "
        "request answers PENDING from the factual inputs (host scores, game states, "
        "the banked best-ball lineup) while the one background compute runs.  The "
        "background attempt is a deterministic stand-in started at the request "
        "(the thread itself is not run by the generator).",
    ),
    "stale": (
        "real_halftime",
        {"serve_lag": 7200.0},
        "REAL halftime capture served two hours after the collector's last tick (no "
        "tick since) — the generation is served as-is at its true age, marked stale.",
    ),
}


def _users(matchups) -> list[dict]:
    return [
        {
            "user_id": f"owner-{m['roster_id']}",
            "display_name": f"Team {m['roster_id']}",
            "metadata": {"team_name": f"Replay roster {m['roster_id']}"},
        }
        for m in matchups
    ]


class _World(FixtureWorld):
    """The collector suite's fixture world: one league, labelled team names."""

    def clients(self) -> live.Clients:
        base = super().clients()
        league = LEAGUES["dynasty_main"]
        return dataclasses.replace(
            base,
            users=lambda sid: _users(self._matchups("dynasty_main")),
            leagues=lambda: [live.LeagueTarget("dynasty_main", str(league["league_id"]), {})],
        )

    def tick(self, **kw) -> live.TickReport:
        return live.run_tick(
            clients=self.clients(), clock=self.clock, force=True, draws=DRAWS, seed=SEED, **kw
        )


def _week_final(sc: dict) -> None:
    """Every game of the week final; unplayed players get the mixed-slate points rule."""
    finished: set[str] = set()
    for e in sc["espn"]["events"]:
        comp = e["competitions"][0]
        comp["status"] = {
            "clock": 0.0,
            "displayClock": "0:00",
            "period": 4,
            "type": {
                "name": "STATUS_FINAL",
                "state": "post",
                "completed": True,
                "shortDetail": "Final",
            },
        }
        for c in comp["competitors"]:
            c.setdefault("score", "20")
            finished.add({"WSH": "WAS"}.get(c["team"]["abbreviation"], c["team"]["abbreviation"]))
    for m in sc["matchups"]["dynasty_main"]:
        pts = m.setdefault("players_points", {})
        for pid in m["players"]:
            if pid in pts:
                continue
            if (PLAYERS.get(pid) or {}).get("team") in finished:
                value = (int(pid) % 17) * 0.75 - (1.25 if int(pid) % 13 == 0 else 0.0)
                pts[pid] = round(value, 2)
        m["points"] = None


def _tick(world: _World) -> None:
    with mock.patch("time.time", side_effect=lambda: world.clock()):
        report = world.tick()
    league = report.leagues.get("dynasty_main") or {}
    if report.exit_code != 0 or not league.get("ok"):
        raise RuntimeError(f"collector tick failed: {report.outcome} {report.error} {league}")


def _serve(owner_id: str, now: float) -> dict:
    league = LEAGUES["dynasty_main"]
    with (
        mock.patch("time.time", return_value=now),
        mock.patch.object(
            matchup_intel, "_fetch_league_week", side_effect=RuntimeError("replay: no network")
        ),
        mock.patch.object(
            matchup_intel,
            "_archive_evidence",
            return_value={"state": "not_captured", "teamsCaptured": 0},
        ),
    ):
        return matchup_intel.build_matchup_intel(
            league_key="dynasty_main",
            sleeper_league_id=str(league["league_id"]),
            owner_id=owner_id,
            season=SEASON,
            week=WEEK,
            draws=DRAWS,
            seed=SEED,
        )


def _run_world(sc: dict, opts: dict) -> tuple[_World, float]:
    """Tick the collector over ``sc`` the way it would have run; returns the world."""
    captured = datetime.fromisoformat(sc["meta"]["capturedAt"]).timestamp()
    world = _World("real_halftime", now=TNF_KICKOFF - 300)
    world.sc = sc
    world.captured_at = captured
    if opts.get("espn_error"):
        world.espn_error = opts["espn_error"]
    if opts.get("pregame"):
        now = datetime(2026, 9, 25, 0, 12, tzinfo=timezone.utc).timestamp()
        world.clock.ts = now
        world.sc = {
            **sc,
            "matchups": {
                k: [
                    {**m, "points": 0.0, "players_points": {p: 0.0 for p in m["players"]}}
                    for m in rows
                ]
                for k, rows in sc["matchups"].items()
            },
        }
        world.espn_override = _pregame_espn(sc["espn"])
        world.weekly_result = replace(REAL_FETCH, observed_at="2026-09-25T00:11:00+00:00")
        _tick(world)
        return world, now
    # A pre-kickoff tick (every game scheduled, the pre-kickoff weekly fetch),
    # then the capture itself — how the collector would have seen the night.
    if not opts.get("espn_error"):
        world.espn_override = _pregame_espn(sc["espn"])
    world.weekly_result = PRE_KICKOFF_WEEKLY
    _tick(world)
    world.clock.ts = captured
    world.espn_override = None
    world.weekly_result = REAL_FETCH
    _tick(world)
    return world, captured


def _build_cold(scenario_dir: str) -> dict:
    """A cold request: no generation, the background compute reported running."""
    captured = datetime.fromisoformat(_scenario(scenario_dir)["meta"]["capturedAt"]).timestamp()
    now = captured + 1.0
    attempt = live.BackgroundAttempt(
        league_key="dynasty_main",
        season=SEASON,
        week=WEEK,
        reason="no_collector_generation",
        started_at=now,
    )
    running = {"state": "running", "triggered": True, **attempt.to_dict(), "previous": None}
    with (
        _replay_seams(scenario_dir) as league,
        mock.patch.object(live, "ensure_background_compute", return_value=running),
        mock.patch("time.time", return_value=now),
    ):
        return matchup_intel.build_matchup_intel(
            league_key="dynasty_main",
            sleeper_league_id=str(league["league_id"]),
            owner_id=f"owner-{ROSTER}",
            season=SEASON,
            week=WEEK,
            draws=DRAWS,
            seed=SEED,
        )


def build(name: str) -> dict:
    """The served payload for one UI scenario (see :data:`SCENARIOS`)."""
    scenario_dir, opts, description = SCENARIOS[name]
    sc = json.loads(json.dumps(_scenario(scenario_dir)))
    tmp = Path(tempfile.mkdtemp(prefix="game_day_ui_payloads_"))
    saved = (live.LIVE_ROOT, game_day_sim._SIM_CACHE_ROOT)
    live.LIVE_ROOT = tmp / "live"
    game_day_sim._SIM_CACHE_ROOT = tmp / "sim"
    live._generation_cache.clear()
    matchup_intel._weekly_memo.clear()
    matchup_intel._live_state_memo.clear()
    try:
        if opts.get("cold"):
            return _finish(_build_cold(scenario_dir), scenario_dir, description)
        if opts.get("week_final"):
            _week_final(sc)
            sc["meta"]["capturedAt"] = "2026-09-29T12:00:00+00:00"
            world, now = _run_world(sc, opts)
            # Pass 2: state the canonical best-ball totals as the host's.
            for m in sc["matchups"]["dynasty_main"]:
                side = _serve(f"owner-{m['roster_id']}", now + SERVE_LAG_SECONDS)["team"]
                m["points"] = side["scoreNow"]["bestBallFromBankedPoints"]
            world.sc = sc
            world.clock.ts = now + 60.0
            _tick(world)
            now = world.clock()
        else:
            world, now = _run_world(sc, opts)
        roster = opts.get("roster", ROSTER)
        payload = _serve(f"owner-{roster}", now + opts.get("serve_lag", SERVE_LAG_SECONDS))
    finally:
        live.LIVE_ROOT, game_day_sim._SIM_CACHE_ROOT = saved
        live._generation_cache.clear()
        shutil.rmtree(tmp, ignore_errors=True)
    return _finish(payload, scenario_dir, description, roster=opts.get("roster", ROSTER))


def _finish(payload: dict, scenario_dir: str, description: str, roster: int = ROSTER) -> dict:
    payload = json.loads(json.dumps(payload, default=list))
    payload["_fixture"] = {
        "scenario": scenario_dir,
        "description": description,
        "generator": "tests/game_day/ui_payloads.py",
        "draws": DRAWS,
        "rosterId": roster,
    }
    return payload


def fixture_path(name: str) -> Path:
    return OUT_DIR / f"{name}.json"


def serialize(payload: dict) -> str:
    # Compact: these are generated API payloads (one line each); inspect them
    # with a JSON viewer rather than a diff.
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None) -> int:
    names = (argv if argv else None) or list(SCENARIOS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in names:
        fixture_path(name).write_text(serialize(build(name)), encoding="utf-8")
        print(f"wrote {fixture_path(name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
