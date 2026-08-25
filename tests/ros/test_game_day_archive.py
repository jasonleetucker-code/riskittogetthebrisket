"""C5-GD-02 — prediction archive without temporal leakage.

Pinned against docs/C_SERIES_SCOPE_MANIFEST.md's C5-GD-02 row and
docs/GAME_DAY_PROBABILITY_SPEC.md §5's archival requirement.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ros.game_day_archive import (
    GameDayArchiveError,
    PlayerPointEstimate,
    WeeklyPredictionSnapshot,
    load_snapshot,
    load_snapshots_for_week,
    record_snapshot,
)


def _roster():
    return [
        PlayerPointEstimate(
            player_id="qb1",
            position="QB",
            is_lineup_eligible=True,
            point_estimate=18.5,
            estimate_source="bdvm",
        ),
        PlayerPointEstimate(
            player_id="rb1",
            position="RB",
            is_lineup_eligible=True,
            point_estimate=None,  # no source covers this player
            estimate_source=None,
        ),
        PlayerPointEstimate(
            player_id="wr1",
            position="WR",
            is_lineup_eligible=False,  # bench, ineligible this week (e.g. bye)
            point_estimate=9.0,
            estimate_source="bdvm",
        ),
    ]


class TestPlayerPointEstimateInvariant:
    def test_missing_estimate_stays_missing_not_zero(self):
        p = PlayerPointEstimate(player_id="x", position="RB", is_lineup_eligible=True)
        assert p.point_estimate is None
        assert p.estimate_source is None

    def test_source_without_estimate_is_refused(self):
        with pytest.raises(GameDayArchiveError):
            PlayerPointEstimate(
                player_id="x",
                position="RB",
                is_lineup_eligible=True,
                point_estimate=None,
                estimate_source="bdvm",
            )

    def test_estimate_without_source_is_refused(self):
        with pytest.raises(GameDayArchiveError):
            PlayerPointEstimate(
                player_id="x",
                position="RB",
                is_lineup_eligible=True,
                point_estimate=12.0,
                estimate_source=None,
            )


class TestSnapshotConstructionInvariants:
    def test_bad_capture_kind_is_refused(self):
        with pytest.raises(GameDayArchiveError):
            WeeklyPredictionSnapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="halftime",  # not in CAPTURE_KINDS
                captured_at="2026-09-15T17:00:00+00:00",
                scoring_config_id="cfg1",
                starter_slots=("QB",),
                roster=tuple(_roster()),
            )

    def test_empty_roster_is_refused(self):
        with pytest.raises(GameDayArchiveError):
            WeeklyPredictionSnapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                captured_at="2026-09-15T17:00:00+00:00",
                scoring_config_id="cfg1",
                starter_slots=("QB",),
                roster=(),
            )

    def test_duplicate_player_in_one_roster_is_refused(self):
        dupe = _roster()
        dupe.append(dupe[0])
        with pytest.raises(GameDayArchiveError):
            WeeklyPredictionSnapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                captured_at="2026-09-15T17:00:00+00:00",
                scoring_config_id="cfg1",
                starter_slots=("QB",),
                roster=tuple(dupe),
            )


class TestRecordAndLoadRoundTrip:
    def test_round_trip_preserves_missing_and_present_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                scoring_config_id="cfg1",
                starter_slots=["QB", "RB", "WR"],
                roster=_roster(),
                run_id="run-1",
                base_dir=base,
            )
            loaded = load_snapshot("dynasty_main", 2026, 3, "1", "pregame", base_dir=base)
        assert loaded is not None
        by_id = {p.player_id: p for p in loaded.roster}
        assert by_id["qb1"].point_estimate == 18.5
        assert by_id["qb1"].estimate_source == "bdvm"
        assert by_id["rb1"].point_estimate is None
        assert by_id["rb1"].estimate_source is None
        assert by_id["wr1"].is_lineup_eligible is False
        assert loaded.run_id == "run-1"
        assert loaded.starter_slots == ("QB", "RB", "WR")

    def test_load_of_never_captured_tuple_is_none_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_snapshot("dynasty_main", 2026, 3, "1", "pregame", base_dir=Path(tmp))
        assert result is None

    def test_captured_at_is_the_real_clock_not_a_caller_supplied_value(self):
        """record_snapshot's signature accepts no captured_at parameter
        at all — this test confirms the stamped value is a real,
        current UTC timestamp, not something a caller could have
        injected."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            before = datetime.now(timezone.utc)
            snap = record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
            after = datetime.now(timezone.utc)
        captured = datetime.fromisoformat(snap.captured_at)
        assert before <= captured <= after

    def test_load_snapshots_for_week_returns_every_team(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for team in ("1", "2", "3"):
                record_snapshot(
                    league_key="dynasty_main",
                    season=2026,
                    week=5,
                    team_id=team,
                    capture_kind="pregame",
                    scoring_config_id="cfg1",
                    starter_slots=["QB"],
                    roster=_roster(),
                    base_dir=base,
                )
            teams = load_snapshots_for_week("dynasty_main", 2026, 5, base_dir=base)
        assert {s.team_id for s in teams} == {"1", "2", "3"}

    def test_load_snapshots_for_week_filters_by_capture_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=5,
                team_id="1",
                capture_kind="pregame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
            record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=5,
                team_id="1",
                capture_kind="postgame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
            pregame_only = load_snapshots_for_week(
                "dynasty_main", 2026, 5, capture_kind="pregame", base_dir=base
            )
        assert len(pregame_only) == 1
        assert pregame_only[0].capture_kind == "pregame"

    def test_a_week_with_nothing_captured_returns_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_snapshots_for_week("dynasty_main", 2026, 99, base_dir=Path(tmp))
        assert result == []


class TestDuplicateCaptureIsRefused:
    """Mutation-proof pair: the second test's assertion only survives if
    the refusal genuinely fires — a version of record_snapshot that
    silently overwrote would still leave `load_snapshot` returning A
    result, so the FIRST test alone would not catch a regression to
    silent-overwrite. The second test's exception assertion is the one
    that actually pins append-only-ness."""

    def test_first_capture_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            snap = record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
        assert snap.team_id == "1"

    def test_second_capture_of_the_same_tuple_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
            with pytest.raises(GameDayArchiveError):
                record_snapshot(
                    league_key="dynasty_main",
                    season=2026,
                    week=3,
                    team_id="1",
                    capture_kind="pregame",
                    scoring_config_id="cfg1",
                    starter_slots=["QB"],
                    # Deliberately DIFFERENT content from the first write —
                    # proves the refusal is on IDENTITY, not a content diff.
                    roster=[
                        PlayerPointEstimate(
                            player_id="somebody_else",
                            position="TE",
                            is_lineup_eligible=True,
                        )
                    ],
                    base_dir=base,
                )
            # The original snapshot must be untouched by the refused write.
            loaded = load_snapshot("dynasty_main", 2026, 3, "1", "pregame", base_dir=base)
            assert {p.player_id for p in loaded.roster} == {p.player_id for p in _roster()}

    def test_a_different_capture_kind_for_the_same_week_is_not_a_duplicate(self):
        """pregame and postgame for the same team-week are distinct
        records, not a collision — the identity includes capture_kind."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="pregame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
            # Must not raise.
            record_snapshot(
                league_key="dynasty_main",
                season=2026,
                week=3,
                team_id="1",
                capture_kind="postgame",
                scoring_config_id="cfg1",
                starter_slots=["QB"],
                roster=_roster(),
                base_dir=base,
            )
