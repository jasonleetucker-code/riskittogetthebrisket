from pathlib import Path
import pytest
from src.steward.repository import inventory, phase_tasks, launch_state, context, github_disposition

ROOT = Path(__file__).resolve().parents[2]


def test_real_repo_inventory_retains_manifest_and_phase_provenance():
    result = inventory(ROOT)
    assert result["manifest_rows"] == 163
    assert result["launch"]["total"] == 30
    phases = phase_tasks(ROOT, result)
    assert len(phases) == 10
    assert {"W1-27", "W1-28", "W1-30"} <= set(phases[0]["todo_ids"])
    assert all(row["source_rows"] and row["acceptance"] for row in phases)
    assert all(r["verification"] == "SOURCE_CLAIM" for r in result["observations"])


def test_launch_denominator_is_literal():
    rows = "\n".join(f"| W1-{i:02} | area | acceptance | VERIFIED |" for i in range(1, 31))
    assert launch_state(rows)["complete"]
    assert not launch_state(
        rows.replace(
            "W1-30 | area | acceptance | VERIFIED",
            "W1-30 | area | acceptance | IMPLEMENTED_UNVERIFIED",
        )
    )["complete"]
    with pytest.raises(ValueError):
        launch_state(rows.replace("W1-30", "W1-31"))


def test_context_budget_and_path_boundary():
    selected = context(ROOT, ["AI_INSTRUCTIONS.md"], max_chars=100)
    assert selected["characters"] == 100
    assert not selected["sources"][0]["complete"]
    with pytest.raises(ValueError):
        context(ROOT, ["../private.txt"])
    assert (
        github_disposition({"state": "closed", "merged_at": None})
        == "PARTIALLY_REUSABLE_REQUIRES_INSPECTION"
    )


def test_all_manifest_work_is_accounted_for_and_real_dependencies_survive():
    from src.steward.repository import reconcile, work_units

    inv = inventory(ROOT)
    tasks = phase_tasks(ROOT, inv)
    reconciliation = reconcile(ROOT, inv, tasks, None)
    units = {row["id"]: row for row in work_units(tasks, inv, reconciliation)}
    excluded = {
        row["id"] for row in reconciliation["manifest"] if row["phase"] in {"BASELINE", "EXCLUDED"}
    }
    assert set(inv["manifest_ids"]) <= units.keys() | excluded
    assert units["W1-28"]["dependencies"] == ["W1-27"]
    assert units["W1-30"]["dependencies"] == ["W1-27", "W1-28"]
    assert "#792" in units["#1173"]["dependencies"]
    assert units["W1-27"]["acceptance"] == [inv["launch"]["rows"]["W1-27"]["acceptance"]]
    closure = [row for key, row in units.items() if key.startswith("C10-")]
    phase_ids = {task["id"] for task in tasks}
    assert closure and all(phase_ids <= set(row["dependencies"]) for row in closure)


def test_final_closure_unlocks_only_after_evidence_validated_phase_contracts():
    from src.steward.repository import reconcile, work_units
    from src.steward.planner import plan, satisfy

    inv = inventory(ROOT)
    tasks = phase_tasks(ROOT, inv)
    units = work_units(tasks, inv, reconcile(ROOT, inv, tasks, None))
    closure = [row for row in units if row["id"].startswith("C10-")]
    before = plan(tasks + closure)
    assert all(
        row["execution"] == "BLOCKED"
        for row in before["phases"]
        if any(key.startswith("C10-") for key in row["tasks"])
    )
    # Synthetic complete evidence exercises the transition, not actual site readiness.
    candidate = [task | {"expected_head": "a" * 40, "candidate_clean": True} for task in tasks]
    evidence = {
        task["id"]: {
            "result": "PASS",
            "head": "a" * 40,
            "criteria": task["acceptance"],
            "references": ["fixture:phase-acceptance"],
            "production_identity": "fixture:deployment",
        }
        for task in candidate
    }
    after = plan(satisfy(candidate, evidence) + closure)
    assert not after["missing_dependencies"]
    assert all(row["execution"] == "READY_FOR_AUTHORITY_CHECK" for row in after["phases"])
