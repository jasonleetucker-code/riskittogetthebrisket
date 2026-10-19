"""The public Trade Advisor category mapping (design §3; test group B).

``trade_decision.public_category_from_decision`` maps the ONE canonical
decision onto five public categories with no threshold of its own.  These
tests pin the full table, the safety invariants the directive names ("do not
label a trade strongly favorable unless the authoritative evaluation supports
that conclusion"; "if the private calculator considers a trade unfavorable to
Team A, the public advisor must not call it strongly favorable"), the
perspective mirror, the fail-closed reason codes, and that the public copy
exists in exactly one backend module.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from src.trade import trade_decision as td
from tests.api.trade_advisor_support import decision

REPO = Path(__file__).resolve().parents[2]

HEADLINES = ("YES", "NO", "NO_TOO_CLOSE", "NOT_ENOUGH_EVIDENCE", "SOMETHING_NEW")
LEANINGS = td.RECOMMENDATIONS
DIRECTIONS = ("favors", "opposes", "neutral", None)
MAGNITUDES = ("modest", "large", None)
DECIDING = ("objectiveValue", "rosterBenefit", "strategy", "both", "executionGate", "evidenceGate")


def _all():
    for h, lean, d, m, dec in itertools.product(
        HEADLINES, LEANINGS, DIRECTIONS, MAGNITUDES, DECIDING
    ):
        yield h, lean, d, m, dec, decision(h, leaning=lean, direction=d, magnitude=m, deciding=dec)


def test_every_combination_maps_to_a_public_category():
    for *_k, dec in _all():
        assert td.public_category_from_decision(dec) in td.PUBLIC_CATEGORIES


def test_strongly_favorable_only_with_yes_a_large_favouring_band_and_make():
    for h, lean, d, m, dec_kind, dec in _all():
        if td.public_category_from_decision(dec) == "STRONGLY_FAVORABLE":
            assert (h, d, m, lean) == ("YES", "favors", "large", "MAKE"), (h, lean, d, m, dec_kind)
            assert dec_kind != "executionGate"


def test_strongly_unfavorable_only_with_no_a_large_opposing_band_and_pass():
    for h, lean, d, m, dec_kind, dec in _all():
        if td.public_category_from_decision(dec) == "STRONGLY_UNFAVORABLE":
            assert (h, d, m, lean) == ("NO", "opposes", "large", "PASS")


def test_never_favourable_with_no_and_never_unfavourable_with_yes():
    for h, *_r, dec in _all():
        cat = td.public_category_from_decision(dec)
        if h == "NO":
            assert cat in ("UNFAVORABLE", "STRONGLY_UNFAVORABLE")
        if h == "YES":
            assert cat in ("FAVORABLE", "STRONGLY_FAVORABLE", "UNAVAILABLE")


def test_not_enough_evidence_and_unknown_headlines_are_unavailable():
    for h, *_r, dec in _all():
        if h in ("NOT_ENOUGH_EVIDENCE", "SOMETHING_NEW"):
            assert td.public_category_from_decision(dec) == "UNAVAILABLE"
    for junk in (None, [], "YES", {"headline": None}):
        assert td.public_category_from_decision(junk) == "UNAVAILABLE"


def test_too_close_is_approximately_even_never_strong():
    for h, *_r, dec in _all():
        if h == "NO_TOO_CLOSE":
            assert td.public_category_from_decision(dec) == "APPROXIMATELY_EVEN"


def test_never_strongly_favorable_when_the_value_band_is_against_the_perspective():
    for h, lean, d, m, _k, dec in _all():
        if d == "opposes" and m == "large":
            assert td.public_category_from_decision(dec) != "STRONGLY_FAVORABLE"


def test_execution_gate_is_unfavorable_with_the_roster_limit_copy():
    dec = decision("NO", deciding="executionGate", leaning="TOO_CLOSE")
    assert td.public_category_from_decision(dec) == "UNFAVORABLE"
    assert td.public_reason_code(dec) == "roster_limit"
    assert td.public_text("UNFAVORABLE", "roster_limit")["headline"] == (
        "DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE"
    )


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
    for h, lean, d, m in itertools.product(_MIRROR_HEADLINE, LEANINGS, DIRECTIONS, MAGNITUDES):
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


@pytest.mark.parametrize(
    ("level", "net", "expected"),
    [
        ("fair", 10, "APPROXIMATELY_EVEN"),
        ("fair", -10, "APPROXIMATELY_EVEN"),
        ("slight", 400, "FAVORABLE"),
        ("slight", -400, "UNFAVORABLE"),
        ("unfair", 900, "STRONGLY_FAVORABLE"),
        ("lopsided", -2000, "STRONGLY_UNFAVORABLE"),
        ("unknown", 5, "UNAVAILABLE"),
        ("slight", None, "UNAVAILABLE"),
    ],
)
def test_net_band_mapping_for_multi_team(level, net, expected):
    assert td.public_category_from_net_band({"level": level}, net) == expected


def test_net_band_mapping_is_sign_symmetric():
    for level in ("fair", "slight", "unfair", "lopsided"):
        for net in (1, 250, 5000):
            a = td.public_category_from_net_band({"level": level}, net)
            b = td.public_category_from_net_band({"level": level}, -net)
            assert _MIRROR_CAT[a] == b


# ── Reason codes ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("gaps", "expected"),
    [
        (["off_board_assets"], "asset_not_evaluable"),
        (["unpriced_assets", "posture_unknown"], "asset_not_evaluable"),
        (["no_priced_assets"], "asset_not_evaluable"),
        (["unheld_assets"], "ownership_unverifiable"),
        (["pick_ownership_unknown", "stale_values"], "ownership_unverifiable"),
        (["unheld_assets", "off_board_assets"], "asset_not_evaluable"),
        (["posture_unknown"], None),
        (["unprojected_players"], None),
        (["quarantined_values"], None),
        (["stale_values"], None),
        (["roster_unknown"], None),
        (["roster_limit_unknown"], None),
        (["forced_drop_unpriced"], None),
        (["off_board_assets", "a_future_code"], None),
        (["a_future_code"], None),
        ([], None),
    ],
)
def test_reason_codes_collapse_and_fail_closed(gaps, expected):
    dec = decision("NOT_ENOUGH_EVIDENCE", deciding="evidenceGate", gaps=gaps)
    assert td.public_reason_code(dec) == expected


def test_every_evidence_gap_code_the_engine_emits_is_classified():
    """A new ``_evidence_gaps`` code must be consciously classified (exposed
    or collapsed); until it is, ``public_reason_code`` answers ``None``."""
    import re

    src = (REPO / "src" / "trade" / "trade_decision.py").read_text()
    body = src[src.index("def _evidence_gaps(") : src.index("def _objective_value(")]
    emitted = set(re.findall(r'_missing\(\s*"([a-z_]+)"', body))
    known = (
        td._PUBLIC_ASSET_GAP_CODES | td._PUBLIC_OWNERSHIP_GAP_CODES | td._PUBLIC_COLLAPSED_GAP_CODES
    )
    assert emitted and emitted <= known, emitted - known


def test_reason_text_is_only_the_public_table():
    assert set(td.PUBLIC_REASON_TEXT) == {
        "asset_not_evaluable",
        "ownership_unverifiable",
        "multi_team_unsupported",
        "roster_limit",
    }
    for text in td.PUBLIC_REASON_TEXT.values():
        assert not any(ch.isdigit() for ch in text)
    for copy in td.PUBLIC_CATEGORY_TEXT.values():
        assert not any(ch.isdigit() for v in copy.values() for ch in v)


def test_category_copy_lives_only_in_the_decision_owner():
    needles = [c["headline"] for c in td.PUBLIC_CATEGORY_TEXT.values()]
    needles += [c["message"] for c in td.PUBLIC_CATEGORY_TEXT.values()]
    hits = []
    for path in [*(REPO / "src").rglob("*.py"), REPO / "server.py"]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(n in text for n in needles):
            hits.append(path.relative_to(REPO).as_posix())
    assert hits == ["src/trade/trade_decision.py"], hits


def test_counterfactuals_flag_skips_only_what_would_change(monkeypatch):
    """``decide(counterfactuals=False)`` returns the same decision with an
    empty ``whatWouldChange`` and never runs the search."""
    from src.trade import trade_decision

    calls = []
    real = trade_decision._what_would_change
    monkeypatch.setattr(
        trade_decision,
        "_what_would_change",
        lambda *a, **k: calls.append(1) or real(*a, **k),
    )
    from tests.api.test_trade_nfl_exposure import _SETTINGS, _contract, _us
    from src.api import trade_simulator
    from src.trade.analyze_trade import analyze_trade

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
