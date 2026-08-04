"""The refit path: what it was, and what it must never become again.

Until 2026-07-26 the weekly refit rewrote the eight ``HILL_*_C/S``
constants in ``src/canonical/player_valuation.py``, rewrote the guard
that was supposed to check them, and pushed to ``main`` — triggering a
deploy — with nothing verifying the result.  Three independent defects,
any one sufficient (ADR-008):

1. ``rebaseline_ktc_reconciliation`` recomputed the guard's expected
   values FROM the challenger, so the residual was zero by
   construction for any curve.
2. KTC is a TRAINING source for the constants the guard scored, so
   even honest pins would have been training-set validation.
3. The guard is auto-marked ``livedata`` and the workflow ran
   ``pytest -m "not livedata"`` — 13 deselected, 0 run.  It never
   executed.

An earlier version of this file pinned those defects so the finding
could not rot.  They are now fixed, so the assertions are inverted:
this file pins the FIXES, and fails if any of the three returns.

Reason (2) is deliberately still asserted as TRUE — KTC remains a
training source.  That is a fact about the fit, not a defect that was
repaired, and it is precisely why the gate had to move off KTC rather
than be repaired in place.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.model_registry.holdout import OFFENSE_TRAINING_SOURCES

REPO = Path(__file__).resolve().parents[2]
REFIT = REPO / "scripts" / "auto_refit_hill_curves.py"
FIT = REPO / "scripts" / "fit_hill_curve_percentile.py"
KTC_TEST = REPO / "tests" / "canonical" / "test_ktc_reconciliation.py"
WORKFLOW = REPO / ".github" / "workflows" / "refit-hill-curves.yml"
PLAYER_VALUATION = REPO / "src" / "canonical" / "player_valuation.py"
CONFTEST = REPO / "tests" / "conftest.py"


def _strip_comments_and_docstrings(text: str) -> str:
    """Assert on code, not on prose about the code.

    ORCHESTRATION.md §2b records a matcher that passed on the CSS
    *comments* documenting a rule rather than the rule itself.  Every
    claim below is about behaviour, and this file's own docstrings
    describe the defects at length — without stripping, several of
    these tests would pass on their own preamble.
    """
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    text = re.sub(r"'''(?:.|\n)*?'''", "", text)
    return re.sub(r"(?m)#.*$", "", text)


# ── Defect 1: the refit rewrote production code and its own guard ──


class TestTheRefitNoLongerWritesProductionCode:
    def test_refit_does_not_write_any_file(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "write_text" not in code, "the refit driver writes a file again"

    def test_refit_cannot_even_import_the_writer(self):
        """MECHANISM TEST. Not importing it is stronger than not calling
        it: a later edit cannot reach the writer by accident."""
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "write_committed_constants" not in code
        import scripts.auto_refit_hill_curves as driver

        assert not hasattr(driver, "write_committed_constants")

    def test_refit_no_longer_rebaselines_the_guard(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "rebaseline" not in code.lower()
        assert "PINNED_DELTAS" not in code
        assert "KTC_RECONCILIATION_TEST" not in code

    def test_the_guard_still_has_real_assertions_to_make(self):
        """The guard itself was left intact — only the thing rewriting
        it was removed. If its pins go stale it should now FAIL, which
        is the tripwire working rather than a regression."""
        code = _strip_comments_and_docstrings(KTC_TEST.read_text())
        assert "assert ours == pinned_ours" in code
        assert "abs(actual_pct - pinned_pct) <= tolerance_pp" in code


class TestTheWorkflowCommitsOnlyTheRegistry:
    def test_workflow_does_not_commit_production_constants(self):
        wf = WORKFLOW.read_text()
        assert "git add config/model_registry/" in wf
        assert "git add src/canonical/player_valuation.py" not in wf
        assert "git add tests/canonical/test_ktc_reconciliation.py" not in wf

    def test_no_git_add_targets_anything_but_the_registry(self):
        """MECHANISM TEST. Catches a second `git add` appended later —
        the rule is 'only the registry', not 'the registry is among the
        things committed'."""
        adds = re.findall(r"^\s*git add (.+)$", WORKFLOW.read_text(), re.MULTILINE)
        assert adds, "no git add found — did the commit step move?"
        for target in adds:
            assert target.strip() == "config/model_registry/", f"unexpected git add: {target}"


# ── Defect 3: the gate is invoked directly, not through a marker ────


class TestTheGateRunsDirectly:
    def test_refit_calls_the_holdout_evaluation_itself(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "evaluate_offense_master" in code
        assert "decide_promotion" in code

    def test_the_gate_does_not_depend_on_pytest_or_markers(self):
        """MECHANISM TEST — the fix for reason 3.

        A gate invoked through pytest can be deselected by a filter; a
        gate invoked as a function call cannot.
        """
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "pytest" not in code, "the gate went back through pytest"
        assert "livedata" not in code

    def test_an_unevaluable_gate_is_an_error_not_a_pass(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "HoldoutError" in code
        assert "EXIT_ERROR" in code

    def test_the_workflow_self_tests_the_gate_before_trusting_it(self):
        assert "pytest tests/model_registry/" in WORKFLOW.read_text()

    def test_the_workflow_no_longer_runs_the_suite_against_rewritten_code(self):
        """It used to run `pytest -m "not livedata"` over constants it
        had just rewritten, while that same filter deselected the one
        test guarding them."""
        assert 'pytest tests/ -q -m "not livedata"' not in WORKFLOW.read_text()


class TestTheLivedataMarkingIsPreserved:
    """Reason 3 must NOT be solved by un-marking the guard.

    The marking exists because data-coupled failures once stalled every
    PR (a yahooBoone row-count dip). Removing it would trade one outage
    class for another. The gate moved instead.
    """

    def test_the_guard_is_still_marked_livedata(self):
        # Parse to the closing brace of the frozenset LITERAL, not to the
        # first ")".  The old ")" split truncated the block at the first
        # parenthesis appearing anywhere inside it — including one in a
        # comment — which made this guard silently read an empty-ish block
        # and fail for a reason that had nothing to do with the marking.
        # ``tests/test_livedata_policy.py`` already parses it this way.
        block = CONFTEST.read_text().partition("_LIVEDATA_MODULES")[2].partition("}")[0]
        assert '"test_ktc_reconciliation.py"' in block, (
            "the guard was un-marked — that re-introduces the PR-stalling "
            "failure the marking was added to prevent"
        )

    def test_the_gate_does_not_rely_on_that_marking_either_way(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "conftest" not in code
        assert "_LIVEDATA_MODULES" not in code


# ── Defect 2: still true, and still why the gate had to move ────────


class TestKtcRemainsATrainingSource:
    def test_ktc_is_a_training_source(self):
        offense_block = FIT.read_text().split("OFFENSE_SOURCES")[1].split("}")[0]
        assert "ktc.csv" in offense_block
        assert "KTC" in OFFENSE_TRAINING_SOURCES

    def test_the_guard_scores_the_constants_ktc_trains(self):
        pv = _strip_comments_and_docstrings(PLAYER_VALUATION.read_text())
        sig = pv.split("def percentile_to_value")[1].split(")")[0]
        assert "midpoint: float = HILL_PERCENTILE_C" in sig
        assert "slope: float = HILL_PERCENTILE_S" in sig

    def test_the_new_gate_scores_the_same_constants_on_other_boards(self):
        """Closes the loop: same parameters, different data."""
        from src.model_registry.hill_masters import VALIDATED_PARAMS

        assert VALIDATED_PARAMS == ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S")


class TestParityWithTheFitSourceList:
    """``holdout.py`` mirrors OFFENSE_SOURCES as a literal. If the fit
    gains a source and the mirror does not, a training board silently
    becomes eligible as holdout."""

    def test_training_mirror_matches_the_fit_script(self):
        block = FIT.read_text().split("OFFENSE_SOURCES: dict[str, tuple[str, str]] = {")[1]
        block = block.split("}")[0]
        found = set(re.findall(r'^\s*"([A-Za-z]+)":', block, re.MULTILINE))
        assert found == set(OFFENSE_TRAINING_SOURCES), (
            f"fit script has {sorted(found)}, holdout mirror has "
            f"{sorted(OFFENSE_TRAINING_SOURCES)} — update src/model_registry/holdout.py"
        )

    def test_mirrored_paths_match_the_fit_script(self):
        block = FIT.read_text().split("OFFENSE_SOURCES: dict[str, tuple[str, str]] = {")[1]
        block = block.split("}")[0]
        for label, (path, _) in OFFENSE_TRAINING_SOURCES.items():
            assert path in block, f"{label} path {path} not in the fit script"


@pytest.mark.livedata
class TestWhyTheOldGuardCouldNotFail:
    """Retained as the demonstration behind ADR-008.

    The rebaseline arithmetic is reproduced here — not called, since it
    no longer exists — to show it passed for ANY curve. That is why the
    guard was replaced rather than repaired.
    """

    def test_rebaselining_drove_the_residual_to_zero_for_any_curve(self):
        from src.model_registry.holdout import hill

        ktc_csv = REPO / "CSVs" / "site_raw" / "ktc.csv"
        if not ktc_csv.exists():
            pytest.skip("KTC fixture missing")

        import csv as _csv

        pick = re.compile(r"^\d{4}\s+(Early|Mid|Late)\s+\d", re.IGNORECASE)
        rows: list[int] = []
        with ktc_csv.open(encoding="utf-8") as f:
            for r in _csv.DictReader(f):
                name = (r.get("name") or "").strip()
                val = (r.get("value") or "").strip()
                if not name or not val or pick.match(name):
                    continue
                try:
                    rows.append(int(val))
                except ValueError:
                    continue
        rows.sort(reverse=True)

        ref_n = int(
            re.search(
                r"_PERCENTILE_REFERENCE_N:\s*int\s*=\s*(\d+)",
                (REPO / "src" / "api" / "data_contract.py").read_text(),
            ).group(1)
        )

        for c, s in ((0.118, 1.17), (0.300, 2.50)):
            for rank in (1, 12, 50, 150, 400):
                ktc = rows[rank - 1]
                p = max(0.0, min(1.0, (rank - 1) / (ref_n - 1)))
                ours = int(round(hill(p, c, s)))
                pinned_ours = ours  # what the rebaseline wrote
                pinned_pct = round(100.0 * (ours - ktc) / ktc, 1)
                actual_pct = 100.0 * (ours - ktc) / ktc
                assert ours == pinned_ours
                assert abs(actual_pct - pinned_pct) <= 10.0

    def test_the_new_gate_rejects_the_curve_the_old_guard_accepted(self):
        """MECHANISM TEST. (0.300, 2.50) passes every pinned rank above.
        The replacement must reject it, or the fix is cosmetic."""
        from src.model_registry.holdout import evaluate_offense_master
        from src.model_registry.promotion import decide_promotion

        champion = evaluate_offense_master(0.118, 1.17)
        absurd = evaluate_offense_master(0.300, 2.50)
        decision = decide_promotion(champion.criterion, absurd.criterion)
        assert not decision.promote
        assert decision.alarm, "a curve this wrong should trip the regression alarm"
