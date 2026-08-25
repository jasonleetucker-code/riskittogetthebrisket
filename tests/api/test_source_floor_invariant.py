"""Invariant: every scraper's internal row-count floor must be >= the
downstream contract floor in ``_DEFAULT_SOURCE_ROW_FLOORS``.

WHY THIS EXISTS
---------------
Three production incidents in May 2026 had the same root cause: a
scraper's *internal* "too few rows" guard was weaker than the
*contract* floor the live board is later asserted against
(``src/api/data_contract.py::_DEFAULT_SOURCE_ROW_FLOORS``, enforced by
``tests/api/test_source_monitoring.py``).  So a partial/degraded
scrape (a vanished position, a republished chart, a dropped sheet)
passed the scraper's own guard, the degraded CSV was written +
auto-committed, and it then HARD-FAILED CI on a clean checkout —
blocking every PR — while #451's runtime coverage gate only catches
it at deploy time.

  * yahooBoone: scraper floor 225 < contract 400 (TE article vanished
    → 360 rows shipped).  Fixed: floor 400 + per-position guard.
  * dlfSf/dlfIdp: scraper min_rows 200/120 < contract 240/150, and
    write-then-WARN (overwrote last-good).  Fixed: floors aligned +
    check-before-write.
  * idpShow: WARN-only at <100 < contract 150.  Fixed: hard-fail at
    <150, preserve last-good.

This test makes the floor>=contract relationship a STATIC, pre-merge
invariant so the class cannot silently recur: a new source, a lowered
scraper floor, or a raised contract floor that breaks the relationship
fails here before it can ship.

ALLOWLIST PATTERN
-----------------
Some scrapers still have no aligned internal floor (legacy
``Dynasty Scraper.py`` exports, or scrapers that only abort at
literally zero rows).  Each is listed in ``_KNOWN_FLOOR_GAPS`` with a
one-line rationale + the follow-up that will close it — same
self-burning-down pattern as
``test_player_identity_regression.KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST``.
``test_known_gaps_are_still_real_gaps`` forces removal of an entry the
moment its scraper is hardened, so the allowlist can only shrink.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from src.api.data_contract import _DEFAULT_SOURCE_ROW_FLOORS

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "scripts"


def _module_int_const(rel_path: str, const_name: str) -> int | None:
    """Statically read ``const_name = <int>`` from a script WITHOUT
    importing it (scrapers do import-time work / require network libs).
    Mirrors the static-parsing approach in test_source_registry_parity.
    """
    # scripts/<rel_path> first; fall back to the repo root so legacy
    # root-level modules (e.g. "Dynasty Scraper.py") resolve too.
    path = _SCRIPTS / rel_path
    if not path.exists():
        path = _REPO / rel_path
    if not path.exists():
        return None
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        # Plain ``X = 400``.
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and tgt.id == const_name
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int)
                ):
                    return int(node.value.value)
        # Annotated ``X: int = 400`` (most scrapers use this form).
        elif isinstance(node, ast.AnnAssign):
            tgt = node.target
            if (
                isinstance(tgt, ast.Name)
                and tgt.id == const_name
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, int)
            ):
                return int(node.value.value)
    return None


def _dlf_board_min_rows(board_key: str) -> int | None:
    """Extract ``"min_rows": N`` for one board out of fetch_dlf.py's
    BOARDS dict (it's a per-board config dict, not a flat constant)."""
    path = _SCRIPTS / "fetch_dlf.py"
    if not path.exists():
        return None
    src = path.read_text()
    # Find the board's block, then the first min_rows int after it.
    m = re.search(rf'"{re.escape(board_key)}"\s*:\s*\{{(.*?)\}}', src, re.S)
    if not m:
        return None
    mr = re.search(r'"min_rows"\s*:\s*(\d+)', m.group(1))
    return int(mr.group(1)) if mr else None


# Effective internal floor per source key — how to read each scraper's
# real guard value.  Resolver returns the int, or None if the scraper
# has NO aligned internal floor (=> must be in _KNOWN_FLOOR_GAPS).
_SCRAPER_FLOOR_RESOLVERS = {
    "yahooBoone": lambda: _module_int_const("fetch_yahoo_boone.py", "_YB_ROW_COUNT_FLOOR"),
    "dynastyNerdsSfTep": lambda: _module_int_const("fetch_dynasty_nerds.py", "_DN_ROW_COUNT_FLOOR"),
    "dynastyDaddySf": lambda: _module_int_const("fetch_dynasty_daddy.py", "_DD_ROW_COUNT_FLOOR"),
    "flockFantasySf": lambda: _module_int_const("fetch_flock_fantasy.py", "_FF_ROW_COUNT_FLOOR"),
    "idpShow": lambda: _module_int_const("fetch_idpshow.py", "_IDPSHOW_ROW_FLOOR"),
    "idpShowCombined": lambda: _module_int_const("fetch_idpshow.py", "_IDPSHOW_COMBINED_ROW_FLOOR"),
    "dlfSf": lambda: _dlf_board_min_rows("dlfSf"),
    "dlfIdp": lambda: _dlf_board_min_rows("dlfIdp"),
    # No aligned internal floor today (legacy Dynasty Scraper.py
    # exports, or abort-only-at-zero scrapers).  Resolver returns None
    # => allowlisted below until the named follow-up hardens it.
    # A2 (2026-05-17) — each now has a contract-aligned fail-loud,
    # preserve-last-good floor; resolvers read the real constant.
    "draftSharks": lambda: _module_int_const("fetch_draftsharks.py", "_DS_SF_ROW_FLOOR"),
    "draftSharksIdp": lambda: _module_int_const("fetch_draftsharks.py", "_DS_IDP_ROW_FLOOR"),
    "fantasyProsFitzmaurice": lambda: _module_int_const(
        "fetch_fantasypros_fitzmaurice.py", "_FPF_ROW_FLOOR"
    ),
    "fantasyProsIdp": lambda: _module_int_const(
        "fetch_fantasypros_idp.py", "_FP_WRITTEN_ROW_FLOOR"
    ),
    # A3 (2026-05-17) — legacy Dynasty Scraper.py FULL_DATA->site_raw
    # export now skips the write below its contract-aligned floor so
    # the existing restore-previous pass preserves last-good.
    "ktc": lambda: _module_int_const("Dynasty Scraper.py", "_KTC_SITE_RAW_FLOOR"),
    # F-10 (2026-08-18) — ``ktcSfTep`` is plucked from the same KTC API
    # payload as ``ktc`` and is the board's only retail blend source, but
    # had neither a contract floor nor a site_raw floor.  Both added; the
    # allowlist below stays empty, per its own instruction to fix the
    # scraper rather than allowlist the gap.
    "ktcSfTep": lambda: _module_int_const("Dynasty Scraper.py", "_KTC_TEP_SITE_RAW_FLOOR"),
    "idpTradeCalc": lambda: _module_int_const("Dynasty Scraper.py", "_IDPTC_SITE_RAW_FLOOR"),
}

# Sources whose scraper has NO aligned internal floor yet.  Each entry:
# one-line rationale + the follow-up PR that will add the guard and
# REMOVE this entry.  This allowlist can only shrink (enforced by
# ``test_known_gaps_are_still_real_gaps``).
_KNOWN_FLOOR_GAPS: dict[str, str] = {
    # FULLY BURNED DOWN 2026-05-17.  Every source in
    # _DEFAULT_SOURCE_ROW_FLOORS now has a contract-aligned, fail-loud,
    # preserve-last-good internal floor (A2 closed the 6 modular
    # scrapers; A3 closed the 2 legacy Dynasty Scraper.py sources).
    # This dict MUST stay empty: a new entry means a new source
    # shipped without an aligned scraper floor — fix the scraper
    # instead of allowlisting it.  test_scraper_floor_meets_or_
    # exceeds_contract_floor now enforces the invariant for ALL
    # sources with no exceptions.
}


class TestScraperFloorInvariant(unittest.TestCase):
    """Static, pre-merge: scraper floor >= contract floor for every
    source not explicitly (and still-validly) allowlisted."""

    def test_every_contract_floor_source_has_a_resolver(self):
        """A new source in _DEFAULT_SOURCE_ROW_FLOORS must be wired
        here (resolver + either aligned floor or allowlist entry) —
        otherwise its scraper floor is unaudited."""
        missing = sorted(set(_DEFAULT_SOURCE_ROW_FLOORS) - set(_SCRAPER_FLOOR_RESOLVERS))
        self.assertEqual(
            missing,
            [],
            f"Sources in _DEFAULT_SOURCE_ROW_FLOORS with no scraper-floor "
            f"resolver in test_source_floor_invariant: {missing}. Wire "
            f"each (aligned internal floor, or _KNOWN_FLOOR_GAPS entry).",
        )

    def test_scraper_floor_meets_or_exceeds_contract_floor(self):
        """The core invariant for every non-allowlisted source."""
        violations: list[str] = []
        for key, contract_floor in sorted(_DEFAULT_SOURCE_ROW_FLOORS.items()):
            if key in _KNOWN_FLOOR_GAPS:
                continue
            resolver = _SCRAPER_FLOOR_RESOLVERS.get(key)
            scraper_floor = resolver() if resolver else None
            if scraper_floor is None:
                violations.append(
                    f"{key}: no internal scraper floor found, but not "
                    f"in _KNOWN_FLOOR_GAPS (contract floor "
                    f"{contract_floor})"
                )
            elif scraper_floor < contract_floor:
                violations.append(
                    f"{key}: scraper floor {scraper_floor} < contract "
                    f"floor {contract_floor} — a partial scrape can "
                    f"ship a CSV that hard-fails the contract test"
                )
        self.assertEqual(
            violations,
            [],
            "Scraper-floor < contract-floor (the yahooBoone class):\n  " + "\n  ".join(violations),
        )

    def test_known_gaps_are_still_real_gaps(self):
        """Self-burning-down: once a scraper is hardened to meet its
        contract floor, its _KNOWN_FLOOR_GAPS entry MUST be removed.
        Mirrors test_player_identity_regression's allowlist
        post-condition."""
        stale: list[str] = []
        for key in sorted(_KNOWN_FLOOR_GAPS):
            self.assertIn(
                key,
                _DEFAULT_SOURCE_ROW_FLOORS,
                f"_KNOWN_FLOOR_GAPS lists '{key}' which is not in "
                f"_DEFAULT_SOURCE_ROW_FLOORS — drop the stale entry.",
            )
            resolver = _SCRAPER_FLOOR_RESOLVERS.get(key)
            scraper_floor = resolver() if resolver else None
            if scraper_floor is not None and scraper_floor >= _DEFAULT_SOURCE_ROW_FLOORS[key]:
                stale.append(
                    f"{key}: scraper now floors at {scraper_floor} >= "
                    f"contract {_DEFAULT_SOURCE_ROW_FLOORS[key]} — remove "
                    f"it from _KNOWN_FLOOR_GAPS (gap is closed)."
                )
        self.assertEqual(
            stale,
            [],
            "Closed gaps still allowlisted (allowlist must shrink):\n  " + "\n  ".join(stale),
        )


if __name__ == "__main__":
    unittest.main()
