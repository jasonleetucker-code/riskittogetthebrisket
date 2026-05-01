"""Targeted tests for ``scripts/generate_weekly_narratives.py`` helpers.

The full CLI is covered by an end-to-end run; these tests exercise the
pure helper(s) where regressions are easy to ship — most importantly,
the season-targeting logic, which the cron uses for live runs and a
human uses for backfills.  Both paths must agree on which season's
files get written.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from tests.public_league.fixtures import build_test_snapshot


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "generate_weekly_narratives.py"


def _load_script_module():
    """Import scripts/generate_weekly_narratives.py as a module.

    The script lives outside any package so a normal import doesn't
    work — we load it via importlib and stash it under a stable name
    in ``sys.modules`` so repeated test calls hit the same module.
    """
    name = "scripts._generate_weekly_narratives_for_tests"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPT_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load script at {_SCRIPT_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class ResolveTargetWeekTests(unittest.TestCase):
    """``_resolve_target_week`` is the script's most logic-heavy helper."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _load_script_module()
        cls.snapshot = build_test_snapshot()

    def test_no_season_no_week_picks_current_recap_week(self) -> None:
        # Fixture's 2025 is fully scored through wk-16.
        season, week = self.script._resolve_target_week(  # noqa: SLF001
            self.snapshot, mode="recap", explicit_week=None, explicit_season=None,
        )
        self.assertEqual(season, "2025")
        self.assertEqual(week, 16)

    def test_explicit_season_routes_to_that_season(self) -> None:
        # Fixture has 2024 + 2025; backfill should target 2024.
        season, week = self.script._resolve_target_week(  # noqa: SLF001
            self.snapshot, mode="recap", explicit_week=None, explicit_season="2024",
        )
        self.assertEqual(season, "2024")
        # 2024 fixture is scored through wk-3.
        self.assertEqual(week, 3)

    def test_explicit_season_and_week_overrides_detector(self) -> None:
        season, week = self.script._resolve_target_week(  # noqa: SLF001
            self.snapshot, mode="preview", explicit_week=14, explicit_season="2024",
        )
        self.assertEqual(season, "2024")
        self.assertEqual(week, 14)

    def test_unknown_season_raises_with_helpful_message(self) -> None:
        with self.assertRaises(RuntimeError) as ctx:
            self.script._resolve_target_week(  # noqa: SLF001
                self.snapshot, mode="recap",
                explicit_week=None, explicit_season="1999",
            )
        self.assertIn("1999", str(ctx.exception))
        self.assertIn("2025", str(ctx.exception))  # available seasons listed

    def test_explicit_week_only_uses_current_season(self) -> None:
        # No --season but explicit --week → current (2025) season.
        season, week = self.script._resolve_target_week(  # noqa: SLF001
            self.snapshot, mode="preview", explicit_week=10, explicit_season=None,
        )
        self.assertEqual(season, "2025")
        self.assertEqual(week, 10)


if __name__ == "__main__":
    unittest.main()
