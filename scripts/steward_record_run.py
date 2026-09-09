#!/usr/bin/env python3
"""Append one completed run's evidence to the report-only Steward store.

This is the one real integration point between `src/steward`'s pure
receipt/evidence primitives and durable storage. It does no network I/O of
its own and calls no model or GitHub API: the caller (a human, a CI step,
or a future Steward runner) supplies the run's facts as a JSON file, and
this script assembles a receipt shaped to
`config/steward/contracts.schema.json` (`steward-receipt/v1` --
`receipts.build_run_receipt` mirrors the schema's enums/patterns in
hand-written Python, checked against it only by tests; nothing here runs
`jsonschema.validate` at runtime) and appends it to the local SQLite
store. Nothing here proposes a promotion or grants authority -- see
`src/steward/evidence.py` for the eligibility computation, which stays a
separate, later step.

Input JSON shape (one run):
{
  "run_id": "pr-1297",
  "lane": "repo_reliability",
  "status": "DONE",
  "agent_os_receipt": "<blob sha>",
  "repo_head_start": "<40-hex sha>",
  "repo_head_end": "<40-hex sha>",
  "started_at": "2026-09-09T10:00:00Z",
  "ended_at": "2026-09-09T13:51:00Z",
  "nodes": [{"node_id": "...", "status": "DONE", "started_at_ms": 0, "ended_at_ms": 1000}, ...],
  "actions": [{"action_id": "...", "kind": "merge_pr", "idempotency_key": "...", "status": "SUCCEEDED"}],
  "unresolved": ["..."],
  "cost_usd": null
}

`cost_usd` and per-node cost/token fields may be `null` when genuinely not
measured -- this script does not coerce a missing figure to zero.

Exit codes:
  0  every run in the input recorded successfully
  1  the input file could not be read or parsed
  2  a run failed schema-conformance validation (see build_run_receipt)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.steward.receipts import NodeReceipt, build_run_receipt  # noqa: E402
from src.steward.store import StewardStore  # noqa: E402


def _node_receipt(row: dict[str, Any]) -> NodeReceipt:
    return NodeReceipt(
        node_id=row["node_id"],
        status=row["status"],
        started_at_ms=row["started_at_ms"],
        ended_at_ms=row["ended_at_ms"],
        attempts=row.get("attempts", 1),
        tool_calls=row.get("tool_calls", 0),
        retries=row.get("retries", 0),
        failure_class=row.get("failure_class"),
        verifier_result=row.get("verifier_result"),
        input_tokens=row.get("input_tokens"),
        output_tokens=row.get("output_tokens"),
        cost_usd=row.get("cost_usd"),
    )


def _record_one(store: StewardStore, run: dict[str, Any]) -> None:
    receipt = build_run_receipt(
        run_id=run["run_id"],
        lane=run["lane"],
        status=run["status"],
        agent_os_receipt=run["agent_os_receipt"],
        repo_head_start=run["repo_head_start"],
        repo_head_end=run["repo_head_end"],
        started_at=run["started_at"],
        ended_at=run["ended_at"],
        nodes=[_node_receipt(row) for row in run.get("nodes", [])],
        actions=run.get("actions", []),
        unresolved=run.get("unresolved", []),
        cost_usd=run.get("cost_usd"),
    )
    store.append_receipt(run["run_id"], receipt, run["ended_at"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "runs_json", type=Path, help="JSON file: one run object, or a JSON array of run objects"
    )
    ap.add_argument("--store", type=Path, required=True, help="path to the SQLite steward store")
    args = ap.parse_args(argv)

    try:
        raw = json.loads(args.runs_json.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read/parse {args.runs_json}: {exc}", file=sys.stderr)
        return 1

    runs = raw if isinstance(raw, list) else [raw]
    args.store.parent.mkdir(parents=True, exist_ok=True)
    store = StewardStore(args.store)
    for run in runs:
        try:
            _record_one(store, run)
        except (KeyError, ValueError) as exc:
            print(
                f"run {run.get('run_id', '<unknown>')!r} failed validation: {exc}", file=sys.stderr
            )
            return 2
        print(f"recorded {run['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
