"""League Hub championship / playoff odds — input integrity (2026-09-26).

Three factual defects, each pinned against the condition that produced it:

* **D1** — refresh run 36220954196 lost ``GET /players/nfl``
  (``ConnectionResetError``).  The empty dump was read as an empty
  universe, every rostered player's name fell back to its raw Sleeper id,
  nothing joined the ROS aggregate, every team strength became 0, and the
  sims — every team on the league-wide distribution with fewer than four
  finished weeks — published ~13/12/10% championship odds stamped
  ``rosStrengthAvailable: true``.
* **D4** — a live week's matchups were frozen as finals once both sides had
  any points (3 of 6 week-3 matchups on Thursday-only scores).
* **D5** — the championship engine resolved no league key, so a
  non-default league was simulated on the default league's team strength,
  rosters and starter slots, and its lazy section read the default
  league's cache file.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.api import league_registry
from src.public_league import metrics, playoff_odds, sleeper_client
from src.ros import championship, playoff_sim, scrape, team_strength

# ── fixtures ──────────────────────────────────────────────────────────


def _cfg(key: str, sleeper_id: str, *, best_ball: bool = False):
    return league_registry.LeagueConfig(
        key=key,
        display_name=key,
        sleeper_league_id=sleeper_id,
        scoring_profile="test",
        roster_settings={"starters": {"WR": 2}},
        idp_enabled=False,
        best_ball=best_ball,
    )


def _league(
    *,
    n_teams: int = 8,
    finished_weeks: int = 2,
    live_week_scored_pairs: int = 0,
    weeks: int = 14,
    root: str = "L1",
    seed: int = 3,
):
    """A SeasonSnapshot-shaped league: ``finished_weeks`` complete weeks
    (host clock agrees), then optionally one LIVE week in which the first
    ``live_week_scored_pairs`` matchups carry Thursday points on both sides,
    then unplayed stub weeks at ``0.0`` (Sleeper pre-generates them)."""
    rng = random.Random(seed)
    owners = [f"o{i}" for i in range(1, n_teams + 1)]
    roster_to_owner = {(root, i): owners[i - 1] for i in range(1, n_teams + 1)}
    live_week = finished_weeks + 1 if live_week_scored_pairs else None
    matchups: dict[int, list[dict]] = {}
    for wk in range(1, weeks + 1):
        rows = []
        rot = owners[:1] + owners[1:][wk % (n_teams - 1) :] + owners[1:][: wk % (n_teams - 1)]
        for m in range(n_teams // 2):
            a, b = rot[m], rot[-(m + 1)]
            for oid in (a, b):
                rid = owners.index(oid) + 1
                if wk <= finished_weeks:
                    pts = round(rng.uniform(80, 150), 2)
                elif wk == live_week and m < live_week_scored_pairs:
                    pts = round(rng.uniform(15, 40), 2)
                else:
                    pts = 0.0
                rows.append({"roster_id": rid, "matchup_id": m + 1, "points": pts})
        matchups[wk] = rows
    season = SimpleNamespace(
        season="2026",
        league_id=root,
        league={
            "settings": {
                "last_scored_leg": finished_weeks,
                "playoff_teams": 4,
                "playoff_week_start": weeks + 1,
            }
        },
        num_teams=n_teams,
        rosters=[{"roster_id": i, "owner_id": owners[i - 1]} for i in range(1, n_teams + 1)],
        matchups_by_week=matchups,
        regular_season_weeks=list(range(1, weeks + 1)),
    )
    managers = SimpleNamespace(by_owner_id={}, roster_to_owner=roster_to_owner)
    return SimpleNamespace(
        seasons=[season],
        current_season=season,
        managers=managers,
        root_league_id=root,
    ), owners


def _strength_rows(owners: list[str], values: list[float]) -> list[dict]:
    return [
        {"ownerId": o, "teamRosStrength": v, "startingLineupScore": v, "benchDepthScore": 0.0}
        for o, v in zip(owners, values)
    ]


class _TmpRosDir(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for mod in (scrape, team_strength, playoff_sim, championship):
            p = patch.object(mod, "ROS_DATA_DIR", self.root)
            p.start()
            self.addCleanup(p.stop)
        team_strength._live_compute_cache.clear()
        self.addCleanup(team_strength._live_compute_cache.clear)


# ── D1 (a): an empty / failed player dump is a FAILURE ────────────────


class TestPlayerDumpFailureIsNotCached(unittest.TestCase):
    def setUp(self) -> None:
        sleeper_client.reset_nfl_players_cache()
        self.addCleanup(sleeper_client.reset_nfl_players_cache)

    def test_a_failed_download_is_retried_not_memoized_as_empty(self) -> None:
        answers = [None, {"123": {"full_name": "Real Player"}}]
        with patch.object(sleeper_client, "_request_json", side_effect=answers):
            self.assertEqual(sleeper_client.fetch_nfl_players(), {})
            self.assertEqual(
                sleeper_client.fetch_nfl_players(), {"123": {"full_name": "Real Player"}}
            )

    def test_an_empty_dump_is_not_memoized_either(self) -> None:
        answers = [{}, {"1": {"full_name": "X"}}]
        with patch.object(sleeper_client, "_request_json", side_effect=answers):
            self.assertEqual(sleeper_client.fetch_nfl_players(), {})
            self.assertEqual(sleeper_client.fetch_nfl_players(), {"1": {"full_name": "X"}})

    def test_the_usability_predicate(self) -> None:
        self.assertFalse(team_strength.nfl_player_dump_is_usable({}))
        self.assertFalse(team_strength.nfl_player_dump_is_usable(None))
        self.assertFalse(team_strength.nfl_player_dump_is_usable([{"x": 1}]))
        self.assertTrue(team_strength.nfl_player_dump_is_usable({"1": {}}))


class TestRefreshKeepsLastGoodTeamStrength(_TmpRosDir):
    LAST_GOOD = [{"ownerId": "o1", "teamRosStrength": 71.5, "startingLineupScore": 80.0}]

    def _seed_last_good(self) -> Path:
        path = team_strength.write_team_strength_snapshot(self.LAST_GOOD, league_key=None)
        return path

    def test_empty_player_dump_writes_nothing_and_reports_every_league(self) -> None:
        path = self._seed_last_good()
        before = path.read_bytes()
        failures: dict[str, str] = {}
        leagues = [_cfg("dynasty_main", "S1"), _cfg("dynasty_new", "S2")]
        with (
            patch.object(league_registry, "active_leagues", return_value=leagues),
            patch.object(sleeper_client, "fetch_nfl_players", return_value={}),
            patch("src.api.sleeper_overlay.fetch_sleeper_overlay") as overlay,
        ):
            out = scrape._refresh_team_strength_snapshot([], failures)
        self.assertEqual(out, {})
        self.assertEqual(path.read_bytes(), before, "last good snapshot was overwritten")
        self.assertEqual(
            failures,
            {
                "dynasty_main": "nfl_player_dump_unavailable",
                "dynasty_new": "nfl_player_dump_unavailable",
            },
        )
        overlay.assert_not_called()

    def _run_one_league(self, nfl_players: dict, aggregate: list[dict]):
        failures: dict[str, str] = {}
        overlay = {"teams": [{"ownerId": "o1", "roster_id": 1, "playerIds": ["p1", "p2"]}]}
        with (
            patch.object(league_registry, "get_league_by_key", return_value=None),
            patch("src.api.sleeper_overlay.fetch_sleeper_overlay", return_value=overlay),
        ):
            path = scrape._refresh_team_strength_for_league(
                _cfg("dynasty_main", "S1"), aggregate, nfl_players, failures
            )
        return path, failures

    def test_rows_with_no_ros_priced_player_are_not_written(self) -> None:
        """The dump loads, but no rostered name joins the aggregate.  The
        composite is NOT zero here (coverage + health terms: 6.67), which is
        why evidence is read from the ROS-priced starting lineup rather than
        from ``teamRosStrength``."""
        path = self._seed_last_good()
        before = path.read_bytes()
        nfl = {"p1": {"full_name": "Nobody Ranked", "position": "WR"}}
        agg = [{"canonicalName": "someone else", "position": "WR", "rosValue": 50.0}]
        written, failures = self._run_one_league(nfl, agg)
        self.assertIsNone(written)
        self.assertEqual(failures, {"dynasty_main": "no_team_strength_evidence"})
        self.assertEqual(path.read_bytes(), before)

    def test_control_real_evidence_is_written(self) -> None:
        nfl = {
            "p1": {"full_name": "Alpha Player", "position": "WR"},
            "p2": {"full_name": "Beta Player", "position": "WR"},
        }
        agg = [
            {"canonicalName": "alpha player", "position": "WR", "rosValue": 60.0},
            {"canonicalName": "beta player", "position": "WR", "rosValue": 40.0},
        ]
        written, failures = self._run_one_league(nfl, agg)
        self.assertIsNotNone(written)
        self.assertEqual(failures, {})
        rows = json.loads(Path(written).read_text())
        self.assertGreater(rows[0]["teamRosStrength"], 0)


class TestRefreshReportsTheFailure(unittest.TestCase):
    def test_main_exits_nonzero_when_the_run_recorded_failures(self) -> None:
        summary = {"failures": {"teamStrength": {"dynasty_main": "nfl_player_dump_unavailable"}}}
        with (
            patch.object(scrape, "run_all", return_value=summary),
            patch.object(sys, "argv", ["ros.scrape"]),
            patch("builtins.print"),
        ):
            self.assertEqual(scrape.main(), 1)

    def test_main_exits_zero_on_a_clean_run(self) -> None:
        with (
            patch.object(scrape, "run_all", return_value={"failures": {}}),
            patch.object(sys, "argv", ["ros.scrape"]),
            patch("builtins.print"),
        ):
            self.assertEqual(scrape.main(), 0)

    def _agg_dir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "history").mkdir()
        return Path(tmp.name)

    def test_run_all_surfaces_team_strength_failures(self) -> None:
        def _fake_refresh(aggregated, failures):
            failures["dynasty_main"] = "nfl_player_dump_unavailable"
            return {}

        with (
            patch.object(scrape, "enabled_ros_sources", return_value=[]),
            patch.object(scrape, "_rebuild_index"),
            patch.object(scrape, "aggregate", return_value=[]),
            patch.object(scrape, "_aggregate_dir", return_value=self._agg_dir()),
            patch.object(scrape, "_refresh_team_strength_snapshot", side_effect=_fake_refresh),
            patch.object(scrape, "_refresh_power_snapshots", return_value={}),
            patch.object(scrape, "_refresh_sim_caches", return_value={}),
        ):
            out = scrape.run_all(canonical_universe={"x"})
        self.assertEqual(
            out["failures"], {"teamStrength": {"dynasty_main": "nfl_player_dump_unavailable"}}
        )


class TestTeamStrengthReadPathRefusesEvidenceLessRows(_TmpRosDir):
    def test_live_overlay_tier_refuses_an_empty_dump(self) -> None:
        cfg = _cfg("dynasty_main", "S1")
        overlay = {"teams": [{"ownerId": "o1", "roster_id": 1, "playerIds": ["p1"]}]}
        agg = [{"canonicalName": "alpha player", "position": "WR", "rosValue": 60.0}]
        with (
            patch.object(league_registry, "get_league_by_key", return_value=cfg),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
            patch("src.api.sleeper_overlay.fetch_sleeper_overlay", return_value=overlay),
        ):
            self.assertEqual(
                team_strength.compute_team_strength_live("dynasty_main", nfl_players={}), []
            )

    def test_snapshot_tier_refuses_a_snapshot_without_a_player_dump(self) -> None:
        snap, _ = _league()
        snap.nfl_players = {}
        agg = [{"canonicalName": "alpha player", "position": "WR", "rosValue": 60.0}]
        with (
            patch.object(league_registry, "get_default_league", return_value=_cfg("m", "S1")),
            patch.object(team_strength, "load_ros_aggregate_players", return_value=agg),
        ):
            self.assertEqual(team_strength.compute_team_strength_from_snapshot(snap), [])

    def test_a_fresh_all_zero_persisted_file_is_not_the_fast_path(self) -> None:
        zero_rows = _strength_rows(["o1", "o2"], [0.0, 0.0])
        target = team_strength._team_strength_path(None)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(zero_rows))
        with patch.object(team_strength, "compute_team_strength_live", return_value=zero_rows):
            self.assertEqual(team_strength.load_or_compute_team_strength(None), [])

    def test_persist_refuses_to_overwrite_with_zero_rows(self) -> None:
        good = team_strength.write_team_strength_snapshot(
            _strength_rows(["o1"], [55.0]), league_key=None
        )
        before = good.read_bytes()
        team_strength._persist_best_effort(
            _strength_rows(["o1"], [0.0]), league_key=None, persist=True
        )
        self.assertEqual(good.read_bytes(), before)


# ── D1 (b)(c): the sims refuse coin flips; the flag means evidence ────


class TestRosStrengthAvailableMeansEvidence(unittest.TestCase):
    def test_predicate(self) -> None:
        f = playoff_sim.ros_strength_available
        self.assertFalse(f({}))
        self.assertFalse(f({"a": 0.0, "b": 0.0}), "an all-zero map is not evidence")
        self.assertTrue(f({"a": 0.0, "b": 12.5}))


class TestDegradedReplayRefusesToPublish(unittest.TestCase):
    """Replays the 2026-09-26 condition end to end through the REAL
    team-strength computation and the REAL distribution builder: an empty
    NFL dump, two finished weeks, best ball."""

    def _degraded_rows(self, owners: list[str]) -> list[dict]:
        teams = [
            {"ownerId": o, "roster_id": i, "playerIds": [f"{i}01", f"{i}02"]}
            for i, o in enumerate(owners, start=1)
        ]
        agg = [
            {"canonicalName": "alpha player", "position": "WR", "rosValue": 60.0},
            {"canonicalName": "beta player", "position": "WR", "rosValue": 40.0},
        ]
        hydrated = team_strength.hydrate_overlay_players(teams, {})  # the failed dump
        # Names fell back to raw ids, exactly as in production.
        self.assertEqual(hydrated[0]["players"][0]["name"], "101")
        rows = team_strength.compute_team_strength(
            hydrated, aggregated_players=agg, starter_slots=["WR", "WR"]
        )
        self.assertFalse(team_strength.team_strength_has_evidence(rows))
        return rows

    def _run(self, engine, snap, rows):
        with (
            patch.object(team_strength, "load_or_compute_team_strength", return_value=rows),
            patch.object(playoff_sim, "_load_starter_slots", return_value=["WR", "WR"]),
        ):
            if engine == "champ":
                return championship.simulate_championship_odds(
                    snap, best_ball=True, n_simulations=200, rng=random.Random(1)
                )
            return playoff_sim.simulate_playoff_odds(
                snap, best_ball=True, n_simulations=200, rng=random.Random(1)
            )

    def test_championship_refuses_instead_of_publishing_coin_flips(self) -> None:
        snap, owners = _league(finished_weeks=2)
        out = self._run("champ", snap, self._degraded_rows(owners))
        self.assertEqual(out["championshipOdds"], [])
        self.assertEqual(out["n_simulations"], 0)
        self.assertIs(out["rosStrengthAvailable"], False)
        self.assertEqual(out["unsimulable"]["reason"], playoff_sim.TEAM_STRENGTH_UNAVAILABLE)
        self.assertIn("not an equal chance", out["unsimulable"]["detail"])

    def test_playoff_engine_refuses_with_the_same_words(self) -> None:
        snap, owners = _league(finished_weeks=2)
        out = self._run("playoff", snap, self._degraded_rows(owners))
        self.assertEqual(out["playoffOdds"], [])
        self.assertIs(out["rosStrengthAvailable"], False)
        self.assertEqual(out["unsimulable"]["reason"], playoff_sim.TEAM_STRENGTH_UNAVAILABLE)

    def test_control_real_strength_still_simulates_and_separates_teams(self) -> None:
        snap, owners = _league(finished_weeks=2)
        rows = _strength_rows(owners, [10.0 * (i + 1) for i in range(len(owners))])
        out = self._run("champ", snap, rows)
        self.assertNotIn("unsimulable", out)
        self.assertIs(out["rosStrengthAvailable"], True)
        odds = [r["championshipOdds"] for r in out["championshipOdds"]]
        self.assertGreater(max(odds) - min(odds), 0.2)

    def test_empirical_only_mode_is_unchanged(self) -> None:
        """Every team has its own finished weeks: no ROS is a weaker model,
        not an absence of evidence, and it still simulates (labelled)."""
        snap, owners = _league(finished_weeks=5)
        out = self._run("champ", snap, [])
        self.assertNotIn("unsimulable", out)
        self.assertIs(out["rosStrengthAvailable"], False)
        self.assertEqual(len(out["championshipOdds"]), len(owners))


# ── D4: live-week results are not frozen as final ────────────────────


class TestLiveWeekFinality(unittest.TestCase):
    def _record(self, snap):
        season = snap.current_season
        return playoff_odds._regular_season_record_to_date(season, snap.managers)

    def test_thursday_scores_are_not_a_final(self) -> None:
        # Week 3 live: 2 of 4 matchups carry Thursday points on both sides.
        snap, owners = _league(finished_weeks=2, live_week_scored_pairs=2)
        rec = self._record(snap)
        games = {o: rec[o]["wins"] + rec[o]["losses"] + rec[o]["ties"] for o in owners}
        self.assertEqual(set(games.values()), {2}, f"a live game was counted: {games}")

    def test_the_whole_live_week_is_simulated(self) -> None:
        snap, _ = _league(finished_weeks=2, live_week_scored_pairs=2)
        posted = playoff_odds._posted_future_matchups(snap.current_season, snap.managers)
        self.assertEqual(len(posted[3]), 4, "the Thursday-scored matchups fell out of the schedule")
        self.assertNotIn(1, posted)
        self.assertNotIn(2, posted)

    def test_record_and_schedule_partition_the_season(self) -> None:
        """Every regular-season matchup is counted OR simulated, exactly once."""
        snap, owners = _league(finished_weeks=2, live_week_scored_pairs=3)
        rec = self._record(snap)
        counted = sum(rec[o]["wins"] + rec[o]["losses"] + rec[o]["ties"] for o in owners) // 2
        scheduled = len(playoff_sim._remaining_schedule(snap))
        total = sum(
            len(metrics.matchup_pairs(r)) for r in snap.current_season.matchups_by_week.values()
        )
        self.assertEqual(counted + scheduled, total)

    def test_finished_weeks_match_the_host_record(self) -> None:
        """Parity: for finalized weeks the simulator's starting record is the
        host's own head-to-head record, owner by owner."""
        snap, owners = _league(finished_weeks=2, live_week_scored_pairs=3)
        season = snap.current_season
        host: dict[str, list[int]] = {o: [0, 0] for o in owners}
        for wk in (1, 2):
            for a, b in metrics.matchup_pairs(season.matchups_by_week[wk]):
                oa = snap.managers.roster_to_owner[(season.league_id, a["roster_id"])]
                ob = snap.managers.roster_to_owner[(season.league_id, b["roster_id"])]
                win, lose = (oa, ob) if a["points"] > b["points"] else (ob, oa)
                host[win][0] += 1
                host[lose][1] += 1
        rec = self._record(snap)
        self.assertEqual({o: [rec[o]["wins"], rec[o]["losses"]] for o in owners}, host)

    def test_a_finished_week_stays_frozen(self) -> None:
        """Once the host clock closes week 3, its results count as finals."""
        snap, owners = _league(finished_weeks=3)
        rec = self._record(snap)
        self.assertTrue(all(rec[o]["wins"] + rec[o]["losses"] == 3 for o in owners))
        posted = playoff_odds._posted_future_matchups(snap.current_season, snap.managers)
        self.assertEqual(min(posted), 4)


# ── D5: each league is simulated on its OWN rosters / strength ────────


class TestPerLeagueIsolation(_TmpRosDir):
    KEYS = {"MAIN": "dynasty_main", "NEW": "dynasty_new"}

    def setUp(self) -> None:
        super().setUp()
        main, self.main_owners = _league(root="MAIN", seed=1)
        new, self.new_owners = _league(root="NEW", seed=2, n_teams=6)
        self.snaps = {"dynasty_main": main, "dynasty_new": new}
        # Different rosters => different strengths, keyed by league.
        self.strength = {
            "dynasty_main": _strength_rows(self.main_owners, [5.0] * 7 + [90.0]),
            "dynasty_new": _strength_rows(self.new_owners, [90.0] + [5.0] * 5),
        }
        self.calls: list[str | None] = []

        def _load(league_key=None, **_):
            self.calls.append(league_key)
            return self.strength.get(league_key, [])

        for target, value in (
            (team_strength, "load_or_compute_team_strength"),
            (team_strength, "resolve_snapshot_league_key"),
        ):
            fn = (
                _load
                if value == "load_or_compute_team_strength"
                else (lambda snap: self.KEYS.get(getattr(snap, "root_league_id", None)))
            )
            p = patch.object(target, value, fn)
            p.start()
            self.addCleanup(p.stop)
        self.slot_calls: list[str | None] = []

        def _slots(league_key=None):
            self.slot_calls.append(league_key)
            return ["WR", "WR"]

        p = patch.object(playoff_sim, "_load_starter_slots", _slots)
        p.start()
        self.addCleanup(p.stop)

    def test_two_leagues_get_their_own_strengths(self) -> None:
        for key, owners, strong in (
            ("dynasty_main", self.main_owners, self.main_owners[-1]),
            ("dynasty_new", self.new_owners, self.new_owners[0]),
        ):
            self.calls.clear()
            self.slot_calls.clear()
            out = championship.simulate_championship_odds(
                self.snaps[key], best_ball=True, n_simulations=400, rng=random.Random(5)
            )
            self.assertEqual(set(self.calls), {key}, f"{key} read another league's strength")
            self.assertEqual(set(self.slot_calls), {key})
            ids = {r["ownerId"] for r in out["championshipOdds"]}
            self.assertEqual(ids, set(owners))
            leader = max(out["championshipOdds"], key=lambda r: r["championshipOdds"])
            self.assertEqual(leader["ownerId"], strong)

    def test_lazy_section_reads_its_own_leagues_cache(self) -> None:
        sims = self.root / "sims"
        sims.mkdir(parents=True)
        (sims / "latest_championship.json").write_text(json.dumps({"league": "main"}))
        (sims / "dynasty_new_championship.json").write_text(json.dumps({"league": "new"}))
        with patch.object(league_registry, "default_league_key", return_value="dynasty_main"):
            new = championship.build_section(self.snaps["dynasty_new"])
            main = championship.build_section(self.snaps["dynasty_main"])
        self.assertEqual((new["league"], new["cached"]), ("new", True))
        self.assertEqual((main["league"], main["cached"]), ("main", True))

    def test_best_ball_flag_is_read_for_the_requested_league(self) -> None:
        cfgs = {
            "dynasty_main": _cfg("dynasty_main", "MAIN", best_ball=False),
            "dynasty_new": _cfg("dynasty_new", "NEW", best_ball=True),
        }
        with (
            patch.object(league_registry, "get_league_by_key", side_effect=cfgs.get),
            patch.object(league_registry, "get_default_league", return_value=cfgs["dynasty_main"]),
        ):
            self.assertIs(playoff_sim._league_best_ball("dynasty_new"), True)
            self.assertIs(playoff_sim._league_best_ball(None), False)


if __name__ == "__main__":
    unittest.main()
