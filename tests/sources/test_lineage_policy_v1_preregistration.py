"""lineage-policy/v1 is preregistered and frozen (owner decision 3, 2026-10-01).

The policy's normative block is hashed (rule: the policy's own §1.2) and the hash
is recorded in a sidecar file in the same preregistration commit. An edit to the
normative block after that commit is a new policy version, never an in-place
change, so this test fails on any drift between the block and the recorded hash.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[2] / "docs" / "sources" / "lineage_policy"
POLICY = POLICY_DIR / "LINEAGE_DEPENDENCE_POLICY_v1_PREREGISTRATION.md"
SIDECAR = POLICY_DIR / "LINEAGE_DEPENDENCE_POLICY_v1.sha256"
BEGIN = "<!-- lineage-policy/v1:BEGIN-NORMATIVE -->"
END = "<!-- lineage-policy/v1:END-NORMATIVE -->"


def _normative_block() -> str:
    lines = POLICY.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")
    assert lines.count(BEGIN) == 1 and lines.count(END) == 1
    start, stop = lines.index(BEGIN), lines.index(END)
    assert start < stop
    return "\n".join(lines[start + 1 : stop]) + "\n"


def test_normative_block_matches_recorded_hash() -> None:
    recorded = SIDECAR.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256(_normative_block().encode("utf-8")).hexdigest()
    assert actual == recorded, (
        "lineage-policy/v1's normative block changed after preregistration; "
        "a method change must be a new policy version (lineage-policy/v2) in a new file"
    )


def test_policy_declares_its_identity_and_fail_closed_use() -> None:
    block = _normative_block()
    assert 'policyVersion: "lineage-policy/v1"' in block.replace("\n", " ")
    assert "Unknown is never independent" in block
    assert "descriptive historical output" in block
