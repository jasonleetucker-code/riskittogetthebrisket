import pytest
from src.steward.planner import plan, satisfy, compatible


def task(key, **extra):
    return {
        "id": key,
        "expected_head": "a" * 40,
        "candidate_clean": True,
        "title": key,
        "state": "PLANNED",
        "dependencies": [],
        "touches": ["src/shared"],
        "rollback_group": "shared",
        "authority": "owner",
        "acceptance": ["test contract"],
        "risk": "low",
        **extra,
    }


def test_dependencies_shared_touches_and_negative_combination():
    result = plan(
        [
            task("foundation"),
            task("consumer", dependencies=["foundation"]),
            task("sibling"),
            task("risk", risk="high"),
            task("other", rollback_group="other"),
        ]
    )
    assert set(result["phases"][0]["tasks"]) == {"foundation", "sibling"}
    consumer = next(p for p in result["phases"] if "consumer" in p["tasks"])
    assert consumer["dependencies"] == ["foundation"]
    assert any("high risk" in str(r) for r in result["unsafe_combinations"])
    assert len(result["phases"]) == 4


def test_missing_dependency_and_cycles_do_not_turn_ready():
    result = plan([task("a", dependencies=["missing"])])
    assert result["missing_dependencies"] == ["missing"]
    assert result["phases"][0]["execution"] == "BLOCKED"
    with pytest.raises(ValueError, match="cycle"):
        plan([task("a", dependencies=["b"]), task("b", dependencies=["a"])])


def test_shared_proof_closes_only_satisfied_acceptance_and_preserves_production_gap():
    tasks = [task("a"), task("b", production_required=True), task("c")]
    proof = {
        "result": "PASS",
        "head": "a" * 40,
        "criteria": ["test contract"],
        "references": ["tests/run/1"],
    }
    updated = satisfy(tasks, {"a": proof, "b": proof})
    assert [t["state"] for t in updated] == ["VERIFIED", "IMPLEMENTED_UNVERIFIED", "PLANNED"]
    with pytest.raises(ValueError):
        satisfy(tasks, {"a": proof | {"criteria": []}})
    with pytest.raises(ValueError):
        plan([task("liar", state="VERIFIED")])


def test_blocked_launch_cannot_be_merged_into_unblocked_phase():
    result = plan([task("launch", blockers=["real game required"]), task("mechanical")])
    assert len(result["phases"]) == 2
    assert result["phases"][0]["execution"] == "BLOCKED"


def test_unknown_risk_or_authority_is_not_permission_to_cluster():
    assert not compatible(task("a", risk=None), task("b"))[0]
    assert not compatible(task("a", authority=None), task("b", authority=None))[0]


def test_shared_blocker_allows_planning_but_never_execution():
    result = plan([task("a", blockers=["owner gate"]), task("b", blockers=["owner gate"])])
    assert len(result["phases"]) == 1
    assert result["phases"][0]["execution"] == "BLOCKED"
    assert result["phases"][0]["blockers"] == ["owner gate"]


def test_explicit_blocked_state_and_dirty_candidate_cannot_pass():
    assert plan([task("a", state="BLOCKED")])["phases"][0]["execution"] == "BLOCKED"
    proof = {
        "result": "PASS",
        "head": "a" * 40,
        "criteria": ["test contract"],
        "references": ["run"],
    }
    with pytest.raises(ValueError):
        satisfy([task("a", candidate_clean=False)], {"a": proof})


def test_forged_or_stale_revision_and_abandoned_prerequisite_are_rejected():
    proof = {
        "result": "PASS",
        "head": "banana",
        "criteria": ["test contract"],
        "references": ["run"],
    }
    with pytest.raises(ValueError):
        satisfy([task("a")], {"a": proof})
    with pytest.raises(ValueError):
        satisfy([task("a")], {"a": proof | {"head": "b" * 40}})
    with pytest.raises(ValueError):
        plan([task("a", state="VERIFIED", evidence={"anything": True})])
    result = plan([task("gone", state="ABANDONED"), task("consumer", dependencies=["gone"])])
    assert result["phases"][0]["execution"] == "BLOCKED"
    result = plan(
        [
            task("old", state="SUPERSEDED", replacement="new"),
            task("new"),
            task("consumer", dependencies=["old"]),
        ]
    )
    consumer = next(p for p in result["phases"] if "consumer" in p["tasks"])
    assert consumer["dependencies"] == ["new"]
