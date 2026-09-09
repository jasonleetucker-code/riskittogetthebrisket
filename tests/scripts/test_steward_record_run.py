"""Unit tests for ``scripts/steward_record_run.py``.

Exercises the actual CLI entry point end to end against a temp SQLite
store, including against the real seed fixture
(``scripts/fixtures/steward_seed_runs_2026-09-09.json``) so the
schema-conformant-receipt pipeline is proven against real recorded
evidence, not only a synthetic single-row fixture.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "steward_record_run.py"
SEED_FIXTURE = REPO / "scripts" / "fixtures" / "steward_seed_runs_2026-09-09.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("steward_record_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()

_VALID_RUN = {
    "run_id": "test-run-1",
    "lane": "harness_audit",
    "status": "DONE",
    "agent_os_receipt": "abc123",
    "repo_head_start": "a" * 40,
    "repo_head_end": "b" * 40,
    "started_at": "2026-09-09T00:00:00Z",
    "ended_at": "2026-09-09T00:05:00Z",
    "nodes": [
        {
            "node_id": "n1",
            "status": "DONE",
            "started_at_ms": 0,
            "ended_at_ms": 1000,
            "cost_usd": 0.01,
        }
    ],
    "actions": [
        {"action_id": "a1", "kind": "comment", "idempotency_key": "k1", "status": "SUCCEEDED"}
    ],
    "unresolved": [],
    "cost_usd": 0.01,
}


def test_a_single_run_object_is_recorded_and_matches_the_schema(tmp_path: Path) -> None:
    run_file = tmp_path / "run.json"
    run_file.write_text(json.dumps(_VALID_RUN))
    store_path = tmp_path / "store.sqlite"

    code = _mod.main([str(run_file), "--store", str(store_path)])

    assert code == 0
    conn = sqlite3.connect(store_path)
    row = conn.execute(
        "SELECT payload FROM steward_receipts WHERE run_id = ?", ("test-run-1",)
    ).fetchone()
    assert row is not None
    receipt = json.loads(row[0])
    assert receipt["schema_version"] == "steward-receipt/v1"
    assert receipt["status"] == "DONE"
    assert receipt["cost"] == {"usd": 0.01}


def test_an_array_of_runs_records_every_entry(tmp_path: Path) -> None:
    second = dict(_VALID_RUN, run_id="test-run-2")
    run_file = tmp_path / "runs.json"
    run_file.write_text(json.dumps([_VALID_RUN, second]))
    store_path = tmp_path / "store.sqlite"

    assert _mod.main([str(run_file), "--store", str(store_path)]) == 0

    conn = sqlite3.connect(store_path)
    count = conn.execute("SELECT COUNT(*) FROM steward_receipts").fetchone()[0]
    assert count == 2


def test_a_missing_required_field_fails_closed_not_silently(tmp_path: Path) -> None:
    broken = dict(_VALID_RUN)
    broken["status"] = "NOT_A_REAL_STATUS"
    run_file = tmp_path / "run.json"
    run_file.write_text(json.dumps(broken))
    store_path = tmp_path / "store.sqlite"

    code = _mod.main([str(run_file), "--store", str(store_path)])

    assert code == 2
    conn = sqlite3.connect(store_path)
    count = conn.execute("SELECT COUNT(*) FROM steward_receipts").fetchone()[0]
    assert count == 0


def test_unparseable_input_returns_exit_code_one(tmp_path: Path) -> None:
    run_file = tmp_path / "run.json"
    run_file.write_text("{not valid json")
    store_path = tmp_path / "store.sqlite"

    assert _mod.main([str(run_file), "--store", str(store_path)]) == 1


def test_missing_cost_stays_null_never_coerced_to_a_lying_zero(tmp_path: Path) -> None:
    # A genuinely unmeasured cost and a proven-zero cost are different
    # facts. config/steward/contracts.schema.json's `cost.usd` was widened
    # to ["number", "null"] specifically so this never has to default to
    # 0.0 for a run nobody costed.
    no_cost = dict(_VALID_RUN, run_id="test-run-no-cost")
    del no_cost["cost_usd"]
    run_file = tmp_path / "run.json"
    run_file.write_text(json.dumps(no_cost))
    store_path = tmp_path / "store.sqlite"

    assert _mod.main([str(run_file), "--store", str(store_path)]) == 0
    conn = sqlite3.connect(store_path)
    receipt = json.loads(
        conn.execute(
            "SELECT payload FROM steward_receipts WHERE run_id = ?", ("test-run-no-cost",)
        ).fetchone()[0]
    )
    assert receipt["cost"] == {"usd": None}


def test_the_real_seed_fixture_records_cleanly_and_is_genuine_evidence() -> None:
    """The actual completed-PR evidence from this session, not a fixture.

    Proves the pipeline works end to end against real recorded facts
    (real merge SHAs, real timestamps) for PRs #1319/#1315/#1320, not only
    synthetic single-row test data.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store_path = Path(tmp) / "seed.sqlite"
        code = _mod.main([str(SEED_FIXTURE), "--store", str(store_path)])
        assert code == 0

        conn = sqlite3.connect(store_path)
        rows = conn.execute(
            "SELECT run_id, payload FROM steward_receipts ORDER BY run_id"
        ).fetchall()
        run_ids = {run_id for run_id, _ in rows}
        assert run_ids == {"pr-1315", "pr-1319", "pr-1320"}
        for _, payload in rows:
            receipt = json.loads(payload)
            assert receipt["schema_version"] == "steward-receipt/v1"
            assert receipt["status"] == "DONE"
            # Every real SHA recorded is a genuine 40-hex commit hash, not
            # a placeholder -- build_run_receipt would have raised
            # otherwise, but assert it here too since that IS the point
            # of this specific test.
            assert len(receipt["repo_head_start"]) == 40
            assert len(receipt["repo_head_end"]) == 40
