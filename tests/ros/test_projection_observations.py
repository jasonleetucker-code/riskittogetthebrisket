"""C5-PROJ-B — canonical projection-stat schema + exact-league rescoring.

Pinned against docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md §4/§5/§6.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.bdvm.projections import ProjectionError, ProjectionRecord, write_snapshot
from src.ros.projection_observations import (
    LoadResult,
    ProjectionObservation,
    ProjectionObservationError,
    load_and_rescore_source,
    rescore_projection_record,
)

SCORING = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "rec_first_down": 0.0}


def _clay_record(*, fpg=None, fpts=None, stat_line=None, is_proxy=False, games=17.0):
    return ProjectionRecord(
        source="clayProjections",
        player_key="player one",
        position="WR",
        season=2026,
        as_of="2026-07-20",
        games=games,
        stat_line=stat_line,
        fpg=fpg,
        fpts=fpts,
        scoring_native=fpg is not None or fpts is not None,
        is_proxy=is_proxy,
        proj_high=None,
        proj_low=None,
    )


class TestRescoreProjectionRecord:
    def test_native_fpg_is_carried_as_diagnostic_and_league_scored_is_the_real_output(self):
        record = _clay_record(fpg=15.0)
        obs = rescore_projection_record(
            record, scoring_settings=SCORING, census_source_key="clayProjections"
        )
        assert isinstance(obs, ProjectionObservation)
        assert obs.native_fpg == 15.0
        assert obs.native_is_scoring_native is True
        # No stat_line supplied, so resolve_fpg falls back to the native fpg.
        assert obs.league_scored_fpg == 15.0
        assert obs.league_scored_is_native is True

    def test_census_fields_are_carried_from_the_c5_proj_a_registry(self):
        record = _clay_record(fpg=15.0)
        obs = rescore_projection_record(
            record, scoring_settings=SCORING, census_source_key="clayProjections"
        )
        assert obs.census_source_key == "clayProjections"
        assert obs.provider_family == "espnClay"
        assert obs.evidence_class == "PROJECTION_MODEL"
        assert obs.horizon == "PRESEASON_FULL_SEASON"
        assert obs.access_posture == "PUBLIC_NO_AUTH"

    def test_proxy_rows_are_excluded_by_default(self):
        record = _clay_record(fpg=15.0, is_proxy=True)
        obs = rescore_projection_record(
            record, scoring_settings=SCORING, census_source_key="clayProjections"
        )
        assert obs is None

    def test_proxy_rows_can_be_included_explicitly_and_stay_labelled(self):
        record = _clay_record(fpg=15.0, is_proxy=True)
        obs = rescore_projection_record(
            record,
            scoring_settings=SCORING,
            census_source_key="clayProjections",
            include_proxy=True,
        )
        assert obs is not None
        assert obs.is_proxy is True

    def test_unknown_census_source_key_raises_rather_than_silently_labels(self):
        record = _clay_record(fpg=15.0)
        with pytest.raises(ProjectionObservationError):
            rescore_projection_record(
                record, scoring_settings=SCORING, census_source_key="totallyMadeUpSource"
            )

    def test_rankings_only_census_source_refuses_to_be_rescored_as_a_projection(self):
        record = ProjectionRecord(
            source="fantasyProsRosSf",
            player_key="player one",
            position="WR",
            season=2026,
            as_of="2026-07-20",
            games=17.0,
            fpg=15.0,
            scoring_native=True,
        )
        with pytest.raises(ProjectionObservationError):
            rescore_projection_record(
                record, scoring_settings=SCORING, census_source_key="fantasyProsRosSf"
            )

    def test_stat_line_is_rescored_through_exact_league_scoring_not_passed_through(self):
        # Stat-line vocabulary is the nflverse column names
        # score_stat_line_per_game/compute_weekly_points read
        # (`receptions`/`receiving_yards`/...), NOT Sleeper scoring-key
        # names (`rec`/`rec_yd`/...) — this is exactly the distinction
        # plan §4/§5 draws between a raw stat line and a scored total.
        # 10 receptions, 100 rec yards, 1 rec TD, over 1 game.
        record = _clay_record(
            stat_line={"receptions": 10.0, "receiving_yards": 100.0, "receiving_tds": 1.0},
            games=1.0,
        )
        obs = rescore_projection_record(
            record, scoring_settings=SCORING, census_source_key="clayProjections"
        )
        # rec(1.0)*10 + rec_yd(0.1)*100 + rec_td(6.0)*1 = 10+10+6 = 26
        assert obs.league_scored_fpg == pytest.approx(26.0, abs=0.5)
        assert obs.stat_line_available is True
        # No native fpg/fpts supplied on this record.
        assert obs.native_fpg is None

    def test_missing_evidence_stays_missing_no_stat_line_no_native_total(self):
        """A record with neither a stat line nor a native total cannot be
        constructed at all — ProjectionRecord.__post_init__ already
        refuses it, which this wrapper inherits rather than papering over
        with a fabricated 0.0."""
        with pytest.raises(ProjectionError):
            _clay_record()  # no fpg, no fpts, no stat_line


class TestLoadAndRescoreSource:
    def test_no_census_entry_is_a_named_refusal(self):
        result = load_and_rescore_source(
            "totallyMadeUpSource", season=2026, scoring_settings=SCORING
        )
        assert isinstance(result, LoadResult)
        assert result.status == "no_census_entry"
        assert result.observations == ()

    def test_no_snapshot_is_a_named_refusal_not_an_empty_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_and_rescore_source(
                "clayProjections",
                season=2026,
                scoring_settings=SCORING,
                base_dir=Path(tmp),
            )
        assert result.status == "no_snapshot"
        assert result.observations == ()

    def test_real_snapshot_round_trips_through_load_and_rescore(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            records = [
                ProjectionRecord(
                    source="clayProjections",
                    player_key="real player",
                    position="WR",
                    season=2026,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=15.0,
                    scoring_native=True,
                    is_proxy=False,
                ),
                ProjectionRecord(
                    source="clayProjections",
                    player_key="proxy player",
                    position="WR",
                    season=2026,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=8.0,
                    scoring_native=True,
                    is_proxy=True,
                ),
            ]
            write_snapshot(records, season=2026, as_of="2026-07-20", base_dir=base_dir)

            result = load_and_rescore_source(
                "clayProjections",
                season=2026,
                scoring_settings=SCORING,
                base_dir=base_dir,
            )
        assert result.status == "ok"
        assert len(result.observations) == 1
        assert result.observations[0].player_key == "real player"
        assert result.proxy_rows_excluded == 1

    def test_other_sources_in_the_same_snapshot_are_not_mixed_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            records = [
                ProjectionRecord(
                    source="clayProjections",
                    player_key="clay player",
                    position="WR",
                    season=2026,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=15.0,
                    scoring_native=True,
                ),
                ProjectionRecord(
                    source="idpShowProjections",
                    player_key="idp player",
                    position="LB",
                    season=2026,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=12.0,
                    scoring_native=True,
                ),
            ]
            write_snapshot(records, season=2026, as_of="2026-07-20", base_dir=base_dir)

            result = load_and_rescore_source(
                "clayProjections",
                season=2026,
                scoring_settings=SCORING,
                base_dir=base_dir,
            )
        assert len(result.observations) == 1
        assert result.observations[0].player_key == "clay player"
