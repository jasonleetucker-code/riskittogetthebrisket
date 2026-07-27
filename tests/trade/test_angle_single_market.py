"""Angle finder must price a package inside ONE market.

``src/trade/angle.py`` routes each PLAYER to the board its position
indexes (``_market_source_for``): IDP to ``idpTradeCalc``, everything
else to ``ktcSfTep``.  That part was always right.  What was wrong is
what happened next — the package total was a plain ``sum`` over that
per-player list, so a package holding a TE and a linebacker added a
KTC number to an IDPTC number and produced a total that corresponds to
no board anyone trades against.

The numbers in these fixtures are the real 2026-07-26 board rather than
round figures, because the size of the error depends on the one place
the two boards genuinely diverge.  Brock Bowers is KTC 9,882 and IDPTC
8,975 — a TE-premium gap of 907 points, matching the measured
per-position ratio of 0.895 in
``src/league_intel/cross_market.POSITION_SCALE_RATIOS``.  Pair him with
Carson Schwesinger (IDPTC 5,667, unpriced by KTC, as every IDP is) and
the mixed sum is 15,549 against a single-market IDPTC total of 14,642.
A test built on QB/WR fixtures would pass either way — the pooled
offense ratio is 0.9997 — and would therefore have proven nothing.
"""

from __future__ import annotations

import unittest

from src.league_intel.cross_market import (
    MARKET_IDPTC,
    MARKET_KTC,
    NormalizationStrategy,
    PackageValuation,
)
from src.trade import angle as angle_mod
from src.trade.angle import find_acquisition_packages, find_angle_packages


# ── Fixtures: real 2026-07-26 values for the divergent cases ─────────

BOWERS_KTC = 9882.0
BOWERS_IDPTC = 8975.0
SCHWESINGER_IDPTC = 5667.0

MIXED_KTC_PLUS_IDPTC_SUM = BOWERS_KTC + SCHWESINGER_IDPTC  # 15549 — wrong
MIXED_SINGLE_MARKET_TOTAL = BOWERS_IDPTC + SCHWESINGER_IDPTC  # 14642 — right


def _row(name, position, my_value, *, ktc=None, idptc=None):
    sites = {}
    if ktc is not None:
        sites["ktcSfTep"] = ktc
    if idptc is not None:
        sites["idpTradeCalc"] = idptc
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "rankDerivedValue": my_value,
        "canonicalSiteValues": sites,
    }


def _board():
    return [
        # ── my roster (owner-me) ──
        _row("Brock Bowers", "TE", 9881, ktc=BOWERS_KTC, idptc=BOWERS_IDPTC),
        _row("Carson Schwesinger", "LB", 6099, idptc=SCHWESINGER_IDPTC),
        _row("Justin Jefferson", "WR", 8382, ktc=7607, idptc=7674),
        _row("Chris Olave", "WR", 5757, ktc=5490, idptc=5534),
        _row("Bench Filler", "RB", 900, ktc=880, idptc=875),
        # ── opposing roster (owner-them) ──
        _row("Puka Nacua", "WR", 11000, ktc=9000, idptc=9100),
        _row("Fred Warner", "LB", 7000, idptc=6200),
        _row("Malik Nabers", "WR", 9500, ktc=8600, idptc=8700),
        _row("Their Filler", "RB", 1200, ktc=1150, idptc=1140),
        # Tuned to land INSIDE the gate's uncertainty band against a
        # Chris Olave offer: +2.0% market gain against a 5% gate, with
        # a ±940-point band on a 5,600-point IDP total.  That is the
        # coin-flip case compare_packages exists to refuse.
        _row("Zaven Collins", "LB", 7000, idptc=5600),
    ]


def _teams():
    return [
        {
            "name": "Mine",
            "ownerId": "owner-me",
            "players": [
                "Brock Bowers",
                "Carson Schwesinger",
                "Justin Jefferson",
                "Chris Olave",
                "Bench Filler",
            ],
        },
        {
            "name": "Theirs",
            "ownerId": "owner-them",
            "players": [
                "Puka Nacua",
                "Fred Warner",
                "Malik Nabers",
                "Their Filler",
                "Zaven Collins",
            ],
        },
    ]


def _offer(names, **kw):
    return find_angle_packages(_board(), names, "owner-me", _teams(), **kw)


def _acquire(names, **kw):
    return find_acquisition_packages(_board(), names, "owner-me", _teams(), **kw)


class TestOfferSideIsSingleMarket(unittest.TestCase):
    def test_mixed_offer_total_is_not_the_two_board_sum(self):
        """The defect, stated as an assertion.

        Pre-fix this total is 15,549: KTC's Bowers plus IDPTC's
        Schwesinger.  There is no board on which those two numbers are
        denominated in the same unit.
        """
        offer = _offer(["Brock Bowers", "Carson Schwesinger"])["offer"]
        self.assertNotEqual(
            offer["market_total"],
            int(round(MIXED_KTC_PLUS_IDPTC_SUM)),
            "offer market_total is the KTC+IDPTC mixed sum",
        )
        self.assertEqual(offer["market_total"], int(round(MIXED_SINGLE_MARKET_TOTAL)))

    def test_mixed_offer_is_stamped_with_the_market_it_used(self):
        offer = _offer(["Brock Bowers", "Carson Schwesinger"])["offer"]
        self.assertEqual(offer.get("market"), MARKET_IDPTC)
        self.assertEqual(
            offer.get("market_strategy"),
            NormalizationStrategy.SINGLE_MARKET.value,
        )

    def test_mixed_offer_player_rows_report_the_package_market(self):
        """Per-player labels must agree with the total above them.

        The UI renders ``market_source`` as a KTC/IDPTC badge next to
        each player.  If Bowers is badged KTC while the package total
        is an IDPTC total, the page is showing its own arithmetic as
        inconsistent.
        """
        offer = _offer(["Brock Bowers", "Carson Schwesinger"])["offer"]
        by_name = {p["name"]: p for p in offer["players"]}
        self.assertEqual(by_name["Brock Bowers"]["market_source"], MARKET_IDPTC)
        self.assertEqual(by_name["Brock Bowers"]["market_value"], int(BOWERS_IDPTC))
        self.assertEqual(by_name["Carson Schwesinger"]["market_source"], MARKET_IDPTC)

    def test_offense_only_offer_still_values_on_ktc(self):
        """The 5%-of-users case must not move.

        ``ktcSfTep`` is the canonical retail anchor for an offense-only
        package and nothing about this fix should touch it.
        """
        offer = _offer(["Justin Jefferson", "Chris Olave"])["offer"]
        self.assertEqual(offer["market_total"], 7607 + 5490)
        self.assertEqual(offer.get("market"), MARKET_KTC)
        for p in offer["players"]:
            self.assertEqual(p["market_source"], MARKET_KTC)

    def test_offense_only_offer_carries_no_uncertainty_band(self):
        """No conversion and no cross-universe assumption -> no band.

        This is what keeps the ``compare_packages`` certainty check
        from suppressing the default offense-only path: a zero band
        cannot straddle the gate.
        """
        offer = _offer(["Justin Jefferson", "Chris Olave"])["offer"]
        self.assertEqual(offer.get("market_uncertainty_band"), 0)

    def test_mixed_offer_carries_a_nonzero_uncertainty_band(self):
        offer = _offer(["Brock Bowers", "Carson Schwesinger"])["offer"]
        self.assertGreater(offer.get("market_uncertainty_band") or 0, 0)


class TestCounterSideIsSingleMarket(unittest.TestCase):
    def test_mixed_counter_package_total_is_single_market(self):
        """``include_idp=True`` admits IDP into the counter pool.

        Once it does, the counter combos hit exactly the same mixed-sum
        bug the offer side had.
        """
        res = _offer(
            ["Justin Jefferson", "Chris Olave"],
            include_idp=True,
            min_my_gain_pct=-1e9,
            max_market_gain_pct=1e9,
            per_team_limit=10**6,
            limit=10**6,
        )
        mixed = [
            c
            for c in res["candidates"]
            if {p["name"] for p in c["players"]} == {"Puka Nacua", "Fred Warner"}
        ]
        self.assertTrue(mixed, "expected a Nacua+Warner counter package")
        cand = mixed[0]
        self.assertEqual(cand["market_total"], int(round(9100 + 6200)))
        self.assertNotEqual(cand["market_total"], int(round(9000 + 6200)))
        self.assertEqual(cand.get("market"), MARKET_IDPTC)
        for p in cand["players"]:
            self.assertEqual(p["market_source"], MARKET_IDPTC)

    def test_offense_only_counter_package_unchanged(self):
        res = _offer(
            ["Justin Jefferson", "Chris Olave"],
            min_my_gain_pct=-1e9,
            max_market_gain_pct=1e9,
            per_team_limit=10**6,
            limit=10**6,
        )
        pair = [
            c
            for c in res["candidates"]
            if {p["name"] for p in c["players"]} == {"Puka Nacua", "Malik Nabers"}
        ]
        self.assertTrue(pair)
        self.assertEqual(pair[0]["market_total"], 9000 + 8600)
        self.assertEqual(pair[0].get("market"), MARKET_KTC)


class TestAcquireSideIsSingleMarket(unittest.TestCase):
    def test_mixed_acquire_side_total_is_single_market(self):
        acq = _acquire(["Puka Nacua", "Fred Warner"])["acquire"]
        self.assertNotEqual(acq["market_total"], int(round(9000 + 6200)))
        self.assertEqual(acq["market_total"], int(round(9100 + 6200)))
        self.assertEqual(acq.get("market"), MARKET_IDPTC)

    def test_mixed_offer_combo_on_acquire_path_is_single_market(self):
        res = _acquire(
            ["Puka Nacua", "Malik Nabers"],
            include_idp=True,
            min_my_gain_pct=-1e9,
            max_market_gain_pct=1e9,
            limit=10**6,
        )
        mixed = [
            c
            for c in res["candidates"]
            if {p["name"] for p in c["players"]} == {"Brock Bowers", "Carson Schwesinger"}
        ]
        self.assertTrue(mixed, "expected a Bowers+Schwesinger offer package")
        self.assertEqual(mixed[0]["market_total"], int(round(MIXED_SINGLE_MARKET_TOTAL)))
        self.assertNotEqual(mixed[0]["market_total"], int(round(MIXED_KTC_PLUS_IDPTC_SUM)))


class TestVerdictCertainty(unittest.TestCase):
    """``compare_packages`` decides whether the gate verdict survives.

    Angle's ±5% gate is a threshold crossing, so a band only matters
    relative to distance from that threshold.  Offense-only packages
    carry a zero band and are certain by construction — that is what
    keeps the default path untouched.  IDP-bearing ones are not.
    """

    def test_offense_only_path_is_never_withheld(self):
        res = _offer(
            ["Justin Jefferson", "Chris Olave"],
            per_team_limit=10**6,
            limit=10**6,
        )
        diag = res["market_diagnostics"]
        self.assertEqual(diag["withheld_uncertain"], 0)
        self.assertEqual(diag["unvaluable"], 0)
        self.assertGreater(diag["combos_valued"], 0)

    def test_idp_counter_at_the_gate_is_withheld_with_a_reason(self):
        """An all-IDP counter against an all-offense offer.

        The whole comparison rests on the assumed offense<->IDP
        exchange rate, so a gain sitting a couple of points from the
        gate is not a decision — it is a coin flip.  Withheld, counted,
        and the reason kept where a caller can render it.
        """
        res = _offer(
            ["Chris Olave"],
            include_idp=True,
            per_team_limit=10**6,
            limit=10**6,
        )
        diag = res["market_diagnostics"]
        self.assertGreater(diag["withheld_uncertain"], 0)
        self.assertTrue(diag["reasons"])
        blob = " ".join(diag["reasons"]) + " " + " ".join(res["warnings"])
        self.assertIn("uncertainty band", blob)
        # Withheld means withheld — the coin-flip package is absent.
        for c in res["candidates"]:
            self.assertNotIn("Zaven Collins", {p["name"] for p in c["players"]})

    def test_fixed_side_carries_the_prose_and_candidates_do_not(self):
        """~500 chars of measured/assumed wording, once, not 50 times.

        The fixed side is where a reader looks for provenance; copying
        it onto every candidate adds tens of KB to the response and
        says nothing the offer block has not already said.
        """
        res = _offer(
            ["Brock Bowers", "Carson Schwesinger"],
            per_team_limit=10**6,
            limit=10**6,
        )
        self.assertIn("market_warnings", res["offer"])
        self.assertTrue(res["offer"]["market_warnings"])
        self.assertIn("market_normalization_version", res["offer"])
        for c in res["candidates"]:
            self.assertNotIn("market_warnings", c)
            self.assertIn("market", c)
            self.assertIn("market_uncertainty_band", c)

    def test_surviving_candidates_publish_their_uncertainty_range(self):
        res = _offer(
            ["Justin Jefferson", "Chris Olave"],
            per_team_limit=10**6,
            limit=10**6,
        )
        self.assertTrue(res["candidates"])
        for c in res["candidates"]:
            self.assertIn("market_gain_low_pct", c)
            self.assertIn("market_gain_high_pct", c)
            self.assertEqual(c["market_uncertainty_band"], 0)


class TestUnvaluablePackagesAreNotSummed(unittest.TestCase):
    """A package with no defensible single-market total must not get one.

    Honest note on reachability: with ``allow_scalar_fallback`` left at
    its default, ``value_package`` can only return SUPPRESSED for an
    empty package or for an asset priced by neither board — and
    ``angle._value_pair`` already drops any row whose own market has no
    value, so the second case cannot arrive through the live path
    today.  The branch is therefore defensive rather than load-bearing,
    and these tests say so by reaching it deliberately: one through the
    empty-offer path that IS live, one by substituting the valuation so
    the handling itself is exercised.  The thing being pinned is that
    the handling exists and excludes rather than silently falling back
    to the mixed sum.
    """

    def test_empty_offer_yields_no_candidates_and_a_reason(self):
        res = _offer(["Nobody At All"])
        self.assertEqual(res["candidates"], [])
        self.assertTrue(res["warnings"])

    def test_suppressed_valuation_excludes_rather_than_sums(self):
        suppressed = PackageValuation(
            strategy=NormalizationStrategy.SUPPRESSED,
            market=None,
            total=None,
            suppressed_reason="fixture: priced on neither market",
            label="Cannot be valued on a single market",
        )
        original = angle_mod.value_package
        try:
            angle_mod.value_package = lambda rows, **kw: suppressed
            res = _offer(
                ["Justin Jefferson", "Chris Olave"],
                min_my_gain_pct=-1e9,
                max_market_gain_pct=1e9,
                per_team_limit=10**6,
                limit=10**6,
            )
        finally:
            angle_mod.value_package = original
        self.assertEqual(res["candidates"], [])
        self.assertEqual(res["offer"]["market_total"], 0)
        self.assertIsNone(res["offer"].get("market"))
        blob = " ".join(res["warnings"])
        self.assertIn("single market", blob.lower())

    def test_unvaluable_counter_is_counted_not_dropped_silently(self):
        """A withheld counter has to leave a trace the caller can render."""
        suppressed = PackageValuation(
            strategy=NormalizationStrategy.SUPPRESSED,
            market=None,
            total=None,
            suppressed_reason="fixture: priced on neither market",
            label="Cannot be valued on a single market",
        )
        real = angle_mod.value_package
        calls = {"n": 0}

        def _fake(rows, **kw):
            calls["n"] += 1
            # First call is the offer side; keep it valuable so the
            # search proceeds and the COUNTER side is what gets
            # suppressed.
            return real(rows, **kw) if calls["n"] == 1 else suppressed

        try:
            angle_mod.value_package = _fake
            res = _offer(
                ["Justin Jefferson", "Chris Olave"],
                min_my_gain_pct=-1e9,
                max_market_gain_pct=1e9,
                per_team_limit=10**6,
                limit=10**6,
            )
        finally:
            angle_mod.value_package = real
        self.assertEqual(res["candidates"], [])
        diag = res.get("market_diagnostics") or {}
        self.assertGreater(diag.get("unvaluable") or 0, 0)


if __name__ == "__main__":
    unittest.main()
