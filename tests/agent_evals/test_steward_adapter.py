"""The eval bridge consumes persisted Steward evidence and fails on tampering."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

from src.steward.receipts import execution_span, run_receipt
from src.steward.store import StewardStore

AGENT_EVALS = Path(__file__).resolve().parents[2] / "agent-evals"
sys.path.insert(0, str(AGENT_EVALS))

from run_eval import main as grade_main  # noqa: E402
from steward_adapter import artifact_from_state  # noqa: E402


def saved_brief(
    tmp_path: Path, *, span_change: tuple[str, object] | None = None
) -> tuple[Path, str]:
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
    if span_change is not None:
        key, value = span_change
        receipt["execution_spans"][0][key] = value
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
    assert all(artifact["flags"].values())
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


@pytest.mark.parametrize(
    ("span_change", "failed_flag"),
    [
        (("phase", "write"), "no_write_or_handoff_spans"),
        (("status", "FAILED"), "plan_completed"),
        (("evidence_refs", []), "spans_have_evidence_refs"),
        (("repo_head_start", "b" * 40), "span_heads_match_receipt"),
    ],
)
def test_persisted_trace_behavior_fails_on_real_span_field(
    tmp_path: Path, capsys, span_change: tuple[str, object], failed_flag: str
):
    state, run_id = saved_brief(tmp_path, span_change=span_change)
    artifact = artifact_from_state(state, run_id)
    assert artifact["flags"][failed_flag] is False
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
        == 1
    )
    assert failed_flag in capsys.readouterr().out
