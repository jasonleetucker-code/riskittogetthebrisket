"""A derived prior may be priced.  It may not be used as evidence.

C1-U6 follow-up 2, repaired 2026-08-16.

``_inject_far_future_pick_sources`` writes cloned, year-stepped values
into ``canonicalSiteValues`` under each vendor's own key so a far-future
pick row can be blended at all.  Those numbers are OURS — classification
PRIOR, family ``measured_vendor_year_step_v1`` — not the vendor's.

The cross-market backbone asks a different question: at which positions
in THIS VENDOR'S OWN published value pool do IDP players sit?  Its answer
translates other sources' ranks onto the shared market.  A synthetic row
sitting in that pool therefore let a derived prior act as market evidence
about OTHER rows, and closed a feedback loop — our derived pick value
shifted the crosswalk, which shifted IDP players' translated votes, which
shifted the blend.  Signal independence forbids exactly that.

The invariant asserted here is the strong form: **for every row that is
not itself the derived pick, the board is identical whether the derived
row is declared synthetic or absent from the board entirely.**  Being on
the board (and priced) is one thing; being counted as an observation is
another, and after this repair only the first is true.

Measured on the 2026-08-16 healthy board when the repair landed: 12
synthetic rows left the pool, the shared-market ladder moved by at most
12 combined ranks (exactly the count removed), 297 rows changed value at
p50 0.085% / p90 0.152%, and two IDP rows moved ~29.5% because a 12-rank
shift crossed the trim boundary of the count-aware blend.  Full record:
``docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md`` §12.
"""

from __future__ import annotations

import copy

import src.api.data_contract as dc


def _row(name: str, position: str, asset_class: str, **site_values):
    return {
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": position,
        "assetClass": asset_class,
        "values": {"overall": None, "rawComposite": None, "finalAdjusted": None},
        "canonicalSiteValues": dict(site_values),
    }


def _board():
    """Offense + IDP + a real pick + one derived far-future pick.

    ``idpTradeCalc`` is the backbone source and prices all four, which is
    the whole reason the shared-market crosswalk exists.
    """
    return [
        _row("Alpha QB", "QB", "offense", idpTradeCalc=9000, ktcSfTep=9000),
        _row("Beta WR", "WR", "offense", idpTradeCalc=7000, ktcSfTep=7000),
        _row("Gamma LB", "LB", "idp", idpTradeCalc=4200, dlfIdp=990000),
        _row("Delta DB", "DB", "idp", idpTradeCalc=3100, dlfIdp=980000),
        _row("Epsilon DL", "DL", "idp", idpTradeCalc=2400, dlfIdp=970000),
        _row("2027 Early 1st", "PICK", "pick", idpTradeCalc=5000, ktcSfTep=5000),
        # The derived one — a value we computed, published under the
        # vendors' keys so the row can be blended.
        _row("2029 Early 1st", "PICK", "pick", idpTradeCalc=3600, ktcSfTep=3600),
    ]


def _values_by_name(rows):
    return {
        r["canonicalName"]: r.get("rankDerivedValue")
        for r in rows
        if r["canonicalName"] != "2029 Early 1st"
    }


def _derivations():
    return {
        dc._canonical_match_key("2029 Early 1st"): {
            "factor": 0.8407,
            "basisYear": 2028,
            "basisName": "2028 Early 1st",
            "family": "measured_vendor_year_step_v1",
            "classification": "PRIOR",
        }
    }


class TestADerivedRowIsNotAnObservation:
    def test_declaring_a_row_synthetic_matches_removing_it_entirely(self):
        """The invariant, in its strongest form.

        Left:  the derived row is on the board and DECLARED synthetic.
        Right: the derived row is not on the board at all.

        Every other row must agree.  If a derived prior were still
        feeding the crosswalk, the left board would differ.
        """
        declared = copy.deepcopy(_board())
        dc._compute_unified_rankings(declared, {}, synthetic_pick_derivations=_derivations())

        absent = [r for r in copy.deepcopy(_board()) if r["canonicalName"] != "2029 Early 1st"]
        dc._compute_unified_rankings(absent, {})

        assert _values_by_name(declared) == _values_by_name(absent)

    def test_the_derived_row_is_still_priced(self):
        """Withdrawing it as EVIDENCE must not withdraw its VALUE.

        C1-PICK-01 requires every valid pick through the horizon to hold
        a finite canonical value; this repair is about what the row
        proves, never about whether it is priced.
        """
        rows = copy.deepcopy(_board())
        dc._compute_unified_rankings(rows, {}, synthetic_pick_derivations=_derivations())
        derived = next(r for r in rows if r["canonicalName"] == "2029 Early 1st")
        value = derived.get("rankDerivedValue")
        assert isinstance(value, (int, float)) and value > 0, derived

    def test_an_undeclared_pick_row_is_still_evidence(self):
        """The boundary, from the other side.

        A vendor-published pick row is a real observation on that
        vendor's own scale and stays in the pool.  If this test ever
        passes trivially — i.e. the two boards agree — the filter has
        stopped discriminating and is excluding nothing, or everything.
        """
        with_pick = copy.deepcopy(_board())
        dc._compute_unified_rankings(with_pick, {}, synthetic_pick_derivations=_derivations())

        without_pick = [
            r
            for r in copy.deepcopy(_board())
            if r["canonicalName"] not in {"2027 Early 1st", "2029 Early 1st"}
        ]
        dc._compute_unified_rankings(without_pick, {})

        left = {k: v for k, v in _values_by_name(with_pick).items() if k != "2027 Early 1st"}
        right = {k: v for k, v in _values_by_name(without_pick).items()}
        assert left != right, (
            "removing a VENDOR-PUBLISHED pick row changed nothing, so the "
            "evidence pool is not actually reading pick rows and the test above "
            "would pass for the wrong reason"
        )
