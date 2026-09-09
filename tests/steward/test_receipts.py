import json
from pathlib import Path

import pytest

from src.steward.receipts import (
    EXECUTED_ACTION_STATUSES,
    RUN_STATUSES,
    NodeReceipt,
    build_run_receipt,
    graph_summary,
    owner_brief,
)

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "config" / "steward" / "contracts.schema.json"
_SHA_A = "a" * 40
_SHA_B = "b" * 40


def test_graph_summary_preserves_unknown_cost():
    summary = graph_summary([NodeReceipt("n", "DONE", 20, 10)])
    assert summary["total_node_latency_ms"] == 0
    assert summary["unknown_cost_nodes"] == 1


def test_owner_brief_is_compact_and_separates_owner_input():
    assert owner_brief(changed=["x"], owner_input=["approve"])["needs_owner_input"] == ["approve"]


def test_run_status_and_executed_action_status_match_the_canonical_schema():
    # The Python enums are a runtime-validation copy of the JSON schema's
    # own enums -- this proves the two never silently drift apart, rather
    # than trusting a docstring's claim that they're kept in sync.
    schema = json.loads(_SCHEMA_PATH.read_text())
    assert set(schema["$defs"]["runStatus"]["enum"]) == RUN_STATUSES
    assert (
        set(schema["$defs"]["executedAction"]["properties"]["status"]["enum"])
        == EXECUTED_ACTION_STATUSES
    )


def test_build_run_receipt_matches_the_schemas_required_shape():
    receipt = build_run_receipt(
        run_id="run-1",
        lane="repo_reliability",
        status="DONE",
        agent_os_receipt="abc123",
        repo_head_start=_SHA_A,
        repo_head_end=_SHA_B,
        started_at="2026-09-09T00:00:00Z",
        ended_at="2026-09-09T00:05:00Z",
        nodes=[NodeReceipt("n1", "DONE", 0, 1000, cost_usd=0.01)],
        actions=[
            {"action_id": "a1", "kind": "comment", "idempotency_key": "k1", "status": "SUCCEEDED"}
        ],
        unresolved=["nothing outstanding"],
        cost_usd=0.01,
    )
    schema = json.loads(_SCHEMA_PATH.read_text())["$defs"]["runReceipt"]
    assert set(schema["required"]).issubset(receipt.keys())
    assert set(receipt.keys()).issubset(schema["properties"].keys())
    assert receipt["schema_version"] == "steward-receipt/v1"
    assert receipt["evidence"] == [
        graph_summary([NodeReceipt("n1", "DONE", 0, 1000, cost_usd=0.01)])
    ]


def test_build_run_receipt_rejects_a_status_outside_the_schema_enum():
    with pytest.raises(ValueError, match="unsupported run status"):
        build_run_receipt(
            run_id="run-1",
            lane="repo_reliability",
            status="NOT_A_REAL_STATUS",
            agent_os_receipt="abc",
            repo_head_start=_SHA_A,
            repo_head_end=_SHA_B,
            started_at="2026-09-09T00:00:00Z",
            ended_at="2026-09-09T00:05:00Z",
        )


def test_build_run_receipt_rejects_a_malformed_sha():
    with pytest.raises(ValueError, match="40-character hex"):
        build_run_receipt(
            run_id="run-1",
            lane="repo_reliability",
            status="DONE",
            agent_os_receipt="abc",
            repo_head_start="not-a-sha",
            repo_head_end=_SHA_B,
            started_at="2026-09-09T00:00:00Z",
            ended_at="2026-09-09T00:05:00Z",
        )


def test_build_run_receipt_rejects_an_action_status_outside_the_schema_enum():
    with pytest.raises(ValueError, match="unsupported executed-action status"):
        build_run_receipt(
            run_id="run-1",
            lane="repo_reliability",
            status="DONE",
            agent_os_receipt="abc",
            repo_head_start=_SHA_A,
            repo_head_end=_SHA_B,
            started_at="2026-09-09T00:00:00Z",
            ended_at="2026-09-09T00:05:00Z",
            actions=[
                {"action_id": "a1", "kind": "comment", "idempotency_key": "k1", "status": "MAYBE"}
            ],
        )
