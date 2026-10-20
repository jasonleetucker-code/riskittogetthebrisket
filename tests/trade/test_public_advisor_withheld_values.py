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


# ── evaluate(): the engine's OWN overall disagrees with the public answer ──
#
# The one case where the public check changes an answer is an engine FAIR /
# NOT_FAIR over a row whose valueState is not ``priced``.  The engine's own
# ``summary.fairnessOverall`` then still says FAIR / NOT_FAIR.  These tests
# hand evaluate() exactly that engine result (they never recompute the overall
# from the already-downgraded teams), so the published overall must come from
# the public per-team states — not a 503 from the cross-check.


def _team(rid, state, reason, *, give_state="priced", recv_state="priced"):
    return {
        "rosterId": rid,
        "gives": [{"assetId": f"p:{rid}0", "value": 4000, "valueState": give_state}],
        "receives": [{"assetId": f"p:{rid}1", "value": 3900, "valueState": recv_state}],
        "fairness": {"state": state, "reasonCode": reason},
    }


def _run_evaluate(monkeypatch, teams, engine_overall):
    from types import SimpleNamespace

    from src.trade.trade_ledger import Leg

    result = {
        "teams": {t["rosterId"]: t for t in teams},
        "summary": {"fairnessOverall": {"state": engine_overall, "reasonCode": "x"}},
    }
    monkeypatch.setattr(analyze_service, "analyze_trade_n", lambda *a, **k: copy.deepcopy(result))
    ledger = SimpleNamespace(
        teams=tuple(t["rosterId"] for t in teams),
        legs=[Leg("p:10", 1, 2), Leg("p:20", 2, 1)],
    )
    return public_advisor.evaluate(object(), ledger)


WITHHELD_STATES = ["off_board", "quarantined", "stale", "unpriced", "not_held", "withheld"]


@pytest.mark.parametrize("row_state", WITHHELD_STATES)
def test_engine_fair_overall_over_a_withheld_row_publishes_unable_not_503(monkeypatch, row_state):
    """The reviewer's reproduction: two engine-FAIR teams, one carrying a
    non-priced row, engine overall FAIR.  Before the fix evaluate() raised
    InvariantViolation (route 503)."""
    out = _run_evaluate(
        monkeypatch,
        [
            _team(1, team_verdicts.FAIR, "within_fairness_threshold"),
            _team(2, team_verdicts.FAIR, "within_fairness_threshold", recv_state=row_state),
        ],
        team_verdicts.FAIR,
    )
    assert out.overall.result == public_advisor.UNABLE_TO_DETERMINE
    assert out.overall.reason_code == "evidence_insufficient"
    t1, t2 = out.teams
    assert (t1.roster_id, t1.result) == (1, public_advisor.FAIR)
    assert (t2.roster_id, t2.result, t2.reason_code) == (
        2,
        public_advisor.UNABLE_TO_DETERMINE,
        "evaluation_unavailable",
    )
    assert t2.unavailable_asset_ids == ()  # F-1: never named


@pytest.mark.parametrize("row_state", ["quarantined", "stale"])
def test_engine_not_fair_resting_on_a_withheld_row_publishes_unable(monkeypatch, row_state):
    out = _run_evaluate(
        monkeypatch,
        [
            _team(1, team_verdicts.NOT_FAIR, "outside_fairness_threshold", give_state=row_state),
            _team(2, team_verdicts.FAIR, "within_fairness_threshold"),
        ],
        team_verdicts.NOT_FAIR,
    )
    assert out.overall.result == public_advisor.UNABLE_TO_DETERMINE
    assert [t.result for t in out.teams] == [
        public_advisor.UNABLE_TO_DETERMINE,
        public_advisor.FAIR,
    ]


def test_a_priced_not_fair_team_keeps_the_overall_not_fair(monkeypatch):
    """Kleene AND: one definite NOT_FAIR on priced evidence still proves the
    trade is not fair for every team, whatever another team's evidence."""
    out = _run_evaluate(
        monkeypatch,
        [
            _team(1, team_verdicts.NOT_FAIR, "outside_fairness_threshold"),
            _team(2, team_verdicts.FAIR, "within_fairness_threshold", recv_state="stale"),
        ],
        team_verdicts.NOT_FAIR,
    )
    assert out.overall.result == public_advisor.NOT_FAIR
    assert [t.result for t in out.teams] == [
        public_advisor.NOT_FAIR,
        public_advisor.UNABLE_TO_DETERMINE,
    ]


def test_engine_fair_team_with_an_unknown_reason_publishes_unable_not_503(monkeypatch):
    """Same class: the reducer fails an unknown reason closed, so the engine's
    FAIR overall must not be copied over it."""
    out = _run_evaluate(
        monkeypatch,
        [
            _team(1, team_verdicts.FAIR, "within_fairness_threshold"),
            _team(2, team_verdicts.FAIR, "a_reason_the_public_side_does_not_know"),
        ],
        team_verdicts.FAIR,
    )
    assert out.overall.result == public_advisor.UNABLE_TO_DETERMINE
    assert out.teams[1].result == public_advisor.UNABLE_TO_DETERMINE


@pytest.mark.parametrize(
    ("states", "engine_overall"),
    [
        ((team_verdicts.FAIR, team_verdicts.FAIR), team_verdicts.NOT_FAIR),
        ((team_verdicts.FAIR, team_verdicts.UNABLE), team_verdicts.FAIR),
        ((team_verdicts.NOT_FAIR, team_verdicts.FAIR), team_verdicts.FAIR),
        ((team_verdicts.NOT_FAIR, team_verdicts.FAIR), team_verdicts.UNABLE),
    ],
)
@pytest.mark.parametrize("withheld", [False, True], ids=["priced", "withheld-row"])
def test_an_engine_that_disagrees_with_itself_is_still_never_published(
    monkeypatch, states, engine_overall, withheld
):
    """The cross-check is kept, at full precision, against the engine's OWN
    per-team states (read before the public downgrade) — a withheld row can
    neither trigger it nor hide a genuine engine inconsistency."""
    reasons = {
        team_verdicts.FAIR: "within_fairness_threshold",
        team_verdicts.NOT_FAIR: "outside_fairness_threshold",
        team_verdicts.UNABLE: "evidence_insufficient",
    }
    teams = [
        _team(i + 1, st, reasons[st], recv_state="quarantined" if withheld else "priced")
        for i, st in enumerate(states)
    ]
    with pytest.raises(public_advisor.InvariantViolation, match="engine overall"):
        _run_evaluate(monkeypatch, teams, engine_overall)


def test_evaluate_never_publishes_an_overall_more_certain_than_the_engine():
    """Every engine-consistent combination of two teams x {FAIR, NOT_FAIR,
    UNABLE} x {priced, withheld}: the published overall is the engine's, or
    UNABLE.  FAIR / NOT_FAIR is never invented."""
    import itertools

    reasons = {
        team_verdicts.FAIR: "within_fairness_threshold",
        team_verdicts.NOT_FAIR: "outside_fairness_threshold",
        team_verdicts.UNABLE: "evidence_insufficient",
    }
    states = [team_verdicts.FAIR, team_verdicts.NOT_FAIR, team_verdicts.UNABLE]
    mp = pytest.MonkeyPatch()
    try:
        for (s1, w1), (s2, w2) in itertools.product(
            itertools.product(states, [False, True]), repeat=2
        ):
            engine_overall = team_verdicts.fairness_overall([s1, s2])["state"]
            teams = [
                _team(1, s1, reasons[s1], give_state="stale" if w1 else "priced"),
                _team(2, s2, reasons[s2], give_state="stale" if w2 else "priced"),
            ]
            out = _run_evaluate(mp, teams, engine_overall)
            published = public_advisor._RESULT_TO_STATE[out.overall.result]
            assert published in (engine_overall, team_verdicts.UNABLE), (s1, w1, s2, w2)
            if not (w1 or w2):
                assert published == engine_overall, (s1, s2)
    finally:
        mp.undo()


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
    """Real board stamps over HTTP.  Note: the ENGINE's own evidence gate
    (``asset_evidence_gaps``) already answers this case UNABLE, so this test
    alone does not exercise the public valueState check — the
    ``..._engine_overall_is_fair_over_a_withheld_row`` route tests below do."""
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


def _with_withheld_row(asset_id: str, row_state: str):
    """Wrap the REAL engine so its answer is the disagreeing shape: the team
    fairness states and ``fairnessOverall`` stay the engine's own (FAIR on
    the clean board) while one asset's rows carry a non-priced valueState."""
    real = analyze_service.analyze_trade_n

    def wrapped(*a, **k):
        res = real(*a, **k)
        for team in res["teams"].values():
            for row in (*team.get("gives", []), *team.get("receives", [])):
                if str(row.get("assetId")) == asset_id:
                    row["valueState"] = row_state
                    row["value"] = None
        return res

    return wrapped


@pytest.mark.parametrize("row_state", ["quarantined", "stale"])
def test_route_answers_unable_not_503_when_the_engine_overall_is_fair_over_a_withheld_row(
    advisor_client, monkeypatch, row_state
):
    """Over HTTP, the path the engine's own gate does NOT already answer: the
    engine overall is FAIR and only the row valueState says the value is
    withheld.  The public check decides, and the answer is a 200 with those
    teams UNABLE TO DETERMINE — not a 503."""
    withheld = _with_withheld_row("p:303", row_state)
    captured = {}

    def spy(*a, **k):
        res = withheld(*a, **k)
        captured["overall"] = res["summary"]["fairnessOverall"]["state"]
        captured["states"] = {rid: t["fairness"]["state"] for rid, t in res["teams"].items()}
        return res

    monkeypatch.setattr(analyze_service, "analyze_trade_n", spy)
    r = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.FAIR_TWO, teams=(1, 3)))
    # The engine itself still said FAIR (this is the disagreeing shape).
    assert captured["overall"] == team_verdicts.FAIR
    assert set(captured["states"].values()) == {team_verdicts.FAIR}
    assert r.status_code == 200, r.text
    body = r.json()
    public_advisor.assert_advisor_payload_value_free(body, kind="analyze")
    assert body["overall"]["result"] == "UNABLE_TO_DETERMINE"
    for team in body["teams"]:
        assert team["result"] == "UNABLE_TO_DETERMINE", team
        assert team["reasonCode"] == "evaluation_unavailable", team
        assert team["unavailableAssetIds"] == [], team
    assert row_state not in r.text.lower()


def test_route_withheld_row_answer_is_decided_by_the_public_check(advisor_client, monkeypatch):
    """Sensitivity control for the test above: with the public check disabled
    the same engine answer would publish FAIR — so the UNABLE above is the
    public check working, not an engine gate answering first."""
    monkeypatch.setattr(
        analyze_service, "analyze_trade_n", _with_withheld_row("p:303", "quarantined")
    )
    monkeypatch.setattr(public_advisor, "_withheld_value_evidence", lambda entry: False)
    r = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.FAIR_TWO, teams=(1, 3)))
    assert r.status_code == 200, r.text
    assert r.json()["overall"]["result"] == "FAIR"
