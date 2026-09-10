from src.steward.sync import classify_movement, evidence_reuse


def observation(paths):
    return {
        "previous_main": "a",
        "origin_main": "b",
        "changed_paths": paths,
        "commits": ["b bot refresh"],
    }


def test_bot_name_is_not_proof_and_consumed_data_is_relevant():
    obs = observation(["exports/latest/manifest.json"])
    assert (
        classify_movement(obs, ["src/steward"])["classification"] == "UNKNOWN_REQUIRES_INSPECTION"
    )
    proof = {
        "reviewed_paths": obs["changed_paths"],
        "commits": ["b"],
        "workflow_evidence": "run/123",
    }
    assert (
        classify_movement(obs, ["src/steward"], automation_proof=proof)["classification"]
        == "BENIGN_AUTOMATION_MOVE"
    )
    assert (
        classify_movement(obs, ["exports/latest"], automation_proof=proof)["classification"]
        == "RELEVANT_BASE_MOVE"
    )


def test_reuse_is_bound_to_candidate_and_dependency_surface():
    evidence = {
        "head": "candidate",
        "result": "PASS",
        "scope": "implementation",
        "dependencies": ["src/steward"],
        "dependencies_complete": True,
    }
    benign = {"classification": "BENIGN_AUTOMATION_MOVE", "affected": []}
    assert evidence_reuse(evidence, candidate_head="candidate", movement=benign)["reuse"]
    assert not evidence_reuse(evidence, candidate_head="changed", movement=benign)["reuse"]
    assert not evidence_reuse(
        evidence | {"scope": "release_tree"}, candidate_head="candidate", movement=benign
    )["reuse"]
    relevant = {"classification": "RELEVANT_BASE_MOVE", "affected": ["src/trade/finder.py"]}
    assert evidence_reuse(evidence, candidate_head="candidate", movement=relevant)["reuse"]
    relevant["affected"] = [".github/workflows/pr-validation.yml"]
    assert not evidence_reuse(evidence, candidate_head="candidate", movement=relevant)["reuse"]
