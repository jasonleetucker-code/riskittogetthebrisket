"""R1-L2 / F2 (public side): a quarantined or stale value must never back a
public FAIR / NOT FAIR.  The engine's evidence gate already answers UNABLE for
both; ``public_advisor.team_fairness_input`` re-reads the evidence through the
decision owner's own ``asset_evidence_codes`` so the public answer fails
closed even if the gate order or the engine row contract changes (today the
engine rows still say ``valueState: "priced"`` for a quarantined value —
#1882 F2; a newer non-``priced`` row state is honoured as well).
"""

from __future__ import annotations

import pytest

from src.trade import public_advisor, team_verdicts


def _asset(name, value=4000, **flags):
    return {"name": name, "value": value, **flags}


def _entry(*, state, reason, sim_assets=(), row_states=("priced", "priced")):
    gives_state, recv_state = row_states
    return {
        "rosterId": 1,
        "gives": [{"assetId": "p:1", "value": 4000, "valueState": gives_state}],
        "receives": [{"assetId": "p:2", "value": 3900, "valueState": recv_state}],
        "simulation": {
            "sending": [_asset("One")],
            "receiving": list(sim_assets) or [_asset("Two", 3900)],
        },
        "fairness": {"state": state, "reasonCode": reason},
    }


FAIR = (team_verdicts.FAIR, "within_fairness_threshold")
NOT_FAIR = (team_verdicts.NOT_FAIR, "outside_fairness_threshold")


@pytest.mark.parametrize("verdict", [FAIR, NOT_FAIR])
def test_clean_evidence_keeps_the_engine_verdict(verdict):
    state, reason = verdict
    t = public_advisor.team_fairness_input(_entry(state=state, reason=reason))
    assert (t.state, t.reason_code) == (state, reason)


@pytest.mark.parametrize("verdict", [FAIR, NOT_FAIR])
@pytest.mark.parametrize(
    "flags",
    [{"quarantined": True}, {"valueFreshness": "low"}],
    ids=["quarantined", "stale"],
)
def test_withheld_value_in_the_simulation_fails_closed(verdict, flags):
    state, reason = verdict
    entry = _entry(state=state, reason=reason, sim_assets=[_asset("Two", 3900, **flags)])
    t = public_advisor.team_fairness_input(entry)
    assert t.state == team_verdicts.UNABLE
    assert t.reason_code == "evaluation_unavailable"
    assert t.unavailable_asset_ids == ()  # no asset named (owner exposure decision F-1)
    out = public_advisor._team_result(t)
    assert out.result == public_advisor.UNABLE_TO_DETERMINE
    assert out.label == "UNABLE TO DETERMINE"


@pytest.mark.parametrize("row_state", ["quarantined", "stale", "withheld", "unpriced"])
def test_any_non_priced_row_state_fails_closed(row_state):
    """Forward-compatible with Lane A adding an explicit row state."""
    state, reason = FAIR
    t = public_advisor.team_fairness_input(
        _entry(state=state, reason=reason, row_states=("priced", row_state))
    )
    assert (t.state, t.reason_code) == (team_verdicts.UNABLE, "evaluation_unavailable")


def test_engine_unable_reasons_are_left_alone():
    """An engine UNABLE keeps its own reason (and its named ids)."""
    entry = _entry(
        state=team_verdicts.UNABLE,
        reason="asset_not_evaluable",
        row_states=("priced", "unpriced"),
    )
    t = public_advisor.team_fairness_input(entry)
    assert (t.state, t.reason_code) == (team_verdicts.UNABLE, "asset_not_evaluable")
    assert t.unavailable_asset_ids == ("p:2",)


def test_overall_is_unable_not_fair_when_the_only_verdict_rests_on_a_withheld_value():
    a = _entry(state=team_verdicts.FAIR, reason="within_fairness_threshold")
    b = dict(
        _entry(
            state=team_verdicts.FAIR,
            reason="within_fairness_threshold",
            sim_assets=[_asset("Two", 3900, quarantined=True)],
        ),
        rosterId=2,
    )
    teams = [public_advisor.team_fairness_input(e) for e in (a, b)]
    overall = team_verdicts.fairness_overall([t.state for t in teams])["state"]
    assert overall == team_verdicts.UNABLE
    res = public_advisor.reduce_fairness(teams, overall_state=overall, legs=[])
    assert res.overall.result == public_advisor.UNABLE_TO_DETERMINE
