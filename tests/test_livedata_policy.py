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

2026-10 follow-up (workstream C, test reliability): the same defect, at scale.
Fifteen modules (350 tests) were listed whole.  Most asserted invariants of OUR
code -- rank coherence, tier alignment, single-curve, pick passes, FAAB
calibration -- over ``exports/latest``, so the advisory tier held checks that
could not fail a PR while a health floor beside them was the thing it was meant
to isolate.  They now build from ``tests.archive_fixtures`` (the newest archived
scrape the contract's own source-health definition calls complete) and block;
the genuinely live remainder is marked per class/test with
``@pytest.mark.livedata`` and the list below keeps only wholly-live modules.

These tests do not re-litigate the policy. They check the two things
about it that can be checked mechanically: entries name real files, and
the module rescued above stays rescued.

The item that used to be recorded here as STILL OPEN -- ``test_dlf_source.py``
carrying the pure-logic ``TestDlfCsvEnrichment`` -- is closed: the whole module
reads no live data (it passes with ``exports/`` and ``CSVs/`` deleted) and is no
longer listed.
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
    # The list is MEANT to shrink (see the module docstring); what this guards
    # is the parse, so pin the entries that are wholly live by construction.
    assert {"test_ktc_reconciliation.py", "test_ktc_import_live.py"} <= set(
        declared
    ), f"parsed {declared}; the regex is stale or a wholly-live module left the list"


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


def test_the_anchor_end_to_end_half_now_blocks_too():
    """The split stays split, and the end-to-end half no longer hides.

    ``TestAnchorEndToEnd`` used to be the reason ``test_pick_rookie_anchor.py``
    was exempted: it read ``exports/latest`` and hard-coded the literal 2026
    (a class that has since been drafted, so five of its six tests skipped
    forever).  It now derives the slotted class from the board and builds from
    a complete archived scrape, so the module blocks like its sibling.
    """
    src = (REPO_ROOT / "tests" / "api" / "test_pick_rookie_anchor.py").read_text(encoding="utf-8")
    assert "test_pick_rookie_anchor.py" not in _declared_modules(), (
        "the rookie-anchor end-to-end module is back in the advisory tier; "
        "it builds from a complete archived board and must be able to fail a PR"
    )
    assert "class TestAnchorPassCore" not in src, (
        "TestAnchorPassCore is back in the end-to-end module — it belongs in "
        "test_pick_rookie_anchor_core.py"
    )
    assert "class TestAnchorEndToEnd" in src
    assert not _opens_todays_scrape(src), (
        "the end-to-end class reads today's scrape again; use "
        "tests.archive_fixtures.newest_complete_contract"
    )


def _opens_todays_scrape(text: str) -> bool:
    """True when code (not prose) opens ``exports/latest``.

    Matches the two spellings tests have used -- ``REPO / "exports" / "latest"``
    and a ``glob("exports/latest/...")`` -- and nothing that merely mentions
    the directory in a docstring or comment.
    """
    return bool(re.search(r'"exports"\s*/\s*"latest"|glob\(\s*["\']exports/latest', text))


#: Modules promoted into the hard gate by the 2026-10 reliability pass.  Each is
#: either wholly archive-pinned or wholly pure; none may be re-exempted whole,
#: and the ones that build a board must not read today's scrape.
_PROMOTED_MODULES = {
    "test_launch_readiness.py": False,
    "test_source_monitoring.py": False,
    "test_picks_end_to_end.py": False,
    "test_pick_refinement.py": False,
    "test_pick_rookie_anchor.py": True,
    "test_player_identity_regression.py": False,
    "test_single_curve_live.py": True,
    "test_single_authority.py": True,
    "test_per_source_freshness.py": True,
    "test_dlf_source.py": True,
    "test_fantasypros_idp_integration.py": False,
    "test_fetch_flock_fantasy_rookies.py": True,
    "test_faab_calibration.py": False,  # three market-banded tests stay livedata
}


def test_promoted_modules_are_not_exempted_whole_again():
    declared = set(_declared_modules())
    back = sorted(m for m in _PROMOTED_MODULES if m in declared)
    assert not back, (
        f"{back} were promoted into the hard gate because they check invariants of our "
        "code, not live data; mark the individual live test or class with "
        "@pytest.mark.livedata instead of exempting the module"
    )


def test_wholly_pinned_modules_never_read_todays_scrape():
    """A module that is promoted in whole must build from the archive fixture.

    ``exports/latest`` is a function of the last scrape's health -- one KTC
    timeout empties a board -- which is exactly what the hard gate may not
    depend on (CLAUDE.md "CI has two lanes").
    """
    files = _test_files()
    offenders = [
        name
        for name, whole in _PROMOTED_MODULES.items()
        if whole and _opens_todays_scrape(files[name].read_text(encoding="utf-8"))
    ]
    assert not offenders, f"{offenders} read exports/latest; use tests.archive_fixtures"


def test_the_archive_fixture_finds_a_complete_board():
    """Every pinned test SKIPS (not fails) when no complete archived board
    exists, so a vanished archive would turn them all into silent no-ops.
    That must be loud: this is the one place it fails."""
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, name = newest_complete_raw_payload()
    assert payload is not None, (
        "no complete archived scrape in exports/archive -- the archive-pinned "
        "hard-gate tests would all skip"
    )
    assert name
