"""Every CI check must resolve to exactly one release-gate category (V1-121).

``docs/VERSION_1_COMPLETION_CONTRACT.md`` V1-121: "a real blocker must not be
treated as noise, nor a detector block releases." Before this test, no
manifest anywhere answered "what category is this check" for any of the
repo's 31 workflow files / 33 jobs / 235 steps -- see
``scripts/ci_gate_classification.py``'s module docstring for the full
rationale, including why classification is by explicit declaration in
``config/ci/release_gate_classification.json`` rather than inferred (a
heuristic classifier was already tried and measured wrong, per
``docs/ops/STABILIZATION_2026-08-16.md`` section 3d-bis).

Bidirectional, on purpose, the same shape ``check_planning_integrity.py``'s
CE-registry check and ``check_decision_coercions.py``'s baseline ratchet both
use: a step with no manifest entry is exactly as wrong as a manifest entry
naming a step that no longer exists. An allowance nobody can check is how a
DIFFERENT gate's ``_LIVEDATA_MODULES`` exemption hid tests from CI for
months -- this test refuses to create a third copy of that failure mode.

A third check catches drift PRESENCE alone cannot: a step's classification
going stale in place. Adding ``continue-on-error: true`` to a step the
manifest still calls ``blocking`` silently turns a real blocker into noise;
removing it from a step the manifest calls ``advisory`` silently lets a
detector start blocking releases. Both are exactly what V1-121's own wording
warns against, and neither shows up as an unclassified OR a stale key.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ci_gate_classification import (  # noqa: E402
    category_mismatches,
    diff_against_live_workflows,
    enumerate_workflow_steps,
    load_manifest,
)


def test_every_workflow_step_has_a_manifest_entry():
    live = enumerate_workflow_steps()
    assert live, "no workflow steps found -- this guard would pass vacuously"
    diff = diff_against_live_workflows()
    assert diff["unclassified"] == [], (
        "unclassified CI check(s) with no release-gate category -- "
        f"add an entry to config/ci/release_gate_classification.json: {diff['unclassified']}"
    )


def test_no_manifest_entry_names_a_step_that_no_longer_exists():
    diff = diff_against_live_workflows()
    assert diff["stale"] == [], (
        "release_gate_classification.json names step(s) that no longer exist in any "
        f"workflow -- remove these entries (or the step was renamed and needs a new one): {diff['stale']}"
    )


def test_declared_category_matches_the_live_workflow_structure():
    mismatches = category_mismatches()
    assert mismatches == [], (
        "manifest category disagrees with what the workflow structurally declares "
        f"(continue-on-error): {mismatches}"
    )


def test_manifest_is_well_formed():
    manifest = load_manifest()
    assert manifest.get("version") == 1
    assert set(manifest.get("categories", {})) == {"blocking", "advisory"}
    entries = manifest.get("entries", {})
    assert entries, "manifest has zero entries -- this guard would pass vacuously"
    for key, entry in entries.items():
        assert entry.get("category") in (
            "blocking",
            "advisory",
        ), f"{key}: invalid category {entry.get('category')!r}"
        for flag in entry.get("flags", []):
            assert flag in manifest.get("flags", {}), f"{key}: undeclared flag {flag!r}"
