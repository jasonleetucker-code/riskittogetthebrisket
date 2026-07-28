"""Unit tests for ``scripts/refresh_bdvm_projections.py``.

Pins the timer's operational contract: stage composition order,
exit-code aggregation (0 wrote / 1 soft / 2 hard), session staging
probe order, and the missing-session skip that keeps a proxy-only
refresh a warning rather than a failure.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "refresh_bdvm_projections.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("refresh_bdvm_projections", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()


class TestAutoSeason(unittest.TestCase):
    def test_prefers_contract_current_draft_year(self):
        # The repo's committed export carries currentDraftYear; whatever
        # it says is the answer (no date math involved).
        exports = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
        if not exports:
            self.skipTest("no contract export in tree")
        season = _mod._auto_season()
        self.assertIsInstance(season, int)
        self.assertGreater(season, 2000)

    def test_date_rule_fallback(self):
        with mock.patch.object(_mod, "REPO", Path("/nonexistent")):
            season = _mod._auto_season()
        self.assertIsInstance(season, int)


class _RunHarness(unittest.TestCase):
    """Drive main() with _run_stage mocked to scripted exit codes."""

    def _run(self, argv, stage_codes, session_exists=False):
        calls = []

        def fake_stage(name, cmd):
            calls.append((name, cmd))
            return stage_codes[name]

        fake_session = mock.MagicMock()
        fake_session.exists.return_value = session_exists
        real_repo = _mod.REPO

        class FakeRepo:
            def __truediv__(self, other):
                if other == _mod.SESSION_NAME:
                    return fake_session
                return real_repo / other

        with (
            mock.patch.object(_mod, "_run_stage", side_effect=fake_stage),
            mock.patch.object(_mod, "_stage_session_file", return_value=None),
            mock.patch.object(_mod, "REPO", FakeRepo()),
            mock.patch.object(sys, "argv", ["refresh_bdvm_projections.py", *argv]),
        ):
            rc = _mod.main()
        return rc, calls


class TestExitCodeAggregation(_RunHarness):
    def test_all_stages_write(self):
        rc, calls = self._run(
            ["--season", "2026"],
            {"baseline": 0, "clay": 0, "idpshow": 0},
            session_exists=True,
        )
        self.assertEqual(rc, 0)
        # order matters: proxies first so real records supersede them
        self.assertEqual([c[0] for c in calls], ["baseline", "clay", "idpshow"])

    def test_baseline_writes_real_sources_soft_fail_is_still_success(self):
        rc, _ = self._run(
            ["--season", "2026"],
            {"baseline": 0, "clay": 1, "idpshow": 1},
            session_exists=True,
        )
        self.assertEqual(rc, 0)

    def test_nothing_written_is_soft_failure(self):
        rc, _ = self._run(
            ["--season", "2026"],
            {"baseline": 1, "clay": 1, "idpshow": 1},
            session_exists=True,
        )
        self.assertEqual(rc, 1)

    def test_hard_error_with_nothing_written_is_2(self):
        rc, _ = self._run(
            ["--season", "2026"],
            {"baseline": 2, "clay": 1, "idpshow": 1},
            session_exists=True,
        )
        self.assertEqual(rc, 2)

    def test_hard_error_after_a_write_is_still_0(self):
        # A written baseline serves; the idpshow error shows in the
        # journal via the ERROR log line, not the exit code.
        rc, _ = self._run(
            ["--season", "2026"],
            {"baseline": 0, "clay": 0, "idpshow": 2},
            session_exists=True,
        )
        self.assertEqual(rc, 0)

    def test_clay_alone_writing_is_success(self):
        rc, _ = self._run(
            ["--season", "2026"],
            {"baseline": 1, "clay": 0, "idpshow": 1},
            session_exists=True,
        )
        self.assertEqual(rc, 0)

    def test_missing_session_skips_idpshow_stage(self):
        rc, calls = self._run(
            ["--season", "2026"],
            {"baseline": 0, "clay": 0},
            session_exists=False,
        )
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in calls], ["baseline", "clay"])

    def test_skip_flags(self):
        rc, calls = self._run(
            ["--season", "2026", "--skip-baseline", "--skip-clay", "--skip-idpshow"],
            {},
        )
        self.assertEqual(rc, 1)  # nothing written → soft
        self.assertEqual(calls, [])


class TestSessionStaging(unittest.TestCase):
    """Staging must be newest-wins (a stale repo jar can never shadow a
    fresh operator re-mint forever), atomic + 0600, and OSError-proof
    (session trouble never breaks the exit-code contract)."""

    def test_newer_candidate_replaces_stale_repo_copy(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            work = base / "work"
            repo.mkdir()
            work.mkdir()
            repo_jar = repo / _mod.SESSION_NAME
            repo_jar.write_text("stale")
            os.utime(repo_jar, (1000, 1000))
            candidate = work / _mod.SESSION_NAME
            candidate.write_text("fresh")
            os.utime(candidate, (2000, 2000))
            with mock.patch.object(_mod, "REPO", repo):
                staged_from = _mod._stage_session_file(str(candidate))
            self.assertEqual(staged_from, candidate)
            self.assertEqual(repo_jar.read_text(), "fresh")
            self.assertEqual(repo_jar.stat().st_mode & 0o777, 0o600)

    def test_fresher_repo_copy_is_kept(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            work = base / "work"
            repo.mkdir()
            work.mkdir()
            repo_jar = repo / _mod.SESSION_NAME
            repo_jar.write_text("current")
            os.utime(repo_jar, (2000, 2000))
            candidate = work / _mod.SESSION_NAME
            candidate.write_text("older")
            os.utime(candidate, (1000, 1000))
            with mock.patch.object(_mod, "REPO", repo):
                staged_from = _mod._stage_session_file(str(candidate))
            self.assertIsNone(staged_from)
            self.assertEqual(repo_jar.read_text(), "current")

    def test_oserror_on_candidate_is_tolerated(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo = base / "repo"
            repo.mkdir()
            candidate = base / _mod.SESSION_NAME
            candidate.write_text("x")
            with (
                mock.patch.object(_mod, "REPO", repo),
                mock.patch.object(
                    _mod, "_atomic_copy_0600", side_effect=OSError("permission denied")
                ),
            ):
                # must not raise — the stage is skipped, contract preserved
                self.assertIsNone(_mod._stage_session_file(str(candidate)))
            self.assertFalse((repo / _mod.SESSION_NAME).exists())

    def test_nothing_found_anywhere(self):
        with mock.patch.object(_mod, "REPO", Path("/nonexistent")):
            with mock.patch.object(_mod.Path, "is_file", return_value=False):
                self.assertIsNone(_mod._stage_session_file("/also/nonexistent"))


if __name__ == "__main__":
    unittest.main()
