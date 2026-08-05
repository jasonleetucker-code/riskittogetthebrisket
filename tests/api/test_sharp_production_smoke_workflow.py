"""The Sharp production smoke has to be able to reach its own verdict.

R13 / W23-F004 / W23-F005.  Two ways a check reported health it had not
measured:

* ``verify-sharp-production.yml`` ran on every push to main, polled
  production for up to 40 minutes, then died at
  ``git add data/ops/sharp-production-smoke.json``.  ``.gitignore:45`` is
  a bare ``data/`` and only ``data/ros/`` is re-included, so git refuses
  the explicitly-named ignored pathspec with exit 1; Actions' default
  shell is ``bash -e {0}``, so the step failed, the commit never ran, and
  the "Enforce healthy population" step — which carries the default
  ``if: success()`` — was skipped every single time.  ``git log --all --
  data/ops/`` returns nothing, which is what a permanently-failing add
  looks like from the outside.
* the same workflow read ``unmappedAssets`` out of ``dataQuality``, a key
  ``/api/sharp/market`` has never emitted (``src/sharp/market.py`` puts
  it under ``coverage``).  With ``or {}`` and a ``, 0`` default, the miss
  was indistinguishable from a genuine zero — a clean bill of health,
  forever.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"

# The three sibling workflows whose commit step is last and
# ``if: always()``: they lose only their artifact, so a forced add is the
# right fix for them.
SIBLINGS = [
    ("force-sharp-production-now.yml", "data/ops/sharp-force-production-live.json"),
    ("trigger-sharp-no-environment.yml", "data/ops/sharp-no-environment-result.json"),
    ("trigger-sharp-now-via-merge.yml", "data/ops/sharp-merge-trigger-result.json"),
]


def _text(name: str) -> str:
    path = WORKFLOWS / name
    if not path.exists():  # pragma: no cover - workflow removed
        pytest.skip(f"{name} not present")
    return path.read_text(encoding="utf-8")


def test_the_verdict_step_is_not_gated_behind_an_impossible_commit():
    """`data/` is gitignored, so a plain `git add` of that path exits 1
    and everything after it is skipped."""
    text = _text("verify-sharp-production.yml")
    assert "git add data/ops/" not in text
    assert "Enforce healthy population" in text


@pytest.mark.parametrize("name,path", SIBLINGS)
def test_sibling_workflows_force_the_add_of_their_ignored_artifact(name: str, path: str):
    text = _text(name)
    if f"git add {path}" in text or f"git add -f {path}" in text:
        assert f"git add -f {path}" in text, f"{name} adds an ignored path without -f"


def test_the_smoke_reads_unmapped_assets_from_the_key_the_api_emits():
    text = _text("verify-sharp-production.yml")
    assert 'market.get("dataQuality")' not in text
    assert 'market.get("coverage")' in text


def test_the_api_still_emits_unmapped_assets_under_coverage():
    """Pins the other side of the join — if the payload key moves, this
    fails instead of the workflow silently reading zero again."""
    import inspect

    from src.sharp import market

    src = inspect.getsource(market)
    coverage_block = src.split('"coverage": {', 1)
    assert len(coverage_block) == 2, "market payload no longer has a coverage block"
    assert '"unmappedAssets"' in coverage_block[1].split("},", 1)[0]


def test_an_absent_unmapped_count_is_not_reported_as_zero():
    """`.get(key, 0)` on a missing key is a health CLAIM.  The workflow
    must record null instead."""
    text = _text("verify-sharp-production.yml")
    idx = text.find('"unmappedAssets":')
    assert idx > 0
    snippet = text[idx : idx + 200]
    assert '"unmappedAssets", 0' not in snippet
