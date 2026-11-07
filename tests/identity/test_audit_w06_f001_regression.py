"""CW-40 / master-site-audit W06-F001 regression evidence (P1).

Finding: one human occupies two board rows -- a resolved row and an unresolved
"ghost" holding stranded vendor votes (Matt / Matthew Hibner, Jam / Jamarion Miller).

Adjudication (docs/audits/remediation_2026-11-06/CW40_P1_OPEN_ADJUDICATION.md):
PARTIAL.

* CLOSED path: the scraper's dedup pass has a first-name-drift rung
  (``Dynasty Scraper.py``, "Second rung: first-name drift") that folds an
  id-less ghost into the single identified row it is a first-name variant of.
  The rule is ``name_clean.is_first_name_variant`` and is pinned in
  ``tests/api/test_first_name_variant_ghosts.py``.
* STILL OPEN: the same two ghosts are present on the newest tracked archive board
  (``dynasty_export_20261106_194518``).  They are not vendor-CSV ghosts; they are
  re-created AFTER that rung by the must-have rookie guarantee, which looks
  names up by exact key / ``normalize_lookup_name`` only and is seeded from
  ``rookie_must_have.txt`` ("Matthew Hibner", "Jamarion Miller").  The ghost rows
  carry ``_fallbackReason == "must_have_rookie_guarantee"``.

The archive is tracked and immutable, so the xfail is deterministic; it is pinned
to that one bundle by name (skips if retention ever removes it).
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

from src.utils.name_clean import is_first_name_variant

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20261106_194518.zip"
SCRAPER = REPO / "Dynasty Scraper.py"
MUST_HAVE = REPO / "rookie_must_have.txt"


def _players() -> dict:
    with zipfile.ZipFile(ARCHIVE) as zf:
        name = next(n for n in zf.namelist() if n.startswith("dynasty_data_"))
        return json.loads(zf.read(name))["players"]


def _split_pairs(players: dict) -> list[tuple[str, str]]:
    """(ghost, resolved) pairs: an id-less row that is a first-name variant of
    exactly the kind of row the scraper's rung would have folded it into."""
    resolved = [n for n, e in players.items() if isinstance(e, dict) and e.get("_sleeperId")]
    ghosts = [n for n, e in players.items() if isinstance(e, dict) and not e.get("_sleeperId")]
    return sorted((g, r) for g in ghosts for r in resolved if is_first_name_variant(g, r))


def test_scraper_keeps_the_first_name_drift_rung_with_its_identity_gate():
    """The closed half, pinned at its wiring: the rung exists, uses the one rule,
    and only merges an id-less ghost into exactly one identified row."""
    src = SCRAPER.read_text(encoding="utf-8")
    assert "Second rung: first-name drift (W06-F001)" in src
    assert re.search(r"for _n in _identified if is_first_name_variant\(_ghost, _n\)", src)
    assert 'not _e.get("_sleeperId")' in src
    assert "if len(_matches) != 1:" in src


@pytest.mark.skipif(not ARCHIVE.exists(), reason="pinned archive bundle absent")
def test_the_surviving_ghosts_are_must_have_rookie_guarantee_rows():
    """Cause, as data: every surviving first-name ghost is a fallback row created by
    the must-have rookie guarantee, from a name listed in rookie_must_have.txt."""
    players = _players()
    must_have = {
        line.strip() for line in MUST_HAVE.read_text(encoding="utf-8").splitlines() if line.strip()
    }
    for ghost, _resolved in _split_pairs(players):
        assert players[ghost].get("_fallbackReason") == "must_have_rookie_guarantee", ghost
        assert ghost in must_have, ghost


@pytest.mark.skipif(not ARCHIVE.exists(), reason="pinned archive bundle absent")
@pytest.mark.xfail(
    strict=True,
    reason="W06-F001: must-have rookie guarantee re-creates Matthew Hibner / Jamarion Miller ghosts",
)
def test_no_unresolved_row_is_a_first_name_variant_of_a_resolved_row():
    pairs = _split_pairs(_players())
    assert pairs == [], f"split identities on the board: {pairs}"
