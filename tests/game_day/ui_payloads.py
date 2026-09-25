"""Game Day U7 — real ``/api/matchup/intel`` payloads for the UI, from the U4 replay.

The Game Day UI is a pure renderer of the matchup payload, so its component
tests must read what the backend ACTUALLY emits rather than a hand-written
approximation of it.  This module runs the real endpoint assembly
(:func:`src.api.matchup_intel.build_matchup_intel`) over the captured replay
inputs in ``tests/fixtures/game_day/replay/`` — the same seams
``test_game_day_replay.py`` replaces, nothing else — and writes the JSON the
frontend tests load from ``frontend/__tests__/fixtures/game-day/``.

``test_game_day_ui_fixtures.py`` regenerates every scenario and fails if a
committed fixture differs, so a backend change that alters what the UI reads
cannot land without the UI fixtures (and therefore the UI tests) seeing it.

Regenerate::

    python -m tests.game_day.ui_payloads

Labelling.  Team names are replay labels (``Team 8``), never real managers.
Every non-capture input is named in each fixture's ``_fixture.description``:
the pregame scenario re-stamps the REAL 00:58Z weekly projections fetch as
observed at 00:11Z so a pre-kickoff board exists (no capture predates kickoff)
— exactly the ``projections_synthetic_pre_kickoff.json`` caveat, applied to
every game — and ``week-final`` finishes the rest of the week synthetically.
Volatile fields that describe the machine rather than the payload
(simulation cache timestamps, the local pregame archive) are normalized.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from src.api import matchup_intel
from src.nfl_data.live_game_state import parse_scoreboard
from src.ros import game_day_sim
from tests.game_day.test_game_day_replay import (
    PLAYERS,
    PRE_KICKOFF_FETCH,
    REAL_FETCH,
    REPLAY,
    SEASON,
    WEEK,
    _json,
    _scenario,
    _schedule_rows,
)

OUT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "__tests__" / "fixtures" / "game-day"
#: Enough draws for stable leverage rows; the replay suite's own count is 200.
DRAWS = 400
#: Roster 8 vs 10 is the closest real matchup in the capture (~80/20 at halftime).
ROSTER = 8

#: name -> (scenario dir, options, description)
SCENARIOS: dict[str, tuple[str, dict, str]] = {
    "pregame": (
        "real_end_q1",
        {"pregame": True},
        "SYNTHETIC CLOCK over real inputs: now = 2026-09-25T00:12Z (before GB@ATL "
        "kickoff); live feed not yet consulted; the REAL 00:58Z weekly projection "
        "fetch re-stamped as observed 00:11Z.",
    ),
    "halftime": ("real_halftime", {}, "REAL capture: GB@ATL halftime."),
    "overtime": (
        "synthetic_overtime",
        {},
        "SYNTHETIC: real halftime capture with GB@ATL rewritten to overtime.",
    ),
    "final": (
        "real_final",
        {},
        "REAL capture: GB@ATL final; the host week is otherwise unplayed, so the "
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
        "lineup total of those points (two-pass build).",
    ),
    "live-feed-down": (
        "real_halftime",
        {"snapshot_error": "fetch_failed:TimeoutError"},
        "REAL halftime capture with the live scoreboard read failing.",
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


def build(name: str) -> dict:
    """The normalized payload for one UI scenario (see :data:`SCENARIOS`)."""
    scenario_dir, opts, description = SCENARIOS[name]
    sc = json.loads(json.dumps(_scenario(scenario_dir)))
    if opts.get("week_final"):
        _week_final(sc)
        sc["meta"]["capturedAt"] = "2026-09-29T12:00:00+00:00"
        # Pass 1 reads the canonical lineup totals; pass 2 states them as the
        # host totals (labelled in the scenario description).
        first = _build_payload(sc, opts, all_rosters=True)
        for m in sc["matchups"]["dynasty_main"]:
            m["points"] = first[str(m["roster_id"])]
    return _finish(_build_payload(sc, opts), scenario_dir, description)


def _build_payload(sc: dict, opts: dict, *, all_rosters: bool = False):
    league = _json(REPLAY / "shared" / "dynasty_main_league.json")
    matchups = sc["matchups"]["dynasty_main"]
    pregame = bool(opts.get("pregame"))
    if pregame:
        now_dt = datetime.fromisoformat("2026-09-25T00:12:00+00:00")
        # No player has played: the host reports nothing banked yet.
        matchups = [
            {**m, "points": 0.0, "players_points": {pid: 0.0 for pid in m["players"]}}
            for m in matchups
        ]
    else:
        now_dt = datetime.fromisoformat(sc["meta"]["capturedAt"])
    now = now_dt.timestamp()
    rosters = [
        {
            "roster_id": m["roster_id"],
            "owner_id": f"owner-{m['roster_id']}",
            "players": m["players"],
        }
        for m in matchups
    ]
    fetched = matchup_intel._LeagueFetch(
        league=league,
        users=_users(matchups),
        rosters=rosters,
        matchups=matchups,
        players=PLAYERS,
        fetched_at=now,
    )
    if pregame:
        snapshot = parse_scoreboard(None, observed_at=now_dt, error="flag_disabled", enabled=False)
        fetches = (replace(REAL_FETCH, observed_at="2026-09-25T00:11:00+00:00"),)
    elif opts.get("snapshot_error"):
        snapshot = parse_scoreboard(None, observed_at=now_dt, error=opts["snapshot_error"])
        fetches = (PRE_KICKOFF_FETCH, REAL_FETCH)
    else:
        snapshot = parse_scoreboard(sc["espn"], observed_at=now_dt - timedelta(seconds=30))
        fetches = (PRE_KICKOFF_FETCH, REAL_FETCH)

    tmp = tempfile.mkdtemp(prefix="game_day_ui_payloads_")
    original_root = game_day_sim._SIM_CACHE_ROOT
    game_day_sim._SIM_CACHE_ROOT = Path(tmp)
    try:
        with (
            mock.patch.object(matchup_intel, "_fetch_league_week", return_value=fetched),
            mock.patch.object(
                matchup_intel,
                "_schedule_context",
                return_value=(_schedule_rows(sc["espn"]), now - 3600.0, now),
            ),
            mock.patch.object(matchup_intel, "_observe_live_state", return_value=snapshot),
            mock.patch.object(
                matchup_intel, "_weekly_projection_fetches", return_value=(fetches, "ok", None)
            ),
            mock.patch.object(matchup_intel, "_resolve_estimates", return_value=({}, None, (), ())),
            mock.patch.object(
                matchup_intel,
                "_archive_evidence",
                return_value={"state": "not_captured", "teamsCaptured": 0},
            ),
        ):
            if all_rosters:
                totals = {}
                for m in matchups:
                    out = matchup_intel.build_matchup_intel(
                        league_key="dynasty_main",
                        sleeper_league_id=str(league["league_id"]),
                        owner_id=f"owner-{m['roster_id']}",
                        season=SEASON,
                        week=WEEK,
                        draws=DRAWS,
                    )
                    totals[str(m["roster_id"])] = out["team"]["actualLineup"]["total"]
                return totals
            return matchup_intel.build_matchup_intel(
                league_key="dynasty_main",
                sleeper_league_id=str(league["league_id"]),
                owner_id=f"owner-{ROSTER}",
                season=SEASON,
                week=WEEK,
                draws=DRAWS,
            )
    finally:
        game_day_sim._SIM_CACHE_ROOT = original_root
        shutil.rmtree(tmp, ignore_errors=True)


def _finish(payload: dict, scenario_dir: str, description: str) -> dict:
    payload = json.loads(json.dumps(payload, default=list))
    sim = (payload.get("lineage") or {}).get("simulation")
    if sim:
        # Machine-local cache facts, not properties of the payload.
        sim["cached"] = False
        sim["cacheComputedAt"] = payload["lineage"].get("sleeperFetchedAt")
    payload["_fixture"] = {
        "scenario": scenario_dir,
        "description": description,
        "generator": "tests/game_day/ui_payloads.py",
        "draws": DRAWS,
        "rosterId": ROSTER,
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
