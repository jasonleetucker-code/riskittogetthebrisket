"""The eval bridge consumes persisted Steward evidence and fails on tampering."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from src.steward.receipts import execution_span, run_receipt
from src.steward.store import StewardStore

AGENT_EVALS = Path(__file__).resolve().parents[2] / "agent-evals"
sys.path.insert(0, str(AGENT_EVALS))

from run_eval import main as grade_main  # noqa: E402
from steward_adapter import artifact_from_state  # noqa: E402


def saved_brief(tmp_path: Path) -> tuple[Path, str]:
    head = "a" * 40
    at = datetime.now(timezone.utc).isoformat()
    receipt = run_receipt(
        head=head,
        agent_os="agent-os-hash",
        evidence=[{"kind": "private report", "secret": "PRIVATE-SOURCE-CONTENT"}],
        unresolved=[],
        routes=[],
        started_at=at,
    )
    receipt["execution_spans"] = [
        execution_span(
            receipt,
            phase="plan",
            action="build_brief",
            started_at=at,
            ended_at=at,
            duration_ms=1.0,
            status="DONE",
            evidence_refs=["repository:HEAD"],
        )
    ]
    state = tmp_path / "state.sqlite3"
    with_state = StewardStore(state)
    with_state.append_evidence(
        receipt["run_id"],
        {
            "source": "steward brief",
            "at": at,
            "repo_head": head,
            "content": {
                "receipt": receipt,
                "report": {"head": head, "dirty": False, "private": "PRIVATE-SOURCE-CONTENT"},
            },
            "complete": True,
        },
    )
    with_state.close()
    return state, receipt["run_id"]


def test_persisted_brief_exports_bounded_artifact_and_grades(tmp_path: Path, capsys):
    state, run_id = saved_brief(tmp_path)
    artifact = artifact_from_state(state, run_id)
    assert artifact["case_id"] == "steward-report-only-receipt"
    assert artifact["flags"]["spans_correlated"] is True
    assert "PRIVATE-SOURCE-CONTENT" not in json.dumps(artifact)
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert (
        grade_main(
            [
                "--case",
                artifact["case_id"],
                "--artifact",
                str(path),
                "--steward-state",
                str(state),
                "--require-verified-steward-receipt",
            ]
        )
        == 0
    )
    assert "[VERIFIED_AGAINST_ARTIFACT] steward_receipt_mapping" in capsys.readouterr().out


def test_edited_artifact_fails_source_mapping(tmp_path: Path, capsys):
    state, run_id = saved_brief(tmp_path)
    artifact = artifact_from_state(state, run_id)
    artifact["summary"] += " fabricated success"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    assert (
        grade_main(
            [
                "--case",
                artifact["case_id"],
                "--artifact",
                str(path),
                "--steward-state",
                str(state),
                "--require-verified-steward-receipt",
            ]
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "does not match the persisted Steward receipt" in output
    assert "[NOT_CHECKED] steward_receipt_mapping (artifact_mismatch)" in output
    assert "[VERIFIED_AGAINST_ARTIFACT] steward_receipt_mapping" not in output
