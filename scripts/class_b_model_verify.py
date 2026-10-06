"""Trusted verifier for the one model-involved documentation branch contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MAX_OUTPUT_BYTES = 64 * 1024
SOURCE_NAME = "CLASS_B_ISOLATION.md"
EVIDENCE_NAME = "CLASS_B_BRANCH_PILOT.md"
OUTPUT_NAME = "candidate.md"
PROOF_NAME = "pilot-proof.json"
TASK_ID = "class-b-isolation-status"
PILOT_RUN_ID = 37388008366
PILOT_HEAD_SHA = "7d71b7b1ed0f5ba87bc2595eb29f770de052b55c"
PILOT_PROOF = {
    "schema": "class-b-pilot-proof/v1",
    "run_id": PILOT_RUN_ID,
    "head_sha": PILOT_HEAD_SHA,
    "workflow_conclusion": "success",
    "worker_step_conclusion": "success",
}
MODEL_SHA256 = "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046"
RUNTIME_SHA256 = "7119bef261611b26f326f7c4da4dc3fdeb7bb28e2faf1ec392bda7b21215ef52"
BEFORE_STATUS = (
    "**Status:** PROBE ONLY. No Class-B worker, branch writer, Git credential, model\n"
    "runtime, or autonomous fan-out is enabled by this unit."
)
AFTER_STATUS = (
    "**Status:** BOUNDED MODEL TASK. The general Class-B lane remains inactive;\n"
    "one documentation contract can run through a credential-free model worker."
)
BEFORE_BODY = (
    "The next unit must run a worker through this boundary with deterministic\n"
    "command/path policy, auditable refusal events, bounded execution and retries,\n"
    "isolated branch/worktree handling, and independent verification. A green probe\n"
    "alone must not promote `B_REVERSIBLE_BRANCH` to active use."
)
AFTER_BODY = (
    "The fixed-document pilot has since exercised this boundary with an independently\n"
    "verified repair. A separate credential-free model task can now propose one\n"
    "documentation change under a fixed contract; a trusted coordinator may publish\n"
    "only that verified change to a review branch. This evidence does not authorize\n"
    "general `B_REVERSIBLE_BRANCH` work."
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare_pilot_proof(run_api: Path, jobs_api: Path, destination: Path) -> dict:
    """Reduce public GitHub Actions evidence to the one audited pilot run."""
    run = json.loads(run_api.read_text(encoding="utf-8"))
    jobs = json.loads(jobs_api.read_text(encoding="utf-8"))
    if any(
        (
            run.get("id") != PILOT_RUN_ID,
            run.get("head_sha") != PILOT_HEAD_SHA,
            run.get("name") != "Class B Branch Pilot",
            run.get("path") != ".github/workflows/class-b-branch-pilot.yml",
            run.get("event") != "pull_request",
            run.get("status") != "completed",
            run.get("conclusion") != "success",
            run.get("run_attempt") != 1,
        )
    ):
        raise ValueError("pilot workflow run is not the audited successful head")
    matching = [
        job
        for job in jobs.get("jobs", [])
        if job.get("name") == "fixed-document-task"
        and job.get("conclusion") == "success"
        and job.get("status") == "completed"
        and job.get("run_id") == PILOT_RUN_ID
        and job.get("run_attempt") == 1
        and job.get("head_sha") == PILOT_HEAD_SHA
    ]
    if len(matching) != 1 or not any(
        step.get("name") == "Run credential-free worker and independently verify exact output"
        and step.get("conclusion") == "success"
        for step in matching[0].get("steps", [])
    ):
        raise ValueError("pilot worker and independent verification did not pass")
    destination.write_text(json.dumps(PILOT_PROOF, sort_keys=True) + "\n", encoding="utf-8")
    return PILOT_PROOF


def verify(source: Path, evidence: Path, output_dir: Path, *, require_network: bool) -> dict:
    for path, name in ((source, SOURCE_NAME), (evidence, EVIDENCE_NAME)):
        if path.name != name or path.is_symlink() or not path.is_file():
            raise ValueError("authorized source or evidence file is unsafe")
        if path.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("authorized input exceeds size limit")
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("worker output directory is unsafe")
    expected_files = {OUTPUT_NAME, PROOF_NAME, "receipt.json", "model-output.txt"}
    observed_files = {path.name for path in output_dir.iterdir()}
    if observed_files != expected_files:
        raise ValueError("worker output file set exceeds fixed contract")
    for name in expected_files:
        path = output_dir / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("worker output file is unsafe")
    before = source.read_bytes()
    after = (output_dir / OUTPUT_NAME).read_bytes()
    text = before.decode("utf-8")
    if text.count(BEFORE_STATUS) != 1 or text.count(BEFORE_BODY) != 1:
        raise ValueError("authorized document before-state is absent or ambiguous")
    expected_after = text.replace(BEFORE_STATUS, AFTER_STATUS, 1).replace(
        BEFORE_BODY, AFTER_BODY, 1
    )
    if after != expected_after.encode("utf-8"):
        raise ValueError("candidate exceeds the exact authorized document change")
    pilot = evidence.read_text(encoding="utf-8")
    if not re.search(r"deterministic\s+Class-B execution", pilot):
        raise ValueError("pilot evidence no longer supports the task")
    proof_bytes = (output_dir / PROOF_NAME).read_bytes()
    if json.loads(proof_bytes) != PILOT_PROOF:
        raise ValueError("pilot run proof does not match the audited successful head")
    model_output = (output_dir / "model-output.txt").read_text(encoding="utf-8")
    if not re.fullmatch(r"\s*COMPLETE(?:\s*\n\s*> EOF by user)?\s*", model_output, re.I):
        raise ValueError("model did not authorize the fixed transition")
    receipt = json.loads((output_dir / "receipt.json").read_text(encoding="utf-8"))
    expected = {
        "schema": "class-b-model-task/v1",
        "task_id": TASK_ID,
        "model_sha256": MODEL_SHA256,
        "runtime_sha256": RUNTIME_SHA256,
        "source_sha256": _digest(before),
        "evidence_sha256": _digest(evidence.read_bytes()),
        "pilot_proof_sha256": _digest(proof_bytes),
        "candidate_sha256": _digest(after),
        "model_output_sha256": _digest(model_output.encode("utf-8")),
        "decision": "COMPLETE",
        "test": "exact-document-contract",
        "test_result": "passed",
    }
    if set(receipt) != set(expected) | {"refusals"}:
        raise ValueError("worker receipt has unexpected fields")
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("worker receipt disagrees with verified bytes")
    refusals = {"path_denied", "command_denied"}
    if require_network:
        refusals.add("network_denied_by_container")
    if (
        not isinstance(receipt["refusals"], list)
        or len(receipt["refusals"]) != len(refusals)
        or set(receipt["refusals"]) != refusals
    ):
        raise ValueError("required refusal evidence is missing")
    return {
        "schema": "class-b-model-verification/v1",
        "task_id": TASK_ID,
        "candidate_sha256": _digest(after),
        "verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--require-network", action="store_true")
    parser.add_argument("--run-api", type=Path)
    parser.add_argument("--jobs-api", type=Path)
    parser.add_argument("--proof-output", type=Path)
    args = parser.parse_args()
    if args.run_api or args.jobs_api or args.proof_output:
        if not all((args.run_api, args.jobs_api, args.proof_output)):
            parser.error("pilot proof needs run API, jobs API and output paths")
        print(json.dumps(prepare_pilot_proof(args.run_api, args.jobs_api, args.proof_output)))
    else:
        if not all((args.source, args.evidence, args.output_dir)):
            parser.error("verification needs source, evidence and output paths")
        print(
            json.dumps(
                verify(
                    args.source,
                    args.evidence,
                    args.output_dir,
                    require_network=args.require_network,
                ),
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
