#!/usr/bin/env python3
"""Shared owner for "does every CI check have a release-gate category" (V1-121).

WHY THIS EXISTS
---------------
``docs/VERSION_1_COMPLETION_CONTRACT.md`` V1-121 requires that no CI check be an
unclassified unknown: a real blocker must not be treated as noise, nor a detector
block releases. Before this file, no manifest anywhere answered "what category is
THIS step" for the repo's 31 workflow files / 33 jobs / 235 steps. The nearest
artifacts (``docs/CI_RELIABILITY_LANE.md``'s failure taxonomy,
``docs/ops/CI_FAILURE_MATRIX_2026-08-20.md``) classify *investigated failures*
after the fact, never a per-step category up front.

WHY CLASSIFICATION IS BY EXPLICIT DECLARATION, NOT INFERENCE
--------------------------------------------------------------
``docs/ops/STABILIZATION_2026-08-16.md`` section 3d-bis already tried a
heuristic/AST-based classifier and measured it wrong: 23 hits, narrowed to 5,
all 5 false positives. This module does not repeat that attempt. The only two
signals it reads are structural and load-bearing in GitHub Actions itself:

  * ``continue-on-error: true`` (step or job level) -- GitHub's own definition
    of "this step's failure must not fail the run", i.e. ``advisory``.
  * an ``if:`` condition that tests a ``vars.``/``secrets.`` value for
    inequality to empty -- i.e. this step can be SKIPPED by missing
    configuration, which is the same "skip must not read as success" concern
    ``tests/deploy/test_no_workflow_exits_green_on_missing_secrets.py`` polices
    for ``exit 0`` paths. Flagged ``conditional_skip`` rather than classified
    into its own category, because the step is still ``blocking`` when it DOES
    run -- the flag says "verify this one didn't just skip," not "this is
    advisory."

Everything else defaults to ``blocking``, because that is what "no
continue-on-error" means in GitHub Actions: a failing step fails the job.

USAGE
-----
``enumerate_workflow_steps()`` is the single source of truth for "what steps
exist right now" -- both the manifest-generation path and the structural test
import it, so they cannot drift apart from each other. Only the *manifest*
(``config/ci/release_gate_classification.json``) can drift from the workflows,
and that is exactly what ``tests/deploy/test_release_gate_classification.py``
polices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
MANIFEST_PATH = ROOT / "config" / "ci" / "release_gate_classification.json"


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert (
        files
    ), "no workflow files found under .github/workflows -- this guard would pass vacuously"
    return files


def _is_conditional_skip(step_if: Any) -> bool:
    text = str(step_if or "")
    return ("vars." in text or "secrets." in text) and "!=" in text


def enumerate_workflow_steps() -> dict[str, dict]:
    """Every (file, job, step) triple across every workflow, keyed
    ``"<file>::<job_id>::<step name-or-id-or-positional>"``.

    The key uses the step's own ``name`` (falling back to ``id``, then a
    positional ``step_<index>``) because that is what a human reads in the
    Actions UI and in a failure notification -- the same identity the
    classification manifest and a release-gate report both need to speak in.
    """
    steps: dict[str, dict] = {}
    for path in _workflow_files():
        document = yaml.safe_load(path.read_text()) or {}
        jobs = document.get("jobs", {}) or {}
        for job_id, job in jobs.items():
            job = job or {}
            job_advisory = bool(job.get("continue-on-error", False))
            job_steps = job.get("steps", []) or []
            for index, step in enumerate(job_steps):
                step = step or {}
                name = step.get("name") or step.get("id") or f"step_{index}"
                key = f"{path.name}::{job_id}::{name}"
                declared_advisory = job_advisory or bool(step.get("continue-on-error", False))
                steps[key] = {
                    "file": path.name,
                    "job": job_id,
                    "step": name,
                    "declared_category": "advisory" if declared_advisory else "blocking",
                    "conditional_skip": _is_conditional_skip(step.get("if")),
                }
    return steps


def load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def diff_against_live_workflows() -> dict[str, list[str]]:
    """Compare the committed manifest against the live workflow tree.

    Returns a dict with two keys:
      * ``unclassified`` -- steps that exist in the workflows but have no
        manifest entry (the mutation this guard exists to catch: an
        unclassified check must RED).
      * ``stale`` -- manifest entries naming a step that no longer exists
        (the other half of the ratchet -- an allowance nobody can check is
        exactly how ``_LIVEDATA_MODULES`` hid tests from a different gate
        for months, per ``scripts/check_decision_coercions.py``'s own
        docstring).
    """
    live = enumerate_workflow_steps()
    manifest = load_manifest()
    entries = manifest.get("entries", {})
    unclassified = sorted(key for key in live if key not in entries)
    stale = sorted(key for key in entries if key not in live)
    return {"unclassified": unclassified, "stale": stale}


def category_mismatches() -> list[str]:
    """Manifest entries whose declared ``category`` disagrees with what the
    live workflow structurally declares (``continue-on-error``). This is the
    one check that can catch a REAL classification drift, not just presence:
    someone adds ``continue-on-error: true`` to a previously-blocking step
    without updating the manifest, silently turning a real blocker into
    noise -- or removes it from a step the manifest still calls advisory,
    silently making a detector block releases. Both are exactly what V1-121's
    own wording warns against.
    """
    live = enumerate_workflow_steps()
    manifest = load_manifest()
    entries = manifest.get("entries", {})
    mismatches = []
    for key, live_step in live.items():
        entry = entries.get(key)
        if entry is None:
            continue  # reported separately by diff_against_live_workflows
        declared = entry.get("category")
        actual = live_step["declared_category"]
        if declared != actual:
            mismatches.append(
                f"{key}: manifest says {declared!r}, workflow structurally declares {actual!r}"
            )
    return mismatches


if __name__ == "__main__":
    diff = diff_against_live_workflows()
    mismatches = category_mismatches()
    print(f"workflow steps: {len(enumerate_workflow_steps())}")
    print(f"unclassified (in workflows, not in manifest): {len(diff['unclassified'])}")
    for key in diff["unclassified"]:
        print(f"  UNCLASSIFIED: {key}")
    print(f"stale (in manifest, not in workflows): {len(diff['stale'])}")
    for key in diff["stale"]:
        print(f"  STALE: {key}")
    print(f"category mismatches: {len(mismatches)}")
    for line in mismatches:
        print(f"  MISMATCH: {line}")
