import json
import subprocess
import sys
from pathlib import Path

from src.steward.store import StewardStore
from src.steward.receipts import run_receipt

ROOT = Path(__file__).resolve().parents[2]


def test_fresh_process_recovers_provenance_and_partial_state(tmp_path):
    path = tmp_path / "state.db"
    first = StewardStore(path)
    first.append_evidence(
        "raw-A",
        {
            "source": "session-A",
            "at": "2026-09-10T00:00:00Z",
            "repo_head": "a" * 40,
            "content": "test next",
            "complete": True,
        },
    )
    first.remember(
        {
            "id": "decision-A",
            "topic": "campaign",
            "layer": "working",
            "summary": "verify acceptance next",
            "authority": "observation",
            "evidence_ids": ["raw-A"],
            "repo_head": "a" * 40,
            "at": "2026-09-10T00:00:00Z",
        },
        expected_revision=0,
    )
    first.write(
        "campaign",
        {
            "objective": "test continuity",
            "partial": ["P1"],
            "completed": ["route tests"],
            "origin_main": "a" * 40,
        },
        expected_revision=0,
    )
    first.close()
    output = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "src.steward",
            "--repo",
            str(ROOT),
            "--state",
            str(path),
            "retrieve",
            "campaign",
        ],
        text=True,
        encoding="utf-8",
    )
    recovered = json.loads(output)
    assert recovered["records"][0]["evidence_ids"] == ["raw-A"]
    assert recovered["revision_mismatches"] == ["decision-A"]
    assert len(recovered["current_head"]) == 40
    fresh = StewardStore(path)
    assert fresh.read("campaign")[1]["partial"] == ["P1"]
    assert fresh.raw_evidence("raw-A")["content"] == "test next"
    fresh.close()


def test_run_receipt_matches_canonical_shape_and_unknown_cost():
    schema = json.loads((ROOT / "config/steward/contracts.schema.json").read_text())
    receipt = run_receipt(
        head="a" * 40,
        agent_os="b" * 40,
        evidence=[{"check": "unit"}],
        unresolved=["production unknown"],
        routes=[],
        started_at="2026-09-10T00:00:00Z",
    )
    definition = schema["$defs"]["runReceipt"]
    assert set(definition["required"]) <= receipt.keys()
    assert receipt.keys() <= definition["properties"].keys()
    assert receipt["status"] == "PARTIAL"
    assert receipt["cost"]["usd"] is None
    assert "null" in definition["properties"]["cost"]["properties"]["usd"]["type"]
