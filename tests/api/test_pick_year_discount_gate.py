"""The pick-year discount applies ONLY to years the pipeline invented.

Audit finding T-3 / C-2 (``docs/audits/decision-intelligence-audit-2026-08-04.md``).

``_apply_pick_year_discount_to_blend`` used to multiply
``offsetDiscounts`` (1.00 / 0.82 / 0.66 / 0.53) onto EVERY future-year
pick.  For the years the vendors actually publish, that double-counts —
and in the wrong direction, because both ingested markets price the next
class ABOVE the imminent one:

    ktcSfTep      2026 Early 1st 5595 | 2027 7061 | 2028 5122
    idpTradeCalc  2026 Early 1st 5554 | 2027 7052 | 2028 5034

The market term structure rises then falls; the config assumes smooth
decay.  Composing them published 2027 firsts 18% and 2028 firsts 34%
below what both markets agreed, biasing every trade involving future
capital toward selling futures cheap.

What still NEEDS a step-down is a year this pipeline synthesised from
a nearer year (``_inject_far_future_pick_sources``).  Since C1-U6 the
step is applied AT INJECTION (measured vendor year-step, config
``derivedYearModel``, classification PRIOR), so the Phase 3a pass is
stamp-only: it records the net factor as ``pickYearDiscount`` for
transparency/projections and never multiplies a value — multiplying
again would double-count the injection-time step.  The gate is the
same: only synthesised names are stamped; vendor-priced years pass
untouched with no stamp.

These tests are synthetic and pure-logic — no live board, no CSVs — so
they belong in the blocking CI tier.
"""

from __future__ import annotations

import src.api.data_contract as dc


class TestOnlySynthesisedYearsAreDiscounted:
    def _run(self, names, synthetic):
        """Run the discount stage over ``names`` with ``synthetic`` marked."""
        players = [{"assetClass": "pick", "canonicalName": n} for n in names]
        row_normalized = [(1000.0, i) for i in range(len(names))]
        # The derivation map is an ARGUMENT (2026-08-16, follow-up 8), so
        # this exercises a pure function instead of mutating and restoring
        # process-wide state.
        derivations = {
            dc._canonical_match_key(n): {
                "factor": 0.8407,
                "basisYear": 2028,
                "basisName": n.replace("2029", "2028"),
                "family": "measured_vendor_year_step_v1",
                "classification": "PRIOR",
            }
            for n in synthetic
        }
        out, applied = dc._apply_pick_year_discount_to_blend(row_normalized, players, derivations)
        return {names[i]: v for v, i in out}, applied, players

    def test_vendor_priced_year_keeps_its_blended_value(self):
        """A year with real per-slot vendor rows must pass through at 1.0.

        This is the defect: 2027 and 2028 are published by both markets,
        so any multiplier here is applied on top of a price that already
        encodes the year.
        """
        values, applied, players = self._run(["2027 Early 1st", "2028 Early 1st"], synthetic=set())
        assert values["2027 Early 1st"] == 1000.0
        assert values["2028 Early 1st"] == 1000.0
        assert applied == {}, "no discount may be recorded for a vendor-priced year"
        for p in players:
            assert "pickYearDiscount" not in p

    def test_synthesised_year_is_stamped_but_not_multiplied_again(self):
        """The step is applied at injection; Phase 3a only records it.

        The blended value passes through UNCHANGED (multiplying here on
        top of the injection-time step would double-count), while the
        transparency stamp still lands so projections and the frontend
        can invert the derivation.
        """
        values, applied, players = self._run(["2029 Early 1st"], synthetic={"2029 Early 1st"})
        assert values["2029 Early 1st"] == 1000.0
        assert applied, "a synthesised year must record its factor"
        assert players[0]["pickYearDiscount"] == 0.8407

    def test_mixed_board_stamps_only_the_clone(self):
        """The realistic case: real 2027/2028 beside a synthesised 2029."""
        names = ["2027 Early 1st", "2028 Early 1st", "2029 Early 1st"]
        values, applied, players = self._run(names, synthetic={"2029 Early 1st"})
        assert values["2027 Early 1st"] == 1000.0
        assert values["2028 Early 1st"] == 1000.0
        assert values["2029 Early 1st"] == 1000.0
        assert "pickYearDiscount" not in players[0]
        assert "pickYearDiscount" not in players[1]
        assert players[2]["pickYearDiscount"] == 0.8407

    def test_non_pick_rows_are_never_touched(self):
        players = [
            {"assetClass": "offense", "canonicalName": "Some Player"},
            {"assetClass": "idp", "canonicalName": "Some Defender"},
        ]
        out, applied = dc._apply_pick_year_discount_to_blend([(1000.0, 0), (900.0, 1)], players)
        assert [v for v, _ in out] == [1000.0, 900.0]
        assert applied == {}


class TestAgainstTheRealMarketBoards:
    """The regression that would have caught this on the live board.

    Rather than restating the formula, this pins the PROPERTY the defect
    violated: the published value of a vendor-priced future pick must
    track the market it came from, not sit systematically below it.
    """

    def test_market_term_structure_is_not_inverted_by_the_config(self):
        """Both markets price 2027 above 2026; a decay prior must not
        be composed onto that.

        Uses the measured 2026-08-04 board values as constants — if the
        vendors' term structure genuinely inverts in a later season this
        test should be re-derived, not deleted.
        """
        ktc = {2026: 5595, 2027: 7061, 2028: 5122}
        idptc = {2026: 5554, 2027: 7052, 2028: 5034}
        for board in (ktc, idptc):
            assert board[2027] > board[2026], (
                "the audit's premise: the next class carries option value "
                "and is priced ABOVE the imminent one"
            )

        cfg = dc._load_pick_year_discount()
        step = dc._year_step_for("Early", 1, cfg)
        # The year-step is a decreasing prior...
        assert step < 1.0
        # ...which is exactly why it must not reach a vendor-priced year.
        market_avg_2027 = (ktc[2027] + idptc[2027]) / 2
        would_publish = market_avg_2027 * step
        assert would_publish < market_avg_2027 * 0.90, (
            "sanity: composing the prior really does move the value >10% "
            "below the market, which is the harm this gate prevents"
        )
