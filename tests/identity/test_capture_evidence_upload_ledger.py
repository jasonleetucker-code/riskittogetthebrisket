"""A lost artifact upload must be LOUD, recorded, and never block the refresh.

The manifest (written before the upload, and sealed in the archive zip) points
at the run's artifact.  If the upload fails on exactly the G1 or G2 refresh,
the gate is permanently BLOCKED - so the outcome is recorded in a committed,
bounded ledger the verify script reads, and announced at the time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from scripts import record_identity_capture_upload as recorder
from scripts import verify_identity_capture_evidence as cli
from src.identity import capture_evidence as ce

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "scheduled-refresh.yml"
TS = "2026-11-04T02:00:00+00:00"
ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_RUN_ID": "555",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_REPOSITORY": "owner/repo",
}


def _write_run(root: Path, env=ENV, ts=TS) -> dict:
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "A", 1, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE)
    col.attach("ktc", "A", "A", 1, ["roster_exact"])
    return ce.write_evidence(
        col.build_sidecar({"A": {"ktc": 1}}, scrape_timestamp=ts), root, env=env
    )


def _ledger(root: Path) -> list[dict]:
    return [json.loads(x) for x in (root / ce.UPLOADS_REL).read_text(encoding="utf-8").splitlines()]


# ── the workflow wiring ─────────────────────────────────────────────────


def _steps():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["refresh"]["steps"]


def test_upload_is_bounded_nonblocking_and_followed_by_the_recorder():
    steps = _steps()
    names = [s.get("name", "") for s in steps]
    i = next(k for k, s in enumerate(steps) if s.get("id") == "identity_upload")
    up, rec = steps[i], steps[i + 1]
    assert up["uses"].startswith("actions/upload-artifact@")
    assert up["continue-on-error"] is True and 0 < int(up["timeout-minutes"]) <= 5
    assert up["if"] == "${{ !cancelled() }}"
    assert "scripts/record_identity_capture_upload.py" in rec["run"]
    assert "${{ steps.identity_upload.outcome }}" in rec["run"]
    assert rec["run"].strip().endswith("|| true")
    assert rec["continue-on-error"] is True and int(rec["timeout-minutes"]) <= 5
    assert rec["if"] == "${{ !cancelled() }}"
    # both run before the commit that carries data/scrape_state/ (the ledger's home)
    assert i + 1 < names.index("Commit updated data")
    assert ce.UPLOADS_REL.as_posix().startswith("data/scrape_state/")
    assert re.search(r"git add -f data/scrape_state/", WORKFLOW.read_text(encoding="utf-8"))


# ── the ledger ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("step", "want"),
    [
        ("success", ce.UPLOAD_UPLOADED),
        ("failure", ce.UPLOAD_FAILED),
        ("cancelled", ce.UPLOAD_FAILED),
        ("skipped", ce.UPLOAD_SKIPPED),
        ("", ce.UPLOAD_FAILED),
        ("weird", ce.UPLOAD_FAILED),
    ],
)
def test_step_outcome_mapping_never_reads_a_loss_as_retained(step, want):
    assert ce.upload_from_step_outcome(step) == want


def test_a_successful_upload_is_recorded(tmp_path):
    m = _write_run(tmp_path)
    rec = ce.record_upload_outcome(tmp_path, step_outcome="success", env=ENV, recorded_at="t")
    assert rec == {
        "scrapeTimestamp": TS,
        "evidenceSha256": m["evidence"]["sha256"],
        "artifactUpload": "uploaded",
        "artifact": "identity-capture-evidence-555-1",
        "runId": "555",
        "runAttempt": "1",
        "recordedAt": "t",
    }
    assert ce.upload_status(tmp_path / ce.UPLOADS_REL, m) == ce.UPLOAD_UPLOADED


def test_success_without_the_evidence_file_is_a_failure(tmp_path):
    m = _write_run(tmp_path)
    (tmp_path / ce.EVIDENCE_DIR_REL / m["evidence"]["filename"]).unlink()
    rec = ce.record_upload_outcome(tmp_path, step_outcome="success", env=ENV)
    assert rec["artifactUpload"] == ce.UPLOAD_FAILED


def test_no_claim_without_this_runs_manifest(tmp_path):
    assert ce.record_upload_outcome(tmp_path, step_outcome="success", env=ENV) is None
    _write_run(tmp_path, env={**ENV, "GITHUB_RUN_ID": "554"})  # a previous run's manifest
    assert ce.record_upload_outcome(tmp_path, step_outcome="success", env=ENV) is None
    assert ce.record_upload_outcome(tmp_path, step_outcome="success", env={}) is None
    assert not (tmp_path / ce.UPLOADS_REL).exists()


def test_the_ledger_is_bounded_and_last_line_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "UPLOAD_LEDGER_KEEP", 3)
    m = _write_run(tmp_path)
    for outcome in ("failure", "success", "success", "success"):
        ce.record_upload_outcome(tmp_path, step_outcome=outcome, env=ENV)
    assert len(_ledger(tmp_path)) == 3
    assert ce.upload_status(tmp_path / ce.UPLOADS_REL, m) == ce.UPLOAD_UPLOADED
    ce.record_upload_outcome(tmp_path, step_outcome="failure", env=ENV)
    assert ce.upload_status(tmp_path / ce.UPLOADS_REL, m) == ce.UPLOAD_FAILED


def test_status_is_unrecorded_for_unknown_boards_and_torn_lines(tmp_path):
    m = _write_run(tmp_path)
    ledger = tmp_path / ce.UPLOADS_REL
    assert ce.upload_status(ledger, m) == ce.UPLOAD_UNRECORDED
    ledger.write_text('{"scrapeTimestamp": "' + TS + '", "evidenceSha2\n', encoding="utf-8")
    assert ce.upload_status(ledger, m) == ce.UPLOAD_UNRECORDED
    other = {"scrapeTimestamp": TS, "evidenceSha256": "0" * 64, "artifactUpload": "uploaded"}
    ledger.write_text(json.dumps(other) + "\n", encoding="utf-8")
    assert ce.upload_status(ledger, m) == ce.UPLOAD_UNRECORDED  # same time, other evidence


def test_the_manifest_is_never_rewritten(tmp_path):
    _write_run(tmp_path)
    before = (tmp_path / ce.MANIFEST_REL).read_bytes()
    ce.record_upload_outcome(tmp_path, step_outcome="failure", env=ENV)
    assert (tmp_path / ce.MANIFEST_REL).read_bytes() == before


# ── the recorder script: loud, never failing ────────────────────────────


def test_a_failed_upload_is_loud_and_exits_zero(tmp_path, monkeypatch, capsys):
    m = _write_run(tmp_path)
    summary = tmp_path / "summary.md"
    for k, val in {**ENV, "GITHUB_STEP_SUMMARY": str(summary)}.items():
        monkeypatch.setenv(k, val)
    assert recorder.main(["--outcome", "failure", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("::error title=Identity evidence NOT retained::")
    assert TS in out and m["evidence"]["sha256"] in out
    text = summary.read_text(encoding="utf-8")
    assert "NOT retained" in text and TS in text and m["evidence"]["sha256"] in text


def test_the_recorder_never_fails_the_refresh(tmp_path, monkeypatch, capsys):
    for k, val in ENV.items():
        monkeypatch.setenv(k, val)
    assert recorder.main(["--outcome", "success", "--root", str(tmp_path / "nothing")]) == 0

    def boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ce, "record_upload_outcome", boom)
    assert recorder.main(["--outcome", "failure", "--root", str(tmp_path)]) == 0
    assert "::warning" in capsys.readouterr().out


# ── the verify script reports the outcome ───────────────────────────────


def test_verify_reports_evidence_not_retained(tmp_path, capsys):
    m = _write_run(tmp_path)
    ce.record_upload_outcome(tmp_path, step_outcome="failure", env=ENV)
    args = [
        "--manifest",
        str(tmp_path / ce.MANIFEST_REL),
        "--uploads",
        str(tmp_path / ce.UPLOADS_REL),
    ]
    assert cli.main(args) == 1
    out = capsys.readouterr().out
    assert "artifact upload: failed" in out and "evidence not retained" in out
    # a file that DOES verify (e.g. recovered elsewhere) is still decided by its checksum
    evidence = tmp_path / ce.EVIDENCE_DIR_REL / m["evidence"]["filename"]
    assert cli.main([*args, "--evidence", str(evidence)]) == 0


def test_verify_reports_uploaded_and_unrecorded(tmp_path, capsys):
    _write_run(tmp_path)
    ledger = tmp_path / ce.UPLOADS_REL
    base = ["--manifest", str(tmp_path / ce.MANIFEST_REL), "--uploads", str(ledger)]
    assert cli.main(base) == 0
    assert "artifact upload: unrecorded" in capsys.readouterr().out
    ce.record_upload_outcome(tmp_path, step_outcome="success", env=ENV)
    assert cli.main(base) == 0
    assert "artifact upload: uploaded" in capsys.readouterr().out
