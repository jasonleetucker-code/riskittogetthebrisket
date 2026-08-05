"""Sharp Score: eligibility gates, no-single-signal-dominates, and the
separation of score from confidence."""

from __future__ import annotations

import pytest

from src.sharp import score as S


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
        points_for_percentiles=[0.6, 0.6, 0.6, 0.6],
        roster_value_ratios=[1.05, 1.02, 1.10, 1.0],
        trades_completed=12,
        abandoned_rosters=0,
        days_since_last_activity=10,
    )
    base.update(kw)
    return S.ManagerRecord(user_id=user_id, **base)


def population(n=30):
    """A spread of ordinary managers, so percentiles are meaningful."""
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
                finish_percentiles=[frac, frac, frac, frac],
                roster_value_ratios=[0.7 + 0.7 * frac] * 4,
            )
        )
    return out


class TestEligibilityGates:
    def test_thin_history_is_not_evaluable_rather_than_badly_scored(self):
        thin = rec(
            "thin", completed_seasons=1, completed_games=14, observed_leagues=1, dynasty_leagues=1
        )
        [result] = [s for s in S.score_managers([thin, *population()]) if s.user_id == "thin"]
        assert result.evaluable is False
        assert result.score is None
        assert result.qualified is False
        assert result.ineligible_reasons

    def test_ineligible_reasons_are_specific(self):
        thin = rec(
            "thin", completed_seasons=1, completed_games=10, observed_leagues=1, dynasty_leagues=1
        )
        reasons = " ".join(S.check_eligibility(thin))
        assert "completed season" in reasons
        assert "qualifying dynasty league" in reasons
        assert "completed games" in reasons

    def test_no_dynasty_league_is_ineligible(self):
        r = rec("redraft_only", dynasty_leagues=0)
        assert any("dynasty" in x for x in S.check_eligibility(r))
        # v2: keeper leagues no longer help — only dynasty >= 2 seasons old.
        assert any("dynasty only" in x for x in S.check_eligibility(r))

    def test_abandoned_rosters_disqualify(self):
        r = rec("ghost", observed_leagues=4, abandoned_rosters=3)
        assert any("abandoned" in x for x in S.check_eligibility(r))

    def test_long_inactivity_disqualifies(self):
        r = rec("gone", days_since_last_activity=900)
        assert any("no activity" in x for x in S.check_eligibility(r))

    def test_healthy_record_is_evaluable(self):
        assert S.check_eligibility(rec()) == []


class TestNoSingleSignalDominates:
    def test_many_leagues_alone_never_qualifies(self):
        """The brief's explicit rule: being in many leagues is
        availability, not skill."""
        joiner = rec(
            "joiner",
            observed_leagues=40,
            dynasty_leagues=40,
            completed_seasons=4,
            # Just past the win-rate floor so they stay EVALUABLE — the
            # point is that breadth alone must not qualify someone who
            # clears every gate but is unremarkable everywhere.
            wins=30,
            losses=26,
            playoff_appearances=0,
            championships=0,
            finish_percentiles=[0.45] * 40,
            roster_value_ratios=[0.95] * 40,
        )
        scored = S.score_managers([joiner, *population()])
        result = next(s for s in scored if s.user_id == "joiner")
        assert result.evaluable is True
        assert result.qualified is False, "league count alone must never qualify"

    def test_consistency_is_a_share_so_adding_mediocre_leagues_cannot_help(self):
        cfg = S.load_config()
        strong = rec(finish_percentiles=[0.9, 0.85, 0.95, 0.88])
        diluted = rec(finish_percentiles=[0.9, 0.85, 0.95, 0.88] + [0.4] * 8)
        strong_v, _ = S._consistency_component(strong, cfg)
        diluted_v, _ = S._consistency_component(diluted, cfg)
        assert diluted_v < strong_v

    def test_activity_is_capped_so_churn_cannot_buy_qualification(self):
        cfg = S.load_config()
        busy = S._activity_component(rec(trades_completed=500), cfg)
        normal = S._activity_component(rec(trades_completed=24), cfg)
        assert busy == normal == pytest.approx(1.0), "both saturate at the cap"

    def test_championship_rate_is_shrunk_toward_base(self):
        """One title in one season is mostly luck and must not read as
        a 100% championship rate."""
        lucky = S._shrunk_rate(successes=1, trials=1, base_rate=0.08, prior_n=6.0)
        sustained = S._shrunk_rate(successes=4, trials=8, base_rate=0.08, prior_n=6.0)
        assert lucky < 0.25
        assert sustained > lucky


class TestScoreVsConfidence:
    def test_score_and_confidence_are_separate_outputs(self):
        scored = S.score_managers(population())
        entry = next(s for s in scored if s.evaluable)
        assert entry.score is not None
        assert 0.0 <= entry.confidence <= 1.0
        assert entry.confidence_tier in ("high", "medium", "low")

    def test_high_score_on_thin_evidence_does_not_qualify(self):
        """Both bars must be cleared — an elite-looking record with
        minimal evidence stays out of the cohort."""
        thin_elite = rec(
            "thin_elite",
            completed_seasons=2,
            observed_leagues=2,
            completed_games=28,
            wins=24,
            losses=4,
            playoff_appearances=2,
            championships=2,
            finish_percentiles=[0.99, 0.98],
            roster_value_ratios=[2.0, 2.0],
        )
        scored = S.score_managers([thin_elite, *population()])
        result = next(s for s in scored if s.user_id == "thin_elite")
        cfg = S.load_config()
        min_conf = cfg["qualification"]["minConfidence"]
        assert result.confidence < min_conf
        assert result.qualified is False

    def test_confidence_rises_with_seasons_and_leagues(self):
        cfg = S.load_config()
        thin, _ = S.compute_confidence(rec(completed_seasons=2, observed_leagues=2), cfg)
        deep, _ = S.compute_confidence(rec(completed_seasons=8, observed_leagues=8), cfg)
        assert deep > thin

    def test_uncertainty_penalty_shrinks_with_evidence(self):
        cfg = S.load_config()
        thin = S._uncertainty_penalty(rec(completed_seasons=2, observed_leagues=2), cfg)
        deep = S._uncertainty_penalty(rec(completed_seasons=6, observed_leagues=6), cfg)
        assert thin > deep >= 0.0


class TestExplainability:
    def test_qualified_manager_stores_component_breakdown(self):
        scored = S.score_managers(population(40))
        evaluable = [s for s in scored if s.evaluable]
        assert evaluable
        entry = max(evaluable, key=lambda s: s.score or 0)
        for key in (
            "performance",
            "rosterQuality",
            "multiLeagueConsistency",
            "longevity",
            "activity",
            "uncertaintyPenalty",
        ):
            assert key in entry.components
        assert entry.components["uncertaintyPenalty"] <= 0.0

    def test_strong_manager_gets_human_readable_contributors(self):
        strong = rec(
            "strong",
            completed_seasons=6,
            observed_leagues=6,
            completed_games=84,
            wins=58,
            losses=26,
            playoff_appearances=5,
            championships=2,
            finish_percentiles=[0.95, 0.9, 0.88, 0.92, 0.85, 0.9],
            roster_value_ratios=[1.6] * 6,
        )
        scored = S.score_managers([strong, *population()])
        entry = next(s for s in scored if s.user_id == "strong")
        assert entry.contributors, "a qualified manager must explain itself"
        assert entry.qualified is True

    def test_coverage_never_claims_completeness(self):
        scored = S.score_managers(population())
        for entry in scored:
            assert entry.coverage["historyComplete"] is False
            assert "not from a manager's complete" in entry.coverage["note"]

    def test_methodology_version_is_stamped(self):
        # Asserted against the config, not a literal. Hardcoding
        # "sharp-v2" made every legitimate version bump fail here, which
        # turns the config's own "methodologyVersion must move with any
        # change" rule into an obstacle instead of a guard. What a
        # consumer needs is that the stamp matches the config that
        # produced the score.
        expected = S.methodology_version()
        assert expected
        scored = S.score_managers(population())
        assert all(s.methodology_version == expected for s in scored)


class TestCohortTiers:
    def test_four_tiers_are_distinguished(self):
        thin = rec(
            "thin", completed_seasons=1, completed_games=8, observed_leagues=1, dynasty_leagues=1
        )
        scored = S.score_managers([thin, *population()])
        tiers = S.cohort_tiers(scored)
        assert tiers["observableManagers"] == 31
        # v2 gates (dynasty-only, league age, win-rate floor) genuinely
        # bite, so evaluable is now well below observable — assert the
        # ordering, not a brittle exact count.
        assert tiers["evaluableManagers"] < tiers["observableManagers"]
        assert tiers["qualifiedManagers"] < tiers["evaluableManagers"]
        assert tiers["qualifiedManagers"] >= 1

    def test_qualification_bar_is_a_percentile_so_it_tightens_with_coverage(self):
        cfg = S.load_config()
        # v2: top quartile (0.75) rather than v1's top 15%.
        assert cfg["qualification"]["minScorePercentile"] >= 0.67


class TestPercentileRank:
    def test_identical_population_scores_midpoint_not_elite(self):
        assert S.percentile_rank(1.0, [1.0] * 10) == 0.5

    def test_empty_population_is_neutral(self):
        assert S.percentile_rank(0.9, []) == 0.5

    def test_monotone(self):
        pop = [0.1, 0.2, 0.3, 0.4, 0.5]
        assert S.percentile_rank(0.05, pop) < S.percentile_rank(0.45, pop)
