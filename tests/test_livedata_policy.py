"""The ``livedata`` exemption list, checked instead of trusted.

``tests/conftest.py`` marks every test in ``_LIVEDATA_MODULES`` as
``livedata``, which moves it out of CI's hard gate into a non-blocking
advisory tier. That policy is sound — a yahooBoone row-count dip should
not block every PR — but it is applied at MODULE granularity, so one
entry exempts every test in the file including the ones that need no
live data at all.

Two things that went unnoticed because nothing checked the list:

* ``test_pick_rookie_anchor.py`` held ten synthetic pure-logic tests
  whose own class docstring said "no live data required". They guarded
  pipeline step 11 — current-year pick tethering, which sets the value
  of all 72 slot picks — and could not fail a PR. Measured before the
  split: ``-m "not livedata"`` collected 15 deselected, 0 run. Now in
  ``test_pick_rookie_anchor_core.py``.
* ``test_footballguys_source.py`` was listed and does not exist.

These tests do not re-litigate the policy. They check the two things
about it that can be checked mechanically: entries name real files, and
the module rescued above stays rescued.

STILL OPEN, deliberately not fixed here: ``test_dlf_source.py`` carries
``TestDlfCsvEnrichment``, which builds a temporary CSV explicitly
"without touching the real CSVs/site_raw tree" — the same pure-logic
half in a live-data module. Splitting it is the same move as the pick
anchor and wants its own change rather than being smuggled into one
about pick tethering.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFTEST = REPO_ROOT / "tests" / "conftest.py"


def _declared_modules() -> list[str]:
    """The literal entries of ``_LIVEDATA_MODULES``.

    Parsed from source rather than imported, so a broken conftest fails
    this test loudly instead of taking the whole suite down with it.
    """
    src = CONFTEST.read_text(encoding="utf-8")
    _, _, after = src.partition("_LIVEDATA_MODULES")
    block, _, _ = after.partition("}")
    return re.findall(r'"(test_[A-Za-z0-9_]+\.py)"', block)


def _test_files() -> dict[str, Path]:
    return {p.name: p for p in REPO_ROOT.joinpath("tests").rglob("test_*.py")}


def test_the_parse_finds_the_list():
    """Guard on the guard: an empty parse would make every assertion
    below pass by checking nothing."""
    declared = _declared_modules()
    assert len(declared) >= 10, f"only parsed {len(declared)} entries; the regex is stale"
    assert "test_pick_rookie_anchor.py" in declared


def test_every_exempted_module_exists():
    """A stale entry is a policy line that looks load-bearing and is
    not. ``test_footballguys_source.py`` sat here after its file was
    removed, and nothing said so."""
    missing = [m for m in _declared_modules() if m not in _test_files()]
    assert not missing, (
        f"_LIVEDATA_MODULES names files that do not exist: {missing}. "
        "Remove them — a dead exemption makes the list unreadable."
    )


def test_the_pure_logic_anchor_module_is_not_exempted():
    """The rescue must stay rescued.

    Re-adding this module to the list, or moving the synthetic tests
    back into the live-data one, would silently return pipeline step
    11's guards to the advisory tier — which is exactly how they spent
    however long they spent there.
    """
    declared = _declared_modules()
    assert "test_pick_rookie_anchor_core.py" not in declared, (
        "the synthetic rookie-anchor tests are pure logic and must keep "
        "blocking; exempting them re-creates the defect they were split out of"
    )
    core = REPO_ROOT / "tests" / "api" / "test_pick_rookie_anchor_core.py"
    assert core.exists(), "the pure-logic anchor module is gone; step 11 is unguarded again"


def test_the_exempted_anchor_module_kept_only_its_live_half():
    """The split has to have actually happened.

    If the synthetic class were copied rather than moved, the tests
    would run in both tiers and the live module would still be the one
    people read.
    """
    src = (REPO_ROOT / "tests" / "api" / "test_pick_rookie_anchor.py").read_text(encoding="utf-8")
    assert "class TestAnchorPassCore" not in src, (
        "TestAnchorPassCore is back in the livedata module — it belongs in "
        "test_pick_rookie_anchor_core.py, where it can fail a PR"
    )
    assert "class TestAnchorEndToEnd" in src, (
        "the end-to-end class left the livedata module; it reads "
        "exports/latest/ and belongs in the advisory tier"
    )
