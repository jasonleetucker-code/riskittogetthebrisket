"""The compact view must not ship one weight without the other.

WHY THIS EXISTS
===============
``sourceRankMeta`` carries two weights, stamped side by side in
``data_contract.py``, and they are not the same number:

* ``appliedWeight`` — what the count-aware blend actually multiplies
  this source's vote by. The number doing the work.
* ``effectiveWeight`` — the depth-scaled coverage DIAGNOSTIC
  (declared x min(1, depth/60)). ``docs/open-modeling-decisions.md``
  decision #1 is the *measured* call not to apply it; the contract's
  own methodology text says "never applied to the blend".

``_SLIM_SOURCE_RANK_META_FIELDS`` carried ``effectiveWeight`` alone.
Measured on the pinned 2026-07-30 contract:

    sourceRankMeta entries carrying BOTH weights   6,461
    ...on which the two genuinely DIFFER             147
    shipped to the compact view          effectiveWeight only

So mobile rendered the deliberately-inert diagnostic on every entry,
and on 147 of them it was a *different* number from the applied one.
The desktop fix made the asymmetry sharper rather than smaller:
``board-sections.jsx`` now labels them honestly ("Weight (applied)"
ahead of "Coverage wt (diagnostic)"), but on the compact view the
honest row cannot render at all, because the field never arrives.
That is the same defect one surface over.

WHAT COULD DISAGREE WITH IT, BEFORE
===================================
Nothing. ``tests/api/test_compact_view.py`` asserted
``ktc_meta["effectiveWeight"] == 1.0`` on a fixture that did not carry
an ``appliedWeight`` at all — the fixture mirrored the buggy set, so
the shape it pinned was the shape of the defect.

WHAT THIS ASSERTS
=================
Symmetry, not membership: **whenever the slim set ships one weight it
ships the other.** Phrased that way, dropping either one goes red and
a future decision to ship neither (a genuine payload call) stays legal
— what is illegal is shipping exactly the one that is not applied.

Non-vacuity is explicit, in two places: the fixture's two weights must
actually differ (otherwise the round-trip assertion would pass on a
copy of the wrong field), and the backend must actually stamp both
(otherwise the slim-set entry would be a no-op).

Cost, measured on the pinned contract so it is on the record rather
than waved through: +258,440 B raw, **+5,105 B gzipped** on a 697 KB
compact payload — +0.73% over the wire, and production runs
GZipMiddleware.

NOT ``livedata``-marked: pure logic over a fixture and the source
tree, must block.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.api import compact_view as cv

REPO_ROOT = Path(__file__).resolve().parents[2]

_WEIGHT_FIELDS = ("appliedWeight", "effectiveWeight")


def _contract_with_differing_weights() -> dict:
    """One source whose two weights differ, one where they agree.

    ``dlfSf`` mirrors the live shape that motivated this: 147 of the
    6,461 entries on the pinned contract have a depth-scaled
    ``effectiveWeight`` below the ``appliedWeight`` of 1.0.
    """
    return {
        "players": {
            "Josh Allen": {
                "name": "Josh Allen",
                "rankDerivedValue": 9200,
                "sourceRankMeta": {
                    "ktcSfTep": {
                        "valueContribution": 9100,
                        "appliedWeight": 1.0,
                        "effectiveWeight": 1.0,
                        "method": "value_direct",
                        "percentile": 0.0001,
                    },
                    "dlfSf": {
                        "valueContribution": 8800,
                        "appliedWeight": 1.0,
                        "effectiveWeight": 0.4667,
                        "method": "rank_hill",
                        "percentile": 0.002,
                    },
                },
            }
        },
        "playersArray": [
            {
                "displayName": "Josh Allen",
                "rankDerivedValue": 9200,
                "sourceRankMeta": {
                    "dlfSf": {
                        "valueContribution": 8800,
                        "appliedWeight": 1.0,
                        "effectiveWeight": 0.4667,
                        "method": "rank_hill",
                    },
                },
            }
        ],
    }


class TestTheFixtureIsNotVacuous(unittest.TestCase):
    def test_the_two_weights_actually_differ_on_the_fixture(self) -> None:
        """Without this, every assertion below would pass against a
        payload in which ``appliedWeight`` was a copy of the diagnostic
        — which is precisely the confusion being guarded against."""
        meta = _contract_with_differing_weights()["players"]["Josh Allen"]["sourceRankMeta"]
        self.assertNotEqual(meta["dlfSf"]["appliedWeight"], meta["dlfSf"]["effectiveWeight"])

    def test_the_backend_still_stamps_both_weights(self) -> None:
        """The slim set can only ship a field the pipeline stamps.

        If ``appliedWeight`` stopped being stamped, adding it to the
        slim set would be a silent no-op and this module would be
        asserting over a field that never exists — green, and useless.
        """
        src = (REPO_ROOT / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
        for field in _WEIGHT_FIELDS:
            self.assertRegex(
                src,
                rf'meta\[[\'"]{field}[\'"]\]\s*=',
                msg=(
                    f"data_contract.py no longer stamps sourceRankMeta.{field}. "
                    "The compact view's slim set cannot ship a field the pipeline "
                    "does not produce — revisit both together."
                ),
            )


class TestSlimSetShipsWeightsTogether(unittest.TestCase):
    def test_neither_weight_ships_without_the_other(self) -> None:
        present = [f for f in _WEIGHT_FIELDS if f in cv._SLIM_SOURCE_RANK_META_FIELDS]
        self.assertIn(
            len(present),
            (0, 2),
            msg=(
                f"_SLIM_SOURCE_RANK_META_FIELDS ships {present} and omits "
                f"{[f for f in _WEIGHT_FIELDS if f not in present]}. The two weights "
                "are different numbers on 147 of the 6,461 sourceRankMeta entries of "
                "the live contract, and only appliedWeight is applied to the blend. "
                "Ship both or neither — never the diagnostic alone."
            ),
        )

    def test_the_applied_weight_is_the_one_currently_shipped(self) -> None:
        """The state this fix establishes, stated positively.

        Kept separate from the symmetry assertion above so a future
        payload decision to drop BOTH weights fails here — loudly, on a
        test whose name says what is being given up — rather than
        sliding through the symmetry check unnoticed.
        """
        self.assertIn("appliedWeight", cv._SLIM_SOURCE_RANK_META_FIELDS)


class TestCompactPayloadCarriesBoth(unittest.TestCase):
    def test_players_dict_entry_keeps_both_weights_unchanged(self) -> None:
        out = cv.compact_contract(_contract_with_differing_weights())
        meta = out["players"]["Josh Allen"]["sourceRankMeta"]["dlfSf"]
        self.assertEqual(meta["appliedWeight"], 1.0)
        self.assertEqual(meta["effectiveWeight"], 0.4667)
        # Still slimmed — this is not a licence to stop pruning.
        self.assertNotIn("percentile", meta)

    def test_players_array_entry_keeps_both_weights(self) -> None:
        out = cv.compact_contract(_contract_with_differing_weights())
        meta = out["playersArray"][0]["sourceRankMeta"]["dlfSf"]
        self.assertEqual(meta["appliedWeight"], 1.0)
        self.assertEqual(meta["effectiveWeight"], 0.4667)

    def test_a_reader_of_the_compact_view_can_tell_the_two_apart(self) -> None:
        """The user-facing consequence, asserted directly.

        ``board-sections.jsx`` renders "Weight (applied)" only when
        ``meta.appliedWeight != null``. With the field pruned that row
        vanishes and the compact view shows the diagnostic under a
        label that admits it is one — leaving no applied number on the
        screen at all.
        """
        out = cv.compact_contract(_contract_with_differing_weights())
        meta = out["players"]["Josh Allen"]["sourceRankMeta"]["dlfSf"]
        rendered = {k: v for k, v in meta.items() if k in _WEIGHT_FIELDS}
        self.assertEqual(
            len(set(rendered.values())),
            2,
            msg=(
                f"compact view renders {rendered}: the applied weight and the "
                "diagnostic are indistinguishable, so a mobile reader cannot see "
                "which number the blend used."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
