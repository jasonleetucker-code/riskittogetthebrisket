"""Degraded and hostile inputs to the valuation pipeline.

"Full confidence" lives here more than in the happy path: a scrape
that half-fails, a source that publishes one absurd cell, a vendor
that ties every rank.  None of those should crash, and — more
importantly — none should silently reprice players.

Two guards get explicit regression tests because they are *load
bearing and invisible*:

  * ``_safe_num`` rejecting non-finite values.  It is the only thing
    standing between one ``inf`` cell and a board-wide repricing —
    ``value_source_max`` takes an unbounded max, and the value-direct
    formula divides by it.  See ``TestSiteMaxContamination``.
  * negative / zero source values being dropped rather than voted.

A known **unfixed** gap is characterised (not asserted as correct) in
``TestSiteMaxContamination.test_out_of_range_finite_value_rescales_the_board``
— see ``docs/python-coverage-audit.md``.
"""

from __future__ import annotations

import math
from typing import Any

from src.api import data_contract as dc


IDP_POSITIONS = ("DL", "LB", "DB")


def _row(name: str, position: str, **sites: Any) -> dict[str, Any]:
    if position == "PICK":
        asset_class = "pick"
    elif position in IDP_POSITIONS:
        asset_class = "idp"
    else:
        asset_class = "offense"
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": asset_class,
        "canonicalSiteValues": dict(sites),
        "values": {
            "overall": 0,
            "rawComposite": None,
            "finalAdjusted": None,
            "displayValue": None,
        },
        "sourceCount": 0,
        "sourcePresence": {},
        "rookie": False,
    }


def _anchor_qb() -> dict[str, Any]:
    return _row("Anchor QB", "QB", ktcSfTep=9999, idpTradeCalc=9999)


def _by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["canonicalName"]: r for r in rows}


# ── Empty / absent sources ───────────────────────────────────────────


class TestEmptyAndAbsentSources:
    def test_empty_player_array_does_not_crash(self):
        rows: list[dict[str, Any]] = []
        dc._compute_unified_rankings(rows, {})
        assert rows == []

    def test_rows_with_no_source_coverage_get_no_value(self):
        """A player nobody ranks must be left unvalued, not zero-valued.

        Stamping 0 would place them at the bottom of a real board;
        leaving them unstamped keeps them off it entirely.
        """
        rows = [_row("Ghost", "WR"), _row("Also Ghost", "RB")]
        dc._compute_unified_rankings(rows, {})
        for r in rows:
            assert r.get("rankDerivedValue") is None

    def test_a_source_missing_from_every_row_does_not_disturb_the_others(self):
        """Simulates a source CSV that failed to fetch entirely.

        The surviving sources must produce exactly the values they
        would have produced on their own.
        """
        with_absent = [
            _row("Star", "WR", ktcSfTep=9000, idpTradeCalc=9000),
            _row("Mid", "WR", ktcSfTep=4500, idpTradeCalc=4500),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(with_absent, {})
        got = _by_name(with_absent)
        # Two agreeing value-direct sources ⇒ n=2 mean ⇒ the raw value.
        assert got["Star"]["rankDerivedValue"] == 9000
        assert got["Mid"]["rankDerivedValue"] == 4500

    def test_canonical_site_values_of_none_is_tolerated(self):
        """A row whose site-value map is ``None``, not ``{}``."""
        broken = _row("Broken", "WR")
        broken["canonicalSiteValues"] = None
        rows = [broken, _anchor_qb()]
        dc._compute_unified_rankings(rows, {})
        assert _by_name(rows)["Broken"].get("rankDerivedValue") is None
        # The healthy row is unaffected.
        assert _by_name(rows)["Anchor QB"]["rankDerivedValue"] == 9999


# ── Zero variance ────────────────────────────────────────────────────


class TestZeroVariance:
    """Every value identical — the classic division-by-zero shape."""

    def test_identical_values_across_pool_do_not_divide_by_zero(self):
        rows = [_row(f"Clone {i}", "WR", ktcSfTep=5000, idpTradeCalc=5000) for i in range(5)]
        dc._compute_unified_rankings(rows, {})
        for r in rows:
            # All tied at the top of both boards ⇒ all normalise to 9999.
            assert r["rankDerivedValue"] == 9999
            assert r["sourceSpread"] == 0.0

    def test_identical_values_within_one_player_give_zero_spread(self):
        rows = [
            _row("Agreed", "WR", ktcSfTep=5000, idpTradeCalc=5000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        agreed = _by_name(rows)["Agreed"]
        assert agreed["rankDerivedValue"] == 5000
        assert agreed["sourceSpread"] == 0.0
        # stdev across 2 identical contributions is also 0, not None.
        assert agreed["hillValueSpread"] == 0.0


# ── Non-positive and non-finite values ───────────────────────────────


class TestNonPositiveAndNonFiniteValues:
    def test_negative_zero_and_none_are_all_treated_as_absent(self):
        """A negative site value must not vote, and must not be clamped
        to 0 and voted either — it is missing data, not a cheap player.

        Each of these rows therefore rests on its single remaining
        source (idpTradeCalc=3000) and takes the single-source haircut:
        3000 × 0.30 = 900.
        """
        rows = [
            _row("Neg", "WR", ktcSfTep=-500, idpTradeCalc=3000),
            _row("Zero", "WR", ktcSfTep=0, idpTradeCalc=3000),
            _row("Nil", "WR", ktcSfTep=None, idpTradeCalc=3000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)
        for name in ("Neg", "Zero", "Nil"):
            assert got[name]["rankDerivedValue"] == 900, name
            assert got[name]["singleSourceValuePenaltyApplied"] is True

    def test_safe_num_rejects_non_finite_and_non_numeric(self):
        """``_safe_num`` is the coercion gate every site value passes.

        This is not a trivia test: ``value_source_max`` takes an
        unbounded ``max()`` over these values and the value-direct
        branch divides by it, so an ``inf`` reaching that dict prices
        every player in the source at zero.  Keep this guard.
        """
        assert dc._safe_num(float("inf")) is None
        assert dc._safe_num(float("-inf")) is None
        assert dc._safe_num(float("nan")) is None
        assert dc._safe_num("not-a-number") is None
        assert dc._safe_num(None) is None
        # Booleans are explicitly not numbers here.
        assert dc._safe_num(True) is None
        # Genuine numbers pass through unchanged.
        assert dc._safe_num(4200) == 4200.0
        assert dc._safe_num("4200") == 4200.0


class TestSiteMaxContamination:
    """The value-direct branch is ``raw / site_max × 9999``.

    ``site_max`` is an unbounded max over the pool, so one bad cell in
    a value-based source rescales *every* player in that source.
    """

    def test_non_finite_values_never_become_the_site_max(self):
        """Regression guard for a board-wide repricing.

        Built through the real entry point so the ``_safe_num``
        coercion in ``_canonical_site_values`` is in the path.  Here
        the values must be *identical* with and without the poisoned
        row.

        Removing the ``math.isfinite`` guard breaks this two ways,
        both verified by mutation:
          * via ``build_api_data_contract`` the ``inf`` reaches
            ``_to_int_or_none`` and raises ``OverflowError``;
          * calling ``_compute_unified_rankings`` directly with an
            ``inf`` cell (no coercion layer) makes it ``site_max``,
            and every other player's contribution from that source
            collapses toward zero — measured at ~50% board-wide.
        """
        clean = dc.build_api_data_contract(_payload())
        poisoned = dc.build_api_data_contract(_payload(corrupt=float("inf")))

        clean_vals = _contract_values(clean)
        poisoned_vals = _contract_values(poisoned)

        for name, value in clean_vals.items():
            assert (
                poisoned_vals[name] == value
            ), f"{name} was repriced by a non-finite cell in another row"

    def test_out_of_range_finite_value_rescales_the_board(self):
        """CHARACTERISATION of a known, unfixed gap — not an endorsement.

        ``_safe_num`` only rejects non-finite values.  A finite but
        out-of-scale cell (e.g. an extra digit: 99990 on a board that
        tops out at 9999) is accepted, becomes ``site_max``, and
        deflates every player's contribution from that source.

        This test pins the CURRENT behaviour so that whenever a range
        guard is added the change is deliberate and visible, rather
        than landing silently.  See ``docs/python-coverage-audit.md``
        (Defect D-1) for the numbers and the open policy question.
        """
        clean = _contract_values(dc.build_api_data_contract(_payload()))
        poisoned = _contract_values(dc.build_api_data_contract(_payload(corrupt=99990)))

        # Today: every player is deflated, and by the same proportion.
        deflated = [
            poisoned[n] / clean[n] for n in clean if clean[n] and poisoned.get(n) is not None
        ]
        assert deflated, "fixture produced no comparable players"
        assert all(r < 0.75 for r in deflated), (
            "expected the documented board-wide deflation; if this now "
            "passes at ~1.0 a range guard has been added — update "
            "docs/python-coverage-audit.md D-1 and turn this into a "
            "no-contamination assertion"
        )


def _payload(corrupt: Any = None) -> dict[str, Any]:
    """120 spread-out players, optionally plus one corrupt cell.

    Sized past the point where everything crowds the top of the Hill
    curve — with only a handful of rows every value pins near 9999 and
    a contamination bug is invisible.
    """
    positions = ["QB", "RB", "WR", "TE"]
    players: dict[str, Any] = {}
    n = 120
    for i in range(n):
        ktc = int(9500 - (9000 * i / (n - 1)))
        players[f"Player {i:03d}"] = {
            "position": positions[i % 4],
            "team": "FA",
            "_sites": 2,
            "_canonicalSiteValues": {"ktcSfTep": ktc, "idpTradeCalc": ktc},
        }
    if corrupt is not None:
        players["Glitch Guy"] = {
            "position": "WR",
            "team": "FA",
            "_sites": 2,
            "_canonicalSiteValues": {"ktcSfTep": corrupt, "idpTradeCalc": 4000},
        }
    return {"players": players}


def _contract_values(contract: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in contract.get("playersArray") or []:
        name = row.get("displayName")
        value = row.get("rankDerivedValue")
        if name and name != "Glitch Guy" and isinstance(value, (int, float)):
            out[str(name)] = int(value)
    return out


# ── Ties and duplicates ──────────────────────────────────────────────


class TestTiesAndDuplicates:
    def test_tied_source_values_produce_identical_player_values(self):
        """Two players a vendor ranks identically must price identically.

        Any tie-break that leaked into the *value* (rather than only
        into the display ordering) would make the board depend on dict
        iteration order.
        """
        rows = [
            _row("Tie A", "WR", ktcSfTep=4000, idpTradeCalc=4000),
            _row("Tie B", "WR", ktcSfTep=4000, idpTradeCalc=4000),
            _row("Lower", "WR", ktcSfTep=3000, idpTradeCalc=3000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)
        assert got["Tie A"]["rankDerivedValue"] == got["Tie B"]["rankDerivedValue"]
        assert got["Tie A"]["rankDerivedValue"] > got["Lower"]["rankDerivedValue"]

    def test_tied_rank_signal_values_also_tie(self):
        """Same, for a rank-encoded source rather than a value source."""
        rows = [
            _row("Tie A", "WR", dlfSf=950000, idpTradeCalc=4000),
            _row("Tie B", "WR", dlfSf=950000, idpTradeCalc=4000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        got = _by_name(rows)
        assert got["Tie A"]["rankDerivedValue"] == got["Tie B"]["rankDerivedValue"]

    def test_duplicate_names_are_valued_independently(self):
        """Two rows sharing a name must not merge or overwrite.

        The pipeline keys its working maps on row index, so a duplicate
        display name (a real scrape hazard — two players, same name)
        must keep each row's own evidence.
        """
        rows = [
            _row("Josh Allen", "QB", ktcSfTep=9000, idpTradeCalc=9000),
            _row("Josh Allen", "LB", ktcSfTep=2000, idpTradeCalc=2000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        values = [r["rankDerivedValue"] for r in rows if r["position"] in ("QB", "LB")]
        assert 9000 in values
        # The LB row keeps its own (much lower) evidence rather than
        # inheriting the QB's.
        assert max(values) != min(values)


# ── Sanity: no NaN ever escapes into the contract ────────────────────


class TestNoNaNEscapes:
    def test_no_stamped_value_is_nan(self):
        """A NaN in any numeric stamp would poison sorting downstream."""
        rows = [
            _row("Split", "WR", ktcSfTep=9000, idpTradeCalc=1000),
            _row("Solo", "WR", ktcSfTep=4000),
            _row("Def", "LB", idpTradeCalc=6000, dlfIdp=900000),
            _anchor_qb(),
        ]
        dc._compute_unified_rankings(rows, {})
        numeric_fields = (
            "rankDerivedValue",
            "_blendedValueUncapped",
            "sourceSpread",
            "hillValueSpread",
            "anchorValue",
            "subgroupBlendValue",
            "subgroupDelta",
            "alphaShrinkage",
        )
        for row in rows:
            for field in numeric_fields:
                value = row.get(field)
                if isinstance(value, float):
                    assert not math.isnan(value), f"{row['canonicalName']}.{field} is NaN"
                    assert math.isfinite(value), f"{row['canonicalName']}.{field} not finite"
