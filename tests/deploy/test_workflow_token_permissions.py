"""Every workflow job runs with an explicit GITHUB_TOKEN grant (T13, 2026-11-20).

A job with no ``permissions:`` and no top-level block inherits the repository
default, which can be write-all.  Each job must therefore be covered by its
own block or by a top-level one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_an_explicit_token_grant(path):
    doc = _load(path)
    top = "permissions" in doc
    uncovered = [
        name
        for name, job in (doc.get("jobs") or {}).items()
        if not top and "permissions" not in (job or {})
    ]
    assert not uncovered, f"{path.name}: jobs with no token grant: {uncovered}"


def test_deploy_validate_job_is_covered_by_the_read_only_default():
    doc = _load(ROOT / ".github/workflows/deploy.yml")
    assert doc["permissions"] == {"contents": "read"}
    assert "permissions" not in doc["jobs"]["validate"]
