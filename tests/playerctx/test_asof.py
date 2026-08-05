"""Date → observable week, on fixtures rather than the network.

The `snapTrend` axis cannot be replayed without this: `snap_counts` has
no date column and is republished with every completed week, so reading
it unbounded for a past date is a look-ahead. These pin the two ways
that goes wrong quietly — counting a week whose games are still to be
played, and counting the same day's games.
"""

from __future__ import annotations

from src.playerctx import asof


def game(week: int, gameday: str, *, game_type: str = "REG") -> dict[str, str]:
    return {"week": str(week), "gameday": gameday, "game_type": game_type}


SEASON_2025 = [
    game(1, "2025-09-04"),
    game(1, "2025-09-07"),
    game(1, "2025-09-08"),  # MNF
    game(2, "2025-09-14"),
    game(2, "2025-09-15"),  # MNF
    game(3, "2025-09-21"),
    game(3, "2025-09-22"),  # MNF
]


class TestCompletedWeekOn:
    def test_a_week_counts_only_once_every_game_is_played(self):
        # Sunday of week 2 is done but MNF is not — week 2 is not final,
        # so the answer is still week 1.
        assert asof.completed_week_on(SEASON_2025, "2025-09-15") == 1
        assert asof.completed_week_on(SEASON_2025, "2025-09-16") == 2

    def test_the_same_days_games_do_not_count(self):
        """Snap counts publish after the game, not during it.

        Week 1's last game is Monday 8 September. On the 8th those snaps
        do not exist yet; counting them would leak a few hours of the
        future into every Monday replay.
        """
        assert asof.completed_week_on(SEASON_2025, "2025-09-08") is None
        assert asof.completed_week_on(SEASON_2025, "2025-09-09") == 1

    def test_a_preseason_date_is_none_not_zero(self):
        # None is "no replay is possible here"; 0 would be a week number
        # a caller could pass to `through_week` and get an empty file
        # back, which reads as a fold with no players rather than as a
        # refusal.
        assert asof.completed_week_on(SEASON_2025, "2025-08-01") is None

    def test_after_the_season_it_is_the_last_week(self):
        assert asof.completed_week_on(SEASON_2025, "2026-03-01") == 3

    def test_an_undated_game_blocks_its_week_rather_than_being_ignored(self):
        rows = [*SEASON_2025, game(4, "")]
        assert asof.completed_week_on(rows, "2026-03-01") == 3

    def test_a_gap_stops_at_the_gap(self):
        # Week 5 complete but week 4 unplayed must not report 5 — the
        # replay would read weeks 1-5 including the unplayed one.
        rows = [game(1, "2025-09-07"), game(4, "2025-12-01"), game(5, "2025-10-05")]
        assert asof.completed_week_on(rows, "2025-11-01") == 1

    def test_postseason_weeks_are_in_range(self):
        rows = [game(22, "2026-02-08", game_type="SB")]
        assert asof.completed_week_on(rows, "2026-02-10") == 22

    def test_no_rows_is_none(self):
        assert asof.completed_week_on([], "2025-11-01") is None

    def test_a_junk_date_is_none_rather_than_an_exception(self):
        assert asof.completed_week_on(SEASON_2025, "") is None


class TestObservableAsOf:
    def _fetch(self, table):
        return lambda season: table.get(season, [])

    def test_an_in_season_date_resolves_to_that_season(self):
        window = asof.observable_as_of("2025-09-16", fetch_rows=self._fetch({2025: SEASON_2025}))
        assert window.season == 2025
        assert window.through_week == 2
        assert window.depth_as_of == "2025-09-16"

    def test_january_falls_back_to_the_previous_season(self):
        # The calendar year has no football yet; the season that is
        # actually in progress started the year before.
        window = asof.observable_as_of(
            "2026-01-15", fetch_rows=self._fetch({2026: [], 2025: SEASON_2025})
        )
        assert window.season == 2025
        assert window.through_week == 3

    def test_the_offseason_snap_window_is_one_frozen_observation(self):
        """The finding that made this whole exercise necessary.

        Every offseason date resolves to the same completed season and
        the same final week, because that is genuinely what was
        observable. `snapTrend` is therefore the same number on 16 April
        and on 3 August, and a caller replaying an all-offseason panel
        gets one observation resampled — which it can detect here and
        refuse, rather than reporting it as several folds.

        Asserted on the snap window alone, not the whole `AsOf`:
        `depth_as_of` is the date itself and legitimately differs, since
        the depth-chart file does carry dated offseason snapshots. It is
        the snap half that is frozen.
        """
        fetch = self._fetch({2026: [], 2025: SEASON_2025})
        windows = {
            (w.season, w.through_week)
            for w in (
                asof.observable_as_of(d, fetch_rows=fetch)
                for d in ("2026-04-16", "2026-06-01", "2026-08-03")
            )
        }
        assert windows == {(2025, 3)}

    def test_before_any_football_is_none(self):
        assert (
            asof.observable_as_of("2025-08-01", fetch_rows=self._fetch({2025: SEASON_2025})) is None
        )

    def test_a_failing_fetch_degrades_rather_than_raising(self):
        def boom(season):
            raise RuntimeError("network down")

        assert asof.observable_as_of("2025-11-01", fetch_rows=boom) is None

    def test_a_malformed_date_is_none(self):
        assert asof.observable_as_of("nope", fetch_rows=self._fetch({})) is None
