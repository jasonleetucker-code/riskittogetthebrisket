"""Public recommendation categories are a MAPPING of the one decision owner
(Brisket Trade Advisor B0-d; design §3; test group B).  No new threshold, no
second engine.

``trade_decision.public_category_from_decision`` maps the ONE canonical
decision onto five public categories.  These tests pin:

* the exhaustive table over (headline x leaning x A.direction x A.magnitude x
  deciding) with the invariants the owner directive names ("do not label a
  trade strongly favorable unless the authoritative evaluation supports that
  conclusion"; "if the private calculator considers a trade unfavorable to
  Team A, the public advisor must not call it strongly favorable");
* the execution gate: NO -> UNFAVORABLE ``roster_limit``; a gate on any other
  headline is contradictory and fails closed to UNAVAILABLE, so a blocked
  trade never renders a favourable (or "fair") verdict;
* the perspective mirror;
* the 3-4-team net-band mapping (a non-fair band with no sign is UNAVAILABLE);
* public reason codes: unknown or malformed fails closed, otherwise asset
  before ownership by code (never by list position), which equals "first gap"
  on every list the evidence gates can emit;
* that the public copy exists in exactly one backend module and carries no
  digit;
* ``counterfactuals=False`` changes nothing but ``whatWouldChange``;
* the asset evidence helpers the gates and the market lens share.

One file, one owner: this merges the two copies #1853 (B0-d) and #1861 (B2/B3)
each added; every expectation that changed is named in the reconciling commit.
"""

from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

import pytest

from src.trade import trade_decision as td
from src.valuation_math import fairness_bands
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


# ── Copy ──────────────────────────────────────────────────────────────────


def test_categories_and_copy_are_complete():
    assert set(td.PUBLIC_CATEGORY_TEXT) == set(td.PUBLIC_CATEGORIES)
    for cat in td.PUBLIC_CATEGORIES:
        t = td.public_text(cat)
        assert set(t) == {"recommendation", "headline", "message"}
        assert t["recommendation"] in ("ACCEPT", "FAIR", "DECLINE", "NONE")
    assert td.public_text("UNFAVORABLE", "roster_limit")["headline"] == (
        "DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE"
    )
    # ``roster_limit`` copy is only for the gate's own category.
    assert td.public_text("UNAVAILABLE", "roster_limit") == td.public_text("UNAVAILABLE")
    assert td.public_text("NOT_A_CATEGORY") == td.public_text("UNAVAILABLE")
    # No digit anywhere in public copy: it can never carry a value.
    blob = repr(td.PUBLIC_CATEGORY_TEXT) + repr(td.PUBLIC_REASON_TEXT)
    blob += repr(td.PUBLIC_ROSTER_LIMIT_TEXT)
    assert not any(ch.isdigit() for ch in blob)


def test_reason_text_is_only_the_public_table():
    assert set(td.PUBLIC_REASON_TEXT) == {
        "asset_not_evaluable",
        "ownership_unverifiable",
        "multi_team_unsupported",
        "roster_limit",
    }
    # Every non-None engine-gap mapping lands inside the public table.
    assert {r for r in td._PUBLIC_GAP_REASON.values() if r} <= set(td.PUBLIC_REASON_TEXT)


def test_category_copy_lives_only_in_the_decision_owner():
    needles = [c["headline"] for c in td.PUBLIC_CATEGORY_TEXT.values()]
    needles += [c["message"] for c in td.PUBLIC_CATEGORY_TEXT.values()]
    hits = []
    for path in [*(REPO / "src").rglob("*.py"), REPO / "server.py"]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(n in text for n in needles):
            hits.append(path.relative_to(REPO).as_posix())
    assert hits == ["src/trade/trade_decision.py"], hits


# ── Two-team mapping ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("headline", "lean", "direction", "magnitude", "deciding"),
    list(itertools.product(HEADLINES, LEANINGS, DIRECTIONS, MAGNITUDES, DECIDING)),
)
def test_exhaustive_mapping_invariants(headline, lean, direction, magnitude, deciding):
    d = _decision(headline, lean, direction, magnitude, deciding)
    cat = td.public_category_from_decision(d)
    gate = deciding == "executionGate"
    assert cat in td.PUBLIC_CATEGORIES
    if headline in ("NOT_ENOUGH_EVIDENCE", "BOGUS"):
        assert cat == "UNAVAILABLE"
    if headline == "NO_TOO_CLOSE":
        assert cat == ("UNAVAILABLE" if gate else "APPROXIMATELY_EVEN")
    if cat == "STRONGLY_FAVORABLE":
        assert headline == "YES" and direction == "favors" and magnitude == "large"
        assert lean == "MAKE" and not gate
    if cat == "STRONGLY_UNFAVORABLE":
        assert headline == "NO" and direction == "opposes" and magnitude == "large"
        assert lean == "PASS" and not gate
    if headline == "NO":
        assert cat in ("UNFAVORABLE", "STRONGLY_UNFAVORABLE"), "never favourable with NO"
    if headline == "YES":
        if gate:
            # The gate only ever produces NO; YES + gate is contradictory and
            # a blocked trade must never render a favourable verdict.
            assert cat == "UNAVAILABLE"
        else:
            assert cat in ("FAVORABLE", "STRONGLY_FAVORABLE"), "never unfavourable with YES"
    if gate:
        assert cat in ("UNFAVORABLE", "UNAVAILABLE"), "a blocked trade is never favourable"
        assert td.public_reason_code(d) == ("roster_limit" if headline == "NO" else None)


def test_strongly_favorable_only_with_yes_a_large_favouring_band_and_make():
    for h, lean, d, m, dec_kind, dec in _all():
        if td.public_category_from_decision(dec) == "STRONGLY_FAVORABLE":
            assert (h, d, m, lean) == ("YES", "favors", "large", "MAKE"), (h, lean, d, m, dec_kind)
            assert dec_kind != "executionGate"


def test_never_strongly_favorable_when_the_value_band_is_against_the_perspective():
    for _h, _lean, d, m, _k, dec in _all():
        if d == "opposes" and m == "large":
            assert td.public_category_from_decision(dec) != "STRONGLY_FAVORABLE"


def test_execution_gate_is_unfavorable_with_the_roster_limit_copy():
    dec = decision("NO", deciding="executionGate", leaning="TOO_CLOSE")
    assert td.public_category_from_decision(dec) == "UNFAVORABLE"
    assert td.public_reason_code(dec) == "roster_limit"
    assert td.public_text("UNFAVORABLE", "roster_limit")["headline"] == (
        "DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE"
    )


@pytest.mark.parametrize("headline", ["YES", "NO_TOO_CLOSE", "NOT_ENOUGH_EVIDENCE", "BOGUS"])
def test_execution_gate_on_any_other_headline_fails_closed(headline):
    dec = _decision(headline, "MAKE", "favors", "large", "executionGate")
    assert td.public_category_from_decision(dec) == "UNAVAILABLE"
    assert td.public_reason_code(dec) is None


def test_the_engine_gate_only_produces_no():
    """The fail-closed branch above guards a state ``decide`` cannot reach:
    its execution gate returns ``_out("NO", deciding="executionGate", ...)``
    and nothing else.  If that ever changes, the mapping must be revisited."""
    src = (REPO / "src" / "trade" / "trade_decision.py").read_text(encoding="utf-8")
    body = src[src.index("def decide(") : src.index("# ── Public categories")]
    gate_calls = re.findall(r'_out\(\s*"([A-Z_]+)",\s*deciding="executionGate"', body)
    assert gate_calls == ["NO"], gate_calls


def test_malformed_decisions_fail_closed():
    for bad in (None, [], "YES", {}, {"headline": None}, {"headline": "YES", "components": "x"}):
        assert td.public_category_from_decision(bad) in ("UNAVAILABLE", "FAVORABLE")
    for bad in (None, [], "YES", {}, {"headline": None}):
        assert td.public_category_from_decision(bad) == "UNAVAILABLE"
    # "YES otherwise" (design §3): a YES without a readable band is FAVORABLE,
    # never STRONGLY_FAVORABLE — strength needs the band's own evidence.
    assert td.public_category_from_decision({"headline": "YES"}) == "FAVORABLE"
    assert td.public_category_from_decision({"headline": "NO"}) == "UNFAVORABLE"


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
        assert _MIRROR_CAT[td.public_category_from_decision(a)] == td.public_category_from_decision(
            b
        )


# ── Three-or-four-team mapping ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("level", "net", "expected"),
    [
        ("fair", 10, "APPROXIMATELY_EVEN"),
        ("fair", -10, "APPROXIMATELY_EVEN"),
        ("fair", 0, "APPROXIMATELY_EVEN"),
        ("slight", 400, "FAVORABLE"),
        ("slight", -400, "UNFAVORABLE"),
        ("unfair", 900, "STRONGLY_FAVORABLE"),
        ("lopsided", -3000, "STRONGLY_UNFAVORABLE"),
        # A non-fair band with no sign is contradictory: never a default side.
        ("slight", 0, "UNAVAILABLE"),
        ("unfair", 0, "UNAVAILABLE"),
        ("lopsided", 0.0, "UNAVAILABLE"),
        ("weird", 10, "UNAVAILABLE"),
        (None, 10, "UNAVAILABLE"),
        ("slight", None, "UNAVAILABLE"),
        ("slight", True, "UNAVAILABLE"),
        ("slight", "400", "UNAVAILABLE"),
        ("slight", math.nan, "UNAVAILABLE"),
        ("unfair", math.inf, "UNAVAILABLE"),
        ("fair", -math.inf, "UNAVAILABLE"),
    ],
)
def test_net_band_mapping(level, net, expected):
    assert td.public_category_from_net_band({"level": level}, net) == expected
    assert td.public_category_from_net_band(level, net) == expected


def test_net_band_mapping_is_sign_symmetric():
    for level in ("fair", "slight", "unfair", "lopsided"):
        for net in (1, 250, 5000):
            a = td.public_category_from_net_band({"level": level}, net)
            b = td.public_category_from_net_band({"level": level}, -net)
            assert _MIRROR_CAT[a] == b


def test_net_band_strong_agrees_with_the_two_team_strong_cut():
    """'Strong' at N >= 3 is the same band cut component A calls ``large``."""
    for net, larger in [(300, 20000), (900, 9000), (2500, 6000), (-700, 9000), (100, 5000)]:
        band = fairness_bands.classify(net, larger)
        cat = td.public_category_from_net_band(band, net)
        large = band["level"] in ("unfair", "lopsided")
        assert cat.startswith("STRONGLY_") == large


# ── Reason codes ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        (["off_board_assets"], "asset_not_evaluable"),
        (["unpriced_assets"], "asset_not_evaluable"),
        (["no_priced_assets"], "asset_not_evaluable"),
        (["off_board_assets", "posture_unknown"], "asset_not_evaluable"),
        (["unpriced_assets", "posture_unknown"], "asset_not_evaluable"),
        (["unheld_assets"], "ownership_unverifiable"),
        (["pick_ownership_unknown"], "ownership_unverifiable"),
        (["unheld_assets", "stale_values"], "ownership_unverifiable"),
        (["pick_ownership_unknown", "stale_values"], "ownership_unverifiable"),
        # Several public codes: asset before ownership, by code.
        (["off_board_assets", "unheld_assets"], "asset_not_evaluable"),
        (["unheld_assets", "off_board_assets"], "asset_not_evaluable"),
        # A collapsed code cannot change the answer by where it sits.
        (["quarantined_values", "off_board_assets"], "asset_not_evaluable"),
        (["posture_unknown", "pick_ownership_unknown"], "ownership_unverifiable"),
        # Only collapsed codes -> None.
        (["quarantined_values"], None),
        (["stale_values"], None),
        (["posture_unknown"], None),
        (["unprojected_players"], None),
        (["roster_unknown"], None),
        (["roster_limit_unknown"], None),
        (["forced_drop_unpriced"], None),
        # Any unknown code fails closed, wherever it sits.
        (["a_code_added_next_year"], None),
        (["off_board_assets", "a_code_added_next_year"], None),
        (["a_code_added_next_year", "unheld_assets"], None),
        ([], None),
    ],
)
def test_reason_codes_collapse_and_fail_closed(codes, expected):
    for d in (
        decision("NOT_ENOUGH_EVIDENCE", deciding="evidenceGate", gaps=codes),
        {
            "headline": "NOT_ENOUGH_EVIDENCE",
            "missingEvidence": [{"code": c, "text": "t", "evidence": {}} for c in codes],
        },
    ):
        assert td.public_reason_code(d) == expected
    if expected is not None:
        assert expected in td.PUBLIC_REASON_TEXT


@pytest.mark.parametrize(
    "gaps",
    [
        None,
        "off_board_assets",
        [{"code": "off_board_assets"}, "junk"],
        [{"code": "off_board_assets"}, {"text": "no code"}],
        [{"code": "off_board_assets"}, {"code": None}],
        [{"code": "off_board_assets"}, {"code": 7}],
    ],
)
def test_malformed_gaps_fail_closed(gaps):
    """A gap entry without a string code is an unknown, never a skippable
    row: it cannot let a known code speak for the whole list."""
    d = {"headline": "NOT_ENOUGH_EVIDENCE", "missingEvidence": gaps}
    assert td.public_reason_code(d) is None


def test_reason_code_is_none_on_a_decided_trade():
    for h in ("YES", "NO", "NO_TOO_CLOSE"):
        assert td.public_reason_code({"headline": h, "deciding": "objectiveValue"}) is None
        gapped = {"headline": h, "missingEvidence": [{"code": "off_board_assets"}]}
        assert td.public_reason_code(gapped) is None
    for junk in (None, [], "NOT_ENOUGH_EVIDENCE"):
        assert td.public_reason_code(junk) is None


def _emitted_gap_codes() -> list[str]:
    """The gate codes in the order ``_evidence_gaps`` can emit them."""
    src = (REPO / "src" / "trade" / "trade_decision.py").read_text(encoding="utf-8")
    body = src[src.index("def _evidence_gaps(") : src.index("def _objective_value(")]
    return re.findall(r'_missing\(\s*"([a-z_]+)"', body)


def test_every_evidence_gap_code_the_engine_emits_is_classified():
    """A new ``_evidence_gaps`` code must be consciously classified (exposed
    or collapsed); until it is, ``public_reason_code`` answers ``None``."""
    emitted = _emitted_gap_codes()
    unclassified = set(emitted) - set(td._PUBLIC_GAP_REASON)
    assert emitted and not unclassified, unclassified


def test_precedence_is_the_gates_own_order():
    """Every asset code is emitted before every ownership code, and both
    before every collapsed code — so precedence-by-code is the gates' order."""
    emitted = _emitted_gap_codes()
    rank = {r: i for i, r in enumerate(td._PUBLIC_REASON_PRECEDENCE)}
    groups = [rank.get(td._PUBLIC_GAP_REASON[c], len(rank)) for c in emitted]
    assert groups == sorted(groups), list(zip(emitted, groups))


def test_on_every_gate_ordered_list_the_first_gap_decides():
    """On every list the gates can emit (any subset, in gate order) the
    answer equals the first gap's own public reason — the first-gap rule,
    which therefore holds on real decisions while the order-independent rule
    above is what makes it robust off them."""
    emitted = _emitted_gap_codes()
    for k in range(1, len(emitted) + 1):
        for subset in itertools.combinations(emitted, k):
            d = {
                "headline": "NOT_ENOUGH_EVIDENCE",
                "missingEvidence": [{"code": c} for c in subset],
            }
            assert td.public_reason_code(d) == td._PUBLIC_GAP_REASON[subset[0]], subset


def test_asset_gap_labels_name_only_asset_gaps():
    d = {
        "headline": "NOT_ENOUGH_EVIDENCE",
        "missingEvidence": [
            {"code": "off_board_assets", "evidence": {"assets": ["A", "B"]}},
            {"code": "unpriced_assets", "evidence": {"assets": ["B", "C"]}},
            {"code": "quarantined_values", "evidence": {"assets": ["Q"]}},
            {"code": "unheld_assets", "evidence": {"assets": ["U"]}},
            {"code": "no_priced_assets", "evidence": None},
            "junk",
        ],
    }
    assert td.public_asset_gap_labels(d) == ["A", "B", "C"]
    assert td.public_asset_gap_labels(None) == []
    assert td.public_asset_gap_labels({"missingEvidence": None}) == []


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
        assert td.public_category_from_decision(on["decision"]) == (
            td.public_category_from_decision(off["decision"])
        )


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
