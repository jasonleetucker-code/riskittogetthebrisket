"""The weekly re-validation job must not report a crash as verdict drift.

``consensus-edge-revalidate.yml`` has three kinds of outcome:

* the re-run produced verdicts and they match the committed ones,
* the re-run produced verdicts and they DIFFER (``VERDICT DRIFT``),
* the re-run never produced verdicts (a crash, a failed install, a failed
  self-test).

The job summary used to collapse the last two into one message, "The
committed measurement no longer describes the code".  From 2026-08-05 to
2026-10-07 the weekly run crashed ten times in a row inside
``validate_consensus_edge_board.py`` (``Path.relative_to`` on the
``/tmp/ce-rerun`` output path), the compare step was SKIPPED, and every one of
those summaries still told the reader the committed measurement was stale --
when in fact no verdict had been compared and the study's own verdict, in every
one of the ten logs, was the committed one ("do not ship yet").

This file pins the split.  It reads the workflow, so it changes nothing about
the study, its gate or its thresholds.

A fourth outcome came out of the review of that fix: the compare step exits 1
on a changed verdict AND on any uncaught Python error (malformed JSON, a
``KeyError``), so "compare failed" alone still could not tell drift from a
crashed comparison.  The compare step now prints one marker line,
``CE_REVALIDATE_RESULT=verdict_drift``, last, right before its ``exit 1`` on
drift; the summary claims drift only when that whole line is in
``compare.txt``, and reports a compare failure without it as "the comparison
crashed".
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "consensus-edge-revalidate.yml"
SUMMARY_STEP = "Job summary"
COMPARE_STEP = "Compare the fresh verdict against the committed one"

DRIFT_TEXT = "The committed measurement no longer describes the code."
HARNESS_TEXT = "The re-run or the comparison did not complete, so no verdict was compared."
CRASH_TEXT = "The comparison crashed, so no verdict was compared."
OK_TEXT = "Committed verdicts still describe the code."
#: The compare step's "every verdict was compared and one changed" line.
DRIFT_MARKER = "CE_REVALIDATE_RESULT=verdict_drift"
#: Where the compare step reads the fresh measurements (substituted in tests).
RERUN_DIR = "/tmp/ce-rerun"


def _steps() -> list[dict]:
    blob = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return blob["jobs"]["revalidate"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {WORKFLOW.name}")


def _guard_of(script: str, text: str) -> str | None:
    """The ``if`` / ``elif`` / ``else`` header of the branch that prints ``text``."""
    header = None
    for raw in script.splitlines():
        line = raw.strip()
        if line.startswith(("if ", "elif ")) or line == "else":
            header = line
        if text in line:
            return header
    return None


def _compare_script() -> str:
    """The Python the compare step pipes through ``tee``, exactly as committed."""
    lines = _step(COMPARE_STEP)["run"].splitlines()
    start = next(
        i
        for i, line in enumerate(lines)
        if line.rstrip().endswith("<<'PY' | tee /tmp/ce-rerun/compare.txt")
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PY")
    return "\n".join(lines[start + 1 : end]) + "\n"


class TestSummaryIsWiredToTheRightSteps(unittest.TestCase):
    def test_the_rerun_and_compare_steps_keep_their_ids(self):
        self.assertEqual(_step("Re-run the board validation").get("id"), "rerun")
        self.assertEqual(
            _step("Compare the fresh verdict against the committed one").get("id"), "compare"
        )

    def test_the_summary_reads_both_outcomes(self):
        env = _step(SUMMARY_STEP).get("env") or {}
        self.assertEqual(env.get("RERUN_OUTCOME"), "${{ steps.rerun.outcome }}")
        self.assertEqual(env.get("COMPARE_OUTCOME"), "${{ steps.compare.outcome }}")

    def test_the_summary_runs_even_when_an_earlier_step_failed(self):
        self.assertEqual(_step(SUMMARY_STEP).get("if"), "always()")

    def test_the_summary_script_does_not_splice_expressions(self):
        # Outcomes are environment variables; an expression in the script text
        # would make the behaviour below untestable and is the shape that let
        # the two-state version go unexamined.
        self.assertNotIn("${{", _step(SUMMARY_STEP)["run"])

    def test_the_drift_message_is_guarded_on_a_compare_failure(self):
        # Static, so Windows CI covers it too (the behaviour tests below are
        # POSIX-only).  The drift message used to sit in a bare ``else``, so
        # (re-run success, compare skipped/cancelled/empty) printed it even
        # though no verdict had been compared.  The branch that prints it must
        # be an ``if``/``elif`` whose condition tests COMPARE_OUTCOME against
        # ``failure`` -- never an ``else``.
        script = _step(SUMMARY_STEP)["run"]
        self.assertEqual(script.count(DRIFT_TEXT.rstrip(".")), 1)
        guard = _guard_of(script, DRIFT_TEXT.rstrip("."))
        self.assertIsNotNone(guard, "drift message not found in the summary script")
        self.assertTrue(guard.startswith(("if ", "elif ")), f"drift message is in {guard!r}")
        self.assertIn("COMPARE_OUTCOME", guard)
        self.assertRegex(guard, r'COMPARE_OUTCOME\}"\s*==\s*"failure"')
        self.assertNotIn("!=", guard)

    def test_the_drift_message_requires_a_successful_rerun(self):
        # The RERUN_OUTCOME half of the guard.  Without it, a re-run that
        # failed after writing a partial measurement could still be called
        # drift by a compare step that ran on it.
        guard = _guard_of(_step(SUMMARY_STEP)["run"], DRIFT_TEXT.rstrip("."))
        self.assertIsNotNone(guard)
        self.assertRegex(guard, r'RERUN_OUTCOME\}"\s*==\s*"success"')

    def test_the_drift_message_requires_the_drift_marker(self):
        # The compare step exits 1 on drift AND on any uncaught error, so the
        # exit status alone is not evidence of drift: the guard must also find
        # the marker, as a whole line (``-x``), as a fixed string (``-F``), in
        # the compare step's own output.
        guard = _guard_of(_step(SUMMARY_STEP)["run"], DRIFT_TEXT.rstrip("."))
        self.assertIsNotNone(guard)
        self.assertIn(f'grep -qxF "{DRIFT_MARKER}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        # ... joined with ``&&`` to the outcome test, not offered as an alternative.
        self.assertNotIn("||", guard)
        self.assertRegex(guard, r"\]\]\s*&&\s*grep ")

    def test_a_compare_failure_without_the_marker_is_reported_as_a_crash(self):
        script = _step(SUMMARY_STEP)["run"]
        self.assertEqual(script.count(CRASH_TEXT.rstrip(".")), 1)
        guard = _guard_of(script, CRASH_TEXT.rstrip("."))
        self.assertIsNotNone(guard, "crash message not found in the summary script")
        self.assertTrue(guard.startswith("elif "), f"crash message is in {guard!r}")
        self.assertRegex(guard, r'COMPARE_OUTCOME\}"\s*==\s*"failure"')
        self.assertRegex(guard, r'RERUN_OUTCOME\}"\s*==\s*"success"')
        # It is the branch AFTER the marker-guarded drift branch: the drift
        # branch is tried first, so only a marker-less failure reaches it.
        self.assertLess(script.index(DRIFT_TEXT.rstrip(".")), script.index(CRASH_TEXT.rstrip(".")))
        self.assertNotIn(DRIFT_MARKER, guard)

    def test_the_compare_step_prints_the_marker_last_on_drift(self):
        # Printed once, as the step's final act before ``sys.exit(1)``: a crash
        # anywhere earlier -- including while printing the drift list -- leaves
        # it out, so its presence means every verdict was compared.
        script = _compare_script()
        self.assertEqual(script.count(DRIFT_MARKER), 1)
        self.assertEqual(script.count("sys.exit(1)"), 1)
        code = [
            line.strip()
            for line in script.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        at = code.index(f'print("{DRIFT_MARKER}")')
        self.assertEqual(code[at + 1], "sys.exit(1)")
        # And the summary looks for exactly the line the compare step prints.
        self.assertIn(DRIFT_MARKER, _step(SUMMARY_STEP)["run"])

    def test_the_fallthrough_branch_is_the_did_not_complete_message(self):
        # Whatever is not "success" and not a proven compare failure lands in
        # the final ``else``, and that branch must be the harness message.
        script = _step(SUMMARY_STEP)["run"]
        branches = re.split(r"(?m)^\s*else\s*$", script)
        self.assertGreaterEqual(
            len(branches), 2, "expected a final else branch in the summary script"
        )
        final = re.split(r"(?m)^\s*fi\s*$", branches[-1], maxsplit=1)[0]
        self.assertIn(HARNESS_TEXT.rstrip("."), final)
        self.assertNotIn(DRIFT_TEXT.rstrip("."), final)

    def test_the_summary_script_never_exits_nonzero_on_purpose(self):
        # A summary must not turn a red job into a differently-red job, nor a
        # green one red.  Exit status comes from the real steps.
        script = _step(SUMMARY_STEP)["run"]
        self.assertNotRegex(script, r"(?m)^\s*exit\s+[1-9]")

    def test_the_step_set_is_unchanged(self):
        # config/ci/release_gate_classification.json keys on these names.
        names = [s.get("name") for s in _steps()]
        self.assertIn(SUMMARY_STEP, names)
        self.assertEqual(names.count(SUMMARY_STEP), 1)


class TestCompareStepMarker(unittest.TestCase):
    """Run the compare step's own Python (every platform): the marker means drift.

    Only the fresh-measurement directory is substituted, so nothing is read
    from or written to ``/tmp``.  The comparison itself runs as committed.
    """

    COMMITTED = {
        "horizonDays": 7,
        "decision": {"recommendation": "do not ship yet"},
        "pooled": {"topBuys": {"medianExcess": -0.0101}},
    }

    def _compare(self, fresh: str) -> subprocess.CompletedProcess:
        script = _compare_script()
        self.assertEqual(script.count(f'"{RERUN_DIR}"'), 1, "the compare step moved its input")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            measurements = root / "docs" / "measurements"
            measurements.mkdir(parents=True)
            (measurements / "consensus-edge-board-validation-h7.json").write_text(
                json.dumps(self.COMMITTED), encoding="utf-8"
            )
            rerun = root / "ce-rerun"
            rerun.mkdir()
            (rerun / "board-validation-h7.json").write_text(fresh, encoding="utf-8")
            program = root / "compare.py"
            program.write_text(
                script.replace(f'"{RERUN_DIR}"', repr(rerun.as_posix())), encoding="utf-8"
            )
            return subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
                [sys.executable, str(program)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

    def test_matching_verdicts_exit_zero_without_the_marker(self):
        done = self._compare(json.dumps(self.COMMITTED))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(DRIFT_MARKER, done.stdout)
        self.assertIn(OK_TEXT, done.stdout)

    def test_a_changed_verdict_exits_one_with_the_marker_last(self):
        fresh = dict(self.COMMITTED, decision={"recommendation": "ship"})
        done = self._compare(json.dumps(fresh))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("VERDICT DRIFT:", done.stdout)
        self.assertEqual(done.stdout.strip().splitlines()[-1], DRIFT_MARKER)

    def test_a_crashed_comparison_exits_nonzero_without_the_marker(self):
        # Exactly the case the summary used to call drift: malformed JSON in a
        # fresh measurement raises, and the step exits 1 all the same.
        done = self._compare("{not json")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("JSONDecodeError", done.stderr)
        self.assertNotIn(DRIFT_MARKER, done.stdout)


@unittest.skipUnless(
    os.name == "posix" and shutil.which("bash"), "needs a POSIX bash (CI runs ubuntu)"
)
class TestSummaryBehaviour(unittest.TestCase):
    """Run the real script with each combination of step outcomes."""

    def _summary(self, rerun: str, compare: str, compare_txt: str | None) -> str:
        script = _step(SUMMARY_STEP)["run"]
        with tempfile.TemporaryDirectory() as tmp:
            rerun_dir = Path(tmp) / "ce-rerun"
            rerun_dir.mkdir()
            if compare_txt is not None:
                (rerun_dir / "compare.txt").write_text(compare_txt, encoding="utf-8")
            summary = Path(tmp) / "summary.md"
            env = {
                "PATH": os.environ.get("PATH", ""),
                "RERUN_OUTCOME": rerun,
                "COMPARE_OUTCOME": compare,
                "CE_RERUN_DIR": str(rerun_dir),
                "GITHUB_STEP_SUMMARY": str(summary),
            }
            done = subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
                [
                    shutil.which("bash"),
                    "--noprofile",
                    "--norc",
                    "-e",
                    "-o",
                    "pipefail",
                    "-c",
                    script,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            return summary.read_text(encoding="utf-8")

    def test_matching_verdicts_say_so(self):
        text = self._summary("success", "success", "h7: fresh 'do not ship yet'\n")
        self.assertIn(OK_TEXT, text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(HARNESS_TEXT, text)
        self.assertIn("h7: fresh", text)

    def test_a_crashed_rerun_is_a_harness_failure_not_drift(self):
        # The exact shape of the ten red weeks: rerun failed, compare skipped,
        # and no compare.txt was ever written.
        text = self._summary("failure", "skipped", None)
        self.assertIn(HARNESS_TEXT, text)
        self.assertIn("not verdict drift", text)
        self.assertIn("re-run step: failure, compare step: skipped", text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_an_earlier_failed_step_is_also_a_harness_failure(self):
        # Self-test or install failed, so the re-run itself never started.
        text = self._summary("skipped", "skipped", None)
        self.assertIn(HARNESS_TEXT, text)
        self.assertNotIn(DRIFT_TEXT, text)

    def test_a_cancelled_compare_after_a_good_rerun_is_not_drift(self):
        # The re-run succeeded but the compare step never reported a verdict.
        text = self._summary("success", "cancelled", None)
        self.assertIn(HARNESS_TEXT, text)
        self.assertIn("re-run step: success, compare step: cancelled", text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_a_skipped_compare_after_a_good_rerun_is_not_drift(self):
        text = self._summary("success", "skipped", None)
        self.assertIn(HARNESS_TEXT, text)
        self.assertIn("re-run step: success, compare step: skipped", text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_an_empty_compare_outcome_after_a_good_rerun_is_not_drift(self):
        text = self._summary("success", "", None)
        self.assertIn(HARNESS_TEXT, text)
        self.assertIn("compare step: unknown", text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_a_real_drift_is_still_reported_as_drift(self):
        text = self._summary(
            "success",
            "failure",
            f"VERDICT DRIFT:\n  - h7 x.json: 'a' -> 'b'\n{DRIFT_MARKER}\n",
        )
        self.assertIn(DRIFT_TEXT, text)
        self.assertIn("VERDICT DRIFT", text)
        self.assertNotIn(HARNESS_TEXT, text)
        self.assertNotIn(CRASH_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_a_compare_failure_without_the_marker_is_a_crash_not_drift(self):
        # The compare step printed its fresh lines, then raised (bad JSON, a
        # KeyError) and exited 1: the outcome is "failure", the marker absent.
        text = self._summary("success", "failure", "h7: fresh   'do not ship yet' (median -0.01)\n")
        self.assertIn(CRASH_TEXT, text)
        self.assertIn("not verdict drift", text)
        self.assertIn("re-run step: success, compare step: failure", text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(HARNESS_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_a_compare_crash_before_any_output_is_a_crash_not_drift(self):
        text = self._summary("success", "failure", None)
        self.assertIn(CRASH_TEXT, text)
        self.assertNotIn(DRIFT_TEXT, text)

    def test_the_marker_counts_only_as_a_whole_line(self):
        text = self._summary("success", "failure", f"  - h7 {DRIFT_MARKER}.json: crashed here\n")
        self.assertIn(CRASH_TEXT, text)
        self.assertNotIn(DRIFT_TEXT, text)

    def test_a_failed_rerun_and_a_failed_compare_is_not_drift(self):
        text = self._summary("failure", "failure", None)
        self.assertIn(HARNESS_TEXT, text)
        self.assertIn("re-run step: failure, compare step: failure", text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(CRASH_TEXT, text)
        self.assertNotIn(OK_TEXT, text)

    def test_a_failed_rerun_is_not_drift_even_with_the_marker(self):
        # Pins the RERUN_OUTCOME half of the drift guard: the marker and a
        # compare failure are not enough when the re-run itself failed.
        text = self._summary("failure", "failure", f"VERDICT DRIFT:\n{DRIFT_MARKER}\n")
        self.assertIn(HARNESS_TEXT, text)
        self.assertNotIn(DRIFT_TEXT, text)
        self.assertNotIn(CRASH_TEXT, text)


if __name__ == "__main__":
    unittest.main()
