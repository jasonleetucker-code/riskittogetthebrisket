"""The closure harness must not manufacture closure, or destroy its ledger.

`tools/verify_closure.py` is the audit's measurement instrument. Four
defects, all of one family — a tool damaging the evidence it exists to
maintain, which is the same failure the squash-merge caused and the
frozen ledger was created to survive:

1. A reproduction that CRASHED was stamped `closed-claimed-rerun`. The
   classifier only asked whether a rerun dict existed, never whether the
   command completed. `W10-F002`'s repro dies with
   `ENOENT: /tmp/dc-auth.json` and registered as closed.

2. `--id X` replaced the entire ledger with the filtered subset.
   Observed live: one `--id` run left 3 records and dropped 429.

3. A missing/unreadable/malformed frozen claims ledger silently became
   "there were no claims". **Measured on the real tree**: pointing
   `--claims-file` at a nonexistent path took claims 86 -> 2, moved 84
   findings from claimed to open, exited 0, and rewrote both outputs.

4. A filtered run whose full ledger was corrupt merged onto `[]`, so the
   subset became the ledger anyway. **Measured**: with a truncated
   closure.json, `--id W10-F002` published 1 record in place of 431 and
   exited 0.

These tests drive the REAL production functions and the REAL CLI. An
earlier version of this file mirrored the classifier and the merge in
test-side helpers; a mirror stays green while production drifts, which
for an evidence-preserving tool is the worst possible place to allow it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "docs/master-site-audit/tools/verify_closure.py"


@pytest.fixture(scope="module")
def vc():
    """The production module itself — not a reimplementation of it."""
    spec = importlib.util.spec_from_file_location("verify_closure_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _findings_fixture(path: Path, ids: list[str]) -> Path:
    """A minimal findings.json the CLI will accept."""
    return _write(
        path,
        {
            "findings": [
                {
                    "id": fid,
                    "priority": "P1",
                    "status": "Implemented but defective",
                    "subsystem": "test",
                    "title": f"fixture finding {fid}",
                    "published": True,
                    "reproduction": {"command": "true"},
                }
                for fid in ids
            ]
        },
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestCrashIsNotClosure:
    """Defect 1 — exercised through the real `classify_closure`."""

    def test_a_crashed_reproduction_is_not_closed(self, vc):
        crashed = {"ran": True, "exit": 1, "stdout": "", "stderr": "ENOENT: /tmp/dc-auth.json"}
        assert (
            vc.classify_closure(claimed=True, run=crashed, has_repro=True, safe=True)
            == "claimed-rerun-failed"
        )

    def test_a_repro_that_never_ran_is_not_closed(self, vc):
        refused = {"ran": False, "reason": "timeout after 180s"}
        assert (
            vc.classify_closure(claimed=True, run=refused, has_repro=True, safe=True)
            == "claimed-rerun-failed"
        )

    def test_a_clean_run_still_needs_adjudication(self, vc):
        """Exit 0 means the command ran, not that the defect is gone.

        The harness never compares stdout against the finding's
        `expected`, so a bucket named "closed" would overstate it.
        """
        ok = {"ran": True, "exit": 0, "stdout": "some output", "stderr": ""}
        verdict = vc.classify_closure(claimed=True, run=ok, has_repro=True, safe=True)
        assert verdict == "claimed-rerun-needs-adjudication"
        assert not verdict.startswith("closed")

    def test_no_rerun_stays_claimed_unverified(self, vc):
        assert (
            vc.classify_closure(claimed=True, run=None, has_repro=True, safe=True)
            == "claimed-unverified"
        )

    def test_unclaimed_buckets(self, vc):
        assert (
            vc.classify_closure(claimed=False, run=None, has_repro=False, safe=False) == "no-repro"
        )
        assert (
            vc.classify_closure(claimed=False, run=None, has_repro=True, safe=False)
            == "open-unsafe-to-rerun"
        )
        assert vc.classify_closure(claimed=False, run=None, has_repro=True, safe=True) == "open"


class TestClaimLedgerFailsClosed:
    """Defect 3 — the load-bearing ledger, via the real loader."""

    def test_missing_ledger_raises(self, vc, tmp_path):
        with pytest.raises(vc.EvidenceLedgerError, match="not found"):
            vc.load_required_claim_ledger(tmp_path / "absent.json")

    def test_malformed_json_raises(self, vc, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text('{"claims": [BROKEN')
        with pytest.raises(vc.EvidenceLedgerError, match="not valid JSON"):
            vc.load_required_claim_ledger(bad)

    def test_wrong_shape_raises(self, vc, tmp_path):
        """A file without the `claims` key is indistinguishable from corruption."""
        wrong = _write(tmp_path / "wrong.json", {"somethingElse": []})
        with pytest.raises(vc.EvidenceLedgerError, match="wrong shape"):
            vc.load_required_claim_ledger(wrong)

    def test_unreadable_ledger_raises(self, vc, tmp_path):
        """A directory in the file's place is an OSError, not a FileNotFoundError."""
        as_dir = tmp_path / "ledger.json"
        as_dir.mkdir()
        with pytest.raises(vc.EvidenceLedgerError):
            vc.load_required_claim_ledger(as_dir)

    def test_explicit_opt_out_is_allowed(self, vc):
        """Deliberate /dev/null is intent; a vanished file is an accident."""
        assert vc.load_required_claim_ledger(Path("/dev/null")) == {}
        assert vc.load_required_claim_ledger(None) == {}

    def test_structurally_valid_empty_ledger_is_fine(self, vc, tmp_path):
        empty = _write(tmp_path / "empty.json", {"claims": []})
        assert vc.load_required_claim_ledger(empty) == {}

    def test_valid_ledger_loads_claims(self, vc, tmp_path):
        good = _write(
            tmp_path / "good.json",
            {"claims": [{"id": "W01-F001", "claimedBy": "abc1234"}, {"id": "W02-F002"}]},
        )
        assert vc.load_required_claim_ledger(good) == {"W01-F001": "abc1234"}


class TestExistingLedgerFailsClosed:
    """Defect 4 — a filtered run cannot merge onto nothing."""

    def test_missing_full_ledger_raises(self, vc, tmp_path):
        with pytest.raises(vc.EvidenceLedgerError, match="does not exist"):
            vc.load_existing_ledger_records(tmp_path / "absent.json")

    def test_corrupt_full_ledger_raises(self, vc, tmp_path):
        corrupt = tmp_path / "closure.json"
        corrupt.write_text('{"records": [BROKEN')
        with pytest.raises(vc.EvidenceLedgerError, match="not valid JSON"):
            vc.load_existing_ledger_records(corrupt)

    def test_wrong_shape_raises(self, vc, tmp_path):
        wrong = _write(tmp_path / "closure.json", {"notRecords": []})
        with pytest.raises(vc.EvidenceLedgerError, match="wrong shape"):
            vc.load_existing_ledger_records(wrong)

    def test_valid_ledger_returns_records(self, vc, tmp_path):
        good = _write(tmp_path / "closure.json", {"records": [{"id": "W01-F001"}]})
        assert vc.load_existing_ledger_records(good) == [{"id": "W01-F001"}]


class TestFilteredMergePreservesLedger:
    """Defect 2 — via the real `merge_filtered_records`."""

    def test_untouched_records_survive(self, vc):
        previous = [
            {"id": "W01-F001", "closure": "open"},
            {"id": "W10-F002", "closure": "claimed-unverified"},
            {"id": "W99-F999", "closure": "open"},
        ]
        merged = vc.merge_filtered_records(
            previous, [{"id": "W10-F002", "closure": "claimed-rerun-failed"}]
        )
        assert len(merged) == 3
        by_id = {r["id"]: r["closure"] for r in merged}
        assert by_id["W10-F002"] == "claimed-rerun-failed"
        assert by_id["W01-F001"] == "open"
        assert by_id["W99-F999"] == "open"

    def test_new_ids_are_appended(self, vc):
        merged = vc.merge_filtered_records([{"id": "A", "closure": "open"}], [{"id": "B"}])
        assert [r["id"] for r in merged] == ["A", "B"]


class TestRealCliFailsClosed:
    """End-to-end: the actual CLI, actual exit codes, actual files."""

    def test_missing_claims_ledger_exits_nonzero_and_writes_nothing(self, tmp_path):
        findings = _findings_fixture(tmp_path / "findings.json", ["W01-F001"])
        out = _write(tmp_path / "closure.json", {"records": [{"id": "SENTINEL"}]})
        report = tmp_path / "CLOSURE_STATUS.md"
        report.write_text("SENTINEL REPORT")

        proc = _run_cli(
            "--claims-file", str(tmp_path / "absent.json"),
            "--findings", str(findings),
            "--out", str(out),
            "--report", str(report),
        )  # fmt: skip

        assert proc.returncode != 0, proc.stdout
        assert "claims ledger not found" in proc.stderr
        # Last known-good outputs untouched.
        assert json.loads(out.read_text())["records"] == [{"id": "SENTINEL"}]
        assert report.read_text() == "SENTINEL REPORT"

    def test_corrupt_claims_ledger_exits_nonzero_and_writes_nothing(self, tmp_path):
        findings = _findings_fixture(tmp_path / "findings.json", ["W01-F001"])
        claims = tmp_path / "claims.json"
        claims.write_text("{not json")
        out = _write(tmp_path / "closure.json", {"records": [{"id": "SENTINEL"}]})
        report = tmp_path / "CLOSURE_STATUS.md"
        report.write_text("SENTINEL REPORT")

        proc = _run_cli(
            "--claims-file", str(claims),
            "--findings", str(findings),
            "--out", str(out),
            "--report", str(report),
        )  # fmt: skip

        assert proc.returncode != 0
        assert "not valid JSON" in proc.stderr
        assert json.loads(out.read_text())["records"] == [{"id": "SENTINEL"}]
        assert report.read_text() == "SENTINEL REPORT"

    def test_filtered_run_with_corrupt_full_ledger_exits_nonzero(self, tmp_path):
        """The exact live failure: --id against an unreadable ledger."""
        findings = _findings_fixture(tmp_path / "findings.json", ["W01-F001", "W02-F002"])
        claims = _write(tmp_path / "claims.json", {"claims": []})
        out = tmp_path / "closure.json"
        out.write_text('{"records": [BROKEN')
        report = tmp_path / "CLOSURE_STATUS.md"
        report.write_text("SENTINEL REPORT")

        proc = _run_cli(
            "--id", "W01-F001",
            "--claims-file", str(claims),
            "--findings", str(findings),
            "--out", str(out),
            "--report", str(report),
        )  # fmt: skip

        assert proc.returncode != 0
        assert "filtered update cannot safely proceed" in proc.stderr
        # The corrupt file is left exactly as found — not replaced by a
        # one-record ledger, which is what used to happen.
        assert out.read_text() == '{"records": [BROKEN'
        assert report.read_text() == "SENTINEL REPORT"

    def test_filtered_run_with_valid_ledger_updates_only_requested(self, tmp_path):
        findings = _findings_fixture(tmp_path / "findings.json", ["W01-F001", "W02-F002"])
        claims = _write(tmp_path / "claims.json", {"claims": []})
        out = _write(
            tmp_path / "closure.json",
            {
                "records": [
                    {"id": "W01-F001", "closure": "STALE", "claimedBy": None, "reproSafe": True},
                    {"id": "W02-F002", "closure": "KEEPME", "claimedBy": None, "reproSafe": True},
                    {"id": "W88-F888", "closure": "KEEPME2", "claimedBy": None, "reproSafe": True},
                ]
            },
        )
        report = tmp_path / "CLOSURE_STATUS.md"

        proc = _run_cli(
            "--id", "W01-F001",
            "--claims-file", str(claims),
            "--findings", str(findings),
            "--out", str(out),
            "--report", str(report),
        )  # fmt: skip

        assert proc.returncode == 0, proc.stderr
        records = {r["id"]: r for r in json.loads(out.read_text())["records"]}
        assert len(records) == 3, "untouched records must survive a filtered run"
        assert records["W01-F001"]["closure"] != "STALE", "the requested id updates"
        assert records["W02-F002"]["closure"] == "KEEPME", "others are preserved verbatim"
        assert records["W88-F888"]["closure"] == "KEEPME2"

    def test_explicit_opt_out_succeeds(self, tmp_path):
        """/dev/null is a supported operator choice, not an accident."""
        findings = _findings_fixture(tmp_path / "findings.json", ["W01-F001"])
        out = tmp_path / "closure.json"
        report = tmp_path / "CLOSURE_STATUS.md"

        proc = _run_cli(
            "--claims-file", "/dev/null",
            "--findings", str(findings),
            "--out", str(out),
            "--report", str(report),
        )  # fmt: skip

        assert proc.returncode == 0, proc.stderr
        assert json.loads(out.read_text())["totals"]["findings"] == 1


class TestTheRealLedgerIsIntact:
    """The committed ledger must remain loadable by the production loader."""

    def test_committed_frozen_ledger_loads(self, vc):
        claims = vc.load_required_claim_ledger(vc.CLAIMS_FROZEN)
        assert len(claims) >= 85, f"expected the frozen 85+ claims, got {len(claims)}"

    def test_committed_closure_ledger_loads(self, vc):
        records = vc.load_existing_ledger_records(vc.OUT)
        assert len(records) > 400, f"expected the full published ledger, got {len(records)}"
