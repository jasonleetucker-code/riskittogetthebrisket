"""The compact view may not prune a field the frontend reads.

WHY THIS FILE EXISTS
────────────────────
``src/api/compact_view.py`` sends a phone fewer bytes.  For months it also
sent a phone a *different board*, and nothing in the repository could tell:
``tests/api/test_compact_view`` pinned the SHAPE of the pruned payload, and
the frontend suite never saw the payload at all.  Adding a field to a prune
list failed no test in either language.

Measured consequences on the live board, before the repair — same player,
same league, same day, mobile versus desktop:

* ``anomalyFlags`` pruned    → /edge's "Flagged" stat tile read **0**
* ``blendedSourceRank`` pruned → it is a SORT KEY (``app/rankings/page.jsx``),
  so sorting by Consensus collapsed and the board's ORDER could differ
* ``confidenceLabel`` pruned → a different confidence string
* ``anchorValue`` + ``subgroupBlendValue`` + ``subgroupDelta`` +
  ``alphaShrinkage`` pruned → PlayerPopup's value-derivation chain collapsed
* ``sourceOriginalRanks`` pruned → flipped "not listed by this source"
  against "listed, no normalized contribution"

Fourteen of the seventeen pruned per-player fields were read by the
materializer.

WHAT IT ASSERTS
───────────────
``frontend/lib/dynasty-data.js::_materializePlayerArrayRow`` is the ONE
function that turns a contract player row into the object every component
renders.  Whatever it reads must survive the compact pass.  Downstream
components read the materialized row, so covering the materializer covers
them.

Deliberately parses the frontend rather than duplicating a list here.  A
hand-maintained mirror is a third place to forget, and this repository
already crosses this language boundary the same way — see
``tests/api/test_source_registry_parity.py``.

The test is a STATIC parse: no Node, no browser, no network, no live board.
It belongs in the blocking gate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.api import compact_view as cv

REPO = Path(__file__).resolve().parents[2]
MATERIALIZER = REPO / "frontend" / "lib" / "dynasty-data.js"

# Reads that are NOT contract fields: locals, deliberate aliases, or fields
# the backend does not stamp.  Listed with a reason each, because an
# unexplained entry here is how this gate would quietly stop gating.
_NOT_CONTRACT_FIELDS = {
    # Deprecated alias the materializer emits for a migration window; the
    # canonical name (``identityResolutionConfidence``) is read beside it.
    "identityConfidence",
    # Underscore-prefixed compatibility mirrors read with a `??` fallback.
    "_sleeperId",
    "_yearsExp",
}


def _materializer_source() -> str:
    src = MATERIALIZER.read_text(encoding="utf-8")
    start = src.index("function _materializePlayerArrayRow")
    # Walk to the matching close brace of the function body.
    depth = 0
    i = src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start : j + 1]
    raise AssertionError("could not find the end of _materializePlayerArrayRow")


def _fields_read_by_materializer() -> set[str]:
    body = _materializer_source()
    fields = set(re.findall(r"\bplayer\.([A-Za-z_][A-Za-z0-9_]*)", body))
    return fields - _NOT_CONTRACT_FIELDS


def test_the_parse_actually_found_the_materializer():
    """Guard the guard.

    A regex that matches nothing passes every assertion below vacuously,
    which is the exact failure mode this file exists to prevent.  Assert a
    floor on the field count AND on a few fields that must be there.
    """
    fields = _fields_read_by_materializer()
    assert len(fields) > 30, f"parsed only {len(fields)} fields — the parse broke"
    for required in ("rankDerivedValue", "canonicalConsensusRank", "sourceRankMeta"):
        assert required in fields, f"{required} missing — the parse broke"


def test_compact_prunes_no_field_the_materializer_reads():
    read = _fields_read_by_materializer()
    pruned_and_read = sorted(read & cv._PRUNED_PLAYER_FIELDS)
    assert not pruned_and_read, (
        "compact_view prunes fields that frontend/lib/dynasty-data.js reads off "
        f"a player row: {pruned_and_read}.\n"
        "Mobile would render a different number from desktop for the same player. "
        "Either stop pruning the field, or remove its read from the materializer."
    )


def test_the_surviving_prunes_are_genuinely_unread():
    """Stated positively, so the list cannot quietly grow.

    Each survivor is named with the reason it has no reader; if one gains
    one, the test above fires.  This one fires if the list changes at all,
    which forces the reason to be written down.
    """
    assert cv._PRUNED_PLAYER_FIELDS == frozenset(
        {"pickDetails", "hillValueSpread", "marketDispersionCV"}
    )


def test_methodology_survives_because_rankings_renders_it():
    """A contract-level regression with the same shape as the per-player one.

    ``methodology`` was pruned, and /rankings renders it — so the
    methodology section was absent on mobile and present on desktop.
    """
    assert "methodology" not in cv._PRUNED_CONTRACT_FIELDS
    rankings = (REPO / "frontend" / "app" / "rankings" / "page.jsx").read_text(encoding="utf-8")
    assert "methodology={rawData?.methodology}" in rankings, (
        "the read this test is protecting has moved; re-point it rather than "
        "deleting it, or the prune list loses its only reason to keep the field"
    )


@pytest.mark.parametrize("field", sorted(cv._PRUNED_CONTRACT_FIELDS))
def test_pruned_contract_fields_have_no_frontend_reader(field: str):
    """No component may read a contract-level field the compact view drops."""
    roots = [
        REPO / "frontend" / "lib",
        REPO / "frontend" / "components",
        REPO / "frontend" / "app",
    ]
    # ``sites`` is too common a word to grep for usefully; the constant's own
    # comment scopes it ("leave sleeper.sites in place") and the shape test
    # covers it.
    if field == "sites":
        pytest.skip("bare 'sites' is not a searchable identifier; covered by shape tests")
    pattern = re.compile(rf"\b(?:data|payload|rawData|contract|base)\??\.{field}\b")
    hits = []
    for root in roots:
        for path in root.rglob("*.js*"):
            if "__tests__" in path.parts or "node_modules" in path.parts:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(REPO)))
    assert not hits, f"compact prunes contract field {field!r}, but it is read in: {hits}"
