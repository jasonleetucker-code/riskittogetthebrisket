"""The market gap does not measure retail against itself — B10-T3a.

THE SIGNAL
──────────
``marketGapDirection`` / ``marketGapMagnitude`` answer: *does the retail
market price this player above or below where the experts have him?*
It is the input to /edge's premium and buy-low labels and to
``MARKET_GAP_MIN_VALUE_RATIO`` in ``config/thresholds.json``.

The whole signal rests on the two sides being **different bodies of
evidence**. ``_compute_market_gap`` split them by the ``is_retail``
registry flag — today exactly ``ktcSfTep`` — and put *every other*
registered source on the consensus side.

THE DEFECT
──────────
``fantasyNavigatorSf`` is not another opinion. The registry declares it
``correlation_group: "ktc"`` and its own comment at
``data_contract.py:1129-1133`` says it *"republishes KTC-derived
numbers"*. It was landing on the **consensus** side.

Measured on the tracked 2026-08-14 export, built through
``build_api_data_contract``:

* **437 rows** carried a retail source and had ``fantasyNavigatorSf`` on
  the consensus side — i.e. retail was being compared against a
  consensus that contains retail;
* moving it to the side it belongs to changes the magnitude on **364
  rows** — median 0.055, p90 0.148, max 0.545 — and **flips the
  direction on 72**. Brandon Aiyuk and Tyreek Hill both go
  ``consensus_premium`` → ``retail_premium``: the published signal was
  pointing the wrong way.

This is the anti-circularity requirement in its plainest form. A body of
evidence affects a conclusion once, and it cannot sit on both sides of a
comparison drawn to measure disagreement *with itself*.

THE FIX, AND WHY IT IS RECLASSIFY RATHER THAN DROP
───────────────────────────────────────────────────
``fantasyNavigatorSf`` is not noise to be discarded — it is
**retail-derived evidence**, so it informs the retail estimate. The
split is therefore taken over the retail *family*
(``expand_correlation_groups``), not the retail *keys*. Dropping it
instead would throw away a real observation to fix a bookkeeping error.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.api.data_contract import (
    _compute_market_gap,
    _retail_source_keys,
    build_api_data_contract,
    correlation_group_for,
    expand_correlation_groups,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def _contract() -> dict:
    candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data*.json"), reverse=True)
    if not candidates:
        pytest.skip("no export available in this environment")
    return build_api_data_contract(json.loads(candidates[0].read_text(encoding="utf-8")))


class TestTheTwoSidesAreDifferentBodiesOfEvidence:
    def test_no_consensus_source_shares_a_family_with_a_retail_source(self):
        """The invariant, asserted over the live board.

        Stated as a property of the SIDES rather than as "fantasyNavigatorSf
        is excluded", so declaring a future retail-derived source into the
        family is enough to protect the signal — no second edit here.
        """
        contract = _contract()
        retail_families = {correlation_group_for(k) for k in _retail_source_keys()}

        offenders: list[tuple[str, list[str]]] = []
        for row in contract["playersArray"]:
            source_ranks = row.get("sourceRanks") or {}
            if not (set(source_ranks) & set(_retail_source_keys())):
                continue
            leaked = [
                key
                for key in source_ranks
                if key not in _retail_source_keys()
                and correlation_group_for(key) in retail_families
            ]
            if leaked:
                offenders.append((str(row.get("displayName")), leaked))

        assert not offenders, (
            f"{len(offenders)} rows measure the retail market against a consensus that "
            f"contains a member of the retail family, e.g. {offenders[:3]}"
        )


class TestTheSplitIsTakenOverFamilies:
    """Unit-level, so the property holds without needing an export."""

    #: One retail source, one source declared into its family, one
    #: genuinely independent source. Values chosen so the two possible
    #: splits give visibly different answers.
    SOURCE_RANKS = {"ktcSfTep": 1, "fantasyNavigatorSf": 2, "idpTradeCalc": 3}
    META = {
        "ktcSfTep": {"valueContribution": 9000.0},
        "fantasyNavigatorSf": {"valueContribution": 8800.0},
        "idpTradeCalc": {"valueContribution": 5000.0},
    }

    def test_the_derived_source_is_priced_with_retail_not_against_it(self):
        direction, magnitude = _compute_market_gap(self.SOURCE_RANKS, self.META)

        # Retail side = mean(9000, 8800) = 8900; consensus = 5000.
        # If the derived source had stayed on the consensus side the
        # consensus mean would be mean(8800, 5000) = 6900 and the gap
        # would be much smaller.
        assert direction == "retail_premium"
        assert magnitude == pytest.approx(abs(8900.0 - 5000.0) / 5000.0, rel=1e-6)

    def test_a_row_with_only_the_derived_source_has_no_consensus_side(self):
        """`fantasyNavigatorSf` alone is a retail reading, not a consensus.

        Reporting a gap here would be comparing retail against nothing and
        calling the result agreement — the missing-is-not-zero rule applied
        to a comparison rather than to a value.
        """
        direction, magnitude = _compute_market_gap(
            {"fantasyNavigatorSf": 2},
            {"fantasyNavigatorSf": {"valueContribution": 8800.0}},
        )
        assert direction == "none"
        assert magnitude is None

    def test_the_retail_family_is_what_the_helper_resolves(self):
        assert expand_correlation_groups(_retail_source_keys()) >= {
            "ktcSfTep",
            "fantasyNavigatorSf",
        }
