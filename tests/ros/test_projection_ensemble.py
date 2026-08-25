"""C5-PROJ-D — ROS / full-season projection ensemble.

Pinned against docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md §6/§9 item 4.
"""

from __future__ import annotations

import statistics
import tempfile
from pathlib import Path

import pytest

from src.bdvm.projections import ProjectionRecord, write_snapshot
from src.ros.projection_ensemble import (
    EnsembleBuildResult,
    EnsembleObservation,
    FamilyValue,
    ProjectionEnsembleError,
    build_ros_full_season_ensemble,
    combine_ensemble,
    reduce_family,
)
from src.ros.projection_observations import ProjectionObservation

SCORING = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rec_first_down": 0.0}


def _obs(
    *,
    provider_family="espnClay",
    census_source_key="clayProjections",
    player_key="player one",
    position="WR",
    season=2026,
    horizon="PRESEASON_FULL_SEASON",
    as_of="2026-07-20",
    games=17.0,
    league_scored_fpg=14.0,
    is_proxy=False,
    evidence_class="PROJECTION_MODEL",
):
    return ProjectionObservation(
        census_source_key=census_source_key,
        provider_family=provider_family,
        evidence_class=evidence_class,
        horizon=horizon,
        access_posture="PUBLIC_NO_AUTH",
        player_key=player_key,
        position=position,
        season=season,
        as_of=as_of,
        games=games,
        league_scored_fpg=league_scored_fpg,
        league_scored_is_native=True,
        native_fpg=league_scored_fpg,
        native_is_scoring_native=True,
        stat_line_available=False,
        proj_high=None,
        proj_low=None,
        is_proxy=is_proxy,
    )


class TestReduceFamily:
    def test_single_observation_is_passthrough(self):
        fv = reduce_family([_obs(league_scored_fpg=14.0)])
        assert isinstance(fv, FamilyValue)
        assert fv.league_scored_fpg == 14.0
        assert fv.source_count == 1
        assert fv.provider_family == "espnClay"

    def test_multiple_observations_in_one_family_reduce_by_median_not_mean(self):
        # Median of [10, 12, 20] is 12 - proves median, not mean (14), is used.
        rows = [
            _obs(league_scored_fpg=10.0, census_source_key="clayProjections"),
            _obs(league_scored_fpg=12.0, census_source_key="clayProjectionsAlt"),
            _obs(league_scored_fpg=20.0, census_source_key="clayProjectionsAlt2"),
        ]
        fv = reduce_family(rows)
        assert fv.league_scored_fpg == 12.0
        assert fv.source_count == 3

    def test_mixed_families_in_one_call_is_refused(self):
        rows = [_obs(provider_family="espnClay"), _obs(provider_family="theIdpShow")]
        with pytest.raises(ProjectionEnsembleError):
            reduce_family(rows)

    def test_mixed_players_in_one_call_is_refused(self):
        rows = [_obs(player_key="player one"), _obs(player_key="player two")]
        with pytest.raises(ProjectionEnsembleError):
            reduce_family(rows)


class TestCombineEnsembleSingleFamily:
    def test_n1_is_honest_passthrough_not_a_fabricated_ensemble(self):
        obs = combine_ensemble([_obs(league_scored_fpg=14.0)], method="median")
        assert isinstance(obs, EnsembleObservation)
        assert obs.family_count == 1
        assert obs.combined_league_scored_fpg == 14.0
        # Forced regardless of the requested method - proves the override fires.
        assert obs.combination_method == "single_family_passthrough"

    def test_n1_disagreement_is_none_not_zero(self):
        """Mutation-proof: if the n=1 branch's disagreement_spread /
        disagreement_stddev were changed from None to 0.0, this test
        (which asserts `is None` specifically, not falsy) would go RED.
        A falsy-style check (`assert not obs.disagreement_spread`) would
        NOT catch that mutation, since 0.0 is also falsy - this is why
        `is None` is required here."""
        obs = combine_ensemble([_obs()])
        assert obs.disagreement_spread is None
        assert obs.disagreement_stddev is None


class TestCombineEnsembleTwoFamilies:
    def test_equal_family_mean_n2(self):
        rows = [
            _obs(
                provider_family="espnClay",
                census_source_key="clayProjections",
                league_scored_fpg=14.0,
            ),
            _obs(
                provider_family="theIdpShow",
                census_source_key="idpShowProjections",
                league_scored_fpg=18.0,
            ),
        ]
        obs = combine_ensemble(rows, method="equal_family_mean")
        assert obs.family_count == 2
        assert obs.combined_league_scored_fpg == 16.0
        assert obs.combination_method == "equal_family_mean"
        assert obs.disagreement_spread == 4.0
        assert obs.disagreement_stddev == pytest.approx(statistics.pstdev([14.0, 18.0]))

    def test_median_method_diverges_from_mean_with_three_families(self):
        # mean([10, 14, 40]) != median([10, 14, 40]) - proves the two
        # methods genuinely produce different answers, not the same
        # computation under two names.
        rows = [
            _obs(
                provider_family="espnClay",
                census_source_key="clayProjections",
                league_scored_fpg=10.0,
            ),
            _obs(
                provider_family="theIdpShow",
                census_source_key="idpShowProjections",
                league_scored_fpg=14.0,
            ),
            _obs(
                provider_family="thirdFamily",
                census_source_key="thirdSource",
                league_scored_fpg=40.0,
            ),
        ]
        mean_obs = combine_ensemble(rows, method="equal_family_mean")
        median_obs = combine_ensemble(rows, method="median")
        assert mean_obs.combined_league_scored_fpg == pytest.approx(21.333333, abs=1e-4)
        assert median_obs.combined_league_scored_fpg == 14.0
        assert mean_obs.combined_league_scored_fpg != median_obs.combined_league_scored_fpg

    def test_trimmed_mean_requires_at_least_three_families(self):
        rows = [
            _obs(
                provider_family="espnClay",
                census_source_key="clayProjections",
                league_scored_fpg=14.0,
            ),
            _obs(
                provider_family="theIdpShow",
                census_source_key="idpShowProjections",
                league_scored_fpg=18.0,
            ),
        ]
        with pytest.raises(ProjectionEnsembleError):
            combine_ensemble(rows, method="trimmed_mean")

    def test_trimmed_mean_with_three_families_drops_both_ends(self):
        rows = [
            _obs(
                provider_family="espnClay",
                census_source_key="clayProjections",
                league_scored_fpg=10.0,
            ),
            _obs(
                provider_family="theIdpShow",
                census_source_key="idpShowProjections",
                league_scored_fpg=14.0,
            ),
            _obs(
                provider_family="thirdFamily",
                census_source_key="thirdSource",
                league_scored_fpg=40.0,
            ),
        ]
        obs = combine_ensemble(rows, method="trimmed_mean")
        # Only the middle value (14.0) survives trimming both ends of 3.
        assert obs.combined_league_scored_fpg == 14.0


class TestMissingFamilyReporting:
    def test_contributing_families_names_which_families_voted(self):
        rows = [
            _obs(
                provider_family="espnClay",
                census_source_key="clayProjections",
                league_scored_fpg=14.0,
            ),
            _obs(
                provider_family="theIdpShow",
                census_source_key="idpShowProjections",
                league_scored_fpg=18.0,
            ),
        ]
        obs = combine_ensemble(rows)
        names = {fv.provider_family for fv in obs.contributing_families}
        assert names == {"espnClay", "theIdpShow"}


class TestGamesConsistency:
    def test_agreeing_games_is_reported(self):
        rows = [
            _obs(provider_family="espnClay", games=17.0),
            _obs(provider_family="theIdpShow", games=17.0),
        ]
        obs = combine_ensemble(rows)
        assert obs.games == 17.0

    def test_disagreeing_games_is_none_not_averaged(self):
        rows = [
            _obs(provider_family="espnClay", games=17.0),
            _obs(provider_family="theIdpShow", games=16.0),
        ]
        obs = combine_ensemble(rows)
        assert obs.games is None


class TestHorizonAndSeasonGuard:
    """Mutation-proof: comment out the `len(horizons) > 1` (or
    `len(seasons) > 1`) branch in `_assert_single_horizon_and_season` and
    these specific tests must go RED. Restore afterward - nothing
    committed mutated."""

    def test_refuses_to_combine_two_horizons_in_one_call(self):
        rows = [
            _obs(horizon="WEEKLY"),
            _obs(horizon="PRESEASON_FULL_SEASON"),
        ]
        with pytest.raises(ProjectionEnsembleError):
            combine_ensemble(rows)

    def test_refuses_to_combine_two_seasons_in_one_call(self):
        rows = [_obs(season=2026), _obs(season=2027)]
        with pytest.raises(ProjectionEnsembleError):
            combine_ensemble(rows)

    def test_refuses_an_empty_observation_set(self):
        with pytest.raises(ProjectionEnsembleError):
            combine_ensemble([])


class TestNoProxyOrRankingsOnlyEnters:
    def test_a_proxy_observation_cannot_enter_the_ensemble(self):
        with pytest.raises(ProjectionEnsembleError):
            combine_ensemble([_obs(is_proxy=True)])

    def test_a_rankings_only_evidence_class_cannot_reach_this_module(self):
        with pytest.raises(ProjectionEnsembleError):
            combine_ensemble([_obs(evidence_class="RANKINGS_ONLY")])


class TestBuildRosFullSeasonEnsemble:
    def test_real_snapshot_round_trip_produces_family_count_2_for_a_shared_defender(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            records = [
                # A defender covered by BOTH live sources - a real n=2 case.
                ProjectionRecord(
                    source="clayProjections",
                    player_key="shared linebacker",
                    position="LB",
                    season=2026,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=12.0,
                    scoring_native=True,
                ),
                ProjectionRecord(
                    source="idpShowProjections",
                    player_key="shared linebacker",
                    position="LB",
                    season=2026,
                    as_of="2026-07-21",
                    games=17.0,
                    fpg=16.0,
                    scoring_native=True,
                ),
                # A WR only Clay covers - a real n=1 passthrough case.
                ProjectionRecord(
                    source="clayProjections",
                    player_key="clay only wr",
                    position="WR",
                    season=2026,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=15.0,
                    scoring_native=True,
                ),
            ]
            write_snapshot(records, season=2026, as_of="2026-07-21", base_dir=base_dir)

            result = build_ros_full_season_ensemble(
                season=2026, scoring_settings=SCORING, base_dir=base_dir
            )

        assert isinstance(result, EnsembleBuildResult)
        by_player = {e.player_key: e for e in result.ensemble}
        assert by_player["shared linebacker"].family_count == 2
        assert by_player["shared linebacker"].combined_league_scored_fpg == 14.0
        assert by_player["shared linebacker"].combination_method == "equal_family_mean"
        assert by_player["clay only wr"].family_count == 1
        assert by_player["clay only wr"].combination_method == "single_family_passthrough"
        assert set(result.sources_loaded) == {"clayProjections", "idpShowProjections"}
        assert result.sources_unavailable == ()

    def test_sources_unavailable_is_named_not_silently_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_ros_full_season_ensemble(
                season=2099, scoring_settings=SCORING, base_dir=Path(tmp)
            )
        assert result.ensemble == ()
        assert set(result.sources_unavailable) == {"clayProjections", "idpShowProjections"}
        assert result.sources_loaded == ()

    def test_requesting_a_horizon_no_named_source_publishes_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(ProjectionEnsembleError):
                build_ros_full_season_ensemble(
                    season=2026,
                    scoring_settings=SCORING,
                    horizon="WEEKLY",
                    base_dir=Path(tmp),
                )
