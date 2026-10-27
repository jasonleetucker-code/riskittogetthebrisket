"""Unit tests for ``scripts/refresh_bdvm_projections.py``.

Pins the timer's operational contract: stage composition order,
exit-code aggregation (0 wrote / 1 soft / 2 hard), session staging
probe order, and the missing-session skip that keeps a proxy-only
refresh a warning rather than a failure.

Also pins the HONESTY contract (box audit 2026-10-26): a stage that did
not land is named in the final summary line and in the machine-readable
run status, even though partial success keeps exit 0 by convention, and
an owner-gated (shadowed) IDP Show stage is never reported as a real
source in the snapshot.
"""

from __future__ import annotations

import importlib.util
import json
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

    def setUp(self):
        # Hermetic: the run status goes to a temp file, never the real
        # data/bdvm/, and the owner switch starts OFF whatever the shell has.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.status_path = Path(tmp.name) / "refresh_status.json"
        self.log_lines = []

    def read_status(self):
        return json.loads(self.status_path.read_text(encoding="utf-8"))

    @property
    def final_line(self):
        return next(line for line in reversed(self.log_lines) if line.startswith("done"))

    def _run(self, argv, stage_codes, session_exists=False, env=None):
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

        run_env = {_mod.STATUS_PATH_ENV: str(self.status_path), **(env or {})}
        with (
            mock.patch.dict(os.environ, run_env),
            mock.patch.object(_mod, "_run_stage", side_effect=fake_stage),
            mock.patch.object(_mod, "_stage_session_file", return_value=None),
            mock.patch.object(_mod, "REPO", FakeRepo()),
            mock.patch.object(_mod, "log", side_effect=self.log_lines.append),
            mock.patch.object(sys, "argv", ["refresh_bdvm_projections.py", *argv]),
        ):
            if _mod.MERGE_ENV_VAR not in (env or {}):
                os.environ.pop(_mod.MERGE_ENV_VAR, None)
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


class TestHonestReporting(_RunHarness):
    """The exit code cannot say "a real source failed" (partial success is 0 by
    convention), so the final line and the status file must."""

    def test_idpshow_soft_failure_is_named_not_hidden(self):
        # The 2026-10-20 box run: clay landed, IDP Show exit 1, unit "success".
        rc, _ = self._run(
            ["--season", "2026"], {"baseline": 0, "clay": 0, "idpshow": 1}, session_exists=True
        )
        self.assertEqual(rc, 0)  # convention kept: partial success is 0
        line = self.final_line
        self.assertNotIn("at least one REAL source", line)
        self.assertIn("DEGRADED", line)
        self.assertIn("idpshow (exit 1: no usable data)", line)
        self.assertIn("real sources in the snapshot: clay", line)
        status = self.read_status()
        self.assertEqual(status["result"], "degraded")
        self.assertEqual(status["exitCode"], 0)
        self.assertEqual(status["failedStages"], ["idpshow"])
        self.assertEqual(status["realSourcesInSnapshot"], ["clay"])
        self.assertTrue(status["snapshotWritten"])
        self.assertEqual(status["stages"]["idpshow"]["status"], "failed")
        self.assertEqual(status["stages"]["idpshow"]["exitCode"], 1)
        self.assertEqual(status["stages"]["clay"]["status"], "ok")
        self.assertEqual(status["summary"], line)

    def test_hard_error_after_a_write_is_named_too(self):
        rc, _ = self._run(
            ["--season", "2026"], {"baseline": 0, "clay": 2, "idpshow": 0}, session_exists=True
        )
        self.assertEqual(rc, 0)
        self.assertIn("clay (exit 2: hard error)", self.final_line)
        self.assertEqual(self.read_status()["failedStages"], ["clay"])

    def test_missing_session_is_named_as_a_stage_that_did_not_land(self):
        rc, calls = self._run(
            ["--season", "2026"], {"baseline": 0, "clay": 0}, session_exists=False
        )
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in calls], ["baseline", "clay"])
        self.assertIn("idpshow (no session cookies)", self.final_line)
        status = self.read_status()
        self.assertEqual(status["stages"]["idpshow"]["status"], "unavailable")
        self.assertEqual(status["result"], "degraded")

    def test_nothing_written_names_every_failed_stage(self):
        rc, _ = self._run(
            ["--season", "2026"], {"baseline": 1, "clay": 1, "idpshow": 1}, session_exists=True
        )
        self.assertEqual(rc, 1)
        status = self.read_status()
        self.assertEqual(status["result"], "failed")
        self.assertEqual(status["failedStages"], ["baseline", "clay", "idpshow"])
        self.assertFalse(status["snapshotWritten"])
        self.assertIn("FAILED stages", self.final_line)
        # Each stage's exit 1 is worded for what THAT stage means by it - one
        # shared "no usable data" blamed a source table for the baseline.
        line = self.final_line
        self.assertIn("baseline (exit 1: built nothing)", line)
        self.assertIn("clay (exit 1: guide unavailable)", line)
        self.assertIn("idpshow (exit 1: no usable data)", line)

    def test_a_baseline_soft_failure_is_not_blamed_on_a_source_table(self):
        # Clay landed, so the run is DEGRADED rather than failed; the baseline's
        # exit 1 must read as the baseline's own, not as "no usable data".
        rc, _ = self._run(
            ["--season", "2026", "--skip-idpshow"], {"baseline": 1, "clay": 0}, session_exists=True
        )
        self.assertEqual(rc, 0)
        line = self.final_line
        self.assertIn("baseline (exit 1: built nothing)", line)
        self.assertNotIn("no usable data", line)
        self.assertEqual(self.read_status()["failedStages"], ["baseline"])

    def test_every_soft_failure_wording_is_stage_specific_and_has_a_fallback(self):
        failed = {"status": _mod.FAILED, "exitCode": 1}
        self.assertEqual(_mod._describe("baseline", failed), "exit 1: built nothing")
        self.assertEqual(_mod._describe("clay", failed), "exit 1: guide unavailable")
        self.assertEqual(_mod._describe("idpshow", failed), "exit 1: no usable data")
        # A stage added later without wording degrades to a generic, true phrase.
        self.assertEqual(_mod._describe("newstage", failed), "exit 1: soft failure")
        # The other statuses do not depend on the stage.
        self.assertEqual(
            _mod._describe("clay", {"status": _mod.ERROR, "exitCode": 2}), "exit 2: hard error"
        )
        self.assertEqual(
            _mod._describe(
                "idpshow",
                {"status": _mod.UNAVAILABLE, "exitCode": None, "detail": "no session cookies"},
            ),
            "no session cookies",
        )

    def test_hard_error_with_nothing_written_is_exit_2_in_status(self):
        rc, _ = self._run(
            ["--season", "2026"], {"baseline": 2, "clay": 1, "idpshow": 1}, session_exists=True
        )
        self.assertEqual(rc, 2)
        status = self.read_status()
        self.assertEqual(status["exitCode"], 2)
        self.assertIn("hard error and nothing written", status["summary"])

    def test_all_landed_is_ok_and_lists_both_real_sources(self):
        rc, calls = self._run(
            ["--season", "2026"],
            {"baseline": 0, "clay": 0, "idpshow": 0},
            session_exists=True,
            env={_mod.MERGE_ENV_VAR: "1"},
        )
        self.assertEqual(rc, 0)
        status = self.read_status()
        self.assertEqual(status["result"], "ok")
        self.assertEqual(status["failedStages"], [])
        self.assertEqual(status["realSourcesInSnapshot"], ["clay", "idpshow"])
        self.assertIn("real sources in the snapshot: clay, idpshow", self.final_line)
        self.assertIn("--merge-into-snapshot", dict(calls)["idpshow"])

    def test_proxy_only_is_labelled_and_still_exit_0(self):
        rc, _ = self._run(["--season", "2026", "--skip-clay", "--skip-idpshow"], {"baseline": 0})
        self.assertEqual(rc, 0)
        status = self.read_status()
        self.assertEqual(status["result"], "proxy_only")
        self.assertEqual(status["realSourcesInSnapshot"], [])
        self.assertIn("PROXY-ONLY", self.final_line)
        self.assertIn("skipped by flag: clay, idpshow", self.final_line)

    def test_status_write_failure_never_changes_the_exit_code(self):
        blocker = self.status_path.parent / "a-file"
        blocker.write_text("x")
        with mock.patch.dict(
            os.environ, {_mod.STATUS_PATH_ENV: str(blocker / "nested" / "status.json")}
        ):
            self.assertIsNone(_mod._write_status({"k": "v"}))  # warns, never raises
        rc, _ = self._run(
            ["--season", "2026"], {"baseline": 0, "clay": 1, "idpshow": 1}, session_exists=True
        )
        self.assertEqual(rc, 0)


class TestOwnerGatedIdpShowIsShadowed(_RunHarness):
    """With the owner switch OFF (the default) a clean IDP Show run parsed to a
    shadow file only: it must not be reported as a real source in the snapshot,
    must not be asked to merge, and must not make a no-write run look written."""

    def test_default_off_reports_shadow_not_real_source(self):
        rc, calls = self._run(
            ["--season", "2026"],
            {"baseline": 0, "clay": 0, "idpshow": 0},
            session_exists=True,
        )
        self.assertEqual(rc, 0)
        self.assertNotIn("--merge-into-snapshot", dict(calls)["idpshow"])
        status = self.read_status()
        self.assertEqual(status["realSourcesInSnapshot"], ["clay"])
        self.assertEqual(status["shadowStages"], ["idpshow"])
        self.assertEqual(status["failedStages"], [])
        self.assertEqual(status["stages"]["idpshow"]["status"], "shadow")
        self.assertFalse(status["idpshowMergeSwitch"]["enabled"])
        self.assertIn("SHADOWED", self.final_line)
        self.assertIn("real sources in the snapshot: clay", self.final_line)

    def test_shadow_alone_does_not_count_as_a_snapshot_write(self):
        rc, _ = self._run(
            ["--season", "2026", "--skip-baseline", "--skip-clay"],
            {"idpshow": 0},
            session_exists=True,
        )
        self.assertEqual(rc, 1)  # nothing was written to any snapshot
        status = self.read_status()
        self.assertFalse(status["snapshotWritten"])
        self.assertEqual(status["shadowStages"], ["idpshow"])

    def test_merge_flag_turns_it_on_and_is_passed_through(self):
        rc, calls = self._run(
            ["--season", "2026", "--merge-idpshow"],
            {"baseline": 0, "clay": 1, "idpshow": 0},
            session_exists=True,
        )
        self.assertEqual(rc, 0)
        self.assertIn("--merge-into-snapshot", dict(calls)["idpshow"])
        status = self.read_status()
        self.assertEqual(status["realSourcesInSnapshot"], ["idpshow"])
        self.assertTrue(status["idpshowMergeSwitch"]["enabled"])

    def test_unrecognised_env_value_stays_off(self):
        for value in ("", "0", "false", "maybe", "2"):
            with self.subTest(value=value):
                rc, calls = self._run(
                    ["--season", "2026"],
                    {"baseline": 0, "clay": 0, "idpshow": 0},
                    session_exists=True,
                    env={_mod.MERGE_ENV_VAR: value},
                )
                self.assertEqual(rc, 0)
                self.assertNotIn("--merge-into-snapshot", dict(calls)["idpshow"])


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
            if os.name == "posix":
                # POSIX permission bits only; Windows reports 0o666 for any
                # writable file whatever was requested.
                self.assertEqual(repo_jar.stat().st_mode & 0o777, 0o600)

    def test_atomic_copy_without_fchmod_still_copies_private(self):
        """Platforms without ``os.fchmod`` (Windows) fall back to ``os.chmod``."""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "src.json"
            dst = Path(td) / "dst.json"
            src.write_text("jar")
            real_chmod = os.chmod
            calls = []

            def _chmod(path, mode, *a, **k):
                calls.append(mode)
                return real_chmod(path, mode, *a, **k)

            saved_fchmod = getattr(os, "fchmod", None)
            if saved_fchmod is not None:
                del os.fchmod
            try:
                with mock.patch.object(_mod.os, "chmod", side_effect=_chmod):
                    _mod._atomic_copy_0600(src, dst)
            finally:
                if saved_fchmod is not None:
                    os.fchmod = saved_fchmod
            self.assertEqual(calls, [0o600])
            self.assertEqual(dst.read_text(), "jar")
            if os.name == "posix":
                self.assertEqual(dst.stat().st_mode & 0o777, 0o600)

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
