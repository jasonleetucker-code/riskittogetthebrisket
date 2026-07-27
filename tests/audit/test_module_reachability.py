"""The "43 unreachable modules" figure, made re-derivable.

Backlog defect #9 reported "43 of 208 ``src/`` modules unreachable
(~12,571 lines)". No instrument produced that number and no test pinned
it, so it could not be checked, acted on, or retired — it aged into
folklore. Measured today with the same import walk the feature-flag
guard uses:

    SERVER   117 modules   55,062 lines   a request can reach it
    SCRIPT    14            3,376         operator tooling, not a defect
    TEST      65           16,867         only its own tests import it
    ORPHAN    16            2,044         nothing imports it at all

The single "unreachable" count collapsed three very different
situations, which is why it was unusable. A refit script reached only
from ``scripts/`` is doing its job; a module reached only from the test
written for it is the ``usage_signals`` shape; genuinely orphaned code
is the third thing.

And 8 of the 16 orphans sit under ``src/ros/sources/`` and
``src/news/providers/``, which ``src/ros/scrape.py:449`` loads by string
via ``importlib.import_module(src_meta["scraper"])`` against the
``ROS_SOURCES`` registry. A static walk cannot see that, so those are
annotated rather than accused — the difference between a report someone
acts on and one that gets a working scraper deleted.

These tests guard the instrument, not the number. The counts move as
the tree moves; what must not move is the walk's ability to see.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit" / "measure_module_reachability.py"


@pytest.fixture(scope="module")
def audit():
    spec = importlib.util.spec_from_file_location("measure_module_reachability", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result(audit):
    return audit.measure()


def test_the_walk_finds_the_bulk_of_the_tree(result):
    """Guard on the guard.

    Every verdict is a function of the import closure. A walk that
    silently returned nothing would class all 212 modules ORPHAN and
    produce a spectacular, entirely false report — the exact failure the
    feature-flag audit had to defend against too.
    """
    assert result["totalModules"] > 150, "src/ shrank unexpectedly, or the scan is broken"
    server = result["byClass"].get("SERVER", {"modules": 0})
    assert server["modules"] > 80, (
        f"only {server['modules']} modules reachable from server.py; "
        "the import walk is not resolving"
    )


def test_the_classes_are_all_populated(result):
    """A classifier that put everything in one bucket would satisfy any
    single-class assertion. All four appearing is what makes the split
    meaningful."""
    present = {c for c, row in result["byClass"].items() if row["modules"] > 0}
    assert present == {"SERVER", "SCRIPT", "TEST", "ORPHAN"}, present


def test_known_live_modules_are_reachable_from_the_server(result):
    """Anchors. If these ever class as anything but SERVER, the walk has
    broken rather than the tree."""
    by_module = {m["module"]: m for m in result["modules"]}
    for dotted in (
        "src.api.data_contract",
        "src.api.feature_flags",
        "src.trade.suggestions",
        "src.ros.pick_projection",
    ):
        assert by_module[dotted]["reachability"] == "SERVER", (
            f"{dotted} is live and should be reachable from server.py, "
            f"got {by_module[dotted]['reachability']}"
        )


def test_dynamically_dispatched_packages_are_annotated_not_accused(result):
    """``src/ros/scrape.py:449`` does
    ``importlib.import_module(src_meta["scraper"])`` over the
    ``ROS_SOURCES`` registry, so those modules are loaded by string and
    a static walk cannot see it.

    They may legitimately class ORPHAN — what must never happen is that
    they class ORPHAN *without the flag*, because that is the row
    someone deletes.
    """
    orphans = [m for m in result["modules"] if m["reachability"] == "ORPHAN"]
    unflagged_sources = [
        m
        for m in orphans
        if m["module"].startswith(("src.ros.sources.", "src.news.providers."))
        and not m["dynamicDispatch"]
    ]
    assert not unflagged_sources, (
        f"dynamically-loaded modules reported as plain orphans: "
        f"{[m['module'] for m in unflagged_sources]}"
    )


def test_the_dynamic_dispatch_hint_actually_matches_something(result):
    """Non-vacuity for the test above.

    If ``DYNAMIC_DISPATCH_HINTS`` stopped matching any real package —
    a rename, a move — the previous test would pass by finding nothing,
    and the protection it describes would be gone.
    """
    flagged = [m for m in result["modules"] if m["dynamicDispatch"]]
    assert flagged, "no module matches DYNAMIC_DISPATCH_HINTS; the hint list is stale"


def test_line_counts_are_real(result):
    """The report ranks by size, so a zero everywhere would silently
    invert the ordering into meaninglessness."""
    assert result["totalLines"] > 10_000
    sizeable = [m for m in result["modules"] if m["lines"] > 0]
    assert len(sizeable) > result["totalModules"] * 0.9


def test_the_report_is_sorted_largest_first(result):
    """It is read top-down and acted on top-down."""
    lines = [m["lines"] for m in result["modules"]]
    assert lines == sorted(lines, reverse=True)
