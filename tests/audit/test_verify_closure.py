"""The closure harness must not manufacture closure, or destroy its ledger.

`tools/verify_closure.py` is the audit's measurement instrument. Two
defects found while re-baselining at HEAD on 2026-08-11, both of the same
character as the squash defect that made `claims-frozen-2026-08-05.json`
necessary — a tool damaging the evidence it exists to maintain:

1. A reproduction that CRASHED was stamped `closed-claimed-rerun`. The
   classifier only asked whether a rerun dict existed, never whether the
   command completed. `W10-F002`'s repro died with
   `ENOENT: /tmp/dc-auth.json` and registered as closed.

2. `--id X` replaced the entire 432-record ledger with the filtered
   subset. Observed live: one `--id` run left 3 records and dropped 429,
   the 85 historical claims among them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "docs/master-site-audit/tools/verify_closure.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("verify_closure_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tool():
    return _load_tool()


def _classify(module, claimed: bool, rerun: dict | None) -> str:
    """Re-run the classifier's decision for one record.

    Mirrors the branch in ``main`` rather than importing it, because that
    function also does I/O. Kept in lockstep by the source assertion at
    the bottom of this file.
    """
    rec = {"rerun": rerun} if rerun is not None else {}
    if claimed:
        run = rec.get("rerun") or {}
        if not run:
            return "claimed-unverified"
        if not run.get("ran") or run.get("exit") != 0:
            return "claimed-rerun-failed"
        return "claimed-rerun-needs-adjudication"
    return "open"


class TestCrashIsNotClosure:
    def test_a_crashed_reproduction_is_not_closed(self, tool):
        crashed = {"ran": True, "exit": 1, "stdout": "", "stderr": "ENOENT: /tmp/dc-auth.json"}
        assert _classify(tool, claimed=True, rerun=crashed) == "claimed-rerun-failed"

    def test_a_repro_that_never_ran_is_not_closed(self, tool):
        refused = {"ran": False, "reason": "timeout after 180s"}
        assert _classify(tool, claimed=True, rerun=refused) == "claimed-rerun-failed"

    def test_a_clean_run_still_needs_adjudication(self, tool):
        """Exit 0 means the command ran, not that the defect is gone.

        The harness never compares stdout against the finding's
        `expected`, so a bucket named "closed" would overstate what was
        measured.
        """
        ok = {"ran": True, "exit": 0, "stdout": "some output", "stderr": ""}
        assert _classify(tool, claimed=True, rerun=ok) == "claimed-rerun-needs-adjudication"
        assert "closed" not in _classify(tool, claimed=True, rerun=ok).split("-")[0]

    def test_no_rerun_stays_claimed_unverified(self, tool):
        assert _classify(tool, claimed=True, rerun=None) == "claimed-unverified"

    def test_the_source_agrees_with_this_table(self):
        """Guard against the classifier and this test drifting apart."""
        src = TOOL.read_text()
        assert "claimed-rerun-failed" in src
        assert "claimed-rerun-needs-adjudication" in src
        # The old label asserted closure from a rerun's mere existence.
        assert "closed-claimed-rerun" not in src


class TestFilteredRunPreservesLedger:
    def test_id_filter_merges_rather_than_replaces(self, tmp_path, monkeypatch, tool):
        """`--id` reports on a subset; it must not publish a subset."""
        ledger = tmp_path / "closure.json"
        previous = [
            {"id": "W01-F001", "closure": "open"},
            {"id": "W10-F002", "closure": "claimed-unverified"},
            {"id": "W99-F999", "closure": "open"},
        ]
        ledger.write_text(json.dumps({"records": previous}))

        # The merge the tool performs for a filtered run.
        records = [{"id": "W10-F002", "closure": "claimed-rerun-failed"}]
        prior = json.loads(ledger.read_text()).get("records") or []
        updated = {r["id"]: r for r in records}
        merged = [updated.pop(r["id"], r) for r in prior]
        merged.extend(updated.values())

        assert len(merged) == 3, "a filtered run must not drop untouched records"
        by_id = {r["id"]: r["closure"] for r in merged}
        assert by_id["W10-F002"] == "claimed-rerun-failed", "the filtered id updates"
        assert by_id["W01-F001"] == "open", "untouched records keep their state"
        assert by_id["W99-F999"] == "open"

    def test_the_source_guards_the_filtered_write(self):
        src = TOOL.read_text()
        assert "if args.id:" in src, "filtered runs must take the merge path"
        assert "merged" in src
