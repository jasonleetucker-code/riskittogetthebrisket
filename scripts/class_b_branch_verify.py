"""Host-side verifier for the fixed Class-B document pilot.

Receipts and file bytes are untrusted worker output. This module never executes
worker-supplied commands or accepts worker-supplied paths or Git refs.
It is loaded from this PR checkout, so it is not an immutable trust root against
future PR authors; the current pilot relies on independent review of this exact head.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

FILE_NAME = "PERFORMANCE_AUDIT.md"
SCHEMA = "class-b-branch-pilot/v1"
TASK_ID = "repair-performance-audit-anchor"
OLD = "[Optimisations that serve a different answer](#optimisations-that-serve-a-different-answer)"
NEW = (
    "[Optimisations that serve a different answer](#7-optimisations-that-serve-a-different-answer)"
)
HEADING = "## 7. Optimisations that serve a different answer"
MAX_BYTES = 128 * 1024


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify(source: Path, output_dir: Path, *, require_network_probe: bool = False) -> dict:
    if source.name != FILE_NAME or source.is_symlink() or not source.is_file():
        raise ValueError("source must be the fixed regular document")
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise ValueError("output directory must be regular")
    names = {path.name for path in output_dir.iterdir()}
    if names != {FILE_NAME, "receipt.json"}:
        raise ValueError("worker output set differs from fixed policy")
    repaired_path = output_dir / FILE_NAME
    receipt_path = output_dir / "receipt.json"
    for path in (repaired_path, receipt_path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError("unsafe worker output file")
    before = source.read_bytes()
    after = repaired_path.read_bytes()
    if len(before) > MAX_BYTES:
        raise ValueError("source too large")
    text = before.decode("utf-8")
    if text.count(OLD) != 1 or text.count(HEADING) != 1 or NEW in text:
        raise ValueError("the real before-state is absent or ambiguous")
    expected = text.replace(OLD, NEW, 1).encode("utf-8")
    if after != expected:
        raise ValueError("worker output exceeds the one-link repair")
    if not re.search(
        r"^## 7\. Optimisations that serve a different answer\r?$",
        after.decode("utf-8"),
        re.MULTILINE,
    ):
        raise ValueError("target heading missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    required = {
        "schema": SCHEMA,
        "task_id": TASK_ID,
        "file": FILE_NAME,
        "before_sha256": digest(before),
        "after_sha256": digest(after),
        "test": "anchor-resolves",
        "test_result": "passed",
    }
    if set(receipt) != set(required) | {"refusals"}:
        raise ValueError("receipt shape drift")
    if any(receipt.get(key) != value for key, value in required.items()):
        raise ValueError("receipt claim mismatch")
    expected_refusals = {"path_denied", "command_denied"}
    if require_network_probe:
        expected_refusals.add("network_denied_by_container")
    if set(receipt["refusals"]) != expected_refusals or len(receipt["refusals"]) != len(
        expected_refusals
    ):
        raise ValueError("required refusal evidence missing")
    return {"schema": SCHEMA, "task_id": TASK_ID, "verified": True, "after_sha256": digest(after)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-network-probe", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.source, args.output, require_network_probe=args.require_network_probe),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
