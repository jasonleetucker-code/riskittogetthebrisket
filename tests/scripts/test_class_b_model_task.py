"""Independent boundary checks for the one model-backed branch task."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import class_b_model_task as worker
from scripts import class_b_model_verify as verifier

ROOT = Path(__file__).resolve().parents[2]


def _inputs(tmp_path: Path, monkeypatch):
    source = tmp_path / worker.SOURCE_NAME
    source.write_bytes(
        (ROOT / "docs/engineering/CLASS_B_ISOLATION.md").read_bytes().replace(b"\r\n", b"\n")
    )
    evidence = tmp_path / worker.EVIDENCE_NAME
    evidence.write_bytes(
        (ROOT / "docs/engineering/CLASS_B_BRANCH_PILOT.md").read_bytes().replace(b"\r\n", b"\n")
    )
    model = tmp_path / "model.gguf"
    model.write_bytes(b"fixed model fixture")
    runtime = tmp_path / "llama-completion"
    runtime.write_bytes(b"fixed runtime fixture")
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(worker, "MODEL_SHA256", worker.file_digest(model))
    monkeypatch.setattr(worker, "RUNTIME_SHA256", worker.file_digest(runtime))
    monkeypatch.setattr(verifier, "MODEL_SHA256", worker.MODEL_SHA256)
    monkeypatch.setattr(verifier, "RUNTIME_SHA256", worker.RUNTIME_SHA256)
    return source, evidence, model, runtime, output


def test_model_decision_writes_only_exact_authorized_document(tmp_path, monkeypatch):
    source, evidence, model, runtime, output = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="COMPLETE\n", returncode=0),
    )
    worker.run(
        source=source,
        evidence=evidence,
        model=model,
        llama_cli=runtime,
        output_dir=output,
        probe_network=False,
    )
    result = verifier.verify(source, evidence, output, require_network=False)
    assert result["verified"]
    assert {path.name for path in output.iterdir()} == {
        "candidate.md",
        "receipt.json",
        "model-output.txt",
    }
    assert source.read_bytes() != (output / "candidate.md").read_bytes()
    (output / "candidate.md").write_text("forged", encoding="utf-8")
    with pytest.raises(ValueError, match="exceeds the exact"):
        verifier.verify(source, evidence, output, require_network=False)


def test_unapproved_model_decision_cannot_write_candidate(tmp_path, monkeypatch):
    source, evidence, model, runtime, output = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="PENDING\n", returncode=0),
    )
    with pytest.raises(ValueError, match="one authorized decision"):
        worker.run(
            source=source,
            evidence=evidence,
            model=model,
            llama_cli=runtime,
            output_dir=output,
            probe_network=False,
        )
    assert not (output / "candidate.md").exists()


def test_sabotaged_path_and_command_policies_fail_closed(tmp_path, monkeypatch):
    source, evidence, model, runtime, output = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(worker, "allowed_path", lambda *_args: True)
    with pytest.raises(ValueError, match="forbidden path"):
        worker.run(
            source=source,
            evidence=evidence,
            model=model,
            llama_cli=runtime,
            output_dir=output,
            probe_network=False,
        )
    monkeypatch.setattr(worker, "allowed_path", lambda *_args: False)
    monkeypatch.setattr(worker, "allowed_command", lambda *_args: True)
    with pytest.raises(ValueError, match="forbidden command"):
        worker.run(
            source=source,
            evidence=evidence,
            model=model,
            llama_cli=runtime,
            output_dir=output,
            probe_network=False,
        )


def test_missing_refusal_or_unsupported_output_fails_verifier(tmp_path, monkeypatch):
    source, evidence, model, runtime, output = _inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="COMPLETE\n", returncode=0),
    )
    worker.run(
        source=source,
        evidence=evidence,
        model=model,
        llama_cli=runtime,
        output_dir=output,
        probe_network=False,
    )
    receipt_path = output / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["refusals"].remove("command_denied")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="refusal"):
        verifier.verify(source, evidence, output, require_network=False)
    receipt["refusals"].append("command_denied")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    (output / "extra").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="file set"):
        verifier.verify(source, evidence, output, require_network=False)
