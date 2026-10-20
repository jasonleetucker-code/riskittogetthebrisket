"""Per-team projections (N-team spec §2.7-§2.9): category, market fairness,
Kleene overall, summary and raw conservation.  Pure — no engine runs here
except where a real ``decide`` result is needed."""

from __future__ import annotations

import itertools

import pytest

from src.trade import team_verdicts as tv
from src.trade import trade_decision as td


def _decision(headline, *, deciding="objectiveValue", direction=None, magnitude=None, lean=None):
    return {
        "headline": headline,
        "deciding": deciding,
        "leaning": lean,
        "components": {"objectiveValue": {"direction": direction, "magnitude": magnitude}},
    }


@pytest.mark.parametrize(
    ("decision", "category", "text"),
    [
        (_decision("NOT_ENOUGH_EVIDENCE"), "UNAVAILABLE", "Unavailable — insufficient evidence"),
        (
            _decision("YES", direction="favors", magnitude="large", lean="MAKE"),
            "STRONGLY_FAVORABLE",
            "Strongly favorable",
        ),
        (
            _decision("YES", direction="favors", magnitude="large", lean="LEAN_MAKE"),
            "FAVORABLE",
            "Favorable",
        ),
        (_decision("YES", direction="neutral"), "FAVORABLE", "Favorable"),
        (_decision("NO_TOO_CLOSE"), "APPROXIMATELY_EVEN", "Approximately even"),
        (
            _decision("NO", deciding="executionGate"),
            "UNFAVORABLE",
            "Unfavorable — roster can't fit this trade",
        ),
        (
            _decision("NO", direction="opposes", magnitude="large", lean="PASS"),
            "STRONGLY_UNFAVORABLE",
            "Strongly unfavorable",
        ),
        (_decision("NO", direction="opposes", magnitude="medium"), "UNFAVORABLE", "Unfavorable"),
        (None, "UNAVAILABLE", "Unavailable — insufficient evidence"),
        ({"headline": "MAYBE"}, "UNAVAILABLE", "Unavailable — insufficient evidence"),
    ],
)
def test_category_table(decision, category, text):
    assert tv.team_category(decision) == category
    assert tv.team_category_text(decision) == text
    # The PUBLIC-section alias is gone with the whole public section (Lane C,
    # fairness-only amendment): the category is private and has one owner.
    assert not hasattr(td, "public_category_from_decision")


def test_category_reason_only_for_the_execution_gate():
    assert tv.team_category_reason(_decision("NO", deciding="executionGate")) == "roster_limit"
    assert tv.team_category_reason(_decision("NO")) is None
    assert tv.team_category_reason(None) is None


# LC-1: the exhaustive (headline x leaning x A.direction x A.magnitude x
# deciding) mapping table — restored from the 2-team public-category test the
# move into ``team_verdicts`` dropped, plus the malformed gate pairings.
HEADLINES = ("YES", "NO", "NO_TOO_CLOSE", "NOT_ENOUGH_EVIDENCE", "BOGUS")
LEANINGS = td.RECOMMENDATIONS + ("??", None)
DIRECTIONS = ("favors", "opposes", "neutral", None)
MAGNITUDES = ("modest", "large", None)
DECIDING = (
    "objectiveValue",
    "rosterBenefit",
    "strategy",
    "both",
    "executionGate",
    "evidenceGate",
    None,
)
#: The only headline ``decide`` emits each gate with.
GATE_HEADLINE = {"executionGate": "NO", "evidenceGate": "NOT_ENOUGH_EVIDENCE"}


@pytest.mark.parametrize(
    ("headline", "lean", "direction", "magnitude", "deciding"),
    list(itertools.product(HEADLINES, LEANINGS, DIRECTIONS, MAGNITUDES, DECIDING)),
)
def test_exhaustive_category_mapping(headline, lean, direction, magnitude, deciding):
    d = _decision(headline, deciding=deciding, direction=direction, magnitude=magnitude, lean=lean)
    cat = tv.team_category(d)
    reason = tv.team_category_reason(d)
    assert cat in tv.CATEGORY_TEXT
    assert tv.team_category_text(d)  # always renders
    malformed_gate = deciding in GATE_HEADLINE and headline != GATE_HEADLINE[deciding]
    if malformed_gate or headline in ("NOT_ENOUGH_EVIDENCE", "BOGUS"):
        assert cat == "UNAVAILABLE"
        assert reason is None
        return
    if headline == "NO_TOO_CLOSE":
        assert cat == "APPROXIMATELY_EVEN" and reason is None
    if headline == "YES":
        assert cat in ("FAVORABLE", "STRONGLY_FAVORABLE"), "never unfavourable with YES"
        assert reason is None
        strong = direction == "favors" and magnitude == "large" and lean == "MAKE"
        assert (cat == "STRONGLY_FAVORABLE") == strong
    if headline == "NO":
        assert cat in ("UNFAVORABLE", "STRONGLY_UNFAVORABLE"), "never favourable with NO"
        if deciding == "executionGate":
            assert cat == "UNFAVORABLE" and reason == "roster_limit"
            assert tv.team_category_text(d) == tv.ROSTER_LIMIT_TEXT
        else:
            assert reason is None
            strong = direction == "opposes" and magnitude == "large" and lean == "PASS"
            assert (cat == "STRONGLY_UNFAVORABLE") == strong
    # Lane A asserted a PUBLIC-section alias here; on this branch the public
    # section is deleted (fairness-only amendment), so there is no alias to
    # agree with — pinned absent rather than silently dropped.
    assert not hasattr(td, "public_category_from_decision")


def test_malformed_gate_pairings_are_unavailable_never_confident():
    """LC-1: ``decide`` cannot emit these; the category must not invent one."""
    for headline in ("YES", "NO_TOO_CLOSE"):
        assert tv.team_category(_decision(headline, deciding="executionGate")) == "UNAVAILABLE"
    for headline in ("YES", "NO", "NO_TOO_CLOSE"):
        assert tv.team_category(_decision(headline, deciding="evidenceGate")) == "UNAVAILABLE"
    strong_yes = _decision(
        "YES", deciding="executionGate", direction="favors", magnitude="large", lean="MAKE"
    )
    assert tv.team_category(strong_yes) == "UNAVAILABLE"
    assert tv.team_category_reason(strong_yes) is None
    for bad in (None, [], "YES", {}, {"headline": "YES", "components": "x"}):
        assert tv.team_category(bad) in ("UNAVAILABLE", "FAVORABLE")
    assert tv.team_category({"headline": "YES"}) == "FAVORABLE"


def test_real_decide_results_never_hit_a_malformed_pairing():
    """Every gate pairing ``decide`` actually emits maps by the table (the
    malformed branch is unreachable from the owner — pinned so a change to
    ``decide`` that starts emitting one is noticed)."""
    from tests.trade import war_room_ui_payloads as gen
    from src.trade.analyze_trade import analyze_trade

    gates_seen = set()
    for name in gen.SCENARIOS:
        full = gen.build(name)
        sim = {k: v for k, v in full.items() if k not in ("analysis", "_fixture")}
        decision = analyze_trade(sim)["decision"]
        gate = GATE_HEADLINE.get(decision.get("deciding"))
        assert gate is None or decision["headline"] == gate, name
        if gate is not None:
            gates_seen.add(decision["deciding"])
            assert tv.team_category(decision) != "FAVORABLE", name
    assert gates_seen, "the fixtures must exercise at least one gate"


def _analysis(level="fair", *, available=True, gap=100, send=5000.0, recv=5100.0, extra=None):
    detail = {
        "band": {"level": level, "relativePct": 1.96, "bands": "fairness_bands_v1"},
        "vaAdjustedGap": gap,
        "sendingAdjusted": send,
        "receivingAdjusted": recv,
        "unresolvedIn": [],
        "unresolvedOut": [],
        "unpricedIn": [],
        "unpricedOut": [],
        "notOwnedBySender": [],
        **(extra or {}),
    }
    return {"lenses": {"market": {"available": available, "detail": detail}}}


def _sim(**kw):
    return {"receiving": [], "sending": [], **kw}


def test_fairness_reads_the_band_and_never_recomputes_it():
    f = tv.team_fairness(_sim(), _analysis("fair"))
    assert f["state"] == "FAIR" and f["reasonCode"] == "within_fairness_threshold"
    assert f["gap"] == 100 and f["largerAdjustedSide"] == 5100.0 and f["relativePct"] == 1.96
    for level in ("slight", "unfair", "lopsided"):
        g = tv.team_fairness(_sim(), _analysis(level))
        assert g["state"] == "NOT_FAIR" and g["level"] == level
        assert g["reasonCode"] == "outside_fairness_threshold"


@pytest.mark.parametrize(
    ("sim", "analysis", "reason"),
    [
        (_sim(), _analysis(available=False), "asset_not_evaluable"),
        (_sim(unresolvedIn=["Ghost"]), _analysis(), "asset_not_evaluable"),
        (_sim(), _analysis(extra={"unpricedOut": ["X"]}), "asset_not_evaluable"),
        (_sim(), _analysis(extra={"notOwnedBySender": [{"label": "P"}]}), "ownership_unverifiable"),
        (
            _sim(ownershipEvidence={"unverifiableAssetIds": ["p:1"]}),
            _analysis(),
            "ownership_unverifiable",
        ),
        (
            _sim(
                pickOwnership={"state": "unavailable", "reason": "x"},
                sending=[{"assetClass": "pick", "value": 10}],
            ),
            _analysis(),
            "ownership_unverifiable",
        ),
        (
            _sim(sending=[{"name": "Q", "value": 900, "quarantined": True}]),
            _analysis(),
            "evaluation_unavailable",
        ),
        (
            _sim(sending=[{"name": "S", "value": 900, "valueFreshness": "low"}]),
            _analysis(),
            "evaluation_unavailable",
        ),
        (_sim(), {"lenses": {}}, "asset_not_evaluable"),
        (None, None, "evaluation_unavailable"),
        (_sim(), _analysis(level="weird"), "evaluation_unavailable"),
    ],
)
def test_fairness_unable_reasons(sim, analysis, reason):
    f = tv.team_fairness(sim, analysis)
    assert f["state"] == "UNABLE" and f["reasonCode"] == reason
    assert f["level"] is None and f["gap"] is None


def test_asset_evidence_gaps_is_the_asset_half_of_the_gates():
    assert td.ASSET_EVIDENCE_GATE_CODES == (
        "no_priced_assets",
        "off_board_assets",
        "unpriced_assets",
        "unheld_assets",
        "pick_ownership_unknown",
        "ownership_unverifiable",
        "quarantined_values",
        "stale_values",
    )


@pytest.mark.parametrize(
    "states",
    list(itertools.product(("FAIR", "NOT_FAIR", "UNABLE"), repeat=3)),
)
def test_overall_is_a_kleene_and(states):
    out = tv.fairness_overall(states)
    if "NOT_FAIR" in states:
        assert out == {"state": "NOT_FAIR", "reasonCode": "not_all_teams_fair"}
    elif "UNABLE" in states:
        assert out == {"state": "UNABLE", "reasonCode": "evidence_insufficient"}
    else:
        assert out == {"state": "FAIR", "reasonCode": "all_teams_fair"}
    # Order never matters.
    for perm in itertools.permutations(states):
        assert tv.fairness_overall(perm) == out


def test_overall_of_nothing_is_unable():
    assert tv.fairness_overall([])["state"] == "UNABLE"


def _team(rid, name, *, gives=(), receives=(), category="FAVORABLE", fairness="FAIR"):
    return {
        "rosterId": rid,
        "team": {"rosterId": rid, "name": name},
        "gives": list(gives),
        "receives": list(receives),
        "analysis": {"decision": {"headline": "YES"}},
        "category": category,
        "categoryText": tv.CATEGORY_TEXT[category],
        "fairness": {"state": fairness},
    }


def test_summary_is_ordered_by_roster_id_and_carries_no_trade_level_verdict():
    g = {"assetId": "p:1", "value": 100, "valueState": "priced"}
    teams = [
        _team(7, "Seven", receives=[g], category="UNFAVORABLE", fairness="NOT_FAIR"),
        _team(3, "Three", gives=[g]),
    ]
    out = tv.all_team_summary(teams, leg_count=1)
    assert [p["rosterId"] for p in out["perTeam"]] == [3, 7]
    assert out["lines"] == ["Three: Favorable.", "Seven: Unfavorable."]
    assert out["fairnessOverall"]["state"] == "NOT_FAIR"
    assert out["conservation"] == {
        "assetsSent": 1,
        "assetsReceived": 1,
        "pricedRawSent": 100,
        "pricedRawReceived": 100,
        "balanced": True,
    }
    for banned in ("overallRecommendation", "winner", "headline", "recommendation"):
        assert banned not in out
    assert out["nonConservedNote"] == tv.NON_CONSERVED_NOTE


def test_conservation_excludes_assets_unpriced_in_either_view():
    priced = {"assetId": "p:1", "value": 100, "valueState": "priced"}
    unheld = {"assetId": "p:2", "value": None, "valueState": "not_held"}
    seen = {"assetId": "p:2", "value": 500, "valueState": "priced"}
    out = tv.conservation(
        [_team(1, "A", gives=[priced, unheld]), _team(2, "B", receives=[priced, seen])],
        leg_count=2,
    )
    assert out["pricedRawSent"] == out["pricedRawReceived"] == 100
    assert out["balanced"] is True
    # A leg counted twice is not balanced.
    dup = tv.conservation([_team(1, "A", gives=[priced, priced]), _team(2, "B")], leg_count=1)
    assert dup["balanced"] is False
