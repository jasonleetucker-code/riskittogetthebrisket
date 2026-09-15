"""VORP's replacement-level baseline must be drawn from the position's
full rostered population (bench included), not just the players who
happened to start.

THE DEFECT, reproduced before it was repaired: ``_vorp_rows`` fed
``_replacement_per_game_for_position`` a population built entirely from
``_player_starter_totals`` — starters only. A league with N starter
slots at a position can never have MORE than N distinct started
players in a single week, so that population is always capped at (or
below) the exact cutoff being used to slice it. ``replacement_per_game``
then has no band "just below the cutoff" to average and silently falls
back to the single worst STARTER's per-game rate — sometimes a much
worse (or even negative) number than any real bench alternative — which
collapses VORP to (or above) a player's raw starter points instead of a
genuine value-over-replacement figure.

Measured live: a starter-only replacement pool made an elite player's
VORP identical to his raw starter points (replacement computed to
~0.0), and in a case with a negative-scoring worst starter, VORP
exceeded raw points outright — an award literally crediting a player
with more value than he scored.
"""

from __future__ import annotations

import unittest

from src.public_league.awards import _vorp_rows
from tests.public_league.fixtures import build_test_snapshot


def _dl_player(i: int) -> str:
    return f"dl-bench-probe-{i}"


def _build_snapshot_with_full_dl_pool(bench_count: int) -> tuple:
    """A snapshot whose 2025 week-1 has 36 STARTED DL players plus
    ``bench_count`` additional DL players who scored but were never
    started — the shape Sleeper's real ``players_points`` carries
    (see ``player_journey.py``: "Sleeper fills all three in
    production"), which the awards test fixtures don't otherwise model.
    """
    snapshot = build_test_snapshot()
    season = snapshot.seasons[0]

    # 36 started DL players, each at a modest, even per-game pace.
    starters = [_dl_player(i) for i in range(36)]
    players_points = {pid: 10.0 for pid in starters}
    # Bench DL players scored too (Sleeper stamps every rostered
    # player's points, not just starters) — a realistic, healthy bench
    # tier a manager could actually turn to, well below the starters.
    bench = [_dl_player(100 + i) for i in range(bench_count)]
    for pid in bench:
        players_points[pid] = 4.0

    season.matchups_by_week = {
        1: [
            {
                "roster_id": 1,
                "matchup_id": 1,
                # A real Sleeper matchup entry always carries its own
                # roster-week total on "points" — the scored-week gate
                # (src/public_league/metrics.py::scored_weeks) reads
                # THIS field, not players_points, to decide whether a
                # week actually happened.
                "points": sum(players_points.values()),
                "starters": starters,
                "players_points": players_points,
            }
        ]
    }

    snapshot.nfl_players = dict(snapshot.nfl_players)
    for pid in starters + bench:
        snapshot.nfl_players[pid] = {"position": "DL", "first_name": "Bench", "last_name": pid}

    return snapshot, season


class VorpReplacementPoolTests(unittest.TestCase):
    def test_bench_population_produces_a_real_replacement_band(self) -> None:
        """With bench DL data present, replacement should reflect the
        bench tier (4.0/game), not degenerate to the worst starter."""
        snapshot, season = _build_snapshot_with_full_dl_pool(bench_count=10)
        rows = _vorp_rows(snapshot, season, regular_season_only=True)
        dl_rows = [r for r in rows if r["position"] == "DL"]
        self.assertTrue(dl_rows)

        for r in dl_rows:
            self.assertAlmostEqual(r["replacementPerGame"], 4.0, places=2)
            # VORP must never exceed a player's own raw starter points —
            # crediting more value than was scored is the exact defect.
            self.assertLessEqual(r["vorp"], r["starterPoints"] + 1e-9)
            self.assertAlmostEqual(r["vorp"], 10.0 - 4.0, places=2)

    def test_without_bench_data_falls_back_safely(self) -> None:
        """Older/incomplete data with no bench points at all (the
        pre-fix fixture shape) must not crash — it degrades to the
        starter-only pool exactly as before, never negative, never
        above raw points."""
        snapshot, season = _build_snapshot_with_full_dl_pool(bench_count=0)
        rows = _vorp_rows(snapshot, season, regular_season_only=True)
        dl_rows = [r for r in rows if r["position"] == "DL"]
        self.assertTrue(dl_rows)
        for r in dl_rows:
            self.assertGreaterEqual(r["vorp"], 0.0)
            self.assertLessEqual(r["vorp"], r["starterPoints"] + 1e-9)

    def test_replacement_reflects_the_real_bench_average_not_a_lone_fallback(self) -> None:
        """A genuinely bad bench week is legitimate signal, and the fix
        must report the REAL bench average (-3.0 across a 6-player
        band) rather than the pre-fix degenerate fallback, which would
        have used the single worst STARTER's rate (10.0, since the
        starter-only pool never sees the bench at all) and silently
        clamped VORP to 0 instead of reflecting the true bench dip.

        This is not the same claim as "VORP can never exceed raw
        points": if the real, broad replacement population truly
        scored negative that week, VORP legitimately exceeding points
        is correct signal, not a bug. The bug was a REPLACEMENT NUMBER
        drawn from one degenerate artifact, not this direction of
        inequality.
        """
        snapshot, season = _build_snapshot_with_full_dl_pool(bench_count=6)
        # Make the bench tier score negative, like a bad backup week.
        bench_ids = {_dl_player(100 + i) for i in range(6)}
        for entry in season.matchups_by_week[1]:
            for pid in bench_ids:
                entry["players_points"][pid] = -3.0
        rows = _vorp_rows(snapshot, season, regular_season_only=True)
        dl_rows = [r for r in rows if r["position"] == "DL"]
        self.assertTrue(dl_rows)
        for r in dl_rows:
            self.assertAlmostEqual(r["replacementPerGame"], -3.0, places=2)
            self.assertAlmostEqual(r["vorp"], 10.0 - (-3.0), places=2)


if __name__ == "__main__":
    unittest.main()
