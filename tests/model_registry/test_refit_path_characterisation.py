"""Pins the honest characterisation of the EXISTING refit path.

These tests do not assert that the current behaviour is good.  They
assert that it is what this workstream documented it to be, so that the
finding cannot rot and so a future change to the refit path shows up
here rather than in a surprise.

The finding, in one sentence: the weekly refit rewrites production
constants AND rewrites the only test that guards them, from the
challenger's own output, against a board that is also a training
source — so the guard cannot fail.

Source of truth for the claims:
  scripts/auto_refit_hill_curves.py
  .github/workflows/refit-hill-curves.yml
  tests/canonical/test_ktc_reconciliation.py
  scripts/fit_hill_curve_percentile.py
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


def _strip_comments_and_docstrings(text: str) -> str:
    """Assert on code, not on prose about the code.

    ORCHESTRATION.md §2b records a matcher that passed on the CSS
    *comments* documenting a rule rather than the rule itself.  Same
    trap applies here: every claim below is about behaviour, and a
    docstring describing the behaviour must not satisfy it.
    """
    text = re.sub(r'"""(?:.|\n)*?"""', "", text)
    text = re.sub(r"'''(?:.|\n)*?'''", "", text)
    return re.sub(r"(?m)#.*$", "", text)


class TestTheRefitRewritesProductionCode:
    def test_refit_writes_player_valuation(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "PLAYER_VALUATION.write_text" in code

    def test_refit_writes_its_own_guard_test(self):
        code = _strip_comments_and_docstrings(REFIT.read_text())
        assert "KTC_RECONCILIATION_TEST.write_text" in code

    def test_workflow_commits_both_files_unreviewed(self):
        wf = WORKFLOW.read_text()
        assert "git commit" in wf and "git push" in wf
        assert "src/canonical/player_valuation.py" in wf
        assert "tests/canonical/test_ktc_reconciliation.py" in wf


class TestTheGuardCannotFail:
    """Two independent reasons, either one sufficient."""

    def test_reason_one_the_pins_are_recomputed_from_the_challenger(self):
        """``rebaseline_ktc_reconciliation`` derives ``ours`` from the
        NEW constants and writes it as the expected value, so the
        test's exact pin has a zero residual by construction."""
        code = _strip_comments_and_docstrings(REFIT.read_text())
        fn = code.split("def rebaseline_ktc_reconciliation")[1].split("\ndef ")[0]
        assert 'c_off = fitted["HILL_PERCENTILE_C"]' in fn
        assert "_hill(p, c_off, s_off)" in fn
        assert "pct_diff" in fn
        assert "PINNED_DELTAS" in fn

    def test_the_guard_asserts_exactly_what_the_refit_wrote(self):
        code = _strip_comments_and_docstrings(KTC_TEST.read_text())
        assert "assert ours == pinned_ours" in code
        assert "abs(actual_pct - pinned_pct) <= tolerance_pp" in code

    def test_reason_two_ktc_is_a_training_source(self):
        """Even with honest pins, scoring the OFFENSE master against KTC
        is training-set validation — ORCHESTRATION.md §2b."""
        fit_code = FIT.read_text()
        offense_block = fit_code.split("OFFENSE_SOURCES")[1].split("}")[0]
        assert "ktc.csv" in offense_block
        assert "KTC" in OFFENSE_TRAINING_SOURCES

    def test_the_guarded_constants_are_the_ones_ktc_trains(self):
        """Closes the loop: the fit trains HILL_PERCENTILE_C/S from a
        set containing KTC, and the guard evaluates exactly those."""
        refit_code = REFIT.read_text()
        assert '"OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S")' in refit_code
        pv = _strip_comments_and_docstrings(PLAYER_VALUATION.read_text())
        sig = pv.split("def percentile_to_value")[1].split(")")[0]
        assert "midpoint: float = HILL_PERCENTILE_C" in sig
        assert "slope: float = HILL_PERCENTILE_S" in sig

    def test_the_workflow_already_admits_the_circularity(self):
        """The comment is in the repo today. This pins it so the fix
        cannot be claimed without removing the admission."""
        wf = WORKFLOW.read_text()
        assert "circular" in wf.lower()


class TestParityWithTheFitSourceList:
    """The holdout module mirrors OFFENSE_SOURCES as a literal. If the
    fit gains a source and the mirror does not, a training board
    silently becomes eligible as holdout."""

    def test_training_mirror_matches_the_fit_script(self):
        fit_code = FIT.read_text()
        block = fit_code.split("OFFENSE_SOURCES: dict[str, tuple[str, str]] = {")[1]
        block = block.split("}")[0]
        found = set(re.findall(r'^\s*"([A-Za-z]+)":', block, re.MULTILINE))
        assert found == set(OFFENSE_TRAINING_SOURCES), (
            f"fit script has {sorted(found)}, holdout mirror has "
            f"{sorted(OFFENSE_TRAINING_SOURCES)} — update src/model_registry/holdout.py"
        )

    def test_mirrored_paths_match_the_fit_script(self):
        fit_code = FIT.read_text()
        block = fit_code.split("OFFENSE_SOURCES: dict[str, tuple[str, str]] = {")[1]
        block = block.split("}")[0]
        for label, (path, _) in OFFENSE_TRAINING_SOURCES.items():
            assert path in block, f"{label} path {path} not in the fit script"


@pytest.mark.livedata
class TestTheCircularityIsReal:
    """Demonstrate it rather than only asserting the code shape."""

    def test_rebaselining_drives_the_residual_to_zero(self):
        """Recompute the pins the way the refit does, then check the
        guard's own assertion against them: the residual is identically
        zero, for ANY curve — which is what 'cannot fail' means."""
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

        # Two wildly different "challengers". Both must pass the
        # rebaselined guard, which is the whole problem.
        for c, s in ((0.118, 1.17), (0.300, 2.50)):
            for rank in (1, 12, 50, 150, 400):
                ktc = rows[rank - 1]
                p = max(0.0, min(1.0, (rank - 1) / (ref_n - 1)))
                ours = int(round(hill(p, c, s)))
                pinned_ours = ours  # what rebaseline writes
                pinned_pct = round(100.0 * (ours - ktc) / ktc, 1)
                actual_pct = 100.0 * (ours - ktc) / ktc

                assert ours == pinned_ours
                assert abs(actual_pct - pinned_pct) <= 10.0


class TestTheGuardIsNotEvenRun:
    """Reason three, independent of the other two.

    ``tests/conftest.py`` auto-marks ``test_ktc_reconciliation.py``
    ``livedata``, and the refit workflow's regression step runs
    ``pytest tests/ -q -m "not livedata"``.  So the refit rewrites the
    guard's expectations and then deselects the guard.

    Each of the three defects is individually sufficient; together they
    mean the constants reach production with no check of any kind.
    """

    def test_the_guard_module_is_auto_marked_livedata(self):
        conftest = (REPO / "tests" / "conftest.py").read_text()
        block = conftest.split("_LIVEDATA_MODULES")[1].split(")")[0]
        assert '"test_ktc_reconciliation.py"' in block

    def test_the_refit_workflow_excludes_livedata(self):
        wf = WORKFLOW.read_text()
        assert 'pytest tests/ -q -m "not livedata"' in wf

    def test_the_two_combine_to_deselect_the_guard(self):
        """MECHANISM TEST. Fails if either the marking or the filter
        changes such that the guard would actually run — at which point
        the other two defects become load-bearing again."""
        conftest = (REPO / "tests" / "conftest.py").read_text()
        marked = '"test_ktc_reconciliation.py"' in conftest.split("_LIVEDATA_MODULES")[1]
        excluded = 'm "not livedata"' in WORKFLOW.read_text()
        assert marked and excluded, (
            "the refit's regression step would now run the KTC guard; "
            "re-check whether the rebaseline circularity still makes it vacuous"
        )
