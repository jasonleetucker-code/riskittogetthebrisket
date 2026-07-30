"""Unit tests for the rank-form drift checker.

``scripts/check_rank_form_drift.py`` is the automation the 2026-07-30
re-tune added, and it has the same problem every alarm has: an alarm that
cannot fire is indistinguishable from a healthy system.  The old offense
pair sat at RMSE 821.7 against a floor of 89.8 for months with nothing
complaining, so "the checker reports ok" is not evidence of anything
until the checker is shown to also report drift.

These tests run on synthetic rows — no live payload, no network — so they
are a hard CI gate rather than ``livedata`` advisory.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.canonical.player_valuation import (  # noqa: E402
    HILL_MIDPOINT,
    HILL_SLOPE,
    IDP_HILL_MIDPOINT,
    IDP_HILL_SLOPE,
    rank_to_value,
)


def _load(name: str) -> object:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECK = _load("check_rank_form_drift")
BACKTEST = _load("backtest_legacy_rank_curve")


def _rows_on_curve(midpoint: float, slope: float, scope: str, n: int = 120) -> list[dict]:
    """Synthetic rows lying exactly on a given rank-form curve."""
    return [
        {
            "name": f"p{rank}",
            "rank": float(rank),
            "value": float(rank_to_value(rank, midpoint=midpoint, slope=slope)),
            "scope": scope,
        }
        for rank in range(1, n + 1)
    ]


class TestRmse(unittest.TestCase):
    def test_zero_on_the_generating_curve(self) -> None:
        rows = _rows_on_curve(65.4, 0.91, "offense")
        # Rounding to integers in ``rank_to_value`` leaves sub-1.0 noise.
        self.assertLess(CHECK._rmse(rows, 65.4, 0.91), 1.0)

    def test_large_when_the_curve_is_wrong(self) -> None:
        rows = _rows_on_curve(65.4, 0.91, "offense")
        self.assertGreater(CHECK._rmse(rows, 48.44, 1.149), 100.0)

    def test_matches_the_production_formula(self) -> None:
        """The checker reimplements the Hill arithmetic (it evaluates in
        bulk).  If that copy diverges from ``rank_to_value``, every number
        it reports is measured against the wrong curve."""
        for rank in (1, 2, 5, 25, 100, 400):
            row = [{"rank": float(rank), "value": float(rank_to_value(rank))}]
            # Committed constants -> the residual is pure rounding.
            self.assertLess(CHECK._rmse(row, HILL_MIDPOINT, HILL_SLOPE), 1.0, msg=f"rank {rank}")


class TestCommittedMapping(unittest.TestCase):
    def test_maps_to_the_real_constants(self) -> None:
        """A rename in ``player_valuation.py`` must not silently orphan a
        scope here — the checker would then report ``ok`` forever."""
        self.assertEqual(
            CHECK._COMMITTED["offense"][1],
            (HILL_MIDPOINT, HILL_SLOPE),
        )
        self.assertEqual(
            CHECK._COMMITTED["idp"][1],
            (IDP_HILL_MIDPOINT, IDP_HILL_SLOPE),
        )

    def test_names_match_the_values(self) -> None:
        import src.canonical.player_valuation as pv

        for _scope, (names, values) in CHECK._COMMITTED.items():
            for name, value in zip(names, values):
                self.assertEqual(getattr(pv, name), value, msg=name)

    def test_picks_are_not_gated(self) -> None:
        """``rank_to_value_for_scope`` routes picks to the offense curve on
        purpose, so a pick-only fit is diagnostic and must not raise an
        alarm of its own."""
        self.assertNotIn("pick", CHECK._COMMITTED)


class TestTheAlarmCanFire(unittest.TestCase):
    """The point of the file: drift is detected, and only real drift is."""

    def _excess(self, rows: list[dict], committed: tuple[float, float]) -> float:
        fit = BACKTEST._fit_rank_form_per_scope(rows)[rows[0]["scope"]]
        return CHECK._rmse(rows, *committed) - CHECK._rmse(rows, fit["midpoint"], fit["slope"])

    def test_committed_constants_score_near_zero_excess_on_their_own_curve(self) -> None:
        rows = _rows_on_curve(HILL_MIDPOINT, HILL_SLOPE, "offense")
        self.assertLess(self._excess(rows, (HILL_MIDPOINT, HILL_SLOPE)), CHECK.DEFAULT_THRESHOLD)

    def test_the_pre_retune_offense_pair_would_have_fired(self) -> None:
        """The regression this automation exists to catch. On the real
        board the old pair scored +731.9 excess RMSE; on a synthetic board
        generated from the current curve it must also blow the budget."""
        rows = _rows_on_curve(HILL_MIDPOINT, HILL_SLOPE, "offense")
        self.assertGreater(self._excess(rows, (48.44, 1.149)), CHECK.DEFAULT_THRESHOLD)

    def test_a_percentile_master_promotion_sized_move_fires(self) -> None:
        """The real drift SOURCE, measured: the 2026-07-29 board refit to
        68.8/0.929 and the post-promotion board to 65.2/0.905. A shift of
        that size must not slip under the threshold, or the alarm is
        decorative."""
        rows = _rows_on_curve(65.2, 0.905, "offense")
        self.assertGreater(self._excess(rows, (68.8, 0.929)), CHECK.DEFAULT_THRESHOLD)

    def test_the_idp_pair_is_checked_independently(self) -> None:
        rows = _rows_on_curve(IDP_HILL_MIDPOINT, IDP_HILL_SLOPE, "idp")
        self.assertLess(
            self._excess(rows, (IDP_HILL_MIDPOINT, IDP_HILL_SLOPE)), CHECK.DEFAULT_THRESHOLD
        )
        self.assertGreater(self._excess(rows, (48.44, 1.149)), CHECK.DEFAULT_THRESHOLD)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
