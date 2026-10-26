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
crashed comparison.  The compare step now ends a failing comparison with
exactly one result line, printed last, right before its ``exit 1``:

* ``CE_REVALIDATE_RESULT=verdict_drift`` -- at least one verdict changed;
* ``CE_REVALIDATE_RESULT=missing_committed_measurement`` -- no compared verdict
  changed, but a fresh horizon had no committed measurement to compare against
  (this used to be reported as drift, with advice to move the flag default).

The summary claims drift, or a missing measurement, only when that whole line
is in ``compare.txt``; a compare failure with neither "did not finish".  The
compare step reads the fresh files in sorted order, so ``h14`` is compared
before ``h7``: a crash on ``h7`` leaves real ``h14`` lines in ``compare.txt``,
and no message may then say that nothing was compared.

The compare step's exit status reaches the job only through ``set -o pipefail``
(``python ... | tee``).  Without it a drift reads as a passing step, so the
summary claims a match only when the step passed AND its output ends the way a
match ends; a passing step whose output says otherwise is reported as a harness
inconsistency, never as success.
"""

from __future__ import annotations

import json
import os
import shlex
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
#: Every step, in order.  config/ci/release_gate_classification.json keys on
#: these names, so none of them may change.
STEP_NAMES = [
    "Checkout",
    "Set up Python",
    "Install dependencies",
    "Self-test the gate before trusting it",
    "Re-run the board validation",
    COMPARE_STEP,
    "Upload the fresh measurements",
    SUMMARY_STEP,
]

OK_TEXT = "Committed verdicts still describe the code."
INCONSISTENT_TEXT = (
    "The compare step passed, but its output does not show a completed match, "
    "so no verdict is reported."
)
DRIFT_TEXT = "The committed measurement no longer describes the code."
MISSING_TEXT = "A fresh measurement has no committed measurement to compare against."
CRASH_TEXT = "The comparison did not finish, so this run reached no verdict."
HARNESS_TEXT = "The re-run or the comparison did not complete, so this run reached no verdict."
#: What every non-result message must say about lines a crash left behind.
PARTIAL_TEXT = "Any per-horizon lines printed below are partial and are not a result."
#: Claims that are false once a crash or a cancellation has left per-horizon
#: lines in compare.txt (h14 compared, then h7 crashed).  No message may make
#: them.
FALSE_WHEN_PARTIAL = (
    "no verdict was compared",
    "neither been confirmed nor contradicted",
    "did not get far enough",
)
NO_OUTPUT_TEXT = "(no comparison output was written)"
#: The compare step's result lines.
DRIFT_MARKER = "CE_REVALIDATE_RESULT=verdict_drift"
MISSING_MARKER = "CE_REVALIDATE_RESULT=missing_committed_measurement"
#: Where the compare step reads the fresh measurements (substituted in tests).
RERUN_DIR = "/tmp/ce-rerun"
TEE_LINE_END = "<<'PY' | tee /tmp/ce-rerun/compare.txt"

#: A POSIX bash for the behaviour tests (CI runs ubuntu).  Never resolved on
#: Windows, where ``bash`` on PATH may be WSL's.
BASH = shutil.which("bash") if os.name == "posix" else None
#: The interpreter the compare step's ``python -`` is pointed at.
PYTHON = Path(sys.executable).as_posix()

COMMITTED_H7 = {
    "horizonDays": 7,
    "decision": {"recommendation": "do not ship yet"},
    "pooled": {"topBuys": {"medianExcess": -0.0101}},
}
COMMITTED_H14 = {
    "horizonDays": 14,
    "decision": {"recommendation": "do not ship yet"},
    "pooled": {"topBuys": {"medianExcess": -0.0203}},
}
COMMITTED_BOTH = {"h7": COMMITTED_H7, "h14": COMMITTED_H14}


def _said(text: str) -> str:
    """``text`` with its line wrapping removed, as a reader sees it."""
    return " ".join(text.split())


def _head(summary: str) -> str:
    """The summary's own message: everything before the copied compare output."""
    return summary.split("```", 1)[0]


def _steps() -> list[dict]:
    blob = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return blob["jobs"]["revalidate"]["steps"]


def _step(name: str) -> dict:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {WORKFLOW.name}")


def _branches(script: str) -> list[tuple[str, str]]:
    """``(header, what the branch echoes)`` for each branch of the summary's chain."""
    out: list[tuple[str, list[str]]] = []
    for raw in script.splitlines():
        line = raw.strip()
        if line.startswith(("if ", "elif ")) or line == "else":
            out.append((line, []))
        elif line == "fi":
            break
        elif out and line.startswith('echo "') and line.endswith('"'):
            out[-1][1].append(line[len('echo "') : -1].replace("\\`", "`"))
    return [(header, _said(" ".join(echoed))) for header, echoed in out]


def _guard_of(script: str, text: str) -> str | None:
    """The ``if`` / ``elif`` / ``else`` header of the branch that echoes ``text``."""
    for header, echoed in _branches(script):
        if text in echoed:
            return header
    return None


def _branch_said(script: str, text: str) -> str:
    """Everything the branch that echoes ``text`` says, line wrapping removed."""
    for _header, echoed in _branches(script):
        if text in echoed:
            return echoed
    raise AssertionError(f"no summary branch says {text!r}")


def _compare_script() -> str:
    """The Python the compare step pipes through ``tee``, exactly as committed."""
    lines = _step(COMPARE_STEP)["run"].splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip().endswith(TEE_LINE_END))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "PY")
    return "\n".join(lines[start + 1 : end]) + "\n"


def _code_lines(script: str) -> list[str]:
    return [
        line.strip()
        for line in script.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _pipefail_on_at_tee(run: str) -> bool:
    """Whether the ``set`` commands before the ``| tee`` line leave pipefail on."""
    on = False
    for raw in run.splitlines():
        if raw.rstrip().endswith(TEE_LINE_END):
            return on
        tokens = raw.split("#", 1)[0].split()
        if not tokens or tokens[0] != "set":
            continue
        for flag, value in zip(tokens[1:], tokens[2:]):
            if value != "pipefail":
                continue
            if flag.startswith("-") and flag.endswith("o"):
                on = True
            elif flag.startswith("+") and flag.endswith("o"):
                on = False
    raise AssertionError("the compare step no longer pipes its Python through tee")


def _write_lf(path: Path, text: str) -> None:
    # Bytes, so Windows cannot turn "\n" into "\r\n" and break ``grep -x``.
    path.write_bytes(text.encode("utf-8"))


def _measurement_dirs(root: Path, committed: dict[str, dict], fresh: dict[str, str]) -> Path:
    measurements = root / "docs" / "measurements"
    measurements.mkdir(parents=True)
    for tag, blob in committed.items():
        _write_lf(
            measurements / f"consensus-edge-board-validation-2026-08-04-{tag}.json",
            json.dumps(blob),
        )
    rerun = root / "ce-rerun"
    rerun.mkdir()
    for tag, text in fresh.items():
        _write_lf(rerun / f"board-validation-{tag}.json", text)
    return rerun


def _run_summary(
    rerun: str, compare: str, rerun_dir: Path, summary: Path
) -> subprocess.CompletedProcess:
    """The real summary script, run the way ``shell: bash`` runs it."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "RERUN_OUTCOME": rerun,
        "COMPARE_OUTCOME": compare,
        "CE_RERUN_DIR": rerun_dir.as_posix(),
        "GITHUB_STEP_SUMMARY": summary.as_posix(),
    }
    return subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
        [BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", _step(SUMMARY_STEP)["run"]],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class TestSummaryIsWiredToTheRightSteps(unittest.TestCase):
    """Static, so Windows CI covers it too (the bash behaviour tests are POSIX-only)."""

    def test_the_rerun_and_compare_steps_keep_their_ids(self):
        self.assertEqual(_step("Re-run the board validation").get("id"), "rerun")
        self.assertEqual(_step(COMPARE_STEP).get("id"), "compare")

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

    def test_the_branches_are_in_this_order(self):
        # Success first, then its inconsistency; after a compare failure the
        # two marker branches before the marker-less one; everything else last.
        script = _step(SUMMARY_STEP)["run"]
        order = [OK_TEXT, INCONSISTENT_TEXT, DRIFT_TEXT, MISSING_TEXT, CRASH_TEXT, HARNESS_TEXT]
        branches = _branches(script)
        self.assertEqual(len(branches), len(order), [h for h, _ in branches])
        for (_header, echoed), text in zip(branches, order):
            self.assertIn(text, echoed)

    def test_success_is_claimed_only_with_the_match_line_and_no_result_line(self):
        # COMPARE_OUTCOME alone is not enough: if ``pipefail`` were lost, a
        # drift (or a crash) would still be "success".  The match message needs
        # the compare step's own closing match line, and neither result line.
        guard = _guard_of(_step(SUMMARY_STEP)["run"], OK_TEXT)
        self.assertIsNotNone(guard, "match message not found in the summary script")
        self.assertTrue(guard.startswith("if "), f"match message is in {guard!r}")
        self.assertRegex(guard, r'^if \[\[ "\$\{COMPARE_OUTCOME\}" == "success" \]\] && ')
        self.assertIn(f'grep -qxF "{OK_TEXT}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        self.assertIn(
            f'! grep -qxF -e "{DRIFT_MARKER}" -e "{MISSING_MARKER}" "${{CE_RERUN_DIR}}/compare.txt"',
            guard,
        )
        self.assertNotIn("||", guard)

    def test_any_other_passing_compare_is_a_harness_inconsistency(self):
        script = _step(SUMMARY_STEP)["run"]
        self.assertEqual(
            _guard_of(script, INCONSISTENT_TEXT),
            'elif [[ "${COMPARE_OUTCOME}" == "success" ]]; then',
        )
        said = _branch_said(script, INCONSISTENT_TEXT)
        self.assertIn("not a match and not drift", said)
        self.assertNotIn(OK_TEXT, said)
        self.assertNotIn(DRIFT_TEXT, said)

    def test_the_drift_message_is_guarded_on_a_compare_failure(self):
        # The drift message used to sit in a bare ``else``, so (re-run success,
        # compare skipped/cancelled/empty) printed it even though no verdict
        # had been compared.  The branch that prints it must be an
        # ``if``/``elif`` whose condition tests COMPARE_OUTCOME against
        # ``failure`` -- never an ``else``.
        script = _step(SUMMARY_STEP)["run"]
        self.assertEqual(script.count(DRIFT_TEXT.rstrip(".")), 1)
        guard = _guard_of(script, DRIFT_TEXT)
        self.assertIsNotNone(guard, "drift message not found in the summary script")
        self.assertTrue(guard.startswith(("if ", "elif ")), f"drift message is in {guard!r}")
        self.assertRegex(guard, r'COMPARE_OUTCOME\}"\s*==\s*"failure"')
        self.assertNotIn("!=", guard)

    def test_the_drift_message_requires_a_successful_rerun(self):
        # The RERUN_OUTCOME half of the guard.  Without it, a re-run that
        # failed after writing a partial measurement could still be called
        # drift by a compare step that ran on it.
        guard = _guard_of(_step(SUMMARY_STEP)["run"], DRIFT_TEXT)
        self.assertIsNotNone(guard)
        self.assertRegex(guard, r'RERUN_OUTCOME\}"\s*==\s*"success"')

    def test_the_drift_message_requires_the_drift_marker(self):
        # The compare step exits 1 on drift AND on any uncaught error, so the
        # exit status alone is not evidence of drift: the guard must also find
        # the marker, as a whole line (``-x``), as a fixed string (``-F``), in
        # the compare step's own output.
        guard = _guard_of(_step(SUMMARY_STEP)["run"], DRIFT_TEXT)
        self.assertIsNotNone(guard)
        self.assertIn(f'grep -qxF "{DRIFT_MARKER}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        self.assertNotIn(MISSING_MARKER, guard)
        # ... joined with ``&&`` to the outcome test, not offered as an alternative.
        self.assertNotIn("||", guard)
        self.assertRegex(guard, r"\]\]\s*&&\s*grep ")

    def test_a_missing_committed_measurement_has_its_own_guarded_message(self):
        script = _step(SUMMARY_STEP)["run"]
        guard = _guard_of(script, MISSING_TEXT)
        self.assertIsNotNone(guard, "missing-measurement message not found")
        self.assertTrue(guard.startswith("elif "), f"missing-measurement message is in {guard!r}")
        self.assertRegex(guard, r'COMPARE_OUTCOME\}"\s*==\s*"failure"')
        self.assertRegex(guard, r'RERUN_OUTCOME\}"\s*==\s*"success"')
        self.assertIn(f'grep -qxF "{MISSING_MARKER}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        self.assertNotIn(DRIFT_MARKER, guard)
        self.assertNotIn("||", guard)
        self.assertRegex(guard, r"\]\]\s*&&\s*grep ")

    def test_the_missing_measurement_message_gives_no_flag_advice(self):
        # Nothing was found to disagree with the committed verdict, so there is
        # no flag-default decision to make; the action is to commit the fresh
        # measurement for the horizon that had none.
        said = _branch_said(_step(SUMMARY_STEP)["run"], MISSING_TEXT)
        self.assertNotIn("flag", said.lower())
        self.assertNotIn("ADR-023", said)
        self.assertIn("not verdict drift", said)
        self.assertIn("commit the fresh measurement for each of those horizons", said)
        self.assertIn("NO COMMITTED MEASUREMENT", said)

    def test_a_compare_failure_without_a_result_line_did_not_finish(self):
        script = _step(SUMMARY_STEP)["run"]
        self.assertEqual(script.count(CRASH_TEXT.rstrip(".")), 1)
        guard = _guard_of(script, CRASH_TEXT)
        self.assertIsNotNone(guard, "did-not-finish message not found in the summary script")
        self.assertTrue(guard.startswith("elif "), f"did-not-finish message is in {guard!r}")
        self.assertRegex(guard, r'COMPARE_OUTCOME\}"\s*==\s*"failure"')
        self.assertRegex(guard, r'RERUN_OUTCOME\}"\s*==\s*"success"')
        # It comes AFTER both marker-guarded branches, so only a failure with
        # neither result line reaches it.
        self.assertLess(script.index(DRIFT_TEXT.rstrip(".")), script.index(CRASH_TEXT.rstrip(".")))
        self.assertLess(
            script.index(MISSING_TEXT.rstrip(".")), script.index(CRASH_TEXT.rstrip("."))
        )
        self.assertNotIn(DRIFT_MARKER, guard)
        self.assertNotIn(MISSING_MARKER, guard)

    def test_the_did_not_finish_message_claims_only_what_is_true(self):
        # h14 is compared before h7, so a crash on h7 leaves real h14 lines in
        # compare.txt: the message may not say nothing was compared.
        said = _branch_said(_step(SUMMARY_STEP)["run"], CRASH_TEXT)
        self.assertIn(PARTIAL_TEXT, said)
        self.assertIn("not verdict drift", said)
        for claim in FALSE_WHEN_PARTIAL:
            self.assertNotIn(claim, said)

    def test_no_message_claims_that_nothing_was_compared(self):
        # The same holds for every branch: a cancelled compare step can also
        # leave partial lines, and the fallback for a missing compare.txt is
        # reached after a successful re-run too.
        script = _step(SUMMARY_STEP)["run"]
        everything = _said(" ".join(echoed for _header, echoed in _branches(script)))
        for claim in FALSE_WHEN_PARTIAL:
            self.assertNotIn(claim, everything)
            self.assertNotIn(claim, script)
        self.assertIn(PARTIAL_TEXT, _branch_said(script, HARNESS_TEXT))
        self.assertIn(f'|| echo "{NO_OUTPUT_TEXT}"', script)

    def test_the_fallthrough_branch_is_the_did_not_complete_message(self):
        # Whatever is not a passing step and not a compare failure after a
        # good re-run lands in the final ``else``: the harness message.
        script = _step(SUMMARY_STEP)["run"]
        header, said = _branches(script)[-1]
        self.assertEqual(header, "else")
        self.assertIn(HARNESS_TEXT, said)
        self.assertIn("not verdict drift", said)
        self.assertNotIn(DRIFT_TEXT, said)

    def test_the_summary_script_never_exits_nonzero_on_purpose(self):
        # A summary must not turn a red job into a differently-red job, nor a
        # green one red.  Exit status comes from the real steps.
        script = _step(SUMMARY_STEP)["run"]
        self.assertNotRegex(script, r"(?m)^\s*exit\s+[1-9]")

    def test_the_step_set_is_unchanged(self):
        self.assertEqual([s.get("name") for s in _steps()], STEP_NAMES)


class TestCompareStepScript(unittest.TestCase):
    """Static checks of the compare step (every platform)."""

    def test_the_compare_step_sets_pipefail_before_the_tee(self):
        # ``python - <<'PY' | tee compare.txt``: the pipeline's status is
        # python's exit 1 only under pipefail.  Without it a drift gives
        # ``COMPARE_OUTCOME=success``.  ``shell: bash`` also passes
        # ``-o pipefail``, but the script must not depend on that.
        step = _step(COMPARE_STEP)
        self.assertEqual(step.get("shell"), "bash")
        self.assertTrue(_pipefail_on_at_tee(step["run"]), "pipefail is not set before the tee")

    def test_the_pipefail_check_sees_a_dropped_pipefail(self):
        # The check above must be able to fail.
        run = _step(COMPARE_STEP)["run"]
        self.assertIn("set -Eeuo pipefail\n", run)
        self.assertFalse(_pipefail_on_at_tee(run.replace("set -Eeuo pipefail\n", "set -Eeu\n")))
        self.assertFalse(
            _pipefail_on_at_tee(
                run.replace("set -Eeuo pipefail\n", "set -Eeuo pipefail\nset +o pipefail\n")
            )
        )

    def test_each_result_line_is_printed_last_right_before_the_exit(self):
        # One print, as the step's final act before ``sys.exit(1)``: a crash
        # anywhere earlier -- including while printing the lists -- leaves it
        # out, so its presence means every fresh horizon was read.
        script = _compare_script()
        self.assertEqual(script.count(DRIFT_MARKER), 1)
        self.assertEqual(script.count(MISSING_MARKER), 1)
        self.assertEqual(script.count("sys.exit(1)"), 1)
        code = _code_lines(script)
        at = code.index("print(marker)")
        self.assertEqual(code[at + 1], "sys.exit(1)")
        self.assertEqual(code.count("print(marker)"), 1)
        assigned = code.index("marker = (")
        self.assertEqual(
            code[assigned:at],
            ["marker = (", f'"{DRIFT_MARKER}"', "if drift", f'else "{MISSING_MARKER}"', ")"],
        )

    def test_a_missing_committed_measurement_is_not_listed_as_drift(self):
        code = _code_lines(_compare_script())
        appends = [line for line in code if "no committed measurement" in line]
        self.assertEqual(
            appends, ['missing.append(f"h{horizon}: no committed measurement to compare against")']
        )

    def test_the_summary_reads_the_lines_the_compare_step_prints(self):
        script = _compare_script()
        summary = _step(SUMMARY_STEP)["run"]
        for marker in (DRIFT_MARKER, MISSING_MARKER):
            self.assertIn(f'"{marker}"', script)
            self.assertIn(f'"{marker}"', summary)
        # The match line the summary requires is the compare step's final print.
        self.assertEqual(_code_lines(script)[-1], f'print("\\n{OK_TEXT}")')


class TestCompareStepMarker(unittest.TestCase):
    """Run the compare step's own Python (every platform).

    Only the fresh-measurement directory is substituted, so nothing is read
    from or written to ``/tmp``.  The comparison itself runs as committed.
    """

    def _compare(
        self, fresh: dict[str, str], committed: dict[str, dict] | None = None
    ) -> subprocess.CompletedProcess:
        script = _compare_script()
        self.assertEqual(script.count(f'"{RERUN_DIR}"'), 1, "the compare step moved its input")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rerun = _measurement_dirs(
                root, COMMITTED_BOTH if committed is None else committed, fresh
            )
            program = root / "compare.py"
            _write_lf(program, script.replace(f'"{RERUN_DIR}"', repr(rerun.as_posix())))
            return subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
                [sys.executable, str(program)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

    def _last_line(self, done: subprocess.CompletedProcess) -> str:
        return done.stdout.strip().splitlines()[-1]

    def test_matching_verdicts_exit_zero_with_the_match_line_last(self):
        done = self._compare({"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H14)})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(DRIFT_MARKER, done.stdout)
        self.assertNotIn(MISSING_MARKER, done.stdout)
        self.assertEqual(self._last_line(done), OK_TEXT)

    def test_a_changed_verdict_exits_one_with_the_drift_line_last(self):
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        done = self._compare({"h7": json.dumps(fresh), "h14": json.dumps(COMMITTED_H14)})
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("VERDICT DRIFT:", done.stdout)
        self.assertNotIn("NO COMMITTED MEASUREMENT:", done.stdout)
        self.assertNotIn(MISSING_MARKER, done.stdout)
        self.assertEqual(self._last_line(done), DRIFT_MARKER)

    def test_a_missing_committed_measurement_has_its_own_line(self):
        # h7 matches; h14 has nothing committed.  Red, but not drift.
        done = self._compare(
            {"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H14)},
            committed={"h7": COMMITTED_H7},
        )
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("NO COMMITTED MEASUREMENT:", done.stdout)
        self.assertIn("h14: no committed measurement to compare against", done.stdout)
        self.assertNotIn("VERDICT DRIFT:", done.stdout)
        self.assertNotIn(DRIFT_MARKER, done.stdout)
        self.assertEqual(self._last_line(done), MISSING_MARKER)

    def test_drift_wins_over_a_missing_committed_measurement(self):
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        done = self._compare(
            {"h7": json.dumps(fresh), "h14": json.dumps(COMMITTED_H14)},
            committed={"h7": COMMITTED_H7},
        )
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("VERDICT DRIFT:", done.stdout)
        self.assertIn("NO COMMITTED MEASUREMENT:", done.stdout)
        self.assertNotIn(MISSING_MARKER, done.stdout)
        self.assertEqual(self._last_line(done), DRIFT_MARKER)

    def test_a_crashed_comparison_exits_nonzero_without_a_result_line(self):
        # Exactly the case the summary used to call drift: malformed JSON in a
        # fresh measurement raises, and the step exits 1 all the same.
        done = self._compare({"h7": "{not json"}, committed={"h7": COMMITTED_H7})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("JSONDecodeError", done.stderr)
        self.assertNotIn(DRIFT_MARKER, done.stdout)
        self.assertNotIn(MISSING_MARKER, done.stdout)

    def test_h14_is_compared_before_an_h7_crash(self):
        # Sorted order puts h14 first.  Whether it matched or drifted, its lines
        # are printed before h7's bad JSON raises, and no result line follows.
        for h14_call in ("do not ship yet", "ship"):
            with self.subTest(h14_call=h14_call):
                fresh_h14 = dict(COMMITTED_H14, decision={"recommendation": h14_call})
                done = self._compare({"h14": json.dumps(fresh_h14), "h7": "{not json"})
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("JSONDecodeError", done.stderr)
                self.assertIn(f"h14: fresh   {h14_call!r}", done.stdout)
                self.assertIn(
                    "h14: consensus-edge-board-validation-2026-08-04-h14.json", done.stdout
                )
                self.assertNotIn(DRIFT_MARKER, done.stdout)
                self.assertNotIn(MISSING_MARKER, done.stdout)


@unittest.skipUnless(BASH, "needs a POSIX bash (CI runs ubuntu)")
class TestSummaryBehaviour(unittest.TestCase):
    """Run the real summary script with each combination of step outcomes."""

    def _summary(self, rerun: str, compare: str, compare_txt: str | None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            rerun_dir = Path(tmp) / "ce-rerun"
            rerun_dir.mkdir()
            if compare_txt is not None:
                _write_lf(rerun_dir / "compare.txt", compare_txt)
            summary = Path(tmp) / "summary.md"
            done = _run_summary(rerun, compare, rerun_dir, summary)
            self.assertEqual(done.returncode, 0, done.stderr)
            text = summary.read_text(encoding="utf-8")
        for claim in FALSE_WHEN_PARTIAL:
            self.assertNotIn(claim, _said(text))
        return text

    def assertSays(self, text: str, expected: str) -> None:  # noqa: N802
        """The summary's message is ``expected`` and none of the others."""
        head = _head(text)
        self.assertIn(expected, head)
        for other in (
            OK_TEXT,
            INCONSISTENT_TEXT,
            DRIFT_TEXT,
            MISSING_TEXT,
            CRASH_TEXT,
            HARNESS_TEXT,
        ):
            if other != expected:
                self.assertNotIn(other, head)

    MATCH_TXT = (
        "h7: fresh   'do not ship yet' (median -0.0101)\n"
        "h7: consensus-edge-board-validation-2026-08-04-h7.json 'do not ship yet' (median -0.0101)\n"
        f"\n{OK_TEXT}\n"
    )

    def test_matching_verdicts_say_so(self):
        text = self._summary("success", "success", self.MATCH_TXT)
        self.assertSays(text, OK_TEXT)
        self.assertIn("h7: fresh", text)

    def test_a_passing_step_without_the_match_line_is_not_success(self):
        # What a lost pipefail turns a crash into: the step "passed", the
        # output stops part-way through.
        text = self._summary(
            "success", "success", "h14: fresh   'do not ship yet' (median -0.02)\n"
        )
        self.assertSays(text, INCONSISTENT_TEXT)

    def test_a_passing_step_with_the_drift_line_is_not_success(self):
        # What a lost pipefail turns a real drift into.
        text = self._summary(
            "success", "success", f"VERDICT DRIFT:\n  - h7 x.json: 'a' -> 'b'\n{DRIFT_MARKER}\n"
        )
        self.assertSays(text, INCONSISTENT_TEXT)
        self.assertIn(DRIFT_MARKER, text)

    def test_a_passing_step_with_the_missing_line_is_not_success(self):
        text = self._summary(
            "success",
            "success",
            f"NO COMMITTED MEASUREMENT:\n  - h14: no committed measurement to compare against\n{MISSING_MARKER}\n",
        )
        self.assertSays(text, INCONSISTENT_TEXT)

    def test_a_result_line_beside_the_match_line_is_not_success(self):
        text = self._summary("success", "success", f"{self.MATCH_TXT}{DRIFT_MARKER}\n")
        self.assertSays(text, INCONSISTENT_TEXT)

    def test_a_passing_step_with_no_output_is_not_success(self):
        text = self._summary("success", "success", None)
        self.assertSays(text, INCONSISTENT_TEXT)
        self.assertIn(NO_OUTPUT_TEXT, text)

    def test_a_crashed_rerun_is_a_harness_failure_not_drift(self):
        # The exact shape of the ten red weeks: rerun failed, compare skipped,
        # and no compare.txt was ever written.
        text = self._summary("failure", "skipped", None)
        self.assertSays(text, HARNESS_TEXT)
        self.assertIn("not verdict drift", text)
        self.assertIn("re-run step: failure, compare step: skipped", text)
        self.assertIn(NO_OUTPUT_TEXT, text)

    def test_an_earlier_failed_step_is_also_a_harness_failure(self):
        # Self-test or install failed, so the re-run itself never started.
        text = self._summary("skipped", "skipped", None)
        self.assertSays(text, HARNESS_TEXT)

    def test_a_cancelled_compare_after_a_good_rerun_is_not_drift(self):
        # The re-run succeeded but the compare step never reported a verdict;
        # what it printed before the cancellation is partial.
        text = self._summary(
            "success", "cancelled", "h14: fresh   'do not ship yet' (median -0.02)\n"
        )
        self.assertSays(text, HARNESS_TEXT)
        self.assertIn("re-run step: success, compare step: cancelled", text)
        self.assertIn(PARTIAL_TEXT, _said(text))
        self.assertIn("h14: fresh", text)

    def test_a_skipped_compare_after_a_good_rerun_is_not_drift(self):
        text = self._summary("success", "skipped", None)
        self.assertSays(text, HARNESS_TEXT)
        self.assertIn("re-run step: success, compare step: skipped", text)

    def test_an_empty_compare_outcome_after_a_good_rerun_is_not_drift(self):
        text = self._summary("success", "", None)
        self.assertSays(text, HARNESS_TEXT)
        self.assertIn("compare step: unknown", text)

    def test_a_real_drift_is_still_reported_as_drift(self):
        text = self._summary(
            "success",
            "failure",
            f"VERDICT DRIFT:\n  - h7 x.json: 'a' -> 'b'\n{DRIFT_MARKER}\n",
        )
        self.assertSays(text, DRIFT_TEXT)
        self.assertIn("VERDICT DRIFT", text)
        self.assertIn("flag default", _said(text))

    def test_drift_plus_a_missing_measurement_is_drift(self):
        text = self._summary(
            "success",
            "failure",
            "VERDICT DRIFT:\n  - h7 x.json: 'a' -> 'b'\n\n"
            "NO COMMITTED MEASUREMENT:\n  - h14: no committed measurement to compare against\n"
            f"{DRIFT_MARKER}\n",
        )
        self.assertSays(text, DRIFT_TEXT)

    def test_a_missing_committed_measurement_is_not_drift(self):
        text = self._summary(
            "success",
            "failure",
            "h7: fresh   'do not ship yet' (median -0.0101)\n"
            "h14: fresh   'do not ship yet' (median -0.0203)\n\n"
            "NO COMMITTED MEASUREMENT:\n  - h14: no committed measurement to compare against\n"
            f"{MISSING_MARKER}\n",
        )
        self.assertSays(text, MISSING_TEXT)
        self.assertNotIn("flag", _said(text).lower())
        self.assertIn("commit the fresh measurement for each of those horizons", _said(text))

    def test_a_compare_failure_without_a_result_line_did_not_finish(self):
        # The compare step printed its fresh lines, then raised (bad JSON, a
        # KeyError) and exited 1: the outcome is "failure", no result line.
        text = self._summary("success", "failure", "h7: fresh   'do not ship yet' (median -0.01)\n")
        self.assertSays(text, CRASH_TEXT)
        self.assertIn("not verdict drift", text)
        self.assertIn("re-run step: success, compare step: failure", text)

    def test_h14_compared_then_an_h7_crash_is_reported_as_partial(self):
        # The reviewer's case: h14 was really compared (here it even drifted),
        # then h7's JSON was malformed.  The summary may not say nothing was
        # compared; it says the run reached no verdict and the lines are partial.
        partial = (
            "h14: fresh   'ship' (median 0.01)\n"
            "h14: consensus-edge-board-validation-2026-08-04-h14.json 'do not ship yet' (median -0.0203)\n"
        )
        text = self._summary("success", "failure", partial)
        self.assertSays(text, CRASH_TEXT)
        self.assertIn(PARTIAL_TEXT, _said(text))
        self.assertIn(partial, text)

    def test_a_compare_crash_before_any_output_did_not_finish(self):
        text = self._summary("success", "failure", None)
        self.assertSays(text, CRASH_TEXT)
        self.assertIn(NO_OUTPUT_TEXT, text)

    def test_a_marker_counts_only_as_a_whole_line(self):
        for marker in (DRIFT_MARKER, MISSING_MARKER):
            with self.subTest(marker=marker):
                text = self._summary("success", "failure", f"  - h7 {marker}.json: crashed here\n")
                self.assertSays(text, CRASH_TEXT)

    def test_a_failed_rerun_and_a_failed_compare_is_not_drift(self):
        text = self._summary("failure", "failure", None)
        self.assertSays(text, HARNESS_TEXT)
        self.assertIn("re-run step: failure, compare step: failure", text)

    def test_a_failed_rerun_is_not_drift_even_with_a_marker(self):
        # Pins the RERUN_OUTCOME half of both marker guards: a marker and a
        # compare failure are not enough when the re-run itself failed.
        for marker in (DRIFT_MARKER, MISSING_MARKER):
            with self.subTest(marker=marker):
                text = self._summary("failure", "failure", f"VERDICT DRIFT:\n{marker}\n")
                self.assertSays(text, HARNESS_TEXT)


@unittest.skipUnless(BASH, "needs a POSIX bash (CI runs ubuntu)")
class TestCompareStepThroughTheSummary(unittest.TestCase):
    """Run the compare step's whole bash script, then the summary on its output.

    The script runs under plain ``bash`` (no ``-e``, no ``-o pipefail``), so
    its own ``set`` line is what carries python's exit status through ``tee``.
    Only the fresh-measurement directory and the interpreter are substituted.
    """

    def _run(
        self,
        fresh: dict[str, str],
        committed: dict[str, dict] | None = None,
        mutate=None,
    ) -> tuple[int, str, str]:
        run = _step(COMPARE_STEP)["run"]
        self.assertEqual(run.count(RERUN_DIR), 2, "the compare step moved its input or output")
        self.assertEqual(run.count("python - <<'PY'"), 1)
        if mutate is not None:
            run = mutate(run)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rerun_dir = _measurement_dirs(
                root, COMMITTED_BOTH if committed is None else committed, fresh
            )
            self.assertNotRegex(rerun_dir.as_posix(), r"\s", "tee's path is unquoted")
            script = run.replace(RERUN_DIR, rerun_dir.as_posix()).replace(
                "python - <<'PY'", f"{shlex.quote(PYTHON)} - <<'PY'"
            )
            compare = subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
                [BASH, "--noprofile", "--norc", "-c", script],
                cwd=root,
                env={k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ},
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            outcome = "success" if compare.returncode == 0 else "failure"
            summary_path = root / "summary.md"
            done = _run_summary("success", outcome, rerun_dir, summary_path)
            self.assertEqual(done.returncode, 0, done.stderr)
            return compare.returncode, outcome, summary_path.read_text(encoding="utf-8")

    def test_a_match_is_green_and_says_so(self):
        code, outcome, text = self._run(
            {"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H14)}
        )
        self.assertEqual((code, outcome), (0, "success"))
        self.assertIn(OK_TEXT, _head(text))
        self.assertNotIn(INCONSISTENT_TEXT, _head(text))

    def test_a_drift_is_red_and_says_so(self):
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        code, outcome, text = self._run({"h7": json.dumps(fresh), "h14": json.dumps(COMMITTED_H14)})
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(DRIFT_TEXT, _head(text))
        self.assertNotIn(OK_TEXT, _head(text))

    def test_a_missing_measurement_is_red_and_says_so(self):
        code, outcome, text = self._run(
            {"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H14)},
            committed={"h7": COMMITTED_H7},
        )
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(MISSING_TEXT, _head(text))
        self.assertNotIn(DRIFT_TEXT, _head(text))
        self.assertNotIn("flag", _said(_head(text)).lower())

    def test_drift_plus_a_missing_measurement_is_red_drift(self):
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        code, outcome, text = self._run(
            {"h7": json.dumps(fresh), "h14": json.dumps(COMMITTED_H14)},
            committed={"h7": COMMITTED_H7},
        )
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(DRIFT_TEXT, _head(text))
        self.assertNotIn(MISSING_TEXT, _head(text))

    def test_h14_compared_then_an_h7_crash_is_red_and_partial(self):
        code, outcome, text = self._run({"h14": json.dumps(COMMITTED_H14), "h7": "{not json"})
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(CRASH_TEXT, _head(text))
        self.assertIn(PARTIAL_TEXT, _said(_head(text)))
        self.assertIn("h14: fresh", text)
        for claim in FALSE_WHEN_PARTIAL:
            self.assertNotIn(claim, _said(text))

    def test_a_dropped_pipefail_is_caught_by_the_summary(self):
        # If pipefail is lost, tee's 0 makes a real drift a passing step.  The
        # static test above stops that change; this pins that the summary still
        # does not call it a match.
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        code, outcome, text = self._run(
            {"h7": json.dumps(fresh), "h14": json.dumps(COMMITTED_H14)},
            mutate=lambda run: run.replace("set -Eeuo pipefail\n", "set -Eeu\n"),
        )
        self.assertEqual((code, outcome), (0, "success"))
        self.assertIn(INCONSISTENT_TEXT, _head(text))
        self.assertNotIn(OK_TEXT, _head(text))
        self.assertIn(DRIFT_MARKER, text)


if __name__ == "__main__":
    unittest.main()
