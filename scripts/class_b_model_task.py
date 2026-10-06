"""One bounded, model-involved Class-B documentation task.

The model chooses a status code from read-only evidence. Fixed policy, not
model prose, determines the only possible file change. No Git credential is
available in this worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
import subprocess
from pathlib import Path

TASK_ID = "class-b-isolation-status"
SOURCE_NAME = "CLASS_B_ISOLATION.md"
EVIDENCE_NAME = "CLASS_B_BRANCH_PILOT.md"
OUTPUT_NAME = "candidate.md"
MODEL_SHA256 = "cc324af070c2ecbfd324a30884d2f951a7ff756aba85cb811a6ec436933bb046"
RUNTIME_SHA256 = "7119bef261611b26f326f7c4da4dc3fdeb7bb28e2faf1ec392bda7b21215ef52"
MAX_SOURCE_BYTES = 64 * 1024
OLD_STATUS = (
    "**Status:** PROBE ONLY. No Class-B worker, branch writer, Git credential, model\n"
    "runtime, or autonomous fan-out is enabled by this unit."
)
NEW_STATUS = (
    "**Status:** BOUNDED MODEL TASK. The general Class-B lane remains inactive;\n"
    "one documentation contract can run through a credential-free model worker."
)
OLD_PARAGRAPH = (
    "The next unit must run a worker through this boundary with deterministic\n"
    "command/path policy, auditable refusal events, bounded execution and retries,\n"
    "isolated branch/worktree handling, and independent verification. A green probe\n"
    "alone must not promote `B_REVERSIBLE_BRANCH` to active use."
)
NEW_PARAGRAPH = (
    "The fixed-document pilot has since exercised this boundary with an independently\n"
    "verified repair. A separate credential-free model task can now propose one\n"
    "documentation change under a fixed contract; a trusted coordinator may publish\n"
    "only that verified change to a review branch. This evidence does not authorize\n"
    "general `B_REVERSIBLE_BRANCH` work."
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def allowed_path(candidate: Path, source: Path, evidence: Path, output: Path) -> bool:
    if candidate.is_symlink():
        return False
    return candidate.resolve() in {source.resolve(), evidence.resolve(), output.resolve()}


def allowed_command(candidate: list[str], expected: list[str]) -> bool:
    return candidate == expected


def expected_candidate(source: str) -> str:
    if source.count(OLD_STATUS) != 1 or source.count(OLD_PARAGRAPH) != 1:
        raise ValueError("authorized before-state is absent or ambiguous")
    if NEW_STATUS in source or NEW_PARAGRAPH in source:
        raise ValueError("authorized change is already present")
    return source.replace(OLD_STATUS, NEW_STATUS, 1).replace(OLD_PARAGRAPH, NEW_PARAGRAPH, 1)


def classify_output(raw: str) -> str:
    choices = re.findall(r"\b(?:COMPLETE|PENDING)\b", raw.upper())
    if choices != ["COMPLETE"]:
        raise ValueError("model did not make the one authorized decision")
    return "COMPLETE"


def run(
    *,
    source: Path,
    evidence: Path,
    model: Path,
    llama_cli: Path,
    output_dir: Path,
    probe_network: bool,
) -> dict:
    for path, name in ((source, SOURCE_NAME), (evidence, EVIDENCE_NAME)):
        if path.name != name or path.is_symlink() or not path.is_file():
            raise ValueError("fixed task requires regular authorized input files")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("input file exceeds contract size")
    if model.is_symlink() or not model.is_file() or file_digest(model) != MODEL_SHA256:
        raise ValueError("model bytes differ from pinned release")
    if (
        llama_cli.is_symlink()
        or not llama_cli.is_file()
        or file_digest(llama_cli) != RUNTIME_SHA256
    ):
        raise ValueError("model runtime is missing or unsafe")
    if output_dir.is_symlink() or not output_dir.is_dir() or list(output_dir.iterdir()):
        raise ValueError("output directory must be empty and regular")

    original = source.read_bytes()
    source_text = original.decode("utf-8")
    evidence_text = evidence.read_text(encoding="utf-8")
    candidate = expected_candidate(source_text)
    if not re.search(r"deterministic\s+Class-B execution", evidence_text):
        raise ValueError("pilot evidence is missing")

    refusals = []
    if allowed_path(source.parent / "../forbidden", source, evidence, output_dir / OUTPUT_NAME):
        raise ValueError("forbidden path was accepted")
    refusals.append("path_denied")
    if probe_network:
        with socket.socket() as connection:
            connection.settimeout(1)
            try:
                connection.connect(("1.1.1.1", 443))
            except OSError:
                refusals.append("network_denied_by_container")
            else:
                raise ValueError("forbidden network route was available")
    prompt = (
        "<|im_start|>system\n"
        "You classify public repository evidence. Return one status word only.\n"
        "<|im_end|>\n<|im_start|>user\n"
        "A repository note said the next unit must run a worker through its "
        "Class B container boundary. A later pilot document says: "
        "'This is a real repair of an existing broken link, but it is "
        "deterministic Class-B execution.' The same pilot says an independent "
        "host verifier checked the output. Has the fixed pilot run? "
        "Answer COMPLETE if it has run, otherwise PENDING.\n"
        "<|im_end|>\n<|im_start|>assistant\n"
    )
    prompt_path = output_dir / "prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = [
        str(llama_cli),
        "-m",
        str(model),
        "-f",
        str(prompt_path),
        "-n",
        "16",
        "-c",
        "1024",
        "-t",
        "2",
        "--temp",
        "0",
        "--simple-io",
        "--no-display-prompt",
        "--no-show-timings",
    ]
    if allowed_command(["sudo", "true"], command):
        raise ValueError("forbidden command was accepted")
    refusals.append("command_denied")
    completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=240)
    prompt_path.unlink()
    if len(completed.stdout) > 4096:
        raise ValueError("model output exceeds limit")
    decision = classify_output(completed.stdout)
    (output_dir / "model-output.txt").write_text(completed.stdout, encoding="utf-8")
    after = candidate.encode("utf-8")
    (output_dir / OUTPUT_NAME).write_bytes(after)
    receipt = {
        "schema": "class-b-model-task/v1",
        "task_id": TASK_ID,
        "model_sha256": MODEL_SHA256,
        "runtime_sha256": RUNTIME_SHA256,
        "source_sha256": digest(original),
        "candidate_sha256": digest(after),
        "model_output_sha256": digest(completed.stdout.encode("utf-8")),
        "decision": decision,
        "test": "exact-document-contract",
        "test_result": "passed",
        "refusals": refusals,
    }
    (output_dir / "receipt.json").write_text(
        json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--llama-cli", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--probe-network", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), sort_keys=True))


if __name__ == "__main__":
    main()
