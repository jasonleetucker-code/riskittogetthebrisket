"""``scripts/smoke_trade_analysis.py``: ledger builder, classifier, CLI, and an
end-to-end run against the real archived board through the real routes."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

from src.trade import team_verdicts, trade_decision

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "smoke_trade_analysis", REPO / "scripts" / "smoke_trade_analysis.py"
)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)  # type: ignore[union-attr]


# ── pinned vocabularies (the script is stdlib-only, so it carries copies) ──


def test_vocabularies_match_the_owners():
    assert smoke.CATEGORIES == team_verdicts.CATEGORIES
    assert smoke.FAIRNESS_STATES == team_verdicts.FAIRNESS_STATES
    assert set(smoke.HEADLINES) == set(trade_decision.HEADLINE_TEXT)


# ── synthetic contract / responses ─────────────────────────────────────────


def _contract(n_teams=4, per_team=3, ambiguous=False):
    teams, ids, rows = [], {}, []
    pid = 100
    for rid in range(1, n_teams + 1):
        pids = []
        for k in range(per_team):
            pid += 1
            pids.append(str(pid))
            ids[str(pid)] = f"P{pid}"
            rows.append({"displayName": f"P{pid}", "rankDerivedValue": 1000 + pid + (k * 10)})
        teams.append({"roster_id": rid, "ownerId": f"o{rid}", "name": f"T{rid}", "playerIds": pids})
    if ambiguous:
        rows.append({"displayName": "P103", "rankDerivedValue": 99999})
    return {"sleeper": {"teams": teams, "idToPlayer": ids}, "playersArray": rows}


def test_builder_picks_each_teams_top_player_deterministically():
    built = smoke.build_trades(_contract(), "dynasty_main")
    assert built["meta"]["threeTeamRosterIds"] == [1, 2, 3]
    assets = built["three"]["assets"]
    # team 1 holds 101..103; top value is 103 (value 1000+103+20)
    assert assets[0] == {"id": "p:103", "from": 1, "to": 2}
    assert [a["from"] for a in assets] == [1, 2, 3] and [a["to"] for a in assets] == [2, 3, 1]
    two = built["two"]
    assert two["team"] == "o1" and two["playerIdsOut"] == ["103"] and two["playerIdsIn"] == ["106"]
    assert smoke.build_trades(_contract(), "dynasty_main") == built


def test_builder_never_uses_an_ambiguous_name_or_unpriced_player():
    c = _contract(ambiguous=True)  # P103 now carried by two rows -> ambiguous
    built = smoke.build_trades(c, "dynasty_main")
    assert built["three"]["assets"][0]["id"] == "p:102"
    c = _contract()
    for r in c["playersArray"]:
        r["rankDerivedValue"] = None
    with pytest.raises(smoke.BuildError):
        smoke.build_trades(c, "dynasty_main")


def test_builder_refuses_a_player_held_by_two_rosters_and_too_few_teams():
    c = _contract()
    c["sleeper"]["teams"][1]["playerIds"].append("103")  # 103 now on two rosters
    assert smoke.build_trades(c, "dynasty_main")["three"]["assets"][0]["id"] == "p:102"
    with pytest.raises(smoke.BuildError):
        smoke.build_trades(_contract(n_teams=2), "dynasty_main")
    with pytest.raises(smoke.BuildError):
        smoke.build_trades({"sleeper": {}}, "dynasty_main")


def _team(rid, *, cat="FAVORABLE", headline="YES", state="priced", value=1000.0, fair="FAIR"):
    row = {"assetId": "p:1", "valueState": state, "value": value}
    return {
        "rosterId": rid,
        "category": cat,
        "fairness": {"state": fair},
        "analysis": {"decision": {"headline": headline}},
        "gives": [dict(row)],
        "receives": [dict(row)],
    }


def _multi_body(**kw):
    teams = kw.pop("teams", [_team(1), _team(2), _team(3)])
    body = {
        "teams": teams,
        "summary": {},
        "rosters": {"state": "current"},
        "decisionRunIds": {"1": None, "2": None, "3": None},
    }
    body.update(kw)
    return body


def test_multi_healthy_passes():
    v = smoke.classify_multi(200, _multi_body(), [1, 2, 3])
    assert v["status"] == "pass" and v["pricedRows"] == 6 and v["rostersState"] == "current"


def test_multi_all_withheld_stale_fails():  # the 2026-11-17 incident
    teams = [
        _team(r, cat="UNAVAILABLE", headline="NOT_ENOUGH_EVIDENCE", state="stale", value=None)
        for r in (1, 2, 3)
    ]
    v = smoke.classify_multi(200, _multi_body(teams=teams), [1, 2, 3])
    assert v["status"] == "fail" and v["code"] == "all_withheld"


def test_multi_priced_but_every_team_insufficient_fails():
    teams = [_team(r, cat="UNAVAILABLE", headline="NOT_ENOUGH_EVIDENCE") for r in (1, 2, 3)]
    assert smoke.classify_multi(200, _multi_body(teams=teams), [1, 2, 3])["code"] == (
        "insufficient_evidence"
    )


def test_multi_one_unavailable_team_is_not_a_failure():
    teams = [_team(1), _team(2), _team(3, cat="UNAVAILABLE", headline="NOT_ENOUGH_EVIDENCE")]
    assert smoke.classify_multi(200, _multi_body(teams=teams), [1, 2, 3])["status"] == "pass"


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (503, {"error": "multi_team_analysis_disabled"}, "flag_off"),
        (401, {"error": "auth_required"}, "auth_failure"),
        (403, {}, "auth_failure"),
        (503, {"error": "data_not_ready"}, "data_not_ready"),
        (503, {"error": "package_model_unavailable"}, "package_model_unavailable"),
        (503, {"error": "analysis_busy"}, "busy"),
        (
            400,
            {"error": "invalid_trade", "reason": "asset_not_owned", "rosterIds": [3]},
            "ownership_refused:asset_not_owned",
        ),
        (400, {"error": "invalid_trade", "reason": "idle_team"}, "refused:invalid_trade:idle_team"),
        (500, {"error": "internal_error"}, "refused:internal_error"),
        (502, "<html>", "http_502"),
    ],
)
def test_multi_refusals_are_classified(status, body, code):
    v = smoke.classify_multi(status, body, [1, 2, 3])
    assert v["status"] == "fail" and v["code"] == code and v["http"] == status


def test_free_text_from_a_response_never_reaches_the_summary():
    v = smoke.classify_multi(
        400,
        {"error": "Bad Thing: Jason's roster!", "reason": "x y", "rosterIds": [3, "Jason"]},
        [1],
    )
    assert v["code"] == "http_400" and v["rosterIds"] == [3]
    v = smoke.classify_two(500, {"error": "internal_error", "reason": "Not snake"})
    assert v["code"] == "refused:internal_error"


def test_bodies_are_asset_only_and_marker_header_is_the_documented_one():
    built = smoke.build_trades(_contract(), "dynasty_main")
    assert built["two"]["useTeamContext"] is False and built["three"]["useTeamContext"] is False
    assert smoke.SMOKE_HEADER.lower() == "x-chase-smoke"


def test_multi_missing_fields_fail_as_schema_drift():
    good = _multi_body()
    cases = {
        "body_not_object": ([], "schema_drift:body_not_object"),
        "no_teams": ({**good, "teams": None}, "schema_drift:teams"),
        "team_set": ({**good, "teams": good["teams"][:2]}, "schema_drift:team_set"),
        "no_summary": ({k: v for k, v in good.items() if k != "summary"}, "schema_drift:summary"),
        "no_run_ids": (
            {k: v for k, v in good.items() if k != "decisionRunIds"},
            "schema_drift:decisionRunIds",
        ),
    }
    for _name, (body, code) in cases.items():
        assert smoke.classify_multi(200, body, [1, 2, 3])["code"] == code
    bad_cat = _multi_body(teams=[_team(1, cat="MEH"), _team(2), _team(3)])
    assert smoke.classify_multi(200, bad_cat, [1, 2, 3])["code"] == "schema_drift:category"
    bad_fair = _multi_body(teams=[_team(1, fair="MAYBE"), _team(2), _team(3)])
    assert smoke.classify_multi(200, bad_fair, [1, 2, 3])["code"] == "schema_drift:fairness"
    bad_head = _multi_body(teams=[_team(1, headline="MAYBE"), _team(2), _team(3)])
    assert smoke.classify_multi(200, bad_head, [1, 2, 3])["code"] == "schema_drift:decision"
    t = _team(1)
    del t["gives"][0]["valueState"]  # a missing state is never read as priced
    assert (
        smoke.classify_multi(200, _multi_body(teams=[t, _team(2), _team(3)]), [1, 2, 3])["code"]
        == "schema_drift:gives.valueState"
    )
    t = _team(1)
    t["receives"] = []
    assert (
        smoke.classify_multi(200, _multi_body(teams=[t, _team(2), _team(3)]), [1, 2, 3])["code"]
        == "schema_drift:receives"
    )


def test_multi_value_zero_or_missing_is_not_priced():
    teams = [_team(r, value=0) for r in (1, 2, 3)]
    assert smoke.classify_multi(200, _multi_body(teams=teams), [1, 2, 3])["code"] == "all_withheld"
    teams = [_team(r, value=None) for r in (1, 2, 3)]
    assert smoke.classify_multi(200, _multi_body(teams=teams), [1, 2, 3])["code"] == "all_withheld"


def test_multi_smoke_header_not_honored_fails():
    body = _multi_body(decisionRunIds={"1": "abc", "2": None, "3": None})
    assert smoke.classify_multi(200, body, [1, 2, 3])["code"] == "smoke_not_honored"


def _two_body(**kw):
    asset = {"value": 900, "quarantined": False, "valueFreshness": "high"}
    body = {
        "sending": [dict(asset)],
        "receiving": [dict(asset)],
        "analysis": {"decision": {"headline": "NO"}, "decisionRunId": None},
    }
    body.update(kw)
    return body


def test_two_team_pass_and_failures():
    assert smoke.classify_two(200, _two_body())["status"] == "pass"
    stale = {"value": 900, "valueFreshness": "low"}
    assert smoke.classify_two(200, _two_body(sending=[stale], receiving=[dict(stale)]))["code"] == (
        "all_withheld"
    )
    nee = _two_body(
        analysis={"decision": {"headline": "NOT_ENOUGH_EVIDENCE"}, "decisionRunId": None}
    )
    assert smoke.classify_two(200, nee)["code"] == "insufficient_evidence"
    assert (
        smoke.classify_two(200, _two_body(sending=[]))["code"] == "schema_drift:sending_receiving"
    )
    assert smoke.classify_two(200, _two_body(analysis={"decision": {}}))["code"] == (
        "schema_drift:decision"
    )
    no_id = _two_body(analysis={"decision": {"headline": "NO"}})
    assert smoke.classify_two(200, no_id)["code"] == "schema_drift:decisionRunId"
    rec = _two_body(analysis={"decision": {"headline": "NO"}, "decisionRunId": "abc"})
    assert smoke.classify_two(200, rec)["code"] == "smoke_not_honored"
    assert smoke.classify_two(401, {"error": "auth_required"})["code"] == "auth_failure"
    assert smoke.classify_two(404, {"error": "team_not_found"})["code"] == "refused:team_not_found"


# ── run() / CLI with a fake transport ──────────────────────────────────────


class FakeClient:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def request(self, path, body=None):
        self.calls.append((path.split("?")[0], body))
        return self.answers[path.split("?")[0]]


def _answers(multi=None, two=None):
    return {
        "/api/data": (200, _contract()),
        "/api/trade/analyze": two or (200, _two_body()),
        "/api/trade/analyze-multi": multi or (200, _multi_body()),
    }


def test_run_passes_and_summary_has_no_names():
    fake = FakeClient(_answers())
    summary = smoke.run(fake, "dynasty_main")
    assert summary["ok"] is True and [c["id"] for c in summary["checks"]] == [
        "analyze_2team",
        "analyze_multi_3team",
    ]
    text = json.dumps(summary)
    assert "P10" not in text and "T1" not in text and "o1" not in text  # ids only
    assert [c[0] for c in fake.calls] == [
        "/api/data",
        "/api/trade/analyze",
        "/api/trade/analyze-multi",
    ]


@pytest.mark.parametrize(
    ("rosters", "code"),
    [
        ({"state": "stale"}, "rosters_not_current:stale"),
        ({"state": "unknown"}, "rosters_not_current:unknown"),
        ({"state": "something-else"}, "rosters_not_current:unstated"),
        (None, "rosters_not_current:unstated"),
    ],
)
def test_non_current_rosters_warn_but_never_fail(rosters, code):
    summary = smoke.run(FakeClient(_answers(multi=(200, _multi_body(rosters=rosters)))), "x")
    assert summary["ok"] is True  # rosters refresh on their own schedule: not a failure
    assert summary["warnings"] == [{"id": "analyze_multi_3team", "code": code}]


def test_current_rosters_and_failed_checks_carry_no_roster_warning():
    assert smoke.run(FakeClient(_answers()), "x")["warnings"] == []
    # a failing check is reported as a failure, not also as a roster warning
    failed = smoke.run(
        FakeClient(
            _answers(multi=(200, _multi_body(rosters={"state": "stale"}, teams=[_team(1)])))
        ),
        "x",
    )
    assert failed["ok"] is False and failed["warnings"] == []


@pytest.mark.parametrize(
    ("github_actions", "expected"),
    [
        (
            "true",
            "::warning title=Trade smoke rosters::analyze_multi_3team: rosters_not_current:stale",
        ),
        (None, "warning: analyze_multi_3team: rosters_not_current:stale"),
    ],
)
def test_main_warns_on_stale_rosters_and_still_passes(
    tmp_path, monkeypatch, capsys, github_actions, expected
):
    cookie = tmp_path / "cookie"
    cookie.write_text("SECRETVALUE", encoding="utf-8")
    if github_actions is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", github_actions)
    monkeypatch.setattr(
        smoke,
        "Client",
        lambda *a, **k: FakeClient(_answers(multi=(200, _multi_body(rosters={"state": "stale"})))),
    )
    argv = ["--origin", "https://x.invalid", "--cookie-file", str(cookie)]
    assert smoke.main(argv) == smoke.EXIT_PASS
    err = capsys.readouterr().err
    assert expected in err
    assert "::error" not in err and "SECRETVALUE" not in err


def test_run_flag_off_fails_with_diagnostic():
    summary = smoke.run(
        FakeClient(_answers(multi=(503, {"error": "multi_team_analysis_disabled"}))), "x"
    )
    assert summary["ok"] is False
    assert summary["checks"][1]["code"] == "flag_off" and summary["checks"][0]["status"] == "pass"


def test_run_unreadable_league_or_unbuildable_trade_fails_not_passes():
    s = smoke.run(FakeClient({"/api/data": (None, None)}), "x")
    assert s["ok"] is False and s["checks"][0]["code"] == "network_error"
    s = smoke.run(FakeClient({"/api/data": (503, {"error": "data_not_ready"})}), "x")
    assert s["ok"] is False and s["checks"][0]["code"] == "data_not_ready"
    s = smoke.run(FakeClient({"/api/data": (200, {"sleeper": {}})}), "x")
    assert s["ok"] is False and s["checks"][0]["code"].startswith("cannot_build_trade:")


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    cookie = tmp_path / "cookie"
    cookie.write_text("SECRETVALUE", encoding="utf-8")
    out = tmp_path / "out.json"
    argv = ["--origin", "https://x.invalid", "--cookie-file", str(cookie), "--out", str(out)]
    monkeypatch.setattr(smoke, "run", lambda _c, _l: {"ok": True, "league": "l", "checks": []})
    assert smoke.main(argv) == smoke.EXIT_PASS
    monkeypatch.setattr(
        smoke,
        "run",
        lambda _c, _l: {
            "ok": False,
            "league": "l",
            "checks": [{"id": "a", "status": "fail", "code": "c"}],
        },
    )
    assert smoke.main(argv) == smoke.EXIT_FAIL
    captured = capsys.readouterr()
    assert "SECRETVALUE" not in captured.out + captured.err
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is False
    assert (
        smoke.main(["--origin", "o", "--cookie-file", str(tmp_path / "missing")])
        == smoke.EXIT_USAGE
    )


def test_http_client_retries_network_errors_once_and_never_http_errors(monkeypatch):
    import urllib.error

    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise urllib.error.URLError("down")

    monkeypatch.setattr(smoke.urllib.request, "urlopen", boom)
    monkeypatch.setattr(smoke.time, "sleep", lambda _s: None)
    logs: list[str] = []
    c = smoke.Client("https://x.invalid", "SECRETVALUE", 1, logs.append)
    assert c.request("/api/trade/analyze?q=1", {"a": 1}) == (None, None)
    assert calls["n"] == 2 and len(logs) == 2 and "SECRETVALUE" not in " ".join(logs)
    assert "?" not in " ".join(logs)

    def http_err(*_a, **_k):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(b'{"error":"data_not_ready"}'))

    calls["n"] = 0
    monkeypatch.setattr(smoke.urllib.request, "urlopen", http_err)
    assert c.request("/api/data") == (503, {"error": "data_not_ready"})
    assert calls["n"] == 1


# ── end to end: real board, real routes, guest session + smoke header ──────

from tests.api.test_trade_analyze_multi_route import (  # noqa: E402, F401 -- fixtures
    app,
    flag_on,
    real_registry,
)


class _RouteClient:
    def __init__(self, client, contract):
        self.client = client
        self.contract = contract

    def request(self, path, body=None):
        headers = {smoke.SMOKE_HEADER: "1"}
        if body is None:  # the league read: serve the fixture board the routes use
            return 200, self.contract
        res = self.client.post(path, json=body, headers=headers)
        try:
            return res.status_code, res.json()
        except ValueError:
            return res.status_code, None


def test_end_to_end_on_the_real_board(app, flag_on, monkeypatch, tmp_path):  # noqa: F811
    import server

    client, contract = app
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda _r: {
            "username": "guest",
            "auth_method": "guest_pass",
            "guest_pass_id": "g1",
            "sleeper_user_id": "u1",
        },
    )
    # The builder must find a trade on the real board's own shape (view=app
    # strips playersArray and serves the legacy ``players`` dict, which the
    # builder also reads), so exercise both encodings.
    built = smoke.build_trades(contract, "dynasty_main")
    assert len(built["meta"]["threeTeamRosterIds"]) == 3
    app_view = {k: v for k, v in contract.items() if k != "playersArray"}
    if isinstance(contract.get("players"), dict) and contract["players"]:
        assert smoke.build_trades(app_view, "dynasty_main")["three"] == built["three"]
    summary = smoke.run(_RouteClient(client, contract), "dynasty_main")
    assert [c["code"] for c in summary["checks"]] == ["ok", "ok"], summary
    assert summary["ok"] is True
    # The smoke wrote nothing into the decision ledger.
    from src.trade import trade_decision_log as tdl

    assert [ln for _n, ln in tdl.iter_decision_log_lines(tmp_path) if ln] == []
