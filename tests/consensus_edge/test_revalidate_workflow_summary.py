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

A third result line closes a false green.  The compare step used to compare
whatever fresh files it found, so a re-run that exited 0 but wrote no ``--out``
file (or fewer files than the horizons it was asked for, or a dispatch of only
spaces, which runs the loop zero times) compared nothing and still printed the
match line.  It now reads the horizons the re-run step recorded
(``steps.rerun.outputs.horizons``, ``7 14`` unless a dispatch named others) and
requires a fresh measurement for every one of them:

* ``CE_REVALIDATE_RESULT=no_fresh_measurement`` -- no compared verdict changed,
  but a requested horizon has no fresh measurement (or none was requested).

Precedence, one line only: ``verdict_drift``, then ``no_fresh_measurement``,
then ``missing_committed_measurement``.  The summary says the run reached no
verdict for the named horizons and gives no flag advice; its success branch
rejects any line that starts ``CE_REVALIDATE_RESULT=``.
"""

from __future__ import annotations

import json
import os
import re
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
RERUN_STEP = "Re-run the board validation"
#: Every step, in order.  config/ci/release_gate_classification.json keys on
#: these names, so none of them may change.
STEP_NAMES = [
    "Checkout",
    "Set up Python",
    "Install dependencies",
    "Self-test the gate before trusting it",
    RERUN_STEP,
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
NO_FRESH_TEXT = (
    "The re-run produced no fresh measurement for the named horizons, "
    "so this run reached no verdict for them."
)
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
#: Every message the summary can give, in the order its branches test them.
ALL_TEXTS = (
    OK_TEXT,
    INCONSISTENT_TEXT,
    DRIFT_TEXT,
    NO_FRESH_TEXT,
    MISSING_TEXT,
    CRASH_TEXT,
    HARNESS_TEXT,
)
#: The compare step's result lines, in order of precedence.
RESULT_PREFIX = "CE_REVALIDATE_RESULT="
DRIFT_MARKER = "CE_REVALIDATE_RESULT=verdict_drift"
NO_FRESH_MARKER = "CE_REVALIDATE_RESULT=no_fresh_measurement"
MISSING_MARKER = "CE_REVALIDATE_RESULT=missing_committed_measurement"
ALL_MARKERS = (DRIFT_MARKER, NO_FRESH_MARKER, MISSING_MARKER)
#: Where the compare step reads the fresh measurements (substituted in tests).
RERUN_DIR = "/tmp/ce-rerun"
TEE_LINE_END = "<<'PY' | tee /tmp/ce-rerun/compare.txt"
#: How the compare step learns which horizons the re-run was asked for.
REQUESTED_ENV = "CE_REQUESTED_HORIZONS"
REQUESTED_EXPR = "${{ steps.rerun.outputs.horizons }}"
#: What the re-run step records when no dispatch input named horizons.
DEFAULT_HORIZONS = "7 14"
#: The pieces of the re-run step a behaviour test substitutes.
HORIZON_INPUT_EXPR = "${{ inputs.horizon_days }}"
STUDY_CALL = "python scripts/validate_consensus_edge_board.py"
#: A stand-in for the study that always exits 0 and writes its ``--out`` file
#: only for a horizon with a prepared measurement in ``$CE_STUB_DIR``: the shape
#: of a study run that succeeds without measuring.
STUB_STUDY = """ce_stub_study() {
  local h="" out=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --horizon-days) h="$2"; shift 2 ;;
      --out) out="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  if [[ -f "${CE_STUB_DIR}/h${h}.json" ]]; then cp "${CE_STUB_DIR}/h${h}.json" "${out}"; fi
}
"""

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


def _base_env() -> dict[str, str]:
    return {k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ}


def _run_rerun_step(
    root: Path, rerun_dir: Path, horizon_input: str, writes: dict[str, str]
) -> tuple[subprocess.CompletedProcess, dict[str, str]]:
    """The real re-run step, with the study replaced by :data:`STUB_STUDY`.

    ``horizon_input`` stands in for ``${{ inputs.horizon_days }}`` (empty on a
    schedule); ``writes`` maps ``h7`` / ``h14`` to the measurement the stub
    writes for that horizon.  Returns the step's result and its outputs.
    """
    run = _step(RERUN_STEP)["run"]
    assert run.count(HORIZON_INPUT_EXPR) == 1, "the re-run step reads its input differently"
    assert run.count(STUDY_CALL) == 1, "the re-run step calls the study differently"
    assert run.count(RERUN_DIR) == 2, "the re-run step moved its output"
    stub_dir = root / "stub"
    stub_dir.mkdir()
    for tag, text in writes.items():
        _write_lf(stub_dir / f"{tag}.json", text)
    outputs = root / "github_output"
    _write_lf(outputs, "")
    script = STUB_STUDY + (
        run.replace(HORIZON_INPUT_EXPR, horizon_input)
        .replace(STUDY_CALL, "ce_stub_study")
        .replace(RERUN_DIR, rerun_dir.as_posix())
    )
    done = subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
        [BASH, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=root,
        env={
            **_base_env(),
            "GITHUB_OUTPUT": outputs.as_posix(),
            "CE_STUB_DIR": stub_dir.as_posix(),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    recorded: dict[str, str] = {}
    for line in outputs.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            recorded[key] = value
    return done, recorded


def _run_compare_step(
    root: Path, rerun_dir: Path, requested: str, mutate=None
) -> subprocess.CompletedProcess:
    """The compare step's whole bash script, under plain ``bash``.

    Only the fresh-measurement directory and the interpreter are substituted;
    ``requested`` is what ``${{ steps.rerun.outputs.horizons }}`` resolves to.
    """
    run = _step(COMPARE_STEP)["run"]
    assert run.count(RERUN_DIR) == 2, "the compare step moved its input or output"
    assert run.count("python - <<'PY'") == 1
    if mutate is not None:
        run = mutate(run)
    assert not any(c.isspace() for c in rerun_dir.as_posix()), "tee's path is unquoted"
    script = run.replace(RERUN_DIR, rerun_dir.as_posix()).replace(
        "python - <<'PY'", f"{shlex.quote(PYTHON)} - <<'PY'"
    )
    return subprocess.run(  # noqa: S603 -- fixed argv, script text from the repo
        [BASH, "--noprofile", "--norc", "-c", script],
        cwd=root,
        env={**_base_env(), REQUESTED_ENV: requested},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class TestSummaryIsWiredToTheRightSteps(unittest.TestCase):
    """Static, so Windows CI covers it too (the bash behaviour tests are POSIX-only)."""

    def test_the_rerun_and_compare_steps_keep_their_ids(self):
        self.assertEqual(_step(RERUN_STEP).get("id"), "rerun")
        self.assertEqual(_step(COMPARE_STEP).get("id"), "compare")

    def test_the_compare_step_reads_the_horizons_the_rerun_recorded(self):
        # The re-run step's own record of what it was asked for -- never a
        # second copy of the ``7 14`` default -- and as an environment
        # variable, so the compare step's script splices no expression.
        step = _step(COMPARE_STEP)
        self.assertEqual((step.get("env") or {}).get(REQUESTED_ENV), REQUESTED_EXPR)
        self.assertNotIn("${{", step["run"])
        self.assertIn(f'os.environ["{REQUESTED_ENV}"]', _compare_script())
        self.assertNotIn(DEFAULT_HORIZONS, _compare_script())

    def test_the_rerun_step_records_every_horizon_it_was_asked_for(self):
        # What the compare step requires is exactly what the loop runs and
        # where each run is told to write.
        run = _step(RERUN_STEP)["run"]
        self.assertIn(f'if [[ -z "${{HORIZONS}}" ]]; then HORIZONS="{DEFAULT_HORIZONS}"; fi', run)
        self.assertIn("for h in ${HORIZONS}; do", run)
        self.assertIn(f'--out "{RERUN_DIR}/board-validation-h${{h}}.json"', run)
        self.assertIn('echo "horizons=${HORIZONS}" >> "$GITHUB_OUTPUT"', run)

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
        # three marker branches, in the compare step's order of precedence,
        # before the marker-less one; everything else last.
        script = _step(SUMMARY_STEP)["run"]
        branches = _branches(script)
        self.assertEqual(len(branches), len(ALL_TEXTS), [h for h, _ in branches])
        for (_header, echoed), text in zip(branches, ALL_TEXTS):
            self.assertIn(text, echoed)

    def test_success_is_claimed_only_with_the_match_line_and_no_result_line(self):
        # COMPARE_OUTCOME alone is not enough: if ``pipefail`` were lost, a
        # drift (or a crash) would still be "success".  The match message needs
        # the compare step's own closing match line, and no result line of any
        # kind: every line that starts ``CE_REVALIDATE_RESULT=`` blocks it,
        # including one added after this test was written.
        guard = _guard_of(_step(SUMMARY_STEP)["run"], OK_TEXT)
        self.assertIsNotNone(guard, "match message not found in the summary script")
        self.assertTrue(guard.startswith("if "), f"match message is in {guard!r}")
        self.assertRegex(guard, r'^if \[\[ "\$\{COMPARE_OUTCOME\}" == "success" \]\] && ')
        self.assertIn(f'grep -qxF "{OK_TEXT}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        self.assertIn(f'&& ! grep -q "^{RESULT_PREFIX}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        self.assertNotIn("||", guard)
        for marker in ALL_MARKERS:
            self.assertTrue(marker.startswith(RESULT_PREFIX), marker)

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
        self.assertNotIn(NO_FRESH_MARKER, guard)
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
        self.assertNotIn(NO_FRESH_MARKER, guard)
        self.assertNotIn("||", guard)
        self.assertRegex(guard, r"\]\]\s*&&\s*grep ")

    def test_a_missing_fresh_measurement_has_its_own_guarded_message(self):
        script = _step(SUMMARY_STEP)["run"]
        self.assertEqual(script.count(NO_FRESH_TEXT.rstrip(".")), 1)
        guard = _guard_of(script, NO_FRESH_TEXT)
        self.assertIsNotNone(guard, "no-fresh-measurement message not found")
        self.assertTrue(guard.startswith("elif "), f"no-fresh-measurement message is in {guard!r}")
        self.assertRegex(guard, r'COMPARE_OUTCOME\}"\s*==\s*"failure"')
        self.assertRegex(guard, r'RERUN_OUTCOME\}"\s*==\s*"success"')
        self.assertIn(f'grep -qxF "{NO_FRESH_MARKER}" "${{CE_RERUN_DIR}}/compare.txt"', guard)
        self.assertNotIn(DRIFT_MARKER, guard)
        self.assertNotIn(MISSING_MARKER, guard)
        self.assertNotIn("!=", guard)
        self.assertNotIn("||", guard)
        self.assertRegex(guard, r"\]\]\s*&&\s*grep ")

    def test_the_no_fresh_message_reaches_no_verdict_and_gives_no_flag_advice(self):
        # Those horizons were never measured, so there is nothing to agree or
        # disagree with the committed verdict, and no flag decision to make.
        said = _branch_said(_step(SUMMARY_STEP)["run"], NO_FRESH_TEXT)
        self.assertNotIn("flag", said.lower())
        self.assertNotIn("ADR-023", said)
        self.assertNotIn("commit the fresh", said.lower())
        self.assertIn("not verdict drift and not a match", said)
        self.assertIn("NO FRESH MEASUREMENT", said)
        self.assertIn("No compared verdict changed.", said)

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
        # It comes AFTER every marker-guarded branch, so only a failure with no
        # result line reaches it.
        for text in (DRIFT_TEXT, NO_FRESH_TEXT, MISSING_TEXT):
            self.assertLess(script.index(text.rstrip(".")), script.index(CRASH_TEXT.rstrip(".")))
        for marker in ALL_MARKERS:
            self.assertNotIn(marker, guard)

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
        # out, so its presence means every fresh horizon was read.  The chain
        # that picks it is the order of precedence: drift, then a missing fresh
        # measurement, then a missing committed one.
        script = _compare_script()
        for marker in ALL_MARKERS:
            self.assertEqual(script.count(marker), 1, marker)
        self.assertEqual(script.count("sys.exit(1)"), 1)
        code = _code_lines(script)
        at = code.index("print(marker)")
        self.assertEqual(code[at + 1], "sys.exit(1)")
        self.assertEqual(code.count("print(marker)"), 1)
        chosen = code.index(f'marker = "{DRIFT_MARKER}"') - 1
        self.assertEqual(
            code[chosen:at],
            [
                "if drift:",
                f'marker = "{DRIFT_MARKER}"',
                "elif no_fresh:",
                f'marker = "{NO_FRESH_MARKER}"',
                "else:",
                f'marker = "{MISSING_MARKER}"',
            ],
        )

    def test_every_result_line_the_compare_step_prints_is_one_of_three(self):
        # The success guard rejects the prefix, so any new result line is safe
        # for the match message; but the summary only has words for these.
        found = set(re.findall(r"CE_REVALIDATE_RESULT=\w+", _compare_script()))
        self.assertEqual(found, set(ALL_MARKERS))

    def test_a_missing_committed_measurement_is_not_listed_as_drift(self):
        code = _code_lines(_compare_script())
        appends = [line for line in code if "no committed measurement" in line]
        self.assertEqual(
            appends, ['missing.append(f"h{horizon}: no committed measurement to compare against")']
        )

    def test_the_summary_reads_the_lines_the_compare_step_prints(self):
        script = _compare_script()
        summary = _step(SUMMARY_STEP)["run"]
        for marker in ALL_MARKERS:
            self.assertIn(f'"{marker}"', script)
            self.assertIn(f'"{marker}"', summary)
        # The match line the summary requires is the compare step's final print.
        self.assertEqual(_code_lines(script)[-1], f'print("\\n{OK_TEXT}")')


class TestCompareStepMarker(unittest.TestCase):
    """Run the compare step's own Python (every platform).

    Only the fresh-measurement directory is substituted, so nothing is read
    from or written to ``/tmp``.  The comparison itself runs as committed, and
    ``requested`` is what ``steps.rerun.outputs.horizons`` resolved to (``None``
    leaves the variable unset).
    """

    def _compare(
        self,
        fresh: dict[str, str],
        committed: dict[str, dict] | None = None,
        requested: str | None = DEFAULT_HORIZONS,
    ) -> subprocess.CompletedProcess:
        script = _compare_script()
        self.assertEqual(script.count(f'"{RERUN_DIR}"'), 1, "the compare step moved its input")
        env = {k: v for k, v in os.environ.items() if k != REQUESTED_ENV}
        if requested is not None:
            env[REQUESTED_ENV] = requested
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
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

    def _last_line(self, done: subprocess.CompletedProcess) -> str:
        return done.stdout.strip().splitlines()[-1]

    def assertOnlyResult(self, done: subprocess.CompletedProcess, marker: str) -> None:  # noqa: N802
        """Exit 1, ``marker`` as the last line, and no other result line."""
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self._last_line(done), marker)
        self.assertNotIn(OK_TEXT, done.stdout)
        for other in ALL_MARKERS:
            if other != marker:
                self.assertNotIn(other, done.stdout)
        self.assertEqual(done.stdout.count(RESULT_PREFIX), 1)

    def assertNoResult(self, done: subprocess.CompletedProcess) -> None:  # noqa: N802
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn(RESULT_PREFIX, done.stdout)
        self.assertNotIn(OK_TEXT, done.stdout)

    def test_matching_verdicts_exit_zero_with_the_match_line_last(self):
        done = self._compare({"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H14)})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(RESULT_PREFIX, done.stdout)
        self.assertNotIn("NO FRESH MEASUREMENT:", done.stdout)
        self.assertEqual(self._last_line(done), OK_TEXT)

    def test_zero_fresh_files_is_no_fresh_measurement(self):
        # The false green: the study exited 0 for both horizons and wrote
        # nothing, so there was nothing to compare -- and the match line used
        # to be printed all the same.
        done = self._compare({})
        self.assertOnlyResult(done, NO_FRESH_MARKER)
        self.assertIn("NO FRESH MEASUREMENT:", done.stdout)
        self.assertIn("h7: the re-run wrote no fresh measurement", done.stdout)
        self.assertIn("h14: the re-run wrote no fresh measurement", done.stdout)
        self.assertNotIn("VERDICT DRIFT:", done.stdout)
        self.assertNotIn("NO COMMITTED MEASUREMENT:", done.stdout)

    def test_one_of_two_horizons_missing_is_no_fresh_measurement(self):
        # h14 was measured and matches; h7 was asked for and never written.
        done = self._compare({"h14": json.dumps(COMMITTED_H14)})
        self.assertOnlyResult(done, NO_FRESH_MARKER)
        self.assertIn("h14: fresh   'do not ship yet'", done.stdout)
        self.assertIn("h7: the re-run wrote no fresh measurement", done.stdout)
        self.assertNotIn("h14: the re-run wrote no fresh measurement", done.stdout)

    def test_drift_wins_over_a_missing_fresh_measurement(self):
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        done = self._compare({"h7": json.dumps(fresh)})
        self.assertOnlyResult(done, DRIFT_MARKER)
        self.assertIn("VERDICT DRIFT:", done.stdout)
        self.assertIn("NO FRESH MEASUREMENT:", done.stdout)
        self.assertIn("h14: the re-run wrote no fresh measurement", done.stdout)

    def test_no_fresh_wins_over_a_missing_committed_measurement(self):
        # h14 is fresh with nothing committed; h7 is committed with nothing
        # fresh.  Neither horizon was compared, and the missing fresh
        # measurement is what this run could not do.
        done = self._compare({"h14": json.dumps(COMMITTED_H14)}, committed={"h7": COMMITTED_H7})
        self.assertOnlyResult(done, NO_FRESH_MARKER)
        self.assertIn("NO FRESH MEASUREMENT:", done.stdout)
        self.assertIn("h7: the re-run wrote no fresh measurement", done.stdout)
        self.assertIn("NO COMMITTED MEASUREMENT:", done.stdout)
        self.assertIn("h14: no committed measurement to compare against", done.stdout)

    def test_drift_wins_over_both_kinds_of_missing_measurement(self):
        drifted = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        h28 = dict(COMMITTED_H14, horizonDays=28)
        done = self._compare(
            {"h7": json.dumps(drifted), "h28": json.dumps(h28)}, requested="7 14 28"
        )
        self.assertOnlyResult(done, DRIFT_MARKER)
        for section in ("VERDICT DRIFT:", "NO FRESH MEASUREMENT:", "NO COMMITTED MEASUREMENT:"):
            self.assertIn(section, done.stdout)

    def test_a_dispatch_of_one_horizon_needs_only_that_one(self):
        done = self._compare({"h14": json.dumps(COMMITTED_H14)}, requested="14")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self._last_line(done), OK_TEXT)
        self.assertNotIn(RESULT_PREFIX, done.stdout)

    def test_a_fresh_file_counts_for_the_horizon_it_measured(self):
        # Keyed on the measurement's own ``horizonDays``, as the comparison is:
        # an h14-named file that measured 7 days is not an h14 measurement.
        done = self._compare({"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H7)})
        self.assertOnlyResult(done, NO_FRESH_MARKER)
        self.assertIn("h14: the re-run wrote no fresh measurement", done.stdout)

    def test_no_requested_horizon_is_no_fresh_measurement(self):
        # A dispatch of only spaces runs the re-run's loop zero times.
        for requested in ("", "   "):
            with self.subTest(requested=requested):
                done = self._compare({}, requested=requested)
                self.assertOnlyResult(done, NO_FRESH_MARKER)
                self.assertIn("no horizon was requested of the re-run", done.stdout)

    def test_an_unset_horizon_list_is_a_crash_without_a_result_line(self):
        # The env mapping is gone: the step cannot know what to require, so it
        # neither matches nor names a result.
        done = self._compare({"h7": json.dumps(COMMITTED_H7)}, requested=None)
        self.assertNoResult(done)
        self.assertIn("KeyError", done.stderr)

    def test_a_non_integer_horizon_is_a_crash_without_a_result_line(self):
        done = self._compare({"h7": json.dumps(COMMITTED_H7)}, requested="7 x")
        self.assertNoResult(done)
        self.assertIn("ValueError", done.stderr)

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
        self.assertIn(expected, _said(head))
        for other in ALL_TEXTS:
            if other != expected:
                self.assertNotIn(other, _said(head))

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

    def test_a_passing_step_with_the_no_fresh_line_is_not_success(self):
        text = self._summary(
            "success",
            "success",
            f"NO FRESH MEASUREMENT:\n  - h7: the re-run wrote no fresh measurement\n{NO_FRESH_MARKER}\n",
        )
        self.assertSays(text, INCONSISTENT_TEXT)

    def test_a_result_line_beside_the_match_line_is_not_success(self):
        # Every result line, and one this summary has no words for yet: the
        # success guard rejects the prefix, not a list.
        for marker in (*ALL_MARKERS, f"{RESULT_PREFIX}something_new"):
            with self.subTest(marker=marker):
                text = self._summary("success", "success", f"{self.MATCH_TXT}{marker}\n")
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

    NO_FRESH_BOTH_TXT = (
        "\nNO FRESH MEASUREMENT:\n"
        "  - h7: the re-run wrote no fresh measurement\n"
        "  - h14: the re-run wrote no fresh measurement\n"
        f"{NO_FRESH_MARKER}\n"
    )

    def test_zero_fresh_measurements_reach_no_verdict(self):
        text = self._summary("success", "failure", self.NO_FRESH_BOTH_TXT)
        self.assertSays(text, NO_FRESH_TEXT)
        self.assertIn("not verdict drift and not a match", _said(text))
        self.assertNotIn("flag", _said(_head(text)).lower())
        self.assertNotIn("ADR-023", text)
        self.assertIn("h14: the re-run wrote no fresh measurement", text)

    def test_one_horizon_without_a_fresh_measurement_reaches_no_verdict(self):
        text = self._summary(
            "success",
            "failure",
            "h14: fresh   'do not ship yet' (median -0.0203)\n"
            "h14: consensus-edge-board-validation-2026-08-04-h14.json 'do not ship yet' (median -0.0203)\n"
            "\nNO FRESH MEASUREMENT:\n  - h7: the re-run wrote no fresh measurement\n"
            f"{NO_FRESH_MARKER}\n",
        )
        self.assertSays(text, NO_FRESH_TEXT)
        self.assertNotIn("flag", _said(_head(text)).lower())

    def test_drift_plus_a_missing_fresh_measurement_is_drift(self):
        text = self._summary(
            "success",
            "failure",
            "VERDICT DRIFT:\n  - h7 x.json: 'a' -> 'b'\n\n"
            "NO FRESH MEASUREMENT:\n  - h14: the re-run wrote no fresh measurement\n"
            f"{DRIFT_MARKER}\n",
        )
        self.assertSays(text, DRIFT_TEXT)

    def test_no_fresh_plus_a_missing_committed_measurement_is_no_fresh(self):
        text = self._summary(
            "success",
            "failure",
            "h14: fresh   'do not ship yet' (median -0.0203)\n\n"
            "NO FRESH MEASUREMENT:\n  - h7: the re-run wrote no fresh measurement\n\n"
            "NO COMMITTED MEASUREMENT:\n  - h14: no committed measurement to compare against\n"
            f"{NO_FRESH_MARKER}\n",
        )
        self.assertSays(text, NO_FRESH_TEXT)
        self.assertNotIn("flag", _said(_head(text)).lower())

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
        for marker in ALL_MARKERS:
            with self.subTest(marker=marker):
                text = self._summary("success", "failure", f"  - h7 {marker}.json: crashed here\n")
                self.assertSays(text, CRASH_TEXT)

    def test_a_failed_rerun_and_a_failed_compare_is_not_drift(self):
        text = self._summary("failure", "failure", None)
        self.assertSays(text, HARNESS_TEXT)
        self.assertIn("re-run step: failure, compare step: failure", text)

    def test_a_failed_rerun_is_not_drift_even_with_a_marker(self):
        # Pins the RERUN_OUTCOME half of every marker guard: a marker and a
        # compare failure are not enough when the re-run itself failed.
        for marker in ALL_MARKERS:
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
        requested: str = DEFAULT_HORIZONS,
    ) -> tuple[int, str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rerun_dir = _measurement_dirs(
                root, COMMITTED_BOTH if committed is None else committed, fresh
            )
            compare = _run_compare_step(root, rerun_dir, requested, mutate)
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

    def test_zero_fresh_files_are_red_and_reach_no_verdict(self):
        code, outcome, text = self._run({})
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(NO_FRESH_TEXT, _head(text))
        self.assertNotIn(OK_TEXT, _head(text))
        self.assertNotIn("flag", _said(_head(text)).lower())
        self.assertIn(NO_FRESH_MARKER, text)

    def test_one_of_two_horizons_missing_is_red_and_reaches_no_verdict(self):
        code, outcome, text = self._run({"h14": json.dumps(COMMITTED_H14)})
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(NO_FRESH_TEXT, _head(text))
        self.assertIn("h7: the re-run wrote no fresh measurement", text)

    def test_drift_plus_a_missing_fresh_measurement_is_red_drift(self):
        fresh = dict(COMMITTED_H7, decision={"recommendation": "ship"})
        code, outcome, text = self._run({"h7": json.dumps(fresh)})
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(DRIFT_TEXT, _head(text))
        self.assertNotIn(NO_FRESH_TEXT, _head(text))

    def test_no_fresh_plus_a_missing_committed_measurement_is_red_no_fresh(self):
        code, outcome, text = self._run(
            {"h14": json.dumps(COMMITTED_H14)}, committed={"h7": COMMITTED_H7}
        )
        self.assertEqual((code, outcome), (1, "failure"))
        self.assertIn(NO_FRESH_TEXT, _head(text))
        self.assertNotIn(MISSING_TEXT, _head(text))


@unittest.skipUnless(BASH, "needs a POSIX bash (CI runs ubuntu)")
class TestRerunThroughTheSummary(unittest.TestCase):
    """Re-run step -> its recorded horizons -> compare step -> summary.

    The re-run step runs as committed, with only the study replaced by a stub
    that exits 0 and writes ``--out`` for the horizons it is given a
    measurement for, and ``${{ inputs.horizon_days }}`` replaced by the
    dispatch input (empty on a schedule).  Its recorded ``horizons`` output is
    handed to the compare step the way ``steps.rerun.outputs.horizons`` would.
    """

    def _chain(self, horizon_input: str, writes: dict[str, str]) -> tuple[str, int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rerun_dir = _measurement_dirs(root, COMMITTED_BOTH, {})
            rerun, outputs = _run_rerun_step(root, rerun_dir, horizon_input, writes)
            self.assertEqual(rerun.returncode, 0, rerun.stderr)
            self.assertIn("horizons", outputs)
            compare = _run_compare_step(root, rerun_dir, outputs.get("horizons", ""))
            outcome = "success" if compare.returncode == 0 else "failure"
            summary_path = root / "summary.md"
            done = _run_summary("success", outcome, rerun_dir, summary_path)
            self.assertEqual(done.returncode, 0, done.stderr)
            return outputs["horizons"], compare.returncode, summary_path.read_text(encoding="utf-8")

    def test_a_scheduled_run_whose_study_writes_nothing_is_not_a_match(self):
        recorded, code, text = self._chain("", {})
        self.assertEqual(recorded, DEFAULT_HORIZONS)
        self.assertEqual(code, 1)
        self.assertIn(NO_FRESH_TEXT, _head(text))
        self.assertNotIn(OK_TEXT, _head(text))
        self.assertIn("h7: the re-run wrote no fresh measurement", text)
        self.assertIn("h14: the re-run wrote no fresh measurement", text)

    def test_a_scheduled_run_whose_study_writes_only_h14_is_not_a_match(self):
        _recorded, code, text = self._chain("", {"h14": json.dumps(COMMITTED_H14)})
        self.assertEqual(code, 1)
        self.assertIn(NO_FRESH_TEXT, _head(text))
        self.assertIn("h7: the re-run wrote no fresh measurement", text)
        self.assertNotIn("h14: the re-run wrote no fresh measurement", text)

    def test_a_dispatch_of_only_spaces_is_not_a_match(self):
        # The loop runs zero times and the step still passes.
        recorded, code, text = self._chain("   ", {"h7": json.dumps(COMMITTED_H7)})
        self.assertEqual(recorded.split(), [])
        self.assertEqual(code, 1)
        self.assertIn(NO_FRESH_TEXT, _head(text))
        self.assertIn("no horizon was requested of the re-run", text)

    def test_a_scheduled_run_that_measures_both_horizons_is_a_match(self):
        recorded, code, text = self._chain(
            "", {"h7": json.dumps(COMMITTED_H7), "h14": json.dumps(COMMITTED_H14)}
        )
        self.assertEqual(recorded, DEFAULT_HORIZONS)
        self.assertEqual(code, 0)
        self.assertIn(OK_TEXT, _head(text))
        self.assertNotIn(INCONSISTENT_TEXT, _head(text))

    def test_a_dispatch_of_one_horizon_is_a_match_on_that_horizon(self):
        recorded, code, text = self._chain("14", {"h14": json.dumps(COMMITTED_H14)})
        self.assertEqual(recorded, "14")
        self.assertEqual(code, 0)
        self.assertIn(OK_TEXT, _head(text))


if __name__ == "__main__":
    unittest.main()
