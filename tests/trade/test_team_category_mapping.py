"""The PRIVATE 5-level category is a MAPPING of the one decision owner.

``team_verdicts.team_category`` (N-team spec §2.7) maps ONE team's own
``trade_decision.decide`` result onto STRONGLY_FAVORABLE .. UNAVAILABLE for the
private calculator / War Room.  It is never public: the public Brisket Trade
Advisor is fairness-only (owner amendment 2026-10-20) and reads the market
fairness state instead (``team_verdicts.team_fairness``), and the decision
owner carries no public section any more.

* exhaustive table over (headline x leaning x A.direction x A.magnitude x
  deciding) with the invariants the private mapping must hold;
* perspective reversal mirrors the category;
* ``counterfactuals=False`` changes nothing but ``whatWouldChange``;
* the asset evidence helpers the gates and the market lens share;
* the decision owner has no public copy / public mapping left.
"""

from __future__ import annotations

import itertools
import re
from pathlib import Path

import pytest

from src.trade import team_verdicts as tv
from src.trade import trade_decision as td
from tests.api.trade_advisor_support import decision

REPO = Path(__file__).resolve().parents[2]

HEADLINES = ("YES", "NO", "NO_TOO_CLOSE", "NOT_ENOUGH_EVIDENCE", "BOGUS")
LEANINGS = td.RECOMMENDATIONS + ("??",)
DIRECTIONS = ("favors", "opposes", "neutral", None)
MAGNITUDES = ("modest", "large", None)
DECIDING = ("objectiveValue", "rosterBenefit", "strategy", "both", "executionGate", "evidenceGate")


def _decision(headline, lean, direction, magnitude, deciding):
    """Components present on EVERY combination (including the gate, which the
    engine never emits with components) so the mapping cannot lean on their
    absence to stay closed."""
    return {
        "headline": headline,
        "leaning": lean,
        "deciding": deciding,
        "components": {"objectiveValue": {"direction": direction, "magnitude": magnitude}},
    }


def _all():
    for h, lean, d, m, dec in itertools.product(
        HEADLINES, LEANINGS, DIRECTIONS, MAGNITUDES, DECIDING
    ):
        yield h, lean, d, m, dec, decision(h, leaning=lean, direction=d, magnitude=m, deciding=dec)


# ── The decision owner is private-only ────────────────────────────────────


def test_the_decision_owner_has_no_public_section():
    """Fairness-only amendment (spec §7, Lane C): the PUBLIC block — public
    categories, ACCEPT / DECLINE copy, the 3-4-team net-band mapping, public
    reason codes — is deleted from ``trade_decision``, not deprecated."""
    for name in (
        "PUBLIC_CATEGORIES",
        "PUBLIC_CATEGORY_TEXT",
        "PUBLIC_ROSTER_LIMIT_TEXT",
        "PUBLIC_REASON_TEXT",
        "public_category_from_decision",
        "public_category_from_net_band",
        "public_reason_code",
        "public_asset_gap_labels",
        "public_text",
    ):
        assert not hasattr(td, name), name
    src = (REPO / "src" / "trade" / "trade_decision.py").read_text(encoding="utf-8")
    for word in ("ACCEPT", "DECLINE", "Public categories"):
        assert word not in src, word


# ── Two-team (any-N) mapping ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("headline", "lean", "direction", "magnitude", "deciding"),
    list(itertools.product(HEADLINES, LEANINGS, DIRECTIONS, MAGNITUDES, DECIDING)),
)
def test_exhaustive_mapping_invariants(headline, lean, direction, magnitude, deciding):
    d = _decision(headline, lean, direction, magnitude, deciding)
    cat = tv.team_category(d)
    gate = deciding == "executionGate"
    assert cat in tv.CATEGORIES
    if headline in ("NOT_ENOUGH_EVIDENCE", "BOGUS"):
        assert cat == "UNAVAILABLE"
    if headline == "NO_TOO_CLOSE":
        assert cat == "APPROXIMATELY_EVEN"
    if cat == "STRONGLY_FAVORABLE":
        assert headline == "YES" and direction == "favors" and magnitude == "large"
        assert lean == "MAKE"
    if cat == "STRONGLY_UNFAVORABLE":
        assert headline == "NO" and direction == "opposes" and magnitude == "large"
        assert lean == "PASS" and not gate
    if headline == "NO":
        assert cat in ("UNFAVORABLE", "STRONGLY_UNFAVORABLE"), "never favourable with NO"
    if headline == "NO" and gate:
        assert cat == "UNFAVORABLE"
        assert tv.team_category_reason(d) == "roster_limit"


def test_strongly_favorable_only_with_yes_a_large_favouring_band_and_make():
    for h, lean, d, m, dec_kind, dec in _all():
        if tv.team_category(dec) == "STRONGLY_FAVORABLE":
            assert (h, d, m, lean) == ("YES", "favors", "large", "MAKE"), (h, lean, d, m, dec_kind)


def test_never_strongly_favorable_when_the_value_band_is_against_the_perspective():
    for _h, _lean, d, m, _k, dec in _all():
        if d == "opposes" and m == "large":
            assert tv.team_category(dec) != "STRONGLY_FAVORABLE"


def test_execution_gate_is_unfavorable_with_the_roster_limit_text():
    dec = decision("NO", deciding="executionGate", leaning="TOO_CLOSE")
    assert tv.team_category(dec) == "UNFAVORABLE"
    assert tv.team_category_reason(dec) == "roster_limit"
    assert tv.team_category_text(dec) == tv.ROSTER_LIMIT_TEXT


def test_the_engine_gate_only_produces_no():
    """``decide``'s execution gate returns ``_out("NO", deciding="executionGate",
    ...)`` and nothing else, so a gate on any other headline is unreachable."""
    src = (REPO / "src" / "trade" / "trade_decision.py").read_text(encoding="utf-8")
    body = src[src.index("def decide(") :]
    gate_calls = re.findall(r'_out\(\s*"([A-Z_]+)",\s*deciding="executionGate"', body)
    assert gate_calls == ["NO"], gate_calls


def test_malformed_decisions_fail_closed():
    for bad in (None, [], "YES", {}, {"headline": None}):
        assert tv.team_category(bad) == "UNAVAILABLE"
    # A YES without a readable band is FAVORABLE, never STRONGLY_FAVORABLE —
    # strength needs the band's own evidence.
    assert tv.team_category({"headline": "YES"}) == "FAVORABLE"
    assert tv.team_category({"headline": "YES", "components": "x"}) == "FAVORABLE"
    assert tv.team_category({"headline": "NO"}) == "UNFAVORABLE"


_MIRROR_HEADLINE = {"YES": "NO", "NO": "YES", "NO_TOO_CLOSE": "NO_TOO_CLOSE"}
_MIRROR_DIR = {"favors": "opposes", "opposes": "favors", "neutral": "neutral", None: None}
_MIRROR_LEAN = {
    "MAKE": "PASS",
    "LEAN_MAKE": "LEAN_PASS",
    "TOO_CLOSE": "TOO_CLOSE",
    "LEAN_PASS": "LEAN_MAKE",
    "PASS": "MAKE",
}
_MIRROR_CAT = {
    "STRONGLY_FAVORABLE": "STRONGLY_UNFAVORABLE",
    "FAVORABLE": "UNFAVORABLE",
    "APPROXIMATELY_EVEN": "APPROXIMATELY_EVEN",
    "UNFAVORABLE": "FAVORABLE",
    "STRONGLY_UNFAVORABLE": "STRONGLY_FAVORABLE",
    "UNAVAILABLE": "UNAVAILABLE",
}


def test_reversing_the_perspective_mirrors_the_category():
    """The other team's decision on the same trade is the mirror image when
    the engine's own answer mirrors (Asset-Only value lens).  The mapping
    adds no asymmetry of its own."""
    for h, lean, d, m in itertools.product(
        _MIRROR_HEADLINE, td.RECOMMENDATIONS, DIRECTIONS, MAGNITUDES
    ):
        a = decision(h, leaning=lean, direction=d, magnitude=m)
        b = decision(
            _MIRROR_HEADLINE[h],
            leaning=_MIRROR_LEAN[lean],
            direction=_MIRROR_DIR[d],
            magnitude=m,
        )
        assert _MIRROR_CAT[tv.team_category(a)] == tv.team_category(b)


# ── Shared evidence helpers ───────────────────────────────────────────────


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


# ── counterfactuals=False ─────────────────────────────────────────────────


def test_counterfactuals_off_changes_only_what_would_change():
    from src.trade.analyze_trade import analyze_trade
    from tests.trade import war_room_ui_payloads as gen

    for name in ("consolidation", "asset-only", "forced-cut"):
        full = gen.build(name)
        sim = {k: v for k, v in full.items() if k not in ("analysis", "_fixture")}
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
        assert tv.team_category(on["decision"]) == tv.team_category(off["decision"])


def test_counterfactual_search_is_not_called_when_off(monkeypatch):
    from src.trade.analyze_trade import analyze_trade
    from tests.trade import war_room_ui_payloads as gen

    full = gen.build("consolidation")
    sim = {k: v for k, v in full.items() if k not in ("analysis", "_fixture")}
    calls = []
    real = td._what_would_change
    monkeypatch.setattr(td, "_what_would_change", lambda *a, **k: calls.append(1) or real(*a, **k))
    analyze_trade(sim, counterfactuals=False)
    assert calls == []
    analyze_trade(sim)
    assert calls == [1] or full["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"


def test_counterfactuals_flag_on_a_simulated_asset_only_trade(monkeypatch):
    """``decide(counterfactuals=False)`` returns the same decision with an
    empty ``whatWouldChange`` and never runs the search (a live
    ``simulate_trade`` result, not a fixture)."""
    from src.api import trade_simulator
    from src.trade.analyze_trade import analyze_trade
    from tests.api.test_trade_nfl_exposure import _SETTINGS, _contract, _us

    calls = []
    real = td._what_would_change
    monkeypatch.setattr(td, "_what_would_change", lambda *a, **k: calls.append(1) or real(*a, **k))
    c = _contract()
    sim = trade_simulator.simulate_trade(
        c,
        resolved_team=_us(c),
        players_in=["WR Buf Star"],
        players_out=["WR Kc"],
        roster_settings=_SETTINGS,
    )
    sim["teamContext"] = {"applied": False, "mode": "asset_only"}
    on = analyze_trade(dict(sim))["decision"]
    assert calls, "the default path runs the counterfactual search"
    calls.clear()
    off = analyze_trade(dict(sim), counterfactuals=False)["decision"]
    assert calls == []
    assert off["whatWouldChange"] == []
    for key in ("headline", "leaning", "deciding", "components", "confidence", "reasons"):
        assert on[key] == off[key], key
