"""Canonical package-construction substrate (V1-36 / C3-PKG-01).

Deliberately NOT under ``src/trade/``.  Four products consume it — the three
trade engines and ``src/roster_intel/packages.py`` — and a shared substrate
that lives inside one of its own consumers is not neutral.  It is also what
``tests/roster_intel/test_packages.py::test_does_not_depend_on_the_pre_fix_trade_engines``
forbids, and that guard is correct: ``roster_intel`` must not depend on the
trade ENGINES.  Depending on shared mechanics is a different relationship, and
the directory name says so rather than the guard being weakened to allow it.

See ``src/packages/construction.py`` for what this owns and what it refuses to.
"""

from src.packages.construction import (
    EligibilityPolicy,
    EnumerationReport,
    PackageAsset,
    PackageShape,
    SidePair,
    adapt_assets,
    by_value_desc,
    enumerate_packages,
    enumerate_sides,
    package_key,
    side_key,
)

__all__ = [
    "EligibilityPolicy",
    "EnumerationReport",
    "PackageAsset",
    "PackageShape",
    "SidePair",
    "adapt_assets",
    "by_value_desc",
    "enumerate_packages",
    "enumerate_sides",
    "package_key",
    "side_key",
]
