"""R1-L2 / F2 (public side): a quarantined or stale value must never back a
public FAIR / NOT FAIR.

ONE owner: the engine's row ``valueState`` (``analyze_service._value_entry``,
Lane A #1882 — ``quarantined`` / ``stale`` / ``unpriced`` / ``off_board`` /
``not_held`` / ``priced``).  ``public_advisor.team_fairness_input`` reads that
state and nothing else: any asset on a team's side that is not ``priced`` makes
the team UNABLE TO DETERMINE with the public reason ``evaluation_unavailable``,
and the asset is NOT named (owner exposure decision F-1 is open; this is the
conservative behaviour).  The public side's former second read of the
simulation through ``trade_decision.asset_evidence_codes`` is deleted.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

import server
from src.trade import analyze_service, public_advisor, team_verdicts
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

REPO = Path(__file__).resolve().parents[2]


def _entry(*, state, reason, row_states=("priced", "priced")):
    gives_state, recv_state = row_states
    return {
        "rosterId": 1,
        "gives": [{"assetId": "p:1", "value": 4000, "valueState": gives_state}],
        "receives": [{"assetId": "p:2", "value": 3900, "valueState": recv_state}],
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
@pytest.mark.parametrize("row_state", ["quarantined", "stale"])
@pytest.mark.parametrize("side", ["gives", "receives"])
def test_engine_withheld_row_state_fails_closed_without_naming_the_asset(verdict, row_state, side):
    state, reason = verdict
    row_states = (row_state, "priced") if side == "gives" else ("priced", row_state)
    t = public_advisor.team_fairness_input(
        _entry(state=state, reason=reason, row_states=row_states)
    )
    assert t.state == team_verdicts.UNABLE
    assert t.reason_code == "evaluation_unavailable"
    assert t.unavailable_asset_ids == ()  # no asset named (owner exposure decision F-1)
    out = public_advisor._team_result(t)
    assert out.result == public_advisor.UNABLE_TO_DETERMINE
    assert out.label == "UNABLE TO DETERMINE"
    assert out.reason_code == "evaluation_unavailable"
    assert out.unavailable_asset_ids == ()


def test_every_engine_value_state_but_priced_fails_closed():
    """The engine's whole vocabulary: only ``priced`` may back a verdict."""
    assert "priced" in analyze_service.VALUE_STATES
    for vs in analyze_service.VALUE_STATES:
        t = public_advisor.team_fairness_input(
            _entry(
                state=team_verdicts.FAIR,
                reason="within_fairness_threshold",
                row_states=("priced", vs),
            )
        )
        expected = team_verdicts.FAIR if vs == "priced" else team_verdicts.UNABLE
        assert t.state == expected, vs


@pytest.mark.parametrize(
    "bad_row", [None, "p:2", {"assetId": "p:2"}], ids=["none", "str", "no-state"]
)
def test_missing_or_malformed_row_state_is_not_priced(bad_row):
    entry = _entry(state=team_verdicts.FAIR, reason="within_fairness_threshold")
    entry["receives"] = [bad_row]
    t = public_advisor.team_fairness_input(entry)
    assert (t.state, t.reason_code) == (team_verdicts.UNABLE, "evaluation_unavailable")


def test_engine_asset_not_evaluable_never_names_a_withheld_asset():
    """An engine UNABLE ``asset_not_evaluable`` names only unpriced / off-board
    assets; a quarantined / stale one on the same side stays unnamed (F-1)."""
    entry = _entry(
        state=team_verdicts.UNABLE,
        reason="asset_not_evaluable",
        row_states=("quarantined", "unpriced"),
    )
    t = public_advisor.team_fairness_input(entry)
    assert (t.state, t.reason_code) == (team_verdicts.UNABLE, "asset_not_evaluable")
    assert t.unavailable_asset_ids == ("p:2",)


def test_public_side_has_no_second_value_state_owner():
    """One owner: the public module never re-derives a value state from the
    simulation (no ``asset_evidence_codes`` / quarantine / freshness read)."""
    src = (REPO / "src" / "trade" / "public_advisor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    for forbidden in ("asset_evidence_codes", "asset_evidence_gaps"):
        assert forbidden not in names | imported, forbidden
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    for forbidden in ("quarantined_values", "stale_values", "valueFreshness"):
        assert forbidden not in strings, forbidden


@pytest.mark.parametrize("row_state", ["quarantined", "stale", "withheld", "unpriced"])
def test_any_non_priced_row_state_fails_closed(row_state):
    """Lane A's explicit states, plus any state a newer engine adds."""
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
            row_states=("priced", "quarantined"),
        ),
        rosterId=2,
    )
    teams = [public_advisor.team_fairness_input(e) for e in (a, b)]
    overall = team_verdicts.fairness_overall([t.state for t in teams])["state"]
    assert overall == team_verdicts.UNABLE
    res = public_advisor.reduce_fairness(teams, overall_state=overall, legs=[])
    assert res.overall.result == public_advisor.UNABLE_TO_DETERMINE


# ── End to end over the real engine and the real route ───────────────────


def _withheld_contract(kind: str) -> dict:
    """The synthetic board with Charlie Backer (p:303) quarantined or stale —
    the pipeline's own stamps, which the engine turns into a row state."""
    c = copy.deepcopy(S.contract())
    for row in c["playersArray"]:
        if row.get("playerId") == "303":
            if kind == "quarantined":
                row["quarantined"] = True
            else:
                row["confidenceAxes"] = {"freshness": "low"}
    return c


@pytest.mark.parametrize("kind", ["quarantined", "stale"])
def test_route_answers_unable_for_every_team_touching_a_withheld_asset(
    advisor_client,
    monkeypatch,
    kind,
):
    monkeypatch.setattr(server, "latest_contract_data", _withheld_contract(kind))
    r = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.FAIR_TWO, teams=(1, 3)))
    assert r.status_code == 200, r.text
    body = r.json()
    public_advisor.assert_advisor_payload_value_free(body, kind="analyze")
    assert body["overall"]["result"] == "UNABLE_TO_DETERMINE"
    for team in body["teams"]:
        # p:303 is on both teams' sides (3 sends it, 1 receives it).
        assert team["result"] == "UNABLE_TO_DETERMINE", team
        assert team["reasonCode"] == "evaluation_unavailable", team
        assert team["unavailableAssetIds"] == [], team  # F-1: not named
    # The withheld state never leaks as a public word.
    assert kind not in r.text.lower()


def test_route_keeps_the_fair_answer_when_every_asset_is_priced(advisor_client):
    """Control for the test above: the same trade on the clean board is FAIR."""
    r = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.FAIR_TWO, teams=(1, 3)))
    assert r.status_code == 200, r.text
    assert r.json()["overall"]["result"] == "FAIR"
