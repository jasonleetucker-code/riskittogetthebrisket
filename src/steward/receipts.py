"""Append-only report-only graph receipts and compact owner briefs.

``config/steward/contracts.schema.json`` is the canonical machine-readable
shape for a completed run's receipt (``runReceipt``, ``schema_version:
"steward-receipt/v1"``). This module is the one place that assembles that
exact shape from real telemetry (:class:`NodeReceipt` rows) -- there is no
second, ad hoc "receipt" concept anywhere else in ``src/steward``.
"""

from __future__ import annotations
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

#: Mirrors ``$defs.runStatus.enum`` in ``config/steward/contracts.schema.json``.
#: Kept in sync by ``tests/steward/test_receipts.py``'s schema-parity test --
#: this is a Python-runtime validation constant, not a second definition of
#: the concept; the JSON schema remains the one machine-readable contract.
RUN_STATUSES = frozenset(
    {
        "QUEUED",
        "RUNNING",
        "DONE",
        "PARTIAL",
        "BLOCKED",
        "FAILED",
        "CANCELLED",
        "HALTED",
        "INCOMPLETE",
    }
)

#: Mirrors ``$defs.executedAction.properties.status.enum``.
EXECUTED_ACTION_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "SKIPPED"})

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class NodeReceipt:
    node_id: str
    status: str
    started_at_ms: int
    ended_at_ms: int
    attempts: int = 1
    tool_calls: int = 0
    retries: int = 0
    failure_class: str | None = None
    verifier_result: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    @property
    def latency_ms(self) -> int:
        return max(0, self.ended_at_ms - self.started_at_ms)


def graph_summary(nodes: Iterable[NodeReceipt]) -> dict[str, object]:
    rows = list(nodes)
    return {
        "node_count": len(rows),
        "total_node_latency_ms": sum(row.latency_ms for row in rows),
        "retry_overhead": sum(row.retries for row in rows),
        "tool_calls": sum(row.tool_calls for row in rows),
        "unknown_cost_nodes": sum(row.cost_usd is None for row in rows),
        "failed_nodes": [row.node_id for row in rows if row.status == "FAILED"],
        "nodes": [asdict(row) | {"latency_ms": row.latency_ms} for row in rows],
    }


def owner_brief(
    *,
    changed: list[str] | None = None,
    broken: list[str] | None = None,
    unresolved: list[str] | None = None,
    owner_input: list[str] | None = None,
) -> dict[str, list[str]]:
    return {
        "changed": changed or [],
        "broken": broken or [],
        "unresolved": unresolved or [],
        "needs_owner_input": owner_input or [],
    }


def build_run_receipt(
    *,
    run_id: str,
    lane: str,
    status: str,
    agent_os_receipt: str,
    repo_head_start: str,
    repo_head_end: str,
    started_at: str,
    ended_at: str,
    nodes: Iterable[NodeReceipt] = (),
    actions: Iterable[Mapping[str, object]] = (),
    unresolved: Iterable[str] = (),
    cost_usd: float | None = None,
) -> dict[str, object]:
    """Assemble a `runReceipt` shaped to `config/steward/contracts.schema.json`.

    This is the reconciliation point between the schema (the pre-existing
    machine-readable contract) and this module's own telemetry primitives:
    `graph_summary(nodes)` becomes ONE entry in the receipt's `evidence`
    array rather than a second, disconnected receipt shape. Raises
    `ValueError` on a status/action-status outside the schema's own enums
    (mirrored here as `RUN_STATUSES`/`EXECUTED_ACTION_STATUSES`, kept in
    sync by a schema-parity test) or a repo SHA that isn't a full
    40-hex-char commit hash -- fail closed on a malformed receipt rather
    than persist one the schema would reject.

    Note what this function does NOT do: nothing in this codebase calls
    `jsonschema.validate(...)` against the schema file at runtime. This is
    hand-written Python parity logic, checked against the schema only by
    the test suite -- a real but weaker guarantee than machine JSON Schema
    validation, and worth knowing before leaning harder on "schema
    conformance" as a safety property.

    `cost_usd` defaults to `None` (genuinely unmeasured), not `0.0` -- a
    real zero and an unmeasured cost are different facts. The schema's
    `cost.usd` was widened to `["number", "null"]` (matching the
    `["boolean", "null"]` / `["string", "null"]` idiom it already uses
    elsewhere for "not yet measured") specifically so this module never
    has to coerce an unmeasured cost into a lying zero.
    """
    if status not in RUN_STATUSES:
        raise ValueError(
            f"unsupported run status: {status!r} (schema enum: {sorted(RUN_STATUSES)})"
        )
    for sha_name, sha_value in (
        ("repo_head_start", repo_head_start),
        ("repo_head_end", repo_head_end),
    ):
        if not _SHA_PATTERN.match(sha_value):
            raise ValueError(
                f"{sha_name} must be a full 40-character hex commit SHA, got {sha_value!r}"
            )
    action_rows = list(actions)
    for action in action_rows:
        action_status = action.get("status")
        if action_status not in EXECUTED_ACTION_STATUSES:
            raise ValueError(
                f"unsupported executed-action status: {action_status!r} "
                f"(schema enum: {sorted(EXECUTED_ACTION_STATUSES)})"
            )
    return {
        "schema_version": "steward-receipt/v1",
        "run_id": run_id,
        "lane": lane,
        "status": status,
        "agent_os_receipt": agent_os_receipt,
        "repo_head_start": repo_head_start,
        "repo_head_end": repo_head_end,
        "started_at": started_at,
        "ended_at": ended_at,
        "evidence": [graph_summary(nodes)],
        "unresolved": list(unresolved),
        "actions": action_rows,
        "cost": {"usd": cost_usd},
    }
