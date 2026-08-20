"""The join and the targets in the adjusted-board backtest.

The comparison engine itself is pinned in
``tests/model_registry/test_board_holdout.py``.  What is pinned here is
the part that decides *what gets compared* — and the three ways this
script could quietly produce a wrong verdict without ever failing:

* dropping the banded reception component, which would score the
  adjustment against a target missing the very thing one of its two live
  axes corrects for;
* double-counting the flat ``rec`` rate on top of it;
* deriving the replacement baseline from the module under test.

The first two used to be pinned against this script's own
``_banded_reception_points``, which bolted band points onto season totals
from the depth histogram. That helper is **deleted**: it made this script
a third owner of what a band is worth, and it carried none of the player
special-teams rules or the pick-six penalty at all. The realized target
now comes from the canonical play-by-play supplement
(``src/nfl_data/pbp_weekly.py``), so the same two failure modes are
pinned against that path instead — the double count is structural there,
because the supplement is an allow-list that cannot write ``rec``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "backtest_adjusted_board", _REPO_ROOT / "scripts" / "backtest_adjusted_board.py"
)
backtest = importlib.util.module_from_spec(_SPEC)
sys.modules["backtest_adjusted_board"] = backtest
_SPEC.loader.exec_module(backtest)


_SCORING = {
    "rec": 0.08,
    "rec_0_4": 0.17,
    "rec_5_9": 0.42,
    "rec_10_19": 0.67,
    "rec_20_29": 0.92,
    "rec_30_39": 1.17,
    "rec_40p": 1.92,
}


# ── banded receptions ───────────────────────────────────────────────────


def _weekly_rows(gsis, receptions, week=1):
    return [
        {
            "player_id": gsis,
            "player_display_name": gsis,
            "position": "WR",
            "season": 2025,
            "week": week,
            "season_type": "REG",
            "receptions": receptions,
            "receiving_yards": 10 * receptions,
        }
    ]


def _patched_realized(monkeypatch, rows, stats):
    """Run ``_realized_points`` against fixed rows and a fixed artifact."""
    from src.nfl_data import ingest, pbp_weekly

    monkeypatch.setattr(ingest, "fetch_weekly_stats", lambda years: rows)
    monkeypatch.setattr(pbp_weekly.SeasonPbpIndex, "for_season", lambda self, season: stats)
    return backtest._realized_points(2025, _SCORING)


def test_the_realized_target_pays_the_band_rate_and_not_a_second_flat_rate(monkeypatch):
    """THE DOUBLE-COUNT GUARD.

    The weekly engine already paid ``rec`` for every catch.  Paying
    ``rec + band`` would pay it twice, inflating every receiver by his
    reception count times 0.08 — a shift large enough to move the verdict
    and invisible in the output.

    Structural now rather than by arithmetic care: the supplement is an
    allow-list of the ten play-by-play-only keys, so it cannot write
    ``rec`` even when handed one.
    """
    from src.nfl_data.pbp_weekly import PbpWeeklyStats

    stats = PbpWeeklyStats(2025, {"g1": {1: {"rec_0_4": 10, "rec_40p": 5, "rec": 999}}}, [1])
    realized, _rows, players = _patched_realized(monkeypatch, _weekly_rows("g1", 15), stats)

    assert realized["g1"]["points"] == pytest.approx(15 * 0.08 + 10 * 0.17 + 5 * 1.92)
    assert players == 1


def test_a_missing_artifact_yields_no_bonus_rather_than_an_error(monkeypatch):
    realized, _rows, players = _patched_realized(monkeypatch, _weekly_rows("g1", 15), None)
    assert realized["g1"]["points"] == pytest.approx(15 * 0.08)
    assert players == 0, "a zero here is what makes a missing artifact visible in the run log"


def test_bands_the_league_does_not_pay_for_contribute_nothing(monkeypatch):
    from src.nfl_data.pbp_weekly import PbpWeeklyStats

    stats = PbpWeeklyStats(2025, {"g1": {1: {"rec_0_4": 10}}}, [1])
    from src.nfl_data import ingest, pbp_weekly

    monkeypatch.setattr(ingest, "fetch_weekly_stats", lambda years: _weekly_rows("g1", 10))
    monkeypatch.setattr(pbp_weekly.SeasonPbpIndex, "for_season", lambda self, season: stats)
    realized, _rows, _players = backtest._realized_points(2025, {"rec": 1.0})
    assert realized["g1"]["points"] == pytest.approx(10 * 1.0)


def test_a_deep_receiver_earns_more_than_a_short_one_at_equal_volume(monkeypatch):
    """The whole point of the banded component, as a sanity check that
    the rates are being read per band and not pooled."""
    from src.nfl_data.pbp_weekly import PbpWeeklyStats

    stats = PbpWeeklyStats(2025, {"deep": {1: {"rec_40p": 40}}, "short": {1: {"rec_0_4": 40}}}, [1])
    rows = _weekly_rows("deep", 40) + _weekly_rows("short", 40)
    realized, _rows, _players = _patched_realized(monkeypatch, rows, stats)
    assert realized["deep"]["points"] > realized["short"]["points"]


# ── replacement baselines ───────────────────────────────────────────────


def _pop(position, points, teams=2):
    return [
        {"position": position, "actual": p, "market": 1.0, "adjusted": 1.0, "games": 1}
        for p in points
    ]


_ROSTER = {"teamCount": 2, "starters": {"RB": 2, "QB": 1, "TE": 0}}


def test_the_baseline_is_the_last_startable_player_at_the_position():
    pop = _pop("RB", [100, 90, 80, 70, 60, 50])
    # 2 starters x 2 teams = 4 startable RBs; the 4th best is the baseline
    assert backtest.replacement_baselines(pop, _ROSTER)["RB"] == 70

    pop = _pop("QB", [300, 200, 100])
    assert backtest.replacement_baselines(pop, _ROSTER)["QB"] == 200


def test_positions_with_no_dedicated_slots_get_no_baseline():
    """Better to leave the position out of the over-replacement view than
    to invent a baseline for it."""
    pop = _pop("TE", [100, 50]) + _pop("K", [10, 5])
    assert backtest.replacement_baselines(pop, _ROSTER) == {}


def test_a_shallow_pool_falls_back_to_its_worst_player():
    """Fewer priced players than startable slots must not index past the
    end of the list."""
    pop = _pop("RB", [100, 90])
    assert backtest.replacement_baselines(pop, _ROSTER)["RB"] == 90


def test_the_baseline_never_consults_the_module_under_test():
    """Deriving the target from ``src.league_intel.replacement`` would
    let the adjustment grade its own paper.  ``replacement_baselines``
    takes only realized points and roster settings, so this is a
    property of its body — asserted here so a future refactor that
    reaches for the solver has to delete this test to do it.

    Scanned on the CODE, with the docstring stripped: that docstring
    names ``src.league_intel.replacement`` precisely to explain why it
    is not used, and a naive substring scan would fail on the
    explanation while passing on a real import.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(backtest.replacement_baselines))
    fn = tree.body[0]
    if (
        fn.body
        and isinstance(fn.body[0], ast.Expr)
        and isinstance(fn.body[0].value, ast.Constant)
        and isinstance(fn.body[0].value.value, str)
    ):
        fn.body = fn.body[1:]
    code = ast.unparse(fn)

    # The strip actually happened — otherwise this scan is vacuous and
    # would pass on any body at all.
    assert "grade its own paper" not in code
    for forbidden in ("league_intel", "compute_scarcity", "compute_replacement_levels"):
        assert forbidden not in code, f"the target is being derived from {forbidden}"


# ── the join ────────────────────────────────────────────────────────────


def _board_row(name, position, value, rank=1):
    return {
        "displayName": name,
        "position": position,
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
    }


def _realized(name, position, points, games=17):
    return {"name": name, "position": position, "points": points, "games": games}


def test_picks_and_unpriced_rows_leave_the_population_and_are_counted():
    """Silent drops are how a join breaks without anyone noticing."""
    rows = [
        _board_row("Real Guy", "WR", 5000),
        _board_row("2026 Early 1st", "PICK", 4000),
        _board_row("Unpriced Guy", "WR", None),
        _board_row("Missing From Nflverse", "WR", 3000),
    ]
    realized = {"g1": _realized("Real Guy", "WR", 200.0)}
    population, stats = backtest._build_population(rows, {}, realized)

    assert [p["name"] for p in population] == ["Real Guy"]
    assert stats == {"boardRows": 4, "picks": 1, "unpriced": 1, "unjoined": 1}


def test_a_player_the_adjustment_does_not_move_keeps_his_market_value():
    """Absence from ``factors`` means unchanged, not zero — the overlay
    is sparse by design (``src.league_intel.publish``)."""
    rows = [_board_row("Untouched", "WR", 5000)]
    population, _ = backtest._build_population(rows, {}, {"g": _realized("Untouched", "WR", 100.0)})
    assert population[0]["adjusted"] == population[0]["market"] == 5000.0


def test_the_factor_is_applied_multiplicatively_to_the_market_value():
    rows = [_board_row("Tilted", "WR", 5000)]
    population, _ = backtest._build_population(
        rows, {"Tilted": 1.1}, {"g": _realized("Tilted", "WR", 100.0)}
    )
    assert population[0]["adjusted"] == pytest.approx(5500.0)


def test_zero_games_does_not_divide_by_zero():
    rows = [_board_row("Injured", "WR", 5000)]
    population, _ = backtest._build_population(
        rows, {}, {"g": _realized("Injured", "WR", 0.0, games=0)}
    )
    assert population[0]["actualPerGame"] is None


# ── factor shape ────────────────────────────────────────────────────────


def test_scalar_only_positions_are_identified_as_such():
    """The table that explains a per-position delta of exactly zero.

    Without it a reader sees ``delta=+0.0000`` for DL and concludes the
    harness is blind, when in fact every DL shares one factor and a
    constant multiplier cannot reorder a position against itself.
    """
    rows = [
        _board_row("A", "DL", 100),
        _board_row("B", "DL", 90),
        _board_row("C", "WR", 100),
        _board_row("D", "WR", 90),
    ]
    shape = backtest.factor_shape(rows, {"A": 1.08, "B": 1.08, "C": 1.02, "D": 0.94})
    assert shape["DL"]["distinct"] == 1
    assert shape["WR"]["distinct"] == 2
    assert shape["WR"]["min"] == 0.94 and shape["WR"]["max"] == 1.02
