"""In-season updating: realized weekly production → posterior µ/σ + ROS.

The contract under test:
1. Preseason no-op — ``actuals=(None, {})`` (or omitted) produces the
   EXACT preseason payload; before week 1 nothing may drift.
2. Posterior math — µ shrinks toward realized per-game production with
   weight n_prior/(n_prior + weeks_played) (blend_ros_mu, the §8.4
   posterior finally wired live); σ shrinks by √(that weight).
3. Players with no observed weeks keep the preseason consensus —
   absence of evidence is never evidence of zero.
4. ROS sums only REMAINING weeks once a current week exists.
5. The actuals feed itself scores rows under league rules via the one
   production scoring path, and returns (None, {}) with no rows.
"""

from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from src.bdvm import service as service_mod
from src.bdvm.actuals import (
    current_nfl_season,
    fetch_current_season_actuals,
    nfl_projection_season,
    weekly_points_from_rows,
)
from src.bdvm.params import load_param_set
from src.bdvm.ros import ros_projection_weight
from src.bdvm.service import run_valuation

PARAMS = load_param_set("params_v1")

SCORING = {"rec": 1.0, "rec_yd": 0.1, "idp_tkl_solo": 1.5}
_norm = lambda s: s.lower()  # noqa: E731


def _contract():
    return {
        "generatedAt": "x",
        "currentDraftYear": 2026,
        "sleeper": {
            "scoringSettings": SCORING,
            "rosterPositions": ["QB", "WR", "WR", "LB", "BN", "BN"],
            "leagueSettings": {"num_teams": 12},
        },
        "playersArray": [
            {
                "playerId": "w1",
                "canonicalName": "steady wr",
                "displayName": "Steady WR",
                "position": "WR",
                "assetClass": "offense",
                "age": 25.0,
                "yearsExp": 3,
            },
            {
                "playerId": "w2",
                "canonicalName": "quiet wr",
                "displayName": "Quiet WR",
                "position": "WR",
                "assetClass": "offense",
                "age": 25.0,
                "yearsExp": 3,
            },
        ],
    }


def _records():
    from src.bdvm.projections import ProjectionRecord

    from tests.bdvm.pool_depth import depth_records

    # Two projected WRs in a 12-team league leaves the WR replacement rank
    # (36 startable + 12 buffer) off the end of the pool, which the engine
    # now reports as unpriced rather than pricing over R = 0 — hence the
    # bench depth (tests/bdvm/pool_depth.py).
    return [
        ProjectionRecord(
            source="a",
            player_key=key,
            position="WR",
            season=2026,
            as_of="2026-07-20",
            games=17.0,
            fpg=12.0,
            scoring_native=True,
        )
        for key in ("steady wr", "quiet wr")
    ] + depth_records()


def _run(actuals=None, schedule_weeks=None):
    return run_valuation(
        _contract(),
        league_key="dynasty_main",
        params=PARAMS,
        projection_records=_records(),
        snapshot_as_of="2026-07-27",
        season=2026,
        actuals=actuals,
        schedule_weeks=schedule_weeks,
    )


class TestPreseasonNoOp(unittest.TestCase):
    def test_omitted_and_empty_actuals_are_identical(self):
        base = _run(actuals=None)
        empty = _run(actuals=(None, {}))
        self.assertEqual(base["meta"]["inSeason"], {"active": False})
        self.assertEqual(empty["meta"]["inSeason"], {"active": False})
        for p_base, p_empty in zip(base["players"], empty["players"]):
            self.assertEqual(p_base["projection"]["fpg"], p_empty["projection"]["fpg"])
            self.assertEqual(p_base["tradeValue"], p_empty["tradeValue"])


class TestPosterior(unittest.TestCase):
    def test_mu_shrinks_toward_actuals_with_prior_weight(self):
        # 4 weeks at 20.0 FPG against a 12.0 preseason µ (offense
        # n_prior = 6): posterior = w·12 + (1−w)·20, w = 6/(6+4).
        samples = [(1, 20.0), (2, 20.0), (3, 20.0), (4, 20.0)]
        payload = _run(actuals=(5, {"steady wr": samples}))
        w = ros_projection_weight(4.0, is_idp=False, params=PARAMS)
        expected_mu = w * 12.0 + (1 - w) * 20.0
        steady = next(p for p in payload["players"] if p["name"] == "Steady WR")
        self.assertAlmostEqual(steady["projection"]["fpg"], round(expected_mu, 3), places=3)
        self.assertEqual(payload["meta"]["inSeason"]["currentWeek"], 5)
        self.assertEqual(payload["meta"]["inSeason"]["playersUpdated"], 1)

    def test_unobserved_player_keeps_preseason_mu(self):
        payload = _run(actuals=(5, {"steady wr": [(1, 20.0)]}))
        quiet = next(p for p in payload["players"] if p["name"] == "Quiet WR")
        self.assertAlmostEqual(quiet["projection"]["fpg"], 12.0, places=3)

    def test_sigma_shrinks_with_evidence(self):
        base = _run()
        updated = _run(actuals=(9, {"steady wr": [(w, 12.0) for w in range(1, 9)]}))
        s_base = next(p for p in base["players"] if p["name"] == "Steady WR")
        s_upd = next(p for p in updated["players"] if p["name"] == "Steady WR")
        # identical production → µ unchanged, σ_source strictly smaller
        self.assertAlmostEqual(s_upd["projection"]["fpg"], s_base["projection"]["fpg"], places=3)
        self.assertLess(
            s_upd["projection"]["sigmaSource"], s_base["projection"]["sigmaSource"] + 1e-9
        )


class TestRosRemainingWeeks(unittest.TestCase):
    def _weeks(self):
        from src.bdvm.ros import RosWeek

        return {"KC": [RosWeek(week=w, is_bye=(w == 6), p_active=1.0) for w in range(1, 19)]}

    def _contract_with_team(self):
        c = _contract()
        for row in c["playersArray"]:
            row["team"] = "KC"
        return c

    def test_ros_counts_only_remaining_weeks(self):
        pre = run_valuation(
            self._contract_with_team(),
            league_key="dynasty_main",
            params=PARAMS,
            projection_records=_records(),
            snapshot_as_of="2026-07-27",
            season=2026,
            schedule_weeks=self._weeks(),
        )
        mid = run_valuation(
            self._contract_with_team(),
            league_key="dynasty_main",
            params=PARAMS,
            projection_records=_records(),
            snapshot_as_of="2026-07-27",
            season=2026,
            schedule_weeks=self._weeks(),
            actuals=(10, {"steady wr": [(w, 12.0) for w in range(1, 10)]}),
        )
        pre_ros = next(p for p in pre["players"] if p["name"] == "Steady WR")["ros"]
        mid_ros = next(p for p in mid["players"] if p["name"] == "Steady WR")["ros"]
        self.assertEqual(pre_ros["weeks"], 18)
        self.assertEqual(mid_ros["weeks"], 9)  # weeks 10..18
        self.assertLess(mid_ros["balanced"], pre_ros["balanced"])
        # Boundary week: current_week=10 means SOME team has played
        # week 9 — Quiet WR has no week-9 sample, so his week 9 is
        # still remaining (nflverse publishes game-by-game; dropping
        # the in-progress week for everyone would vanish a real week
        # of value league-wide from Thursday to Monday).
        quiet_ros = next(p for p in mid["players"] if p["name"] == "Quiet WR")["ros"]
        self.assertEqual(quiet_ros["weeks"], 10)  # weeks 9..18


class TestActualsFeed(unittest.TestCase):
    def test_rows_score_under_league_rules_week_granular(self):
        rows = [
            {
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2026,
                "week": 1,
                "season_type": "REG",
                "receptions": 5,
                "receiving_yards": 70,
            },
            {  # playoffs excluded
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2026,
                "week": 19,
                "season_type": "POST",
                "receptions": 9,
                "receiving_yards": 150,
            },
            {  # other season excluded
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2025,
                "week": 2,
                "season_type": "REG",
                "receptions": 9,
                "receiving_yards": 150,
            },
        ]
        week, by_key = weekly_points_from_rows(rows, SCORING, season=2026, name_normalizer=_norm)
        self.assertEqual(week, 2)
        self.assertEqual(by_key["steady wr"], [(1, 12.0)])  # 5 rec + 7.0 yds

    def test_no_rows_is_preseason(self):
        week, by_key = weekly_points_from_rows([], SCORING, season=2026, name_normalizer=_norm)
        self.assertIsNone(week)
        self.assertEqual(by_key, {})

    def test_week_18_played_means_zero_remaining(self):
        # current_week is deliberately UNCAPPED: after the final slate
        # it must be 19 so ROS sums zero remaining weeks — a cap at 18
        # would double-count the banked final week as future value.
        rows = [
            {
                "player_display_name": "Steady WR",
                "position": "WR",
                "season": 2026,
                "week": 18,
                "season_type": "REG",
                "receptions": 5,
                "receiving_yards": 70,
            }
        ]
        week, _ = weekly_points_from_rows(rows, SCORING, season=2026, name_normalizer=_norm)
        self.assertEqual(week, 19)

    def test_distinct_players_colliding_on_name_are_dropped(self):
        # Byron Murphy (CB) vs Byron Murphy II (DT): the suffix strips
        # to the same key.  A per-week max over two different players
        # is a chimera — mirror the projection side and drop the key.
        def row(pid, week, yards):
            return {
                "player_display_name": "Byron Murphy",
                "player_id": pid,
                "position": "WR",
                "season": 2026,
                "week": week,
                "season_type": "REG",
                "receptions": 1,
                "receiving_yards": yards,
            }

        _week, by_key = weekly_points_from_rows(
            [row("00-001", 1, 100), row("00-002", 1, 50), row("00-002", 2, 60)],
            SCORING,
            season=2026,
            name_normalizer=_norm,
        )
        self.assertNotIn("byron murphy", by_key)
        # Same player id duplicated is NOT a collision — max dedupe.
        _week, by_key = weekly_points_from_rows(
            [row("00-001", 1, 100), row("00-001", 1, 100)],
            SCORING,
            season=2026,
            name_normalizer=_norm,
        )
        self.assertEqual(by_key["byron murphy"], [(1, 11.0)])


class TestSeasonDerivation(unittest.TestCase):
    """The actuals season is the CALENDAR NFL season — never
    currentDraftYear, which points one season ahead for the entire
    Sept–Jan window (review finding, 2026-07-28)."""

    def test_projection_season_agrees_with_the_actuals_season(self):
        """The half the 2026-07-28 review stopped short of (audit M6).

        Fixing only the actuals side left the PROJECTION season keyed on
        ``currentDraftYear``.  The §8.4 posterior blends realized weekly
        points into a projection, so the two seasons must be the same
        season or the blend crosses a season boundary — exactly what
        actuals.py exists to prevent.  Hand-derived: the season being
        played is the calendar year Sept–Dec, the previous year in
        January, and the season about to be played Feb–Aug.
        """
        for day, expected in (
            (date(2026, 9, 10), 2026),  # in progress
            (date(2026, 12, 31), 2026),
            (date(2027, 1, 5), 2026),  # week 18 spills into January
            (date(2026, 2, 1), 2026),  # offseason: the season ahead
            (date(2026, 7, 28), 2026),  # preseason
            (date(2027, 3, 1), 2027),
        ):
            self.assertEqual(nfl_projection_season(day), expected, msg=str(day))
        # …and inside the in-season window the two MUST agree.
        for day in (date(2026, 9, 10), date(2026, 12, 31), date(2027, 1, 5)):
            self.assertEqual(nfl_projection_season(day), current_nfl_season(day), msg=str(day))

    def test_payload_season_is_the_nfl_season_not_the_rookie_draft_year(self):
        """After the May roll the two diverge; meta must carry both."""
        contract = _contract()
        contract["currentDraftYear"] = 2027  # post-roll: the NEXT rookie draft
        with mock.patch.object(service_mod, "nfl_projection_season", return_value=2026):
            payload = run_valuation(
                contract,
                league_key="dynasty_main",
                params=PARAMS,
                projection_records=_records(),
                snapshot_as_of="2026-07-27",
                actuals=(5, {"steady wr": [(1, 20.0), (2, 20.0), (3, 20.0), (4, 20.0)]}),
            )
        self.assertEqual(payload["meta"]["season"], 2026)
        self.assertEqual(payload["meta"]["rookieDraftYear"], 2027)
        # The posterior ran, so the actuals season and the projection
        # season describe the same season by construction.
        self.assertEqual(payload["meta"]["inSeason"]["playersUpdated"], 1)

    def test_calendar_window(self):
        self.assertEqual(current_nfl_season(date(2026, 9, 10)), 2026)
        self.assertEqual(current_nfl_season(date(2026, 12, 31)), 2026)
        self.assertEqual(current_nfl_season(date(2027, 1, 5)), 2026)  # week 18 spill
        self.assertIsNone(current_nfl_season(date(2026, 7, 28)))  # preseason
        self.assertIsNone(current_nfl_season(date(2027, 3, 1)))  # offseason

    def test_out_of_window_is_preseason_signal_without_fetch(self):
        # July: no season in progress → (None, {}) and NO network call
        # (a fetch would raise inside the sandboxed test env).
        week, by_key = fetch_current_season_actuals(
            SCORING, name_normalizer=_norm, today=date(2026, 7, 28)
        )
        self.assertIsNone(week)
        self.assertEqual(by_key, {})


if __name__ == "__main__":
    unittest.main()
