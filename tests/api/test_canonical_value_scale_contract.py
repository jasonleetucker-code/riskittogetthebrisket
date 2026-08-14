"""The canonical value scale is a contract, and it is enforced — B9a.

WHAT A CANONICAL VALUE IS
─────────────────────────
``rankDerivedValue`` is a position on the canonical dynasty board.  Its
range is set by the Hill family the board is built from::

    V(p) = 9999 / (1 + (p/c)^s)

9,999 is the ASYMPTOTE — the value an infinitely good asset would
approach and never reach.  So the scale's declared range is
``1 … 9999``, and a published canonical value outside it is not an
unusually good player; it is a number that the curve which defines the
scale cannot produce.  Today's board tops out at 9,977.

WHY THIS FILE EXISTS
────────────────────
#822 rejected the league-aware methodology for promotion to canonical
and ruled that it "may no longer own a canonical field".  It closed the
engine path (``server.py::_valuation_scoped_contract`` ignores a stored
``leagueAdjusted`` and serves market) and moved
``league_intel.overlay`` onto ``experimentalLeagueAdjusted*`` names.

One path was left open: ``POST /api/rankings/overrides?view=delta`` with
``valuation_mode: "leagueAdjusted"`` still built factors and handed them
to ``build_rankings_delta_payload``, whose ``apply_valuation_factors``
multiplied them straight into ``rankDerivedValue`` — the canonical field
— with the ±25% cap applied to the FACTOR and never to the PRODUCT.

Measured on the 2026-08-14 board before the repair:

===================  ==========================  ================
factor               max canonical value on wire  rows above 9999
===================  ==========================  ================
1.018366 (measured)  10,160                       2
1.25 (the cap)       12,471                      16
===================  ==========================  ================

Two defects in one expression, and the second is the worse of them: a
board the product does not offer and the owner did not approve was
still reachable under the canonical field name.

These tests assert the CONTRACT — canonical values stay inside the scale
that defines them — rather than the absence of one multiply, so they
survive any future re-opening of a validated league-aware methodology.
That methodology would have to renormalise onto the scale, which is one
of the seven reasons this one was rejected.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from src.api.data_contract import build_api_data_contract, build_rankings_delta_payload

#: The Hill asymptote.  Not a tunable — it is the numerator of the curve
#: that defines the scale (``src/canonical/player_valuation.py``).
CANONICAL_VALUE_MAX = 9999
CANONICAL_VALUE_MIN = 1

REPO = pathlib.Path(__file__).resolve().parents[2]


def _raw_export() -> dict:
    candidates = sorted((REPO / "exports" / "latest").glob("dynasty_data*.json"), reverse=True)
    if not candidates:
        pytest.skip("no export available in this environment")
    return json.loads(candidates[0].read_text(encoding="utf-8"))


def _canonical_values(rows) -> list[tuple[str, int]]:
    out = []
    for row in rows:
        value = row.get("rankDerivedValue")
        name = row.get("displayName") or row.get("id") or row.get("canonicalName")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append((str(name), int(value)))
    return out


def _assert_in_range(pairs, *, where: str) -> None:
    bad = [p for p in pairs if not (CANONICAL_VALUE_MIN <= p[1] <= CANONICAL_VALUE_MAX)]
    assert not bad, (
        f"{len(bad)} canonical values outside 1..{CANONICAL_VALUE_MAX} on {where}, "
        f"e.g. {bad[:5]}"
    )


class TestTheDefaultBoardHonoursItsOwnScale:
    def test_full_contract(self):
        contract = build_api_data_contract(_raw_export())
        pairs = _canonical_values(contract["playersArray"])
        assert pairs, "no priced rows — the assertion would be vacuous"
        _assert_in_range(pairs, where="the full contract")

    def test_the_canonical_aliases_agree_with_the_canonical_value(self):
        """``values.overall`` / ``finalAdjusted`` / ``displayValue`` are
        exact aliases (#822 measured them equal on all 1,092 rows).  An
        alias outside the range would be the same defect wearing a
        different field name."""
        contract = build_api_data_contract(_raw_export())
        for row in contract["playersArray"]:
            values = row.get("values")
            canonical = row.get("rankDerivedValue")
            if not isinstance(values, dict) or not isinstance(canonical, (int, float)):
                continue
            for alias in ("overall", "finalAdjusted", "displayValue"):
                seen = values.get(alias)
                if isinstance(seen, (int, float)) and not isinstance(seen, bool):
                    assert CANONICAL_VALUE_MIN <= seen <= CANONICAL_VALUE_MAX
                    assert int(seen) == int(canonical)


class TestTheOverrideDeltaCannotPublishAnOutOfScaleCanonicalValue:
    """The wire shape ``/rankings`` actually consumes."""

    def test_the_plain_override_delta_is_in_range(self):
        payload = build_rankings_delta_payload(_raw_export())
        pairs = _canonical_values(payload["rankingsDelta"]["players"])
        assert pairs
        _assert_in_range(pairs, where="the override delta")

    def test_the_builder_has_no_seam_for_a_non_canonical_repricing(self):
        """The regression proper, made structural.

        The breach was not a bad bound — it was that a rejected
        methodology could reach ``rankDerivedValue`` at all.  A range
        check alone would have passed the day someone added a factor
        source that happened to stay under 9,999 while still publishing
        a board the owner never approved.  So the assertion is that the
        seam is gone: ``build_rankings_delta_payload`` takes no factor
        argument, and ``apply_valuation_factors`` no longer exists.
        """
        import inspect

        from src.api import data_contract

        params = inspect.signature(build_rankings_delta_payload).parameters
        assert not [
            p for p in params if "valuation" in p or "factor" in p
        ], f"the delta builder still accepts a repricing argument: {sorted(params)}"
        assert not hasattr(data_contract, "apply_valuation_factors"), (
            "the canonical-field composition helper is still importable, so a "
            "caller can reintroduce the breach without touching this module"
        )

    def test_the_validator_catches_an_out_of_scale_value(self):
        """The check must not be vacuous.

        ``validate_api_data_contract`` returns ``ok: True`` on the live
        board, which is what we want and also exactly what a check that
        never fires would return.  So inject the breach and require the
        gate to open — ``scripts/validate_api_contract.py`` keys on
        ``ok``, so this is what turns a ceiling breach into a red CI run
        rather than a silently published board.
        """
        from src.api.data_contract import validate_api_data_contract

        contract = build_api_data_contract(_raw_export())
        assert validate_api_data_contract(contract)["ok"] is True

        for row in contract["playersArray"]:
            if isinstance(row.get("rankDerivedValue"), int):
                row["rankDerivedValue"] = 12471  # the old cap-case value
                break

        report = validate_api_data_contract(contract)
        assert report["ok"] is False
        assert any("canonical_value_out_of_scale" in e for e in report["errors"]), report["errors"]

    def test_the_validator_catches_an_out_of_scale_alias(self):
        """``values.*`` are exact copies, so they are the same defect."""
        from src.api.data_contract import validate_api_data_contract

        contract = build_api_data_contract(_raw_export())
        for row in contract["playersArray"]:
            values = row.get("values")
            if isinstance(values, dict) and isinstance(values.get("displayValue"), int):
                values["displayValue"] = 12471
                break

        report = validate_api_data_contract(contract)
        assert report["ok"] is False
        assert any("canonical_value_out_of_scale" in e for e in report["errors"])

    def test_the_published_scale_is_the_scale_that_is_enforced(self):
        """A contract that advertises a range it is not held to is worse
        than one that advertises nothing."""
        from src.api import data_contract

        formula = build_api_data_contract(_raw_export())["methodology"]["formula"]
        assert formula["scaleMin"] == data_contract._CANONICAL_VALUE_MIN == CANONICAL_VALUE_MIN
        assert formula["scaleMax"] == data_contract._CANONICAL_VALUE_MAX == CANONICAL_VALUE_MAX

    def test_the_factor_bound_was_never_the_protection(self):
        """Documents WHY the bound could not have been the fix.

        ``_clamp(combined, lo, hi)`` bounds the FACTOR.  A factor inside
        ±25% still carries any base value above 7,999 out of range, and
        the board's own top row is 9,977 — so on the real board the
        bound permitted a breach at any factor above ~1.0022.
        """
        top_of_board = 9977
        smallest_breaching_factor = (CANONICAL_VALUE_MAX + 1) / top_of_board
        assert smallest_breaching_factor < 1.25, (
            "if the factor cap were tighter than the first breaching factor the "
            "bound would have been sufficient and this finding would not exist"
        )
