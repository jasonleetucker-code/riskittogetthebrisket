from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from threading import Event

import pytest

from src.steward.controller import (
    ContractError,
    Phase1Controller,
    mechanically_count_week1,
    validate_run_contract,
)
from src.steward.store import ConflictError


SCHEMA = Path("config/steward/contracts.schema.json")


def contract(run_id: str = "phase1-test") -> dict:
    return {
        "schema_version": "steward-run/v1",
        "run_id": run_id,
        "lane": "steward_metrics",
        "mode": "report_only",
        "autonomy_class": "A_REPORT_ONLY",
        "goal": "Produce a deterministic report-only Steward observation.",
        "allowed_actions": ["observe", "report"],
        "denied_actions": [
            "repo_write",
            "product_write",
            "production_write",
            "paid_api",
        ],
        "budget": {
            "wall_clock_seconds": 60,
            "max_actions": 1,
            "max_tool_calls": 0,
            "max_retries": 0,
            "max_parallel": 1,
            "max_usd": 0,
        },
        "halt_sentinel": ".agent-runtime/steward/HALT",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "config" / "steward").mkdir(parents=True)
    (repo / "docs" / "season-launch").mkdir(parents=True)
    (repo / "config" / "steward" / "contracts.schema.json").write_text(
        SCHEMA.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rows = "\n".join(
        f"| W1-{number:02d} | Test | Acceptance {number} | VERIFIED |" for number in range(1, 31)
    )
    (repo / "docs" / "season-launch" / "WEEK_1_LAUNCH_CONTRACT.md").write_text(
        rows + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "steward@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Steward Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "fixture"],
        check=True,
    )
    return repo


def test_canonical_week1_is_literal_30_of_30():
    launch = Path("docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md")
    assert mechanically_count_week1(launch) == (30, 30)


def test_contract_validation_rejects_paid_phase1_budget():
    run = contract()
    run["budget"]["max_usd"] = -1
    with pytest.raises(ContractError, match="below its minimum"):
        validate_run_contract(run, SCHEMA)


def test_contract_validation_rejects_class_a_non_report_mode():
    run = contract()
    run["mode"] = "autonomous"
    with pytest.raises(ContractError, match="Class A must use report_only"):
        validate_run_contract(run, SCHEMA)


def test_controller_records_done_receipt_and_zero_cost(tmp_path: Path):
    repo = init_repo(tmp_path)
    runtime = tmp_path / "private-runtime"
    with Phase1Controller(repo, runtime) as controller:
        result = controller.run(contract("done-run"))

    assert result.status == "DONE"
    assert result.receipt["cost"] == {"usd": 0.0}
    assert result.receipt["mutation"] == {
        "repository": False,
        "product": False,
        "production": False,
    }
    assert result.receipt["preflight"]["week1"] == {
        "rows": 30,
        "verified": 30,
    }
    receipt_files = list((runtime / "receipts").glob("*.jsonl"))
    assert len(receipt_files) == 1
    lines = receipt_files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == "done-run"
    assert (runtime / "state.sqlite3").exists()


def test_halt_is_fail_closed_and_receipted(tmp_path: Path):
    repo = init_repo(tmp_path)
    runtime = repo / ".agent-runtime" / "steward"
    runtime.mkdir(parents=True)
    (runtime / "HALT").write_text("operator halt\n", encoding="utf-8")

    with Phase1Controller(repo) as controller:
        result = controller.run(contract("halted-run"))

    assert result.status == "HALTED"
    assert result.receipt["preflight"] == {}
    assert result.receipt["actions"] == []
    assert result.receipt["blockers"] == ["HALT sentinel present before run"]


def test_idempotency_returns_original_without_second_receipt(tmp_path: Path):
    repo = init_repo(tmp_path)
    runtime = tmp_path / "private-runtime"
    with Phase1Controller(repo, runtime) as controller:
        first = controller.run(contract("same-run"))
        second = controller.run(contract("same-run"))

    assert first.status == "DONE"
    assert second.status == "DUPLICATE"
    assert second.duplicate is True
    assert second.receipt == first.receipt
    receipt_file = next((runtime / "receipts").glob("*.jsonl"))
    assert len(receipt_file.read_text(encoding="utf-8").splitlines()) == 1


def test_duplicate_repairs_mirror_after_append_failure(tmp_path: Path, monkeypatch):
    repo = init_repo(tmp_path)
    runtime = tmp_path / "private-runtime"
    with Phase1Controller(repo, runtime) as controller:
        append = controller._append_receipt

        def fail_once(_receipt):
            raise OSError("simulated JSONL sink failure")

        monkeypatch.setattr(controller, "_append_receipt", fail_once)
        with pytest.raises(OSError, match="simulated JSONL sink failure"):
            controller.run(contract("repair-run"))
        assert controller.store.read("phase1-run:repair-run")[1] is not None

        monkeypatch.setattr(controller, "_append_receipt", append)
        retried = controller.run(contract("repair-run"))
        assert retried.status == "DUPLICATE"
        assert retried.duplicate is True

    receipt_file = next((runtime / "receipts").glob("*.jsonl"))
    lines = receipt_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == retried.receipt


def test_duplicate_refuses_conflicting_mirror(tmp_path: Path):
    repo = init_repo(tmp_path)
    runtime = tmp_path / "private-runtime"
    with Phase1Controller(repo, runtime) as controller:
        original = controller.run(contract("conflict-run"))
        receipt_file = next((runtime / "receipts").glob("*.jsonl"))
        altered = original.receipt | {"status": "FAILED"}
        receipt_file.write_text(json.dumps(altered) + "\n", encoding="utf-8")
        with pytest.raises(ConflictError, match="mirror conflicts"):
            controller.run(contract("conflict-run"))
        assert controller.store.read("phase1-run:conflict-run")[1] == original.receipt


def test_duplicate_refuses_truncated_mirror(tmp_path: Path):
    repo = init_repo(tmp_path)
    runtime = tmp_path / "private-runtime"
    with Phase1Controller(repo, runtime) as controller:
        controller.run(contract("truncated-run"))
        receipt_file = next((runtime / "receipts").glob("*.jsonl"))
        receipt_file.write_bytes(b'{"run_id":"truncated-run"')
        with pytest.raises(ConflictError, match="incomplete"):
            controller.run(contract("truncated-run"))


def test_mirror_check_and_append_are_serialized_across_controllers(tmp_path: Path):
    repo = init_repo(tmp_path)
    runtime = tmp_path / "private-runtime"
    ready_first, ready_second = Event(), Event()
    start_first, start_second = Event(), Event()
    first_in_append, release_first, second_entered, second_checked = (
        Event(),
        Event(),
        Event(),
        Event(),
    )

    def first():
        with Phase1Controller(repo, runtime) as controller:
            append = controller._append_receipt

            def paused_append(receipt):
                first_in_append.set()
                assert release_first.wait(5)
                append(receipt)

            controller._append_receipt = paused_append
            ready_first.set()
            assert start_first.wait(5)
            return controller.run(contract("race-run"))

    def second():
        with Phase1Controller(repo, runtime) as controller:
            check = controller._mirror_has_receipt

            def observed_check(receipt):
                second_checked.set()
                return check(receipt)

            controller._mirror_has_receipt = observed_check
            ready_second.set()
            assert start_second.wait(5)
            second_entered.set()
            return controller.run(contract("race-run"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(first)
        second_result = pool.submit(second)
        assert ready_first.wait(5) and ready_second.wait(5)
        start_first.set()
        assert first_in_append.wait(5)
        start_second.set()
        assert second_entered.wait(5)
        try:
            assert not second_checked.wait(0.3)
        finally:
            release_first.set()
        assert first_result.result(timeout=5).status == "DONE"
        assert second_result.result(timeout=5).status == "DUPLICATE"
        assert second_checked.is_set()

    receipt_file = next((runtime / "receipts").glob("*.jsonl"))
    assert len(receipt_file.read_text(encoding="utf-8").splitlines()) == 1


def test_oversized_receipt_is_rejected_before_sqlite_commit(tmp_path: Path):
    repo = init_repo(tmp_path)
    with Phase1Controller(repo, tmp_path / "private-runtime") as controller:
        huge_id = "x" * 1_000_000
        with pytest.raises(ContractError, match="mirror line limit"):
            controller.run(contract(huge_id))
        assert controller.store.read("phase1-run:" + huge_id)[1] is None
        assert not list(controller.receipt_dir.glob("*.jsonl"))


def test_short_os_writes_still_complete_one_jsonl_row(tmp_path: Path, monkeypatch):
    repo = init_repo(tmp_path)
    real_write = os.write
    monkeypatch.setattr(os, "write", lambda fd, data: real_write(fd, data[:7]))
    runtime = tmp_path / "private-runtime"
    with Phase1Controller(repo, runtime) as controller:
        result = controller.run(contract("short-write-run"))
    receipt_file = next((runtime / "receipts").glob("*.jsonl"))
    assert json.loads(receipt_file.read_text(encoding="utf-8")) == result.receipt


def test_incomplete_week1_blocks_and_is_receipted(tmp_path: Path):
    repo = init_repo(tmp_path)
    launch = repo / "docs" / "season-launch" / "WEEK_1_LAUNCH_CONTRACT.md"
    current = launch.read_text(encoding="utf-8")
    launch.write_text(
        current.replace("| VERIFIED |", "| NOT STARTED |", 1),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qm", "incomplete gate"],
        check=True,
    )

    with Phase1Controller(repo, tmp_path / "runtime") as controller:
        result = controller.run(contract("blocked-run"))

    assert result.status == "BLOCKED"
    assert result.receipt["actions"] == []
    assert "29/30 VERIFIED" in result.receipt["blockers"][0]


def test_dirty_repository_blocks_before_report(tmp_path: Path):
    repo = init_repo(tmp_path)
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with Phase1Controller(repo, tmp_path / "runtime") as controller:
        result = controller.run(contract("dirty-run"))

    assert result.status == "BLOCKED"
    assert result.receipt["actions"] == []
    assert "clean repository" in result.receipt["blockers"][0]


def test_phase1_rejects_positive_budget_even_when_schema_allows_it(tmp_path: Path):
    repo = init_repo(tmp_path)
    run = contract("paid-run")
    run["budget"]["max_usd"] = 0.01

    with Phase1Controller(repo, tmp_path / "runtime") as controller:
        result = controller.run(run)

    assert result.status == "BLOCKED"
    assert result.receipt["actions"] == []
    assert "max_usd must remain exactly 0" in result.receipt["blockers"][0]
