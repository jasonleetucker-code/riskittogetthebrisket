"""Game Day U4 — captured-input replay, resolver -> simulation, end to end.

Fixtures: ``tests/fixtures/game_day/replay/`` (see its README).  ``real_*``
scenarios are trimmed REAL captures taken 2026-09-25 during the Thursday
GB@ATL game (ESPN scoreboard + both leagues' Sleeper matchups + Sleeper
weekly projections).  ``synthetic_*`` scenarios are clearly-labelled
mutations of the real halftime capture.

Every scenario runs the real endpoint assembly
(:func:`src.api.matchup_intel.build_matchup_intel`) with only the network
seams replaced by the captured payloads, and a spy on the league simulation
so the WHOLE league's outcomes — not just the two sides the payload shows —
are checked.  What is asserted is the Game Day acceptance criteria: banked points
retained, remaining only for unfinished players (never baseline minus
actual), matchup and median from one simulation, and every withheld state
named.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

from src.api import matchup_intel
from src.nfl_data.live_game_state import parse_scoreboard
from src.ros import game_day_sim
from src.ros.sleeper_weekly_projections import FetchResult

REPLAY = Path(__file__).resolve().parents[1] / "fixtures" / "game_day" / "replay"
SEASON, WEEK = 2026, 3
TNF_TEAMS = {"GB", "ATL"}
DRAWS = 200


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


PLAYERS = _json(REPLAY / "shared" / "players.json")


def _scenario(name: str) -> dict:
    return _json(REPLAY / name / "scenario.json")


def _fetch(name: str) -> FetchResult:
    raw = _json(REPLAY / "shared" / name)
    return FetchResult(
        status="ok",
        season=SEASON,
        week=WEEK,
        url=f"fixture:{name}",
        observed_at=raw["observedAt"],
        rows=tuple(raw["rows"]),
    )


REAL_FETCH = _fetch("projections_real.json")
PRE_KICKOFF_FETCH = _fetch("projections_synthetic_pre_kickoff.json")


def _schedule_rows(espn: dict) -> list[dict]:
    """nflverse-shaped rows DERIVED from the capture's own ESPN kickoffs.

    The nflverse 2026 schedule cache is not available offline; these rows
    carry only what the join needs (teams + kickoff) and no results, which
    is what nflverse shows for an unfinished week.
    """
    et = ZoneInfo("America/New_York")
    rows = []
    for e in espn["events"]:
        comp = e["competitions"][0]
        kickoff = datetime.fromisoformat(comp["date"].replace("Z", "+00:00")).astimezone(et)
        teams = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        rows.append(
            {
                "season": SEASON,
                "week": WEEK,
                "game_type": "REG",
                "gameday": kickoff.strftime("%Y-%m-%d"),
                "gametime": kickoff.strftime("%H:%M"),
                "home_team": {"WSH": "WAS"}.get(teams["home"], teams["home"]),
                "away_team": {"WSH": "WAS"}.get(teams["away"], teams["away"]),
                "home_score": None,
                "away_score": None,
                "result": None,
            }
        )
    return rows


@dataclass
class Run:
    payload: dict
    sim: game_day_sim.LeagueWeekSimulation | None
    teams: tuple
    now: float


@pytest.fixture(autouse=True)
def _hermetic_sim_cache():
    tmp = tempfile.mkdtemp(prefix="game_day_replay_cache_")
    original = game_day_sim._SIM_CACHE_ROOT
    game_day_sim._SIM_CACHE_ROOT = Path(tmp)
    yield
    game_day_sim._SIM_CACHE_ROOT = original
    shutil.rmtree(tmp, ignore_errors=True)


def _run(
    name: str,
    *,
    league_key: str = "dynasty_main",
    roster_id: int = 4,
    fetches=(PRE_KICKOFF_FETCH, REAL_FETCH),
    weekly_on: bool = True,
    live_on: bool = True,
    snapshot_error: str | None = None,
    observation_age_s: float = 30.0,
    matchups_override=None,
) -> Run:
    sc = _scenario(name)
    league = _json(REPLAY / "shared" / f"{league_key}_league.json")
    matchups = matchups_override or sc["matchups"][league_key]
    rosters = [
        {
            "roster_id": m["roster_id"],
            "owner_id": f"owner-{m['roster_id']}",
            "players": m["players"],
        }
        for m in matchups
    ]
    now_dt = datetime.fromisoformat(sc["meta"]["capturedAt"])
    now = now_dt.timestamp()
    fetched = matchup_intel._LeagueFetch(
        league=league,
        users=[],
        rosters=rosters,
        matchups=matchups,
        players=PLAYERS,
        fetched_at=now,
    )
    if not live_on:
        snapshot = parse_scoreboard(None, observed_at=now_dt, error="flag_disabled", enabled=False)
    elif snapshot_error:
        snapshot = parse_scoreboard(None, observed_at=now_dt, error=snapshot_error)
    else:
        snapshot = parse_scoreboard(
            sc["espn"], observed_at=now_dt - timedelta(seconds=observation_age_s)
        )
    weekly = (tuple(fetches), "ok", None) if weekly_on else ((), "feature_disabled", "flag off")

    captured: dict = {}
    real_cached = matchup_intel.get_cached_league_week_simulation

    def _spy(**kwargs):
        result = real_cached(**kwargs)
        captured["sim"] = result
        captured["teams"] = tuple(kwargs["teams"])
        return result

    with (
        mock.patch.object(matchup_intel, "_fetch_league_week", return_value=fetched),
        mock.patch.object(
            matchup_intel,
            "_schedule_context",
            return_value=(_schedule_rows(sc["espn"]), now - 3600.0, now),
        ),
        mock.patch.object(matchup_intel, "_observe_live_state", return_value=snapshot),
        mock.patch.object(matchup_intel, "_weekly_projection_fetches", return_value=weekly),
        # No BDVM preseason snapshot offline: the fallback basis is absent,
        # which is exactly what an honest replay should see.
        mock.patch.object(matchup_intel, "_resolve_estimates", return_value=({}, None, (), ())),
        mock.patch.object(matchup_intel, "get_cached_league_week_simulation", side_effect=_spy),
    ):
        payload = matchup_intel.build_matchup_intel(
            league_key=league_key,
            sleeper_league_id=str(league["league_id"]),
            owner_id=f"owner-{roster_id}",
            season=SEASON,
            week=WEEK,
            draws=DRAWS,
        )
    return Run(payload, captured.get("sim"), captured.get("teams", ()), now)


def _players(payload: dict) -> dict[str, dict]:
    out = {}
    for side in ("team", "opponent"):
        for p in (payload.get(side) or {}).get("players") or ():
            out[p["playerId"]] = p
    return out


def _tnf(pid: str) -> bool:
    return (PLAYERS.get(pid) or {}).get("team") in TNF_TEAMS


def _points_by_player(matchups) -> dict[str, float]:
    return {pid: pts for m in matchups for pid, pts in (m.get("players_points") or {}).items()}


# ── Invariants shared by every live scenario ──────────────────────────────


def _assert_no_double_counting(run: Run, matchups, *, fraction: float | None) -> None:
    host = _points_by_player(matchups)
    for p in _players(run.payload).values():
        pid = p["playerId"]
        baseline = p["providerBaselinePoints"]
        if p["state"] == "completed":
            assert p["projectedRemaining"] == 0.0
        if p["state"] in ("in_progress", "completed"):
            # Banked is the host's own number, verbatim.
            assert p["pointsScored"] == host.get(pid, 0.0)
        if p["state"] == "not_started" and baseline is not None:
            assert p["remainingBasis"] == "pregame_full_baseline"
            assert p["projectedRemaining"] == pytest.approx(
                baseline + (p["imputedPoints"] or 0.0), abs=0.01
            )
        if p["state"] == "in_progress" and p["projectedRemaining"] is not None:
            assert p["remainingBasis"] == "observed_clock"
            full = baseline + (p["imputedPoints"] or 0.0)
            assert p["projectedRemaining"] == pytest.approx(full * fraction, abs=0.01)
            # Never "baseline minus what he already scored".
            if p["pointsScored"]:
                assert p["projectedRemaining"] != pytest.approx(full - p["pointsScored"], abs=0.01)


def _assert_one_coherent_simulation(run: Run) -> None:
    sim = run.sim
    assert sim is not None
    by_id = {t.team_id: t for t in sim.teams}
    for t in sim.teams:
        # Final best ball can only add to what is banked (remaining >= 0).
        assert t.projected_p10 >= t.points_banked - 1e-9
        if t.opponent_id is not None:
            o = by_id[t.opponent_id]
            assert t.win_matchup_pct + o.win_matchup_pct + t.tie_matchup_pct == pytest.approx(
                100.0, abs=0.02
            )
            assert t.tie_matchup_pct == o.tie_matchup_pct
    # Median leg from the SAME draws as the matchups: with 12 teams, exactly
    # 6 beat the draw's own median on every draw without a tie at it.
    if sim.median_enabled:
        total = sum(t.beat_median_pct for t in sim.teams)
        assert total == pytest.approx(len(sim.teams) * 50.0, abs=0.5)


# ── Real captures ────────────────────────────────────────────────────────

REAL_FRACTIONS = {
    # scenario -> TNF observed regulation fraction left
    "real_end_q1": 0.75,
    "real_q2_in_progress": (2 * 900 + 9 * 60 + 38) / 3600,
    "real_halftime": 0.5,
    "real_q3_in_progress": (900 + 12 * 60 + 26) / 3600,
}


@pytest.mark.parametrize("name", sorted(REAL_FRACTIONS))
def test_real_capture_replays_coherently(name):
    run = _run(name)
    sc = _scenario(name)
    out = run.payload
    assert out["mode"] == "live"
    assert out["probabilityState"] == "AVAILABLE"
    assert out["lineage"]["liveGameState"]["state"] == "observed"
    assert out["lineage"]["weeklyProjection"]["state"] == "ok"
    weekly = out["lineage"]["weeklyProjection"]
    assert weekly["sourceLabel"] == "RotoWire via Sleeper"
    # Read from the census, never restated in the payload code.
    assert weekly["licensingStatus"] == "OWNER_ATTESTED_AUTHORIZED"
    _assert_no_double_counting(run, sc["matchups"]["dynasty_main"], fraction=REAL_FRACTIONS[name])
    _assert_one_coherent_simulation(run)
    tnf = [p for p in _players(out).values() if _tnf(p["playerId"])]
    # In play, or ruled Out by the host (Jayden Reed) — never "unknown".
    assert tnf and all(p["state"] in ("in_progress", "inactive") for p in tnf)
    assert any(p["state"] == "in_progress" for p in tnf)
    ev = out["lineage"]["gameEvidence"]["GB"]
    assert ev["source"] == "espn:scoreboard"
    assert ev["remainingFraction"] == pytest.approx(REAL_FRACTIONS[name])
    # Sunday games observed as scheduled: full baseline, not_started.
    assert out["lineage"]["gameEvidence"]["BAL"]["phase"] == "SCHEDULED"


def test_real_capture_weekly_baselines_cover_k_and_idp_with_named_gaps():
    out = _run("real_halftime").payload
    by_pos: dict[str, int] = {}
    for p in _players(out).values():
        if p["projectionBasis"] == "weekly:rotowire_via_sleeper":
            pos = (PLAYERS[p["playerId"]].get("position") or "").upper()
            by_pos[pos] = by_pos.get(pos, 0) + 1
    assert {"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"} <= set(by_pos)
    idp = [
        p
        for p in _players(out).values()
        if PLAYERS[p["playerId"]].get("position") in ("LB", "DB", "DL") and p["projectionBasis"]
    ]
    # League-paid IDP categories the provider does not project are named,
    # never silently zero.
    assert idp and all("idp_def_td" in p["uncoveredScoringKeys"] for p in idp)
    # dynasty_main pays a first-down bonus RotoWire does not project: it is
    # imputed from the canonical fit and labelled as OUR component.
    qbs = [
        p
        for p in _players(out).values()
        if PLAYERS[p["playerId"]].get("position") == "QB" and p["projectionBasis"]
    ]
    assert qbs and all(p["imputedScoringKeys"] == ["bonus_fd_qb"] for p in qbs)
    assert all("bonus_fd_qb" not in p["uncoveredScoringKeys"] for p in qbs)


def test_real_capture_without_pre_kickoff_fetch_leaves_tnf_players_unpriced():
    """Only the post-kickoff 00:58Z fetch exists for real: it must NOT become
    the TNF players' baseline (an in-game read is not a pregame projection)."""
    run = _run("real_halftime", fetches=(REAL_FETCH,))
    out = run.payload
    counts = out["lineage"]["weeklyProjection"]["counts"]
    assert counts["noPreKickoffObservation"] > 0
    for p in _players(out).values():
        if _tnf(p["playerId"]) and p["state"] == "in_progress":
            assert p["projectionBasis"] is None
            assert p["projectedRemaining"] is None
    # Excluded and reported, never drawn as zero.
    unsim = set(out["team"]["outcome"]["unsimulablePlayerIds"])
    assert {p["playerId"] for p in _players(out).values() if _tnf(p["playerId"])} & unsim


def test_real_in_game_provider_update_never_drifts_a_locked_baseline():
    """REAL 01:28:54Z fetch changed 205 rostered lines, 10 of them GB/ATL.

    TNF players keep their pre-kickoff baseline; Sunday players, still
    pre-kickoff at 01:28Z, take the newer line.
    """
    later = _fetch("projections_real_later_changed_only.json")
    base = _players(_run("real_halftime").payload)
    drift = _players(_run("real_halftime", fetches=(PRE_KICKOFF_FETCH, REAL_FETCH, later)).payload)
    changed = {r["player_id"] for r in later.rows}
    tnf_changed = [pid for pid in changed if pid in base and _tnf(pid)]
    sunday_changed = [
        pid
        for pid in changed
        if pid in base and not _tnf(pid) and base[pid]["projectionBasis"] is not None
    ]
    assert tnf_changed and sunday_changed
    for pid in tnf_changed:
        assert drift[pid]["providerBaselinePoints"] == base[pid]["providerBaselinePoints"]
    moved = [
        pid
        for pid in sunday_changed
        if drift[pid]["providerBaselinePoints"] != base[pid]["providerBaselinePoints"]
    ]
    assert moved, "a pre-kickoff update must reach the Sunday baselines"


def test_real_managed_league_replays_on_declared_starters():
    run = _run("real_halftime", league_key="dynasty_new", roster_id=1)
    out = run.payload
    assert out["lineage"]["bestBall"] is False
    assert out["probabilityState"] == "AVAILABLE"
    _assert_one_coherent_simulation(run)
    starters = {
        s
        for m in _scenario("real_halftime")["matchups"]["dynasty_new"]
        if m["roster_id"] == 1
        for s in m["starters"]
        if s != "0"
    }
    pct = out["team"]["outcome"]["playerLineupPct"]
    assert all(pct[pid] == 100.0 for pid in starters if pid in pct)
    assert all(v == 0.0 for pid, v in pct.items() if pid not in starters)


def test_expected_final_is_distinct_from_the_mean_lineup_and_leverage_is_published():
    # Roster 8 vs 10 is the closest real matchup at halftime (~80/20).
    out = _run("real_halftime", roster_id=8).payload
    outcome = out["team"]["outcome"]
    assert outcome["expectedFinalBestBall"] == outcome["projectedMean"]
    assert out["team"]["expectedLineup"]["basis"] == "optimized_individual_means"
    assert "leverageDefinition" in out["lineage"]
    games = outcome["gameLeverage"]
    assert games, "a team with remaining football must have leverage rows"
    assert all(g["leverage"] is None or -100.0 <= g["leverage"] <= 100.0 for g in games)
    # Sorted strongest first.
    mags = [abs(g["leverage"]) for g in games if g["leverage"] is not None]
    assert mags == sorted(mags, reverse=True)
    assert mags and mags[0] > 0.0, "a contested matchup must have a game that matters"
    # The current lineup is a lineup of players who have PLAYED.
    assert out["team"]["actualLineup"]["lineupState"] == "in_progress"
    for slot in out["team"]["actualLineup"]["slots"]:
        assert _tnf(slot["playerId"])


def test_negative_real_score_is_summed_raw_in_the_current_lineup():
    """Real capture: K Trey Smack (13545) sits at -0.14 at halftime."""
    out = _run("real_halftime").payload
    host = _points_by_player(_scenario("real_halftime")["matchups"]["dynasty_main"])
    assert host["13545"] == pytest.approx(-0.14)
    lineup = out["team"]["actualLineup"]
    assert lineup["knownSubtotal"] == pytest.approx(
        sum(s["points"] for s in lineup["slots"]), abs=1e-9
    )


# ── Synthetic mutations: withheld states are named ────────────────────────


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("synthetic_overtime", "overtime"),
        ("synthetic_end_regulation_tied", "overtime_possible"),
        ("synthetic_delayed", "delayed"),
        ("synthetic_postponed", "postponed"),
    ],
)
def test_unstateable_progress_withholds_probability_with_its_reason(name, reason):
    run = _run(name)
    out = run.payload
    assert out["probabilityState"] == "LIVE_PROGRESS_UNAVAILABLE"
    assert reason in out["progressUnavailableReasons"]
    assert out["team"]["outcome"] is None
    assert run.sim is None  # no fabricated odds
    # Banked points survive the withholding.
    assert out["team"]["actualLineup"]["knownSubtotal"] is not None
    for p in _players(out).values():
        if p["progressUnavailableReason"] == reason:
            assert p["projectedRemaining"] is None


def test_stale_live_feed_is_not_presented_as_current():
    out = _run("real_halftime", observation_age_s=600.0).payload
    assert out["lineage"]["liveGameState"]["stale"] is True
    assert out["probabilityState"] == "LIVE_PROGRESS_UNAVAILABLE"
    assert "stale_live_state" in out["progressUnavailableReasons"]


@pytest.mark.parametrize("error", ["fetch_failed:TimeoutError", "http_error:503"])
def test_missing_live_feed_degrades_to_schedule_only_unknown(error):
    out = _run("real_halftime", snapshot_error=error).payload
    assert out["lineage"]["liveGameState"]["state"] == "unavailable"
    assert out["probabilityState"] == "GAME_STATE_OR_SCORING_UNAVAILABLE"
    unknown = set(out["unknownStatePlayerIds"])
    assert unknown and all(_tnf(pid) for pid in unknown)
    assert out["team"]["outcome"] is None
    # Wall time is never used to invent progress for the begun game.
    assert all(p["remainingBasis"] != "wall_time_fallback" for p in _players(out).values())


def test_both_flags_off_still_answers_honestly():
    out = _run("real_halftime", weekly_on=False, live_on=False).payload
    assert out["lineage"]["liveGameState"]["state"] == "disabled"
    assert out["lineage"]["weeklyProjection"]["state"] == "feature_disabled"
    assert out["probabilityState"] == "GAME_STATE_OR_SCORING_UNAVAILABLE"
    assert out["team"]["actualScore"] is not None


def test_final_game_banks_and_a_stat_correction_moves_only_banked():
    base = _run("synthetic_final")
    tnf_players = [p for p in _players(base.payload).values() if _tnf(p["playerId"])]
    assert tnf_players and all(p["state"] == "completed" for p in tnf_players)
    assert all(p["projectedRemaining"] == 0.0 for p in tnf_players)
    _assert_one_coherent_simulation(base)

    # Stat correction after final: Jordan Love (6804) +1.5 in the host feed.
    matchups = json.loads(json.dumps(_scenario("synthetic_final")["matchups"]["dynasty_main"]))
    for m in matchups:
        if "6804" in (m.get("players_points") or {}):
            m["players_points"]["6804"] = round(m["players_points"]["6804"] + 1.5, 2)
    corrected = _run("synthetic_final", matchups_override=matchups)
    before = _players(base.payload)["6804"]
    after = _players(corrected.payload)["6804"]
    assert after["pointsScored"] == pytest.approx(before["pointsScored"] + 1.5)
    assert after["projectedRemaining"] == 0.0 == before["projectedRemaining"]
    # Every non-corrected player's inputs are unchanged.
    for pid, p in _players(base.payload).items():
        if pid != "6804":
            assert _players(corrected.payload)[pid]["pointsScored"] == p["pointsScored"]
            assert _players(corrected.payload)[pid]["projectedRemaining"] == p["projectedRemaining"]
