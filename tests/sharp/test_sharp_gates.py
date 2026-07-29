"""Sharp-cohort gates: dynasty-only, league age, win-rate floor,
multi-league, championship preference, and the top-quartile cutoff.

These pin the criteria as stated: dynasty leagues only, evidence only
from leagues at least two seasons old, a real winning-percentage floor,
multiple leagues, a strong preference for proven winners, and a cohort
limited to roughly the top quarter.
"""

from __future__ import annotations

import pytest

from src.intel import league_filter as lf
from src.sharp import score as S


def league(type_=2, best_ball=0, previous=None):
    lg = {"league_id": "L", "settings": {"type": type_, "best_ball": best_ball}}
    if previous:
        lg["previous_league_id"] = previous
    return lg


class TestDynastyOnlyForSharp:
    def test_dynasty_with_history_is_sharp_eligible(self):
        assert lf.is_sharp_eligible(league(type_=2, previous="old")) is True

    def test_keeper_is_not_sharp_eligible_even_with_history(self):
        """Keeper informs Insider Trading but cannot certify a sharp."""
        lg = league(type_=1, previous="old")
        assert lf.is_eligible(lg) is True, "keeper still counts for Insider Trading"
        assert lf.is_sharp_eligible(lg) is False
        assert lf.sharp_exclusion_reason(lg) == "keeper"

    def test_redraft_is_not_sharp_eligible(self):
        assert lf.is_sharp_eligible(league(type_=0, previous="old")) is False
        assert lf.sharp_exclusion_reason(league(type_=0, previous="old")) == "redraft"

    def test_best_ball_is_not_sharp_eligible(self):
        lg = league(type_=2, best_ball=1, previous="old")
        assert lf.is_sharp_eligible(lg) is False
        assert lf.sharp_exclusion_reason(lg) == "best_ball"

    def test_unknown_type_is_rejected_for_sharp_but_admitted_for_discovery(self):
        """Discovery degrades inclusively; sharp certification must not.

        Calling someone sharp off a league we cannot confirm is dynasty
        would be a claim we cannot support.
        """
        lg = {"league_id": "L", "previous_league_id": "old"}
        assert lf.is_eligible(lg) is True
        assert lf.is_sharp_eligible(lg) is False
        assert lf.sharp_exclusion_reason(lg) == "unknown_type"


class TestLeagueAgeGate:
    def test_first_year_dynasty_league_is_too_new(self):
        """Startup-year churn is not evidence of skill."""
        lg = league(type_=2, previous=None)
        assert lf.is_sharp_eligible(lg) is False
        assert lf.sharp_exclusion_reason(lg) == "too_new"

    def test_previous_league_id_proves_age_two(self):
        assert lf.league_age_seasons(league(type_=2, previous="old")) == 2
        assert lf.league_age_seasons(league(type_=2)) == 1

    def test_age_check_costs_no_extra_api_call(self):
        """previous_league_id ships inside the /user/{id}/leagues payload
        the crawl already fetches — which is why 2 is the default bar."""
        lg = league(type_=2, previous="old")
        assert lf.league_age_seasons(lg) >= 2
        assert set(lg) <= {"league_id", "settings", "previous_league_id"}

    def test_age_bar_is_configurable(self):
        lg = league(type_=2, previous="old")
        assert lf.is_sharp_eligible(lg, min_age_seasons=2) is True
        assert lf.is_sharp_eligible(lg, min_age_seasons=3) is False


def rec(user_id="u", **kw):
    base = dict(
        completed_seasons=4,
        observed_leagues=4,
        dynasty_leagues=3,
        completed_games=56,
        wins=32,
        losses=24,
        ties=0,
        playoff_appearances=2,
        championships=0,
        finish_percentiles=[0.6, 0.55, 0.7, 0.5],
        points_for_percentiles=[0.6] * 4,
        roster_value_ratios=[1.05, 1.02, 1.10, 1.0],
        trades_completed=12,
        abandoned_rosters=0,
        days_since_last_activity=10,
    )
    base.update(kw)
    return S.ManagerRecord(user_id=user_id, **base)


def population(n=40):
    out = []
    for i in range(n):
        frac = i / max(1, n - 1)
        out.append(
            rec(
                user_id=f"pop{i}",
                wins=int(20 + 24 * frac),
                losses=int(36 - 24 * frac),
                playoff_appearances=int(round(4 * frac)),
                championships=1 if frac > 0.9 else 0,
                finish_percentiles=[frac] * 4,
                roster_value_ratios=[0.7 + 0.7 * frac] * 4,
            )
        )
    return out


class TestWinRateFloor:
    def test_below_500_manager_is_ineligible(self):
        loser = rec("loser", wins=20, losses=36)
        reasons = " ".join(S.check_eligibility(loser))
        assert "win rate" in reasons and "floor" in reasons

    def test_exactly_average_manager_is_ineligible(self):
        """0.500 is the structural league mean — average is not sharp."""
        avg = rec("avg", wins=28, losses=28)
        assert avg.win_pct == pytest.approx(0.5)
        assert any("win rate" in r for r in S.check_eligibility(avg))

    def test_clearly_winning_manager_clears_the_floor(self):
        winner = rec("winner", wins=34, losses=22)
        assert not any("win rate" in r for r in S.check_eligibility(winner))

    def test_floor_is_a_viability_gate_not_the_selector(self):
        """Set at 0.52, roughly half a standard deviation above the mean:
        it removes below-average managers without pre-empting the
        percentile bar that actually sizes the cohort."""
        cfg = S.load_config()
        assert 0.50 < cfg["eligibility"]["minWinPct"] <= 0.56

    def test_ties_count_as_half_a_win(self):
        assert rec(wins=10, losses=10, ties=4).win_pct == pytest.approx(0.5)


class TestMultiDynastyLeagueGate:
    def test_single_dynasty_league_is_ineligible(self):
        solo = rec("solo", dynasty_leagues=1)
        reasons = " ".join(S.check_eligibility(solo))
        assert "qualifying dynasty league" in reasons

    def test_reason_names_both_restrictions(self):
        solo = rec("solo", dynasty_leagues=0)
        reasons = " ".join(S.check_eligibility(solo))
        assert "dynasty only" in reasons
        assert "seasons old" in reasons

    def test_two_dynasty_leagues_clears_the_gate(self):
        assert not any("dynasty league" in r for r in S.check_eligibility(rec(dynasty_leagues=2)))

    def test_keeper_leagues_do_not_help_the_gate(self):
        """dynasty_leagues is already sharp-filtered upstream, so a
        manager in many keeper leagues still fails."""
        keeper_heavy = rec("keeper", observed_leagues=9, dynasty_leagues=1)
        assert any("qualifying dynasty league" in r for r in S.check_eligibility(keeper_heavy))


class TestChampionshipPreference:
    def test_title_holder_outscores_identical_manager_without_one(self):
        cfg = S.load_config()
        no_title, _ = S._championship_bonus(rec(championships=0), cfg)
        one_title, notes = S._championship_bonus(rec(championships=1), cfg)
        assert no_title == 0.0
        assert one_title > 0.0
        assert notes and "Won the league" in notes[0]

    def test_additional_titles_add_less_than_the_first(self):
        cfg = S.load_config()
        first, _ = S._championship_bonus(rec(championships=1), cfg)
        second, _ = S._championship_bonus(rec(championships=2), cfg)
        assert second > first
        assert (second - first) < first

    def test_bonus_is_capped(self):
        cfg = S.load_config()
        many, _ = S._championship_bonus(rec(championships=50), cfg)
        assert many <= cfg["championshipPreference"]["maxBonus"]

    def test_a_title_is_not_a_hard_gate(self):
        """Requiring one would cut the cohort far below a top quarter —
        only ~1/12 of managers can win a 12-team league per season."""
        titleless = rec("titleless", championships=0)
        assert S.check_eligibility(titleless) == []

    def test_title_is_named_first_in_contributors(self):
        champ = rec(
            "champ",
            completed_seasons=6,
            observed_leagues=6,
            dynasty_leagues=6,
            completed_games=84,
            wins=58,
            losses=26,
            playoff_appearances=5,
            championships=2,
            finish_percentiles=[0.95, 0.9, 0.88, 0.92, 0.85, 0.9],
            roster_value_ratios=[1.6] * 6,
        )
        scored = S.score_managers([champ, *population()])
        entry = next(s for s in scored if s.user_id == "champ")
        assert entry.contributors
        assert "Won the league" in entry.contributors[0]
        assert entry.components["championshipBonus"] > 0


class TestCohortSize:
    def test_bar_is_top_quartile_of_evaluable(self):
        cfg = S.load_config()
        assert cfg["qualification"]["minScorePercentile"] == 0.75

    def test_qualified_is_roughly_a_quarter_of_evaluable(self):
        scored = S.score_managers(population(80))
        tiers = S.cohort_tiers(scored)
        share = tiers["qualifiedShareOfEvaluable"]
        assert share is not None
        assert 0.10 <= share <= 0.35, f"expected a top-quartile-ish cohort, got {share:.0%}"

    def test_both_share_framings_are_reported(self):
        """'Top quarter' is ambiguous — of everyone found, or of those we
        can actually judge?  Both are published so neither is implied."""
        thin = rec("thin", completed_seasons=1, completed_games=6, dynasty_leagues=1)
        scored = S.score_managers([thin, *population(40)])
        tiers = S.cohort_tiers(scored)
        assert tiers["qualifiedShareOfEvaluable"] is not None
        assert tiers["qualifiedShareOfObservable"] is not None
        assert (
            tiers["qualifiedShareOfObservable"] <= tiers["qualifiedShareOfEvaluable"]
        ), "gates run before the percentile, so the observable share is always smaller"

    def test_every_qualified_manager_cleared_every_hard_gate(self):
        scored = S.score_managers(population(60))
        for entry in scored:
            if entry.qualified:
                assert entry.evaluable is True
                assert not entry.ineligible_reasons

    def test_methodology_version_moved_with_the_criteria_change(self):
        assert S.methodology_version() == "sharp-v2"
