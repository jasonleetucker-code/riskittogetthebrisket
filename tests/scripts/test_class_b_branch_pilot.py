"""Security properties of the fixed Class-B branch pilot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import class_b_branch_verify as verifier
from scripts import class_b_branch_worker as worker


def fixture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / worker.FILE_NAME
    source.write_text(
        "# Performance\n\n[Optimisations that serve a different answer]"
        "(#optimisations-that-serve-a-different-answer).\n\n"
        "## 7. Optimisations that serve a different answer\n",
        encoding="utf-8",
    )
    output = tmp_path / "output"
    output.mkdir()
    return source, output


def test_worker_repairs_real_kind_of_defect_and_verifier_checks_exact_bytes(tmp_path):
    source, output = fixture(tmp_path)
    receipt = worker.execute(source, output)
    verdict = verifier.verify(source, output)
    assert verdict["verified"] is True
    assert receipt["refusals"] == ["path_denied", "command_denied"]
    assert "(#7-optimisations-that-serve-a-different-answer)" in (
        output / worker.FILE_NAME
    ).read_text(encoding="utf-8")


def test_verifier_rejects_unapproved_document_edits(tmp_path):
    source, output = fixture(tmp_path)
    worker.execute(source, output)
    repaired = output / worker.FILE_NAME
    repaired.write_text(repaired.read_text(encoding="utf-8") + "extra\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds"):
        verifier.verify(source, output)


def test_verifier_rejects_receipt_claim_and_extra_output(tmp_path):
    source, output = fixture(tmp_path)
    worker.execute(source, output)
    receipt_path = output / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["refusals"].remove("command_denied")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="refusal"):
        verifier.verify(source, output)
    receipt["refusals"].append("command_denied")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    (output / "unexpected").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="output set"):
        verifier.verify(source, output)


def test_verifier_requires_container_network_evidence(tmp_path):
    source, output = fixture(tmp_path)
    worker.execute(source, output)
    with pytest.raises(ValueError, match="refusal"):
        verifier.verify(source, output, require_network_probe=True)


def test_worker_fails_if_path_or_command_policy_is_sabotaged(tmp_path, monkeypatch):
    source, output = fixture(tmp_path)
    monkeypatch.setattr(worker, "allowed_path", lambda *_: True)
    with pytest.raises(ValueError, match="forbidden path"):
        worker.execute(source, output)
    monkeypatch.undo()
    monkeypatch.setattr(worker, "allowed_command", lambda *_: True)
    with pytest.raises(ValueError, match="forbidden command"):
        worker.execute(source, output)


def test_verifier_rejects_symlink_output(tmp_path):
    source, output = fixture(tmp_path)
    worker.execute(source, output)
    repaired = output / worker.FILE_NAME
    repaired.unlink()
    try:
        repaired.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="unsafe"):
        verifier.verify(source, output)
