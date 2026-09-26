"""``require_full_band`` on ``replacement_per_game`` — the thin-sample gate.

Reproduces the live defect this fixed: with only 1-2 NFL games played this
season, the number of DISTINCT players who have started at a position
(e.g. LB, cutoff 36 in a real 12-team/3-LB-slot league) is often far below
``starter_slots + band_size``. The default fallback then anchors
"replacement level" on the single WORST per-game rate in the whole
position pool — often a one-game emergency fill-in — which is noise, not
a baseline. A real performer's VORP then reads as roughly his full point
total (e.g. the reported "T.J. Watt: 50.0 VORP" through 1-2 games), not a
genuine surplus over a meaningful replacement player.

``require_full_band=True`` turns that degenerate case into an honest
``None`` ("not enough data yet") instead of a fabricated number.
``require_full_band=False`` (the default) preserves the original
single-worst-player fallback, still used by Playoff MVP
(``src/public_league/awards.py::_playoff_mvp_player_rows``), which was
deliberately left out of the strict gate's first application.  League /
Offensive / Defensive Player of the Year and both ROY request the strict
gate via ``awards._vorp_board``.
"""

from __future__ import annotations

from src.scoring.replacement_level import replacement_per_game


def _rows(*points_per_game: float, games: int = 1) -> list[dict]:
    return [{"starterPoints": p * games, "gamesStarted": games} for p in points_per_game]


class TestDefaultFallbackPreserved:
    def test_empty_band_falls_back_to_worst_player_by_default(self) -> None:
        # 3 players, cutoff at slot 2 -> band would be per_game[2:7], which
        # is just the one remaining (worst) player.
        rows = _rows(30.0, 20.0, 2.0)
        value = replacement_per_game(rows, starter_slots=2, band_size=5)
        assert value == 2.0

    def test_partial_band_still_averages_by_default(self) -> None:
        rows = _rows(30.0, 20.0, 10.0, 4.0, 2.0)
        # cutoff=2 -> band = per_game[2:7] = [10.0, 4.0, 2.0]
        value = replacement_per_game(rows, starter_slots=2, band_size=5)
        assert value == (10.0 + 4.0 + 2.0) / 3

    def test_full_band_matches_old_and_new_behavior(self) -> None:
        rows = _rows(30.0, 20.0, 10.0, 9.0, 8.0, 7.0, 6.0)
        # cutoff=2 -> band = per_game[2:7] = [10, 9, 8, 7, 6], a full band.
        lenient = replacement_per_game(rows, starter_slots=2, band_size=5)
        strict = replacement_per_game(rows, starter_slots=2, band_size=5, require_full_band=True)
        assert lenient == strict == (10 + 9 + 8 + 7 + 6) / 5


class TestRequireFullBandGate:
    def test_returns_none_when_population_is_below_cutoff(self) -> None:
        # This is the live shape: a handful of distinct LB starters this
        # early in the season, cutoff far above the population.
        rows = _rows(30.0, 20.0, 2.0)
        value = replacement_per_game(rows, starter_slots=36, band_size=5, require_full_band=True)
        assert value is None

    def test_returns_none_when_band_is_short_but_nonempty(self) -> None:
        rows = _rows(30.0, 20.0, 10.0, 4.0, 2.0)
        # cutoff=2 -> band would be [10.0, 4.0, 2.0], only 3 of 5 needed.
        value = replacement_per_game(rows, starter_slots=2, band_size=5, require_full_band=True)
        assert value is None

    def test_returns_a_real_value_once_the_band_is_full(self) -> None:
        rows = _rows(30.0, 20.0, 10.0, 9.0, 8.0, 7.0, 6.0)
        value = replacement_per_game(rows, starter_slots=2, band_size=5, require_full_band=True)
        assert value == (10 + 9 + 8 + 7 + 6) / 5

    def test_returns_none_rather_than_zero_for_no_rows(self) -> None:
        # Missing is never zero: an undefined baseline must not collapse
        # into the same shape as "confirmed zero replacement level."
        assert replacement_per_game([], starter_slots=5, require_full_band=True) is None
        assert replacement_per_game([], starter_slots=5, require_full_band=False) == 0.0

    def test_a_single_noisy_game_no_longer_manufactures_a_huge_surplus(self) -> None:
        """The exact live shape: a star scores well over a real game or
        two while the rest of the position pool is too thin to define
        replacement level. Reproduces why "VORP" on the Hub screen looked
        like it was just reporting the star's raw points scored."""
        star_points, star_games = 55.0, 2
        thin_pool = _rows(star_points / star_games, 1.0, 0.5)  # 3 distinct LB starters total

        # OLD/default behavior: replacement anchors on the single worst
        # performer (0.5 pts/game) -> VORP is nearly the star's full total.
        lenient_baseline = replacement_per_game(thin_pool, starter_slots=36, band_size=5)
        lenient_vorp = max(0.0, star_points - lenient_baseline * star_games)
        assert lenient_vorp > 50.0  # reproduces the misleading live number

        # NEW behavior: the position is flagged as undefined rather than
        # producing any VORP number at all.
        strict_baseline = replacement_per_game(
            thin_pool, starter_slots=36, band_size=5, require_full_band=True
        )
        assert strict_baseline is None
