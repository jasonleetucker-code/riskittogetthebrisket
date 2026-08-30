"""Sharp Score: eligibility gates, no-single-signal-dominates, and the
separation of score from confidence."""

from __future__ import annotations

import random
import time

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


class TestPercentileRankSorted:
    """``_percentile_rank_sorted`` is the O(log N) hot-path twin of
    ``percentile_rank``, used inside ``score_managers`` (V1-61: calling
    ``percentile_rank`` fresh per manager rescans the whole population on
    every call, which measured as ~196 of ~297 total seconds of a real
    production Sharp Roster Percentage build). It must be exactly
    interchangeable with ``percentile_rank`` on the same underlying
    values — every property already proven of ``percentile_rank`` in
    ``TestPercentileRank`` above is re-proven here for the sorted/binary
    -search path, plus a broader equivalence sweep.
    """

    def test_identical_population_scores_midpoint_not_elite(self):
        assert S._percentile_rank_sorted(1.0, sorted([1.0] * 10)) == 0.5

    def test_empty_population_is_neutral(self):
        assert S._percentile_rank_sorted(0.9, []) == 0.5

    def test_monotone(self):
        pop = sorted([0.1, 0.2, 0.3, 0.4, 0.5])
        assert S._percentile_rank_sorted(0.05, pop) < S._percentile_rank_sorted(0.45, pop)

    def test_matches_percentile_rank_across_populations_and_probes(self):
        populations = [
            [],
            [1.0],
            [1.0] * 10,
            [0.1, 0.2, 0.3, 0.4, 0.5],
            [0.1, 0.1, 0.3, 0.3, 0.3, 0.9],
            [round((i * 37 % 401) * 0.0025, 4) for i in range(400)],  # duplicates + gaps
        ]
        probes = [-5.0, 0.0, 0.1, 0.13, 0.3, 0.5, 0.9, 1.0, 5.0]
        for pop in populations:
            sorted_pop = sorted(pop)
            for value in probes:
                assert S._percentile_rank_sorted(value, sorted_pop) == pytest.approx(
                    S.percentile_rank(value, pop)
                ), (pop, value)


def test_manager_score_to_dict_preserves_unknown_components_and_nested_weights():
    scored = S.ManagerScore(
        user_id="serializer",
        evaluable=True,
        score=88.8,
        components={
            "performance": 0.123456,
            "rosterQuality": None,
            "weightsApplied": {"performance": 0.461538, "rosterQuality": 0.0},
        },
    )

    payload = scored.to_dict()

    assert payload["components"]["performance"] == 0.1235
    assert payload["components"]["rosterQuality"] is None
    assert payload["components"]["weightsApplied"] == {
        "performance": 0.4615,
        "rosterQuality": 0.0,
    }


class TestScoreManagersPercentileWiring:
    """The V1-61 perf fix changed WHERE percentiles get computed
    (``score_managers`` now precomputes one sorted array per population
    axis and looks values up with ``_percentile_rank_sorted``, instead of
    ``_performance_component``/``_roster_quality_component``/the
    qualification loop each calling ``percentile_rank`` fresh per
    manager) but must not change WHAT gets computed. The equivalence
    classes in ``TestPercentileRankSorted`` above prove the primitive
    itself is correct; this proves the wiring — which population gets
    threaded into which call — was not scrambled in the process, by
    substituting the original, untouched ``percentile_rank`` back into
    every call site the fix touched and confirming the full
    ``score_managers`` output is unchanged.

    (Manually verified once, outside the committed suite, with the actual
    pre-fix implementation via ``git stash`` at N=800 and N=6000: byte-
    identical ``ManagerScore.to_dict()`` output both times, real-code not
    reasoning-only. This test is the permanent, automated form of that
    check.)
    """

    def test_matches_reference_percentile_rank_at_every_call_site(self, monkeypatch):
        # Deliberately SHUFFLED: the `population()` helper builds records
        # in monotonically increasing win_pct/finish/roster-ratio order, so
        # `records` (and therefore the internal `raw_scores`, built by
        # appending each manager's total score in iteration order) comes
        # out already ascending by coincidence. A prior version of this
        # test used the unshuffled population and passed even when the
        # `score_percentile` call site was mutated to read the raw
        # (unsorted-by-construction) `raw_scores` list directly instead of
        # `sorted_raw_scores` -- bisect on an already-sorted-by-luck input
        # happens to still be correct. Shuffling breaks that coincidence
        # and is what actually proves the call site sorts before it binary
        # -searches. Verified: this exact mutation (drop `sorted(...)`,
        # feed `_percentile_rank_sorted` the unsorted `raw_scores`) makes
        # ~90 of 94 evaluated managers' scorePercentile disagree with the
        # reference on this shuffled input, and 0 disagree on the
        # unshuffled one -- keep the shuffle.
        records = population(150)
        rng = random.Random(20260830)
        rng.shuffle(records)

        fast = [entry.to_dict() for entry in S.score_managers(records)]

        # Delegate the fast path back to the original O(N) primitive.
        # Sorting doesn't change a multiset, so percentile_rank produces
        # the identical number whether or not its input happens to be
        # pre-sorted -- this is a faithful reference, not an approximation.
        monkeypatch.setattr(S, "_percentile_rank_sorted", S.percentile_rank)

        reference = [entry.to_dict() for entry in S.score_managers(records)]

        assert fast == reference
        # Sanity check the swap actually exercised real evaluable managers,
        # not an early-exit no-op that would make the equality above
        # vacuous.
        evaluated = [e for e in fast if e.get("evaluable") and e.get("score") is not None]
        assert len(evaluated) > 50


class TestScoreManagersScaleGuard:
    """Regression guard against re-introducing an O(N^2) percentile scan
    in ``score_managers`` (V1-61). Measured directly against the real
    pre-fix implementation via ``git stash`` before writing this bound:
    at N=8000, the O(N^2) code took 13.8s and the O(N log N) fix takes
    1.8s. The bound below sits well above the fixed code's real time
    (headroom for a slow CI runner) and well below the quadratic code's
    real time, so a reintroduced rescan-per-manager fails this loudly
    without making routine test runs slow.
    """

    def test_large_population_scores_well_within_the_quadratic_gap(self):
        records = population(8000)
        start = time.perf_counter()
        S.score_managers(records)
        elapsed = time.perf_counter() - start
        assert elapsed < 6.0, (
            f"score_managers took {elapsed:.2f}s for 8000 managers — "
            "this is the V1-61 quadratic-percentile regression guard; "
            "if this is genuinely slow again, check for a percentile_rank "
            "call reintroduced inside the per-manager loop"
        )


class TestChampionshipBaseHoist:
    """The championship shrinkage target is a POPULATION property, hoisted
    out of the per-manager loop (V1-61).

    ``_performance_component`` used to re-derive it on every call via
    ``_mean`` over a list holding one entry per evaluable manager, with an
    ``isinstance`` test per element -- O(N^2). Measured at the production
    population: 162,016,665 ``isinstance`` calls, 92% of ``score_managers``.
    """

    def test_hoisted_base_matches_deriving_it_per_manager(self):
        """The whole output, not just the timing, must be unchanged."""
        records = population(150)
        hoisted = [e.to_dict() for e in S.score_managers(records)]

        # Reproduce the retired per-manager derivation by forcing the
        # component to derive its own base (championship_base=None is that
        # legacy path, kept for ad-hoc callers).
        cfg = S.load_config()
        pop = S.build_population(records, cfg)
        sorted_pop = {
            key: sorted(float(v) for v in vals if isinstance(v, (int, float)))
            for key, vals in pop.items()
        }
        base = S._mean(sorted_pop.get("championshipRate") or []) or 0.08
        for rec in records:
            if S.check_eligibility(rec, cfg):
                continue
            assert S._performance_component(
                rec, sorted_pop, cfg, championship_base=base
            ) == S._performance_component(rec, sorted_pop, cfg), rec.user_id

        assert len(hoisted) == len(records)

    def test_base_is_derived_from_the_list_the_component_actually_receives(self, monkeypatch):
        """Sorted and unsorted hold the same multiset but sum differently.

        Floating-point addition is not associative, so averaging
        ``population`` instead of ``sorted_population`` yields a slightly
        different base, which propagates through ``_shrunk_rate`` into a
        percentile lookup and moves real published values. Measured on a
        45,000-manager population: sourcing it from the unsorted list moved
        one manager's performance component 0.2433 -> 0.2186, his score
        47.4 -> 46.3, and changed 12,720 of 45,000 rows.

        An ordinary test population cannot expose this -- its championship
        rates are all small and similar, so both orders agree to the last
        bit. So the population is replaced with one that is genuinely
        summation-order sensitive, and the base actually handed to
        ``_performance_component`` is captured and checked against the two
        candidates.
        """
        order_sensitive = [1e16] + [1.0] * 200
        from_raw = S._mean(order_sensitive)
        from_sorted = S._mean(sorted(order_sensitive))
        assert from_raw != from_sorted, "fixture no longer separates the two orders"

        real_build_population = S.build_population

        def fake_build_population(records, cfg):
            pop = real_build_population(records, cfg)
            pop["championshipRate"] = list(order_sensitive)
            return pop

        seen: list[float | None] = []
        real_component = S._performance_component

        def spy(rec_, population_, cfg_, championship_base=None):
            seen.append(championship_base)
            return real_component(rec_, population_, cfg_, championship_base=championship_base)

        monkeypatch.setattr(S, "build_population", fake_build_population)
        monkeypatch.setattr(S, "_performance_component", spy)
        S.score_managers(population(40))

        assert seen, "no evaluable manager was scored, so nothing was proven"
        assert set(seen) == {from_sorted}, (
            "score_managers must derive championship_base from the SAME list it "
            "hands the component (sorted_population), not from the raw population"
        )
        assert from_raw not in seen

    def test_an_empty_population_still_falls_back_to_the_prior(self):
        """`or 0.08` is the documented prior, not a coerced zero."""
        cfg = S.load_config()
        rec = population(1)[0]
        value, _ = S._performance_component(rec, {}, cfg, championship_base=None)
        assert isinstance(value, float)
        # An explicit base of 0.0 is falsy; the retired expression turned it
        # into 0.08 and the hoisted one must not diverge from that.
        assert S._performance_component(
            rec, {}, cfg, championship_base=(S._mean([]) or 0.08)
        ) == S._performance_component(rec, {}, cfg, championship_base=0.08)
