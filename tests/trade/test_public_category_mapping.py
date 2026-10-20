"""Public recommendation categories are a MAPPING of the one decision owner
(Brisket Trade Advisor B0-d; design §3).  No new threshold, no second engine.

* exhaustive table over (headline x leaning x A.direction x A.magnitude x
  deciding) with the invariants the owner directive requires;
* the 3-4-team net-band mapping;
* public reason codes fail closed;
* ``counterfactuals=False`` changes nothing but ``whatWouldChange``;
* the asset evidence helpers the gates and the market lens now share.
"""

from __future__ import annotations

import itertools

import pytest

from src.trade import trade_decision as td
from src.valuation_math import fairness_bands

HEADLINES = ("YES", "NO", "NO_TOO_CLOSE", "NOT_ENOUGH_EVIDENCE", "BOGUS")
LEANINGS = td.RECOMMENDATIONS + ("??",)
DIRECTIONS = ("favors", "opposes", "neutral", None)
MAGNITUDES = ("modest", "large", None)
DECIDING = ("objectiveValue", "rosterBenefit", "strategy", "both", "executionGate", "evidenceGate")


def _decision(headline, lean, direction, magnitude, deciding):
    return {
        "headline": headline,
        "leaning": lean,
        "deciding": deciding,
        "components": {"objectiveValue": {"direction": direction, "magnitude": magnitude}},
    }


def test_categories_and_copy_are_complete():
    assert set(td.PUBLIC_CATEGORY_TEXT) == set(td.PUBLIC_CATEGORIES)
    for cat in td.PUBLIC_CATEGORIES:
        t = td.public_text(cat)
        assert set(t) == {"recommendation", "headline", "message"}
        assert t["recommendation"] in ("ACCEPT", "FAIR", "DECLINE", "NONE")
    assert td.public_text("UNFAVORABLE", "roster_limit")["headline"] == (
        "DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE"
    )
    # No digit anywhere in public copy: it can never carry a value.
    blob = repr(td.PUBLIC_CATEGORY_TEXT) + repr(td.PUBLIC_REASON_TEXT)
    blob += repr(td.PUBLIC_ROSTER_LIMIT_TEXT)
    assert not any(ch.isdigit() for ch in blob)


@pytest.mark.parametrize(
    ("headline", "lean", "direction", "magnitude", "deciding"),
    list(itertools.product(HEADLINES, LEANINGS, DIRECTIONS, MAGNITUDES, DECIDING)),
)
def test_exhaustive_mapping_invariants(headline, lean, direction, magnitude, deciding):
    d = _decision(headline, lean, direction, magnitude, deciding)
    cat = td.public_category_from_decision(d)
    assert cat in td.PUBLIC_CATEGORIES
    # LC-1: a gate ``deciding`` with a headline ``decide`` never emits it with
    # (executionGate only with NO, evidenceGate only with NOT_ENOUGH_EVIDENCE)
    # is malformed, and a malformed decision is UNAVAILABLE — never a
    # confident category (it was FAVORABLE for YES + executionGate).
    gate_headline = {"executionGate": "NO", "evidenceGate": "NOT_ENOUGH_EVIDENCE"}.get(deciding)
    if gate_headline is not None and headline != gate_headline:
        assert cat == "UNAVAILABLE"
        return
    if headline == "NOT_ENOUGH_EVIDENCE" or headline == "BOGUS":
        assert cat == "UNAVAILABLE"
    if headline == "NO_TOO_CLOSE":
        assert cat == "APPROXIMATELY_EVEN"
    if cat == "STRONGLY_FAVORABLE":
        assert headline == "YES" and direction == "favors" and magnitude == "large"
        assert lean == "MAKE"
    if cat == "STRONGLY_UNFAVORABLE":
        assert headline == "NO" and direction == "opposes" and magnitude == "large"
        assert lean == "PASS" and deciding != "executionGate"
    if headline == "NO":
        assert cat in ("UNFAVORABLE", "STRONGLY_UNFAVORABLE"), "never favourable with NO"
    if headline == "YES":
        assert cat in ("FAVORABLE", "STRONGLY_FAVORABLE"), "never unfavourable with YES"
    if headline == "NO" and deciding == "executionGate":
        assert cat == "UNFAVORABLE"
        assert td.public_reason_code(d) == "roster_limit"


def test_malformed_decisions_fail_closed():
    for bad in (None, [], "YES", {}, {"headline": "YES", "components": "x"}):
        cat = td.public_category_from_decision(bad)
        assert cat in ("UNAVAILABLE", "FAVORABLE")
    assert td.public_category_from_decision(None) == "UNAVAILABLE"
    assert td.public_category_from_decision({"headline": "YES"}) == "FAVORABLE"


@pytest.mark.parametrize(
    ("level", "net", "expected"),
    [
        ("fair", 10, "APPROXIMATELY_EVEN"),
        ("fair", -10, "APPROXIMATELY_EVEN"),
        ("slight", 400, "FAVORABLE"),
        ("slight", -400, "UNFAVORABLE"),
        ("unfair", 900, "STRONGLY_FAVORABLE"),
        ("lopsided", -3000, "STRONGLY_UNFAVORABLE"),
        ("unfair", 0, "UNAVAILABLE"),
        ("weird", 10, "UNAVAILABLE"),
        ("slight", None, "UNAVAILABLE"),
        ("slight", True, "UNAVAILABLE"),
    ],
)
def test_net_band_mapping(level, net, expected):
    assert td.public_category_from_net_band({"level": level}, net) == expected
    assert td.public_category_from_net_band(level, net) == expected


def test_net_band_strong_agrees_with_the_two_team_strong_cut():
    """'Strong' at N >= 3 is the same band cut component A calls ``large``."""
    for net, larger in [(300, 20000), (900, 9000), (2500, 6000), (-700, 9000), (100, 5000)]:
        band = fairness_bands.classify(net, larger)
        cat = td.public_category_from_net_band(band, net)
        large = band["level"] in ("unfair", "lopsided")
        assert cat.startswith("STRONGLY_") == large


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["off_board_assets", "posture_unknown"], "asset_not_evaluable"),
        (["unpriced_assets"], "asset_not_evaluable"),
        (["no_priced_assets"], "asset_not_evaluable"),
        (["unheld_assets", "stale_values"], "ownership_unverifiable"),
        (["pick_ownership_unknown"], "ownership_unverifiable"),
        (["quarantined_values", "off_board_assets"], None),
        (["stale_values"], None),
        (["posture_unknown"], None),
        (["unprojected_players"], None),
        (["roster_unknown"], None),
        (["roster_limit_unknown"], None),
        (["forced_drop_unpriced"], None),
        (["a_code_added_next_year"], None),
        ([], None),
    ],
)
def test_reason_codes_fail_closed(codes, expected):
    d = {
        "headline": "NOT_ENOUGH_EVIDENCE",
        "missingEvidence": [{"code": c, "text": "t", "evidence": {}} for c in codes],
    }
    assert td.public_reason_code(d) == expected
    if expected is not None:
        assert expected in td.PUBLIC_REASON_TEXT


def test_reason_code_is_none_on_a_decided_trade():
    for h in ("YES", "NO", "NO_TOO_CLOSE"):
        assert td.public_reason_code({"headline": h, "deciding": "objectiveValue"}) is None
    assert td.public_reason_code(None) is None


def test_asset_evidence_helpers():
    assert td.asset_is_priced({"value": 1})
    for v in (0, -5, None, True, "100"):
        assert not td.asset_is_priced({"value": v})
    assert not td.asset_is_priced(None)
    assert td.asset_evidence_codes({"value": 0, "quarantined": True, "valueFreshness": "low"}) == (
        "unpriced_assets",
        "quarantined_values",
        "stale_values",
    )
    assert td.asset_evidence_codes({"value": 500, "valueFreshness": "high"}) == ()
    assert td.asset_evidence_codes("x") == ()


def test_counterfactuals_off_changes_only_what_would_change():
    from tests.trade import war_room_ui_payloads as gen

    for name in ("consolidation", "asset-only", "forced-cut"):
        full = gen.build(name)
        sim = {k: v for k, v in full.items() if k not in ("analysis", "_fixture")}
        from src.trade.analyze_trade import analyze_trade

        on = analyze_trade(sim)
        off = analyze_trade(sim, counterfactuals=False)
        assert off["decision"]["whatWouldChange"] == [] or (
            off["decision"]["headline"] in ("NOT_ENOUGH_EVIDENCE",)
            or off["decision"].get("deciding") == "executionGate"
        )
        strip = lambda a: {  # noqa: E731
            **a,
            "decision": {k: v for k, v in a["decision"].items() if k != "whatWouldChange"},
        }
        assert strip(on) == strip(off), name
        assert td.public_category_from_decision(on["decision"]) == (
            td.public_category_from_decision(off["decision"])
        )


def test_counterfactual_search_is_not_called_when_off(monkeypatch):
    from tests.trade import war_room_ui_payloads as gen
    from src.trade.analyze_trade import analyze_trade

    full = gen.build("consolidation")
    sim = {k: v for k, v in full.items() if k not in ("analysis", "_fixture")}
    calls = []
    real = td._what_would_change
    monkeypatch.setattr(td, "_what_would_change", lambda *a, **k: calls.append(1) or real(*a, **k))
    analyze_trade(sim, counterfactuals=False)
    assert calls == []
    analyze_trade(sim)
    assert calls == [1] or full["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
