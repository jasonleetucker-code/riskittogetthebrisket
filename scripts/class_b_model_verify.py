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
TASK_ID = "class-b-isolation-status"
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


def verify(source: Path, evidence: Path, output_dir: Path, *, require_network: bool) -> dict:
    for path, name in ((source, SOURCE_NAME), (evidence, EVIDENCE_NAME)):
        if path.name != name or path.is_symlink() or not path.is_file():
            raise ValueError("authorized source or evidence file is unsafe")
        if path.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("authorized input exceeds size limit")
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("worker output directory is unsafe")
    expected_files = {OUTPUT_NAME, "receipt.json", "model-output.txt"}
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
    model_output = (output_dir / "model-output.txt").read_text(encoding="utf-8")
    if re.findall(r"\b(?:COMPLETE|PENDING)\b", model_output.upper()) != ["COMPLETE"]:
        raise ValueError("model did not authorize the fixed transition")
    receipt = json.loads((output_dir / "receipt.json").read_text(encoding="utf-8"))
    expected = {
        "schema": "class-b-model-task/v1",
        "task_id": TASK_ID,
        "model_sha256": MODEL_SHA256,
        "runtime_sha256": RUNTIME_SHA256,
        "source_sha256": _digest(before),
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
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-network", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(**vars(args)), sort_keys=True))


if __name__ == "__main__":
    main()
