"""C1-U6-D1 — ONE owner for slot↔tier and for pick-id minting.

**Why this file exists at all.** The 2026-08-17 post-merge audit measured
that C2-U1's retirements held perfectly while C1-U6-D1's and C1-ID-02's
did not, and found the reason: C2-U1 shipped a source-text structural
guard (``tests/lineup/test_single_owner.py``) and the pick units shipped
only behavioural tests.  Behaviour cannot see a duplicate that AGREES —
and every duplicate found in that audit agreed.  That is precisely how a
second owner survives: a disagreeing copy gets caught by a value test, an
agreeing copy is invisible until the day someone changes one of them.

So this is the pick side of the same guard, written against SOURCE TEXT.

**What it does NOT do: quietly repair the two it found.**  Both are real
and both are recorded here as explicitly-named, explicitly-assigned
exceptions rather than as silent allowances, because repairing either
during a feature freeze would be scope expansion rather than a fix:

* ``src/bdvm/service.py::_TIER_FRACTION`` — routing it through the owner
  would MOVE values on a pricing path: early 0.21→0.2083, mid
  0.50→0.5417, late 0.83→0.875 (measured).  Which number is right is a
  methodology question, not an audit repair.
* ``src/platforms/assets.py::canonical_pick_id`` — mints
  ``pick:2027:1:team-12``, a third ``pick:`` grammar the owner cannot
  parse, and its output is a PERSISTED key in the platform ledger.
  Changing it is a data migration.

Naming them costs nothing and makes the next reader inherit a decision
instead of discovering an accident.  The guard's job is to stop the class
GROWING while they wait.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.picks import site_pick_map as owner

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
OWNER_PATH = SRC / "picks" / "site_pick_map.py"
FRONTEND_LIB = REPO / "frontend" / "lib"

#: The two duplicates the audit found, each with the reason it is not
#: repaired here and the unit that owns repairing it.  An entry may be
#: DELETED when its duplicate is retired; adding one requires a decision.
KNOWN_UNRETIRED = {
    "src/bdvm/service.py": (
        "_TIER_FRACTION — routing through the owner moves values on a pricing path "
        "(mid 0.50→0.5417, late 0.83→0.875 measured); methodology, not an audit repair"
    ),
    "src/platforms/assets.py": (
        "canonical_pick_id — mints a third `pick:` grammar whose output is a PERSISTED "
        "ledger key; retiring it is a data migration"
    ),
    # FOUND BY THIS GUARD on its first run, 2026-08-17 — the by-hand
    # census had missed it.  It is an INLINE restatement of
    # ``assets.py::canonical_pick_id``, in the same package, not even
    # calling its own package's helper.  Same persisted-key constraint,
    # so same deferral; recorded because a duplicate of a duplicate is
    # exactly what an unguarded concept accumulates.
    "src/platforms/ffpc/parser.py": (
        "inline `pick:<season>:<round>[:owner]` — a second copy of assets.py's own "
        "canonical_pick_id, same PERSISTED-key constraint"
    ),
}


def _python_sources() -> list[Path]:
    return [
        p
        for p in SRC.rglob("*.py")
        if p != OWNER_PATH and "__pycache__" not in p.parts and p.name != "__init__.py"
    ]


def _rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


class TestNoSecondSlotTierTable:
    """The fingerprint of a second slot↔tier owner is a literal mapping
    of the three tier words onto numbers, or the ``slot <= 4 / <= 8``
    ladder.  Both restate ``slot_tier_ranges``."""

    def test_no_module_outside_the_owner_maps_the_tier_words_to_literals(self):
        offenders: list[str] = []
        tiers = {"early", "mid", "late"}
        for path in _python_sources():
            rel = _rel(path)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover - not our problem here
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Dict) or not node.keys:
                    continue
                keys = [
                    k.value.lower()
                    for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                ]
                if set(keys) != tiers:
                    continue
                if not all(
                    isinstance(v, ast.Constant) and isinstance(v.value, (int, float))
                    for v in node.values
                ):
                    continue
                if rel in KNOWN_UNRETIRED:
                    continue
                offenders.append(f"{rel}:{node.lineno}")
        assert offenders == [], (
            "a tier→number table outside src/picks/site_pick_map.py:\n  "
            + "\n  ".join(offenders)
            + "\nDerive it from slot_tier_ranges() instead, or add an explicit "
            "KNOWN_UNRETIRED entry naming why it cannot be."
        )

    def test_the_known_exceptions_still_exist(self):
        """An allowance for code that has gone is a lie that passes
        forever.  If a duplicate is retired, its entry must be deleted."""
        for rel, why in KNOWN_UNRETIRED.items():
            assert (REPO / rel).exists(), f"KNOWN_UNRETIRED names a missing file: {rel} ({why})"

    def test_the_known_exceptions_are_still_duplicates(self):
        """And an allowance for code that no longer duplicates anything
        is also stale — the entry must be deleted when the duplication
        goes, not left behind as permission."""
        bdvm = (REPO / "src/bdvm/service.py").read_text(encoding="utf-8")
        assert "_TIER_FRACTION" in bdvm, (
            "src/bdvm/service.py no longer defines _TIER_FRACTION — delete its "
            "KNOWN_UNRETIRED entry"
        )
        platforms = (REPO / "src/platforms/assets.py").read_text(encoding="utf-8")
        assert "def canonical_pick_id" in platforms, (
            "src/platforms/assets.py no longer defines canonical_pick_id — delete its "
            "KNOWN_UNRETIRED entry"
        )
        ffpc = (REPO / "src/platforms/ffpc/parser.py").read_text(encoding="utf-8")
        assert 'f"pick:' in ffpc, (
            "src/platforms/ffpc/parser.py no longer mints a pick id inline — delete its "
            "KNOWN_UNRETIRED entry"
        )

    def test_the_contract_derives_its_tier_centres_from_the_owner(self):
        """The fourth copy, retired 2026-08-17 as an exact identity."""
        text = (SRC / "api" / "data_contract.py").read_text(encoding="utf-8")
        assert (
            'tier_centre_slot = {"Early": 2, "Mid": 6, "Late": 10}' not in text
        ), "data_contract.py has regained a hand-written tier-centre table"
        assert (
            "_site_pick_map.slot_tier_ranges(" in text
        ), "data_contract.py no longer derives its tier centres from the owner"


class TestNoSecondPickIdMinter:
    """``pick:``-prefixed identity belongs to ``src/identity/picks.py``."""

    def test_no_new_module_mints_a_pick_prefixed_id(self):
        pattern = re.compile(r'f"pick:')
        offenders = []
        for path in _python_sources():
            rel = _rel(path)
            if rel in KNOWN_UNRETIRED or rel.startswith("src/identity/"):
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{rel}:{i}")
        assert offenders == [], (
            "a `pick:` id is minted outside src/identity/picks.py:\n  "
            + "\n  ".join(offenders)
            + "\nUse LeaguePickIdentity.canonical_id / MarketPickRef.canonical_id."
        )


class TestFrontendTierRangesAreHeldInLockstep:
    """The frontend cannot import the Python owner, so the established
    pattern here is a MIRROR held in lockstep by a parity test — the same
    arrangement ``tests/identity/test_pick_grammar_frontend_parity.py``
    and ``tests/lineup/test_single_owner.py`` already use.

    Without this, ``frontend/lib/trade-logic.js`` carried a hardcoded
    12-team ladder that agreed with the owner and nothing could see it.
    """

    @property
    def _js(self) -> str:
        return (FRONTEND_LIB / "trade-logic.js").read_text(encoding="utf-8")

    def _js_bounds(self) -> tuple[int, int]:
        """The two boundaries the JS ladder actually states."""
        m = re.search(
            r"slot\s*<=\s*(\d+)\s*\?\s*[\"']early[\"']\s*:\s*slot\s*<=\s*(\d+)\s*\?"
            r"\s*[\"']mid[\"']\s*:\s*[\"']late[\"']",
            self._js,
        )
        assert m, (
            "the tier ladder in frontend/lib/trade-logic.js changed shape — re-derive "
            "this parity check against whatever replaced it"
        )
        return int(m.group(1)), int(m.group(2))

    def test_the_js_ladder_matches_the_owner(self):
        js_early_end, js_mid_end = self._js_bounds()
        ranges = owner.slot_tier_ranges(12)
        assert (
            js_early_end == ranges["early"][1]
        ), f"JS says early ends at {js_early_end}; the owner says {ranges['early'][1]}"
        assert (
            js_mid_end == ranges["mid"][1]
        ), f"JS says mid ends at {js_mid_end}; the owner says {ranges['mid'][1]}"

    def test_every_slot_agrees_end_to_end(self):
        """Not just the boundaries — walk all twelve.

        The JS side of this comparison is parsed FROM THE JS.  An earlier
        cut derived both sides from the owner, which made it tautological
        — it passed under a mutation that moved the JS boundary, and the
        mutation proof is what exposed it.
        """
        js_early_end, js_mid_end = self._js_bounds()
        for slot in range(1, 13):
            js = "early" if slot <= js_early_end else ("mid" if slot <= js_mid_end else "late")
            assert js == owner.slot_to_tier(
                slot, 12
            ), f"slot {slot}: JS says {js}, the owner says {owner.slot_to_tier(slot, 12)}"


@pytest.mark.parametrize(
    "name",
    ["slot_tier_ranges", "slot_to_tier", "parse_pick_label", "build_site_pick_map", "PICK_TIERS"],
)
def test_the_owner_still_exposes_its_contract(name: str):
    assert getattr(owner, name, None) is not None, f"src/picks/site_pick_map.py lost {name}"
