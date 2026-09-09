"""Append-only report-only graph receipts and compact owner briefs."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Iterable

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

def owner_brief(*, changed: list[str] | None = None, broken: list[str] | None = None, unresolved: list[str] | None = None, owner_input: list[str] | None = None) -> dict[str, list[str]]:
    return {"changed": changed or [], "broken": broken or [], "unresolved": unresolved or [], "needs_owner_input": owner_input or []}
