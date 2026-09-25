"""Game Day D — a post-final host point change propagates, and history keeps what was known.

Uses the REAL post-final change in the 2026-09-25 TNF replay: between the
first observed final (``real_final_first_seen``, 03:18:41Z) and the next
capture (``real_final``, 03:24:47Z) the host moved two finished players'
points in ``dynasty_main`` roster 4 — 6804 (Jordan Love) 22.07 -> 18.30 and
11559 (Michael Penix) 19.01 -> 18.83 — with GB@ATL final in both.  The
capture cannot tell a stat correction from feed catch-up; either way it is
the host changing a finished player's points, which is what must propagate.

Each link of the chain is its own assertion:

1. the raw league observation log records both host values, append-only;
2. the collector's input fingerprint changes BECAUSE of that change (the
   same tick with the old host points is ``inputs_unchanged``);
3. a NEW generation is published, and the superseded one is retained in the
   generation history with ``supersedes`` linking them;
4. the current lineup, ``scoreNow``, ``expectedFinalBestBall`` and the
   win / beat-median probabilities are recomputed from the corrected value;
5. the ORIGINAL as-known values stay retrievable — from the raw log (by the
   generation's ``leagueObservationSeq``) and from the prior generation's
   history row.

Plus the diagnostic half (labelled synthetic stat lines — the captures hold
host points, not Sleeper's v1 stat dump): a live-stats change to a finished
player that the host has NOT absorbed is reported as
``stat_correction_pending_host`` and never rescored; once the host moves it
is ``reflected_in_host``; a change the league does not score is
``not_scored_by_league``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.nfl_data.sleeper_live_stats import parse_week_stats
from src.ros import game_day_live as live
from tests.game_day.test_game_day_live_collector import (
    DRAWS,
    SEED,
    FixtureWorld,
    _serve,
)
from tests.game_day.test_game_day_replay import SEASON, WEEK, _scenario

KEY = "dynasty_main"
ROSTER = "4"
CHANGED = {"6804": (22.07, 18.3), "11559": (19.01, 18.83)}
BANKED_DROP = round(sum(before - after for before, after in CHANGED.values()), 2)  # 3.95


def _side(gen: dict) -> dict:
    return gen["render"]["sides"][ROSTER]


def _points(side: dict) -> dict[str, float]:
    return {p["playerId"]: p["pointsScored"] for p in side["players"]}


def _lineup_points(side: dict) -> dict[str, float]:
    return {s["playerId"]: s["points"] for s in side["actualLineup"]["slots"]}


def _tnf_final(gen: dict) -> bool:
    ev = gen["render"]["lineage"]["gameEvidence"]
    return ev["GB"]["state"] == "completed" and ev["ATL"]["state"] == "completed"


def _two_ticks():
    world = FixtureWorld("real_final_first_seen")
    first = world.tick()
    gen1 = live.load_generation(KEY, SEASON, WEEK)
    world.set_scenario("real_final")
    world.clock.ts = world.captured_at
    second = world.tick()
    gen2 = live.load_generation(KEY, SEASON, WEEK)
    return world, first, second, gen1, gen2


class TestRealPostFinalChangePropagates:
    def test_link1_the_raw_log_records_both_host_values_append_only(self):
        _, first, second, gen1, gen2 = _two_ticks()
        assert _tnf_final(gen1) and _tnf_final(gen2), "GB@ATL must be final in both"
        obs = live.observation_log(KEY, SEASON, WEEK, live.SOURCE_LEAGUE).observations()
        assert len(obs) == 2
        for pid, (before, after) in CHANGED.items():
            assert obs[0].content[f"matchup:{ROSTER}"]["players_points"][pid] == before
            assert obs[1].content[f"matchup:{ROSTER}"]["players_points"][pid] == after

    def test_link2_the_fingerprint_changes(self):
        _, _, _, gen1, gen2 = _two_ticks()
        assert gen1["inputFingerprint"] != gen2["inputFingerprint"]

    def test_link2_it_changes_because_of_the_host_value(self):
        """Counterfactual: the SECOND capture's scoreboard and clock with the
        FIRST capture's host points is the same input — nothing else between
        the two captures moves the fingerprint."""
        world = FixtureWorld("real_final_first_seen")
        world.tick()
        first_matchups = json.loads(json.dumps(world.sc["matchups"]))
        world.set_scenario("real_final")
        world.sc = {**world.sc, "matchups": first_matchups}
        world.clock.ts = world.captured_at
        report = world.tick()
        assert report.leagues[KEY]["outcome"] == "inputs_unchanged"

    def test_link3_a_new_generation_is_published_and_the_old_one_retained(self):
        _, first, second, gen1, gen2 = _two_ticks()
        assert first.leagues[KEY]["outcome"] == "generation_written"
        assert second.leagues[KEY]["outcome"] == "generation_written"
        assert gen2["generationId"] != gen1["generationId"]
        assert gen2["supersedes"] == gen1["generationId"]
        history = live.load_generation_history(KEY, SEASON, WEEK)
        assert [h["generationId"] for h in history] == [
            gen1["generationId"],
            gen2["generationId"],
        ]
        assert history[1]["supersedes"] == gen1["generationId"]
        assert history[0]["inputFingerprint"] == gen1["inputFingerprint"]

    def test_link4_lineup_score_expected_final_and_probabilities_use_the_corrected_value(self):
        _, _, _, gen1, gen2 = _two_ticks()
        s1, s2 = _side(gen1), _side(gen2)
        for pid, (before, after) in CHANGED.items():
            assert _points(s1)[pid] == before and _points(s2)[pid] == after
            # Both stay in the best-ball lineup, at the corrected points.
            assert _lineup_points(s1)[pid] == before
            assert _lineup_points(s2)[pid] == after
        banked1 = s1["scoreNow"]["bestBallFromBankedPoints"]
        banked2 = s2["scoreNow"]["bestBallFromBankedPoints"]
        assert banked1 - banked2 == pytest.approx(BANKED_DROP, abs=1e-6)
        assert s2["pointsBanked"] == pytest.approx(banked2)
        # The host's own team total moved with it (and is published beside
        # ours, never overwriting it).
        assert (s1["scoreNow"]["hostReportedTotal"], s2["scoreNow"]["hostReportedTotal"]) == (
            52.82,
            49.05,
        )
        # A NEW simulation ran on the corrected inputs (same draws, seed) —
        # computed, not served from the simulation cache.
        assert gen2["simulation"]["cached"] is False
        assert (gen2["draws"], gen2["seed"]) == (gen1["draws"], gen1["seed"])
        o1, o2 = s1["outcome"], s2["outcome"]
        drop = o1["expectedFinalBestBall"] - o2["expectedFinalBestBall"]
        # Lower banked points, identical draws for everything unplayed: the
        # expected final falls, by at most the banked drop (a re-solved
        # lineup can seat someone else's draw in a seat).
        assert 0.0 < drop <= BANKED_DROP + 0.01
        assert o2["pointsBanked"] == pytest.approx(banked2, abs=0.01)
        assert o2["beatMedianPct"] < o1["beatMedianPct"]
        assert o2["winMatchupPct"] <= o1["winMatchupPct"]

    def test_link5_the_original_as_known_values_stay_retrievable(self):
        _, _, _, gen1, gen2 = _two_ticks()
        seq1 = gen1["inputs"]["leagueObservationSeq"]
        seq2 = gen2["inputs"]["leagueObservationSeq"]
        assert (seq1, seq2) == (1, 2)
        raw = {
            o.seq: o
            for o in live.observation_log(KEY, SEASON, WEEK, live.SOURCE_LEAGUE).observations()
        }
        for pid, (before, after) in CHANGED.items():
            assert raw[seq1].content[f"matchup:{ROSTER}"]["players_points"][pid] == before
            assert raw[seq2].content[f"matchup:{ROSTER}"]["players_points"][pid] == after
        history = {h["generationId"]: h for h in live.load_generation_history(KEY, SEASON, WEEK)}
        was = history[gen1["generationId"]]
        assert was["leagueObservationSeq"] == seq1
        assert was["outcomes"][ROSTER]["scoreNow"] == _side(gen1)["scoreNow"]
        assert (
            was["outcomes"][ROSTER]["expectedFinalBestBall"]
            == (_side(gen1)["outcome"]["expectedFinalBestBall"])
        )
        assert was["outcomes"][ROSTER]["actualScore"] == 52.82

    def test_the_api_serves_the_corrected_generation(self):
        world, _, _, _, gen2 = _two_ticks()
        payload = _serve(now=world.clock() + 5)
        assert payload["freshness"]["generationId"] == gen2["generationId"]
        team = {p["playerId"]: p for p in payload["team"]["players"]}
        assert team["6804"]["pointsScored"] == 18.3
        # The host itself carried the change: nothing is pending.
        assert payload["freshness"]["statCorrections"]["pendingHost"] == []
        assert "stat_correction_pending_host" not in payload["freshness"]["reasons"]


def _stats(lines: dict[str, dict[str, float]], at: float):
    return parse_week_stats(
        lines,
        season=SEASON,
        week=WEEK,
        observed_at=datetime.fromtimestamp(at, tz=timezone.utc),
    )


class TestPendingHostCorrection:
    """Labelled synthetic stat lines over the REAL host points."""

    def _tick(self, world, lines):
        clients = world.clients()
        clients.live_stats = lambda season, week: _stats(lines, world.clock())
        return live.run_tick(clients=clients, clock=world.clock, force=True, draws=DRAWS, seed=SEED)

    def test_a_correction_the_host_has_not_absorbed_is_reported_never_rescored(self):
        world = FixtureWorld("real_final_first_seen")
        self._tick(world, {"6804": {"pass_yd": 300.0}})
        gen1 = live.load_generation(KEY, SEASON, WEEK)

        # An hour later (the post-game stats cadence) the stat line has
        # dropped 30 passing yards (-1.0 point under this card); the host
        # still says 22.07.
        world.clock.ts += live.LIVE_STATS_POSTGAME_INTERVAL_SECONDS + 1
        report = self._tick(world, {"6804": {"pass_yd": 270.0}})
        assert report.leagues[KEY]["outcome"] == "inputs_unchanged"
        assert report.sources[live.SOURCE_LIVE_STATS]["postFinalChanges"] == 1

        payload = _serve(now=world.clock() + 5)
        fresh = payload["freshness"]
        assert fresh["generationId"] == gen1["generationId"]
        assert fresh["state"] == "partial"
        assert "stat_correction_pending_host" in fresh["reasons"]
        (pending,) = fresh["statCorrections"]["pendingHost"]
        assert pending["playerId"] == "6804"
        assert pending["state"] == "pending_host"
        assert pending["statChanges"] == {"pass_yd": [300.0, 270.0]}
        assert pending["scoredDeltaUnderLeagueCard"] == pytest.approx(-1.0)
        assert pending["hostPointsBefore"] == 22.07 and pending["hostPointsNow"] == 22.07
        assert fresh["statCorrections"]["scoringSourceOfRecord"].startswith("sleeper:")
        # NOT rescored: host points remain the scoring source of record.
        team = {p["playerId"]: p for p in payload["team"]["players"]}
        assert team["6804"]["pointsScored"] == 22.07

        # The host re-scores (the REAL later capture's host points): reflected,
        # and a new generation carries the host's corrected value.
        world.set_scenario("real_final")
        world.clock.ts += 60
        report = self._tick(world, {"6804": {"pass_yd": 270.0}})
        assert report.leagues[KEY]["outcome"] == "generation_written"
        payload = _serve(now=world.clock() + 5)
        fresh = payload["freshness"]
        assert "stat_correction_pending_host" not in fresh["reasons"]
        assert fresh["statCorrections"]["pendingHost"] == []
        assert fresh["statCorrections"]["reflectedInHostCount"] == 1
        state = live.load_league_state(KEY, SEASON, WEEK)["statCorrections"]["6804"]
        assert state["state"] == "reflected_in_host"
        assert state["hostPointsNow"] == 18.3 and state["reflectedAt"]
        assert {p["playerId"]: p for p in payload["team"]["players"]}["6804"][
            "pointsScored"
        ] == 18.3

    def test_a_change_before_the_final_was_observed_is_not_a_correction(self):
        """A game going final between two stat reads legitimately moves its
        lines; only a change after a final was ALREADY seen counts."""
        world = FixtureWorld("real_q4_in_progress")
        self._tick(world, {"6804": {"pass_yd": 250.0}})
        world.set_scenario("real_final_first_seen")
        world.clock.ts += live.LIVE_STATS_POSTGAME_INTERVAL_SECONDS + 1
        report = self._tick(world, {"6804": {"pass_yd": 300.0}})
        assert report.sources[live.SOURCE_LIVE_STATS]["postFinalChanges"] == 0
        corrections = live.load_league_state(KEY, SEASON, WEEK).get("statCorrections") or {}
        assert corrections == {}


def test_the_replay_fixture_carries_the_real_post_final_change():
    """Guard the evidence itself, so the chain above cannot go vacuous."""
    first = _scenario("real_final_first_seen")["matchups"][KEY]
    later = _scenario("real_final")["matchups"][KEY]
    row1 = next(m for m in first if str(m["roster_id"]) == ROSTER)
    row2 = next(m for m in later if str(m["roster_id"]) == ROSTER)
    for pid, (before, after) in CHANGED.items():
        assert (row1["players_points"][pid], row2["players_points"][pid]) == (before, after)


def test_a_change_the_league_does_not_score_is_recorded_not_pending():
    post = {
        "6804": {
            "playerId": "6804",
            "gameId": "2026_03_GB_ATL",
            "detectedAt": "2026-09-25T04:00:00+00:00",
            "statChanges": {"pts_ppr": [22.07, 18.3]},
        },
        "nobody": {
            "playerId": "nobody",
            "gameId": "2026_03_GB_ATL",
            "detectedAt": "2026-09-25T04:00:00+00:00",
            "statChanges": {"pass_yd": [100.0, 90.0]},
        },
    }
    matchups = [{"roster_id": 4, "players": ["6804"], "players_points": {"6804": 22.07}}]
    out = live.update_stat_corrections(
        {},
        post,
        previous_matchups=matchups,
        matchups=matchups,
        scoring_card={"pass_yd": 0.04},
        now=0.0,
    )
    # pts_ppr is not on the card; an unrostered player is not this league's.
    assert set(out) == {"6804"}
    assert out["6804"]["state"] == "not_scored_by_league"
    assert out["6804"]["scoredDeltaUnderLeagueCard"] == 0.0


def test_raw_stat_changes_keep_absent_distinct_from_zero():
    before = {"p:1": {"pass_yd": 10.0}, "t:GB": {"pts": 1.0}}
    after = {"p:1": {"pass_yd": 10.0, "pass_td": 0.0}, "p:2": {"rec": 1.0}, "t:GB": {"pts": 2.0}}
    assert live.raw_stat_changes(before, after) == {
        "1": {"pass_td": [None, 0.0]},
        "2": {"rec": [None, 1.0]},
    }
