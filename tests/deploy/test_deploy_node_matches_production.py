"""The deploy builds the release artifact on the production box's Node major.

``scripts/stage_release_artifact.py`` refuses an artifact whose recorded Node
major differs from the box's (``release Node major version differs from
production``).  On 2026-11-18 PR #2252 moved every workflow to Node 22 while the
box still ran Node 20; the next Deploy Production run (79c60f26) failed at
staging and auto-rolled back, and every later deploy would have failed the same
way.  CI may test on newer Node; the artifact-building deploy job may not move
until the box is cut over (docs/ops/NODE22_CUTOVER_2026-11-18.md), and the two
must change together — update ``PRODUCTION_NODE_MAJOR`` here in the same PR.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
DEPLOY = WORKFLOWS / "deploy.yml"
#: Lanes that build, validate or exercise what production runs: they must use
#: the production Node major.  (prod-e2e-smoke / v1-authenticated only run test
#: tooling against the live site and may use a newer Node.)
PRODUCTION_RUNTIME_LANES = ("deploy.yml", "release-candidate.yml", "pr-validation.yml", "e2e.yml")

#: The production box's Node major.  Change ONLY together with the box cutover.
PRODUCTION_NODE_MAJOR = "20"


def _node_versions(workflow: dict) -> list[str]:
    found: list[str] = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            uses = str(step.get("uses") or "")
            if uses.startswith("actions/setup-node"):
                found.append(str((step.get("with") or {}).get("node-version")))
    return found


def test_deploy_builds_on_the_production_node_major() -> None:
    workflow = yaml.safe_load(DEPLOY.read_text(encoding="utf-8"))
    versions = _node_versions(workflow)
    assert versions, "deploy.yml no longer sets up Node — re-check how the artifact is built"
    for version in versions:
        major = re.match(r"\d+", version.lstrip("v"))
        assert major and major.group(0) == PRODUCTION_NODE_MAJOR, (
            f"deploy.yml sets up Node {version!r} but production runs Node "
            f"{PRODUCTION_NODE_MAJOR}; stage_release_artifact would refuse the artifact"
        )


def test_the_artifact_records_the_node_that_built_it() -> None:
    text = DEPLOY.read_text(encoding="utf-8")
    assert '--node-version "$(node --version)"' in text


def test_every_production_runtime_lane_uses_the_production_node_major() -> None:
    for name in PRODUCTION_RUNTIME_LANES:
        workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
        versions = _node_versions(workflow)
        assert versions, f"{name} sets up no Node"
        for version in versions:
            major = re.match(r"\d+", version.lstrip("v"))
            assert (
                major and major.group(0) == PRODUCTION_NODE_MAJOR
            ), f"{name} sets up Node {version!r}; production runs Node {PRODUCTION_NODE_MAJOR}"
