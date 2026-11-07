"""Signals native-value probe — read-only, never records, rule fixed in advance.

Plan PR-P (§3.2-§3.4).  Every response, operation, host, token and player
here is SYNTHETIC; no network, no real Signals data, no real session.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

if sys.platform == "win32":
    # The probe is an on-box (Linux) tool whose signatures default to
    # ``os.getuid`` for POSIX store-ownership checks; Windows has no
    # ``os.getuid``, so the script cannot even be imported there.
    # Never skipped on Linux/CI.
    pytest.skip("on-box probe uses os.getuid (POSIX-only)", allow_module_level=True)

from scripts import probe_signals_native as P  # noqa: E402
from src.sources import signals as S  # noqa: E402
from src.sources import signals_auth as SA  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc)

#: The decision rule was written before any probe ran.  Changing its text is
#: a new preregistration, not an edit: update this pin only together with a
#: recorded reason in the Signals IDP v2 evidence folder.
DECISION_RULE_SHA256 = "2d45e6d1fb04df9bc97851d0430770fb16bb788707fbb29f77db82847d2c5f9a"


def _jwt(exp: float) -> str:
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc({'exp': int(exp), 'iss': 'synthetic'})}.sig"


def _store(tmp_path, *, exp_in: float = 3600, state: str | None = None) -> SA.SignalsStore:
    store = SA.SignalsStore(tmp_path / "auth")
    store.write_session(
        {"tokens": {"accessToken": _jwt(NOW.timestamp() + exp_in), "refreshToken": "SYN"}}
    )
    if state:
        store.write_status({"state": state})
    return store


def _snapshot(store: SA.SignalsStore) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(store.root.iterdir())}


def _show(*, next_in: float = 3 * 3600, svc_state: str = "inactive"):
    nxt = int((NOW.timestamp() + next_in) * 1e6)

    def show(unit, props):
        if unit.endswith(".timer"):
            return {"NextElapseUSecRealtime": str(nxt)}
        return {"ActiveState": svc_state}

    return show


# ── the rule ─────────────────────────────────────────────────────────────


def test_the_decision_rule_is_pinned():
    assert P.decision_rule_sha256() == DECISION_RULE_SHA256


def test_all_conditions_pass_only_with_reviewer_evidence():
    findings = {
        "status": "COMPLETE",
        "tier0": {"ran": True, "serverLeagueValueQuery": True, "leagueValueModulePresent": True},
        "tier1c": {
            "ran": True,
            "ok": True,
            "scoringInputs": True,
            "rosterInputs": False,
            "settingsInputs": True,
            "idpCoverage": {"DT": 200, "DE": 200, "LB": 200, "CB": 200, "S": 200},
            "s1": {"familyTopsWithin5pct": False, "curvesWithin5pct": False},
        },
        "tier2": {
            "ran": True,
            "equal": True,
            "publicationBetween": False,
            "candidateEqual": True,
        },
    }
    without = P.evaluate_decision(findings)
    assert without["verdict"] == "INSUFFICIENT"
    assert {k for k, v in without["conditions"].items() if v == P.UNKNOWN} == set(P.REVIEW_ONLY)
    review = dict.fromkeys(P.REVIEW_ONLY, P.PASS)
    assert P.evaluate_decision(findings, review)["verdict"] == "ADMIT"


def test_roster_inputs_reject_as_league_scoped():
    findings = {
        "tier0": {"ran": True, "serverLeagueValueQuery": True},
        "tier1c": {"ran": True, "ok": True, "rosterInputs": True},
    }
    assert P.evaluate_decision(findings)["verdict"] == "REJECT_LEAGUE_SCOPED"


def test_a_browser_computed_value_fails_condition_1():
    d = P.evaluate_decision(
        {
            "tier0": {
                "ran": True,
                "serverLeagueValueQuery": False,
                "leagueValueModulePresent": True,
                "crawlComplete": True,
            }
        }
    )
    assert d["conditions"]["c1_server_observation"] == P.FAIL
    assert d["verdict"] == "REJECT"
    assert d["q6ValueComputedWhere"] == "browser_computed"


def test_s1_per_family_normalisation_is_detected():
    items = []
    for fam_raw in ("DE", "LB", "CB"):
        for k in range(30):
            items.append({"position": fam_raw, "value": 10000 * (0.97**k)})
    s1 = P.s1_from_items(items)
    assert s1 == {"familyTopsWithin5pct": True, "curvesWithin5pct": True}
    assert P.s1_from_items(items[:10])["familyTopsWithin5pct"] is None


# ── the request layer never records ──────────────────────────────────────


@pytest.mark.parametrize(
    "doc",
    [
        "mutation M { deleteThing(id: 1) { id } }",
        "query Q { a } mutation M { b }",
        "subscription S { onValue { v } }",
        "fragment F on X { a } mutation M { b }",
        "  { a } subscription S { b }",
        "query Q{a},mutation M{b}",
        "{a},subscription S{b}",
    ],
)
def test_mutation_and_subscription_documents_are_refused_before_sending(doc):
    sent = []
    client = P.NonRecordingAppSync(
        "SYN-TOKEN", http_post=lambda *a: sent.append(a), deadline=1e18, clock=lambda: 0.0
    )
    with pytest.raises(P.ProbeStop) as exc:
        client.query(doc, {})
    assert exc.value.outcome == "refused_non_query_document"
    assert sent == []


def test_a_string_literal_mentioning_mutation_is_still_a_query():
    P.assert_read_only('query Q { search(q: "mutation subscription") { id } }')


@pytest.mark.parametrize(
    "answer, outcome",
    [
        ((401, {}, b""), "refused"),
        ((403, {}, b""), "refused"),
        ((429, {"retry-after": "1"}, b""), "rate_limited"),
        ((500, {}, b""), "http_500"),
        ((200, {}, json.dumps({"errors": [{"errorType": "Unauthorized"}]}).encode()), "refused"),
    ],
)
def test_a_refusal_stops_once_and_writes_no_auth_state(tmp_path, answer, outcome):
    store = _store(tmp_path)
    before = _snapshot(store)
    calls = []

    def post(url, headers, body, timeout):
        calls.append(headers)
        return answer

    token, _ = SA.peek_fresh_access_token(store, min_remaining_seconds=60, now_fn=NOW.timestamp)
    client = P.NonRecordingAppSync(token, http_post=post, deadline=1e18, clock=lambda: 0.0)
    with pytest.raises(P.ProbeStop) as exc:
        client.query("query Q { a }", {})
    assert exc.value.outcome == outcome
    assert len(calls) == 1  # no renewal, no retry
    assert _snapshot(store) == before  # no record_failure, no status write, no lock file


def test_the_budget_and_the_deadline_are_hard():
    ok = (200, {}, json.dumps({"data": {"a": 1}}).encode())
    client = P.NonRecordingAppSync(
        "T", http_post=lambda *a: ok, max_requests=2, deadline=1e18, clock=lambda: 0.0
    )
    client.query("query Q { a }", {})
    client.query("query Q { a }", {})
    with pytest.raises(P.ProbeStop, match="request_budget_exhausted"):
        client.query("query Q { a }", {})
    late = P.NonRecordingAppSync("T", http_post=lambda *a: ok, deadline=5, clock=lambda: 10.0)
    with pytest.raises(P.ProbeStop, match="wall_clock_exhausted"):
        late.query("query Q { a }", {})


def test_the_probe_has_no_path_to_renew_deny_or_record():
    tree = ast.parse((REPO / "scripts" / "probe_signals_native.py").read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    forbidden = {
        "renew",
        "renew_for_retry",
        "record_failure",
        "deny",
        "get_access_token",
        "AppSyncClient",
        "SignalsAuthTokens",
        "write_status",
        "write_session",
        "lock",
    }
    assert names.isdisjoint(forbidden), sorted(names & forbidden)


# ── read-only token peek ─────────────────────────────────────────────────


def test_peek_never_writes_and_refuses_unfresh_or_stopped(tmp_path):
    store = _store(tmp_path, exp_in=600)
    before = _snapshot(store)
    tok, why = SA.peek_fresh_access_token(store, min_remaining_seconds=900, now_fn=NOW.timestamp)
    assert tok is None and why == "not_fresh_for_window"
    tok, why = SA.peek_fresh_access_token(store, min_remaining_seconds=60, now_fn=NOW.timestamp)
    assert tok and why == "fresh"
    assert _snapshot(store) == before
    stopped = _store(tmp_path / "b", state=SA.ACCESS_DENIED)
    assert (
        SA.peek_fresh_access_token(stopped, min_remaining_seconds=1, now_fn=NOW.timestamp)[0]
        is None
    )
    empty = SA.SignalsStore(tmp_path / "none")
    assert SA.peek_fresh_access_token(empty, min_remaining_seconds=1)[1] == "not_connected"


# ── preflight ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kw, reason",
    [
        ({"show": _show(next_in=600)}, "collector_timer_due"),
        ({"show": _show(svc_state="activating")}, "collector_service_running"),
        ({"exp_in": 900}, "token_not_fresh_for_window"),
        ({"uid": -1}, "auth_store_owner_mismatch"),
    ],
)
def test_preflight_fails_closed(tmp_path, kw, reason):
    store = _store(tmp_path, exp_in=kw.get("exp_in", 3600))
    checks, token = P.preflight(
        now=NOW,
        show=kw.get("show", _show()),
        auth_store=store,
        window_seconds=P.MAX_WALL_SECONDS,
        getuid=(lambda: kw["uid"]) if "uid" in kw else os.getuid,
    )
    assert token is None and checks["ok"] is False
    assert reason in checks["reasons"]


def test_preflight_passes_in_a_quiet_window(tmp_path):
    checks, token = P.preflight(
        now=NOW, show=_show(), auth_store=_store(tmp_path), window_seconds=P.MAX_WALL_SECONDS
    )
    assert checks["ok"] is True and token


# ── Tier 0 ───────────────────────────────────────────────────────────────

ORIGIN = P.WEBAPP_ORIGIN
INDEX = b'<html><script src="/assets/main.js"></script></html>'
MAIN_JS = (
    'import("/assets/chunk-a.js");fetch("https://api.fantasycalc.com/values");'
    "const q=`query SyntheticLeagueValues($season: Int!, $limit: Int) "
    "{ leagueValues(season: $season, limit: $limit) { items { playerId value position } } }`;"
    "const m=`mutation SyntheticSave($id: ID!) { save(id: $id) { id } }`;"
    "function leagueValueFor(p){ if(p.idp){ return replacementLevel(p) } }"
)
CHUNK_JS = (
    'const u="https://synthetic-pool.appsync-api.us-east-2.amazonaws.com/graphql";'
    "const q2=`query SyntheticIdpDynasty($season: Int!) "
    "{ idpValues(season: $season) { items { playerId value position } } }`;"
    "const q3=`query SyntheticNeedsUser($userId: ID!) { user(id: $userId) { value } }`;"
)


def _get_factory(extra_chunks: int = 0):
    files = {
        ORIGIN + "/": INDEX,
        ORIGIN + "/assets/main.js": MAIN_JS.encode()
        + b"".join(f'import("/assets/x{i}.js");'.encode() for i in range(extra_chunks)),
        ORIGIN + "/assets/chunk-a.js": CHUNK_JS.encode(),
    }
    seen = []

    def get(url, headers, timeout):
        seen.append(url)
        assert "Authorization" not in headers  # Tier 0 is unauthenticated
        return (200, {}, files.get(url, b"//synthetic"))

    return get, seen


def test_tier0_finds_operations_hosts_and_markers_and_prints_only_counts():
    get, seen = _get_factory()
    rep = P.run_bundle_mode(get)
    t0 = rep["tier0"]
    assert t0["operationCounts"] == {"query": 3, "mutation": 1, "subscription": 0}
    assert t0["serverLeagueValueQuery"] is True
    assert t0["leagueValueModulePresent"] and t0["idpBranchPresent"] and t0["scarcityMarkers"]
    assert t0["hostClasses"]["fantasycalc"] and t0["hostClasses"]["appsync"]
    pub = P.public_projection(rep)
    text = json.dumps(pub)
    for secret in ("Synthetic", "synthetic-pool", "fantasycalc.com", "leagueValues"):
        assert secret not in text
    assert pub["tier0"]["operationCounts"]["query"] == 3


def test_tier0_is_bounded_and_same_origin():
    get, seen = _get_factory(extra_chunks=80)
    rep = P.run_bundle_mode(get)
    assert len(seen) <= P.MAX_BUNDLE_GETS
    assert rep["tier0"]["truncated"] is True
    assert all(u.startswith(ORIGIN) for u in seen)


def test_tier1b_candidates_never_guess_a_required_variable():
    ops = P.analyse_bundle({"a": MAIN_JS, "b": CHUNK_JS})["_operations"]
    names = [n for n, _ in P.tier1b_candidates(ops, allow_league_footprint=True)]
    assert names == ["SyntheticIdpDynasty", "SyntheticLeagueValues"]  # no mutation, no $userId
    # Without owner decision 6 the league-shaped query is not a candidate.
    assert [n for n, _ in P.tier1b_candidates(ops)] == ["SyntheticIdpDynasty"]


# ── end to end (synthetic) ───────────────────────────────────────────────


def _post_factory():
    data = {
        "items": [
            {"playerId": str(9000 + i), "value": 5000 - i, "position": ("DE", "LB", "CB")[i % 3]}
            for i in range(9)
        ]
    }
    calls = []

    def post(url, headers, body, timeout):
        doc = json.loads(body)
        assert not doc["query"].lstrip().startswith(("mutation", "subscription"))
        calls.append(doc)
        return 200, {}, json.dumps({"data": {"x": data}}).encode()

    return post, calls


def test_native_probe_end_to_end_records_nothing_and_stays_insufficient(tmp_path):
    store = _store(tmp_path)
    before = _snapshot(store)
    get, _ = _get_factory()
    post, calls = _post_factory()
    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=store,
        http_get=get,
        http_post=post,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
    )
    assert rep["status"] == "COMPLETE"
    # Only the non-league query: the league-shaped one needs owner decision 6.
    assert rep["tier1b"]["attempted"] == 1 and rep["tier1b"]["ok"] == 1
    assert rep["tier1c"] == {"ran": False, "skipped": "owner_decision_6_not_given"}
    assert rep["tier2"]["equal"] is True and rep["tier2"]["compared"] == 1
    assert rep["tier2"]["candidateEqual"] is None  # no candidate was ever queried
    assert rep["appsyncRequests"] == len(calls) <= P.MAX_APPSYNC_REQUESTS
    assert rep["decision"]["verdict"] == "INSUFFICIENT"
    assert _snapshot(store) == before
    pub = P.public_projection(rep)
    assert "Synthetic" not in json.dumps(pub)
    assert pub["preflight"]["start"]["ok"] is True


def test_a_failed_preflight_is_blocked_with_no_request(tmp_path):
    post, calls = _post_factory()
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(next_in=60),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=lambda s: None,
    )
    assert rep["status"] == "BLOCKED" and calls == []
    assert P.public_projection(rep)["preflight"]["start"]["reasons"] == {
        "collector_timer_due": True,
        "renewal_timer_due": True,
    }


def test_tier1c_with_roster_inputs_rejects_as_league_scoped(tmp_path):
    post, _ = _post_factory()
    ops = {
        "SyntheticLeagueList": {"document": "query L { leagues { id } }", "variables": ""},
        "SyntheticLeagueValue": {
            "document": "query V($rosterIds: [ID!]) { leagueValue(rosterIds: $rosterIds) { v } }",
            "variables": "($rosterIds: [ID!])",
        },
    }
    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
        league_ops=ops,
        allow_league_footprint=True,
    )
    assert rep["tier1c"]["ok"] is True and rep["tier1c"]["rosterInputs"] is True
    assert rep["decision"]["verdict"] == "REJECT_LEAGUE_SCOPED"


def test_the_cli_prints_only_an_error_class(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("Synthetic Player 1234 token=SYN")

    monkeypatch.setattr(P, "run_bundle_mode", boom)
    assert P.main(["--mode", "bundle"]) == 1
    out, err = capsys.readouterr()
    assert json.loads(out) == {"error": "RuntimeError"}
    assert "Synthetic" not in out + err


def test_signals_constants_used_by_the_probe_exist():
    assert S.APPSYNC_URL.startswith("https://")
    assert P.WEBAPP_ORIGIN.startswith("https://")


# ── review findings (PR #1860): a refusal ends the run ───────────────────

LEAGUE_OPS = {
    "SyntheticLeagueList": {"document": "query L { leagues { id } }", "variables": ""},
    "SyntheticLeagueValue": {
        "document": "query V($season: Int) { leagueValue(season: $season) { v } }",
        "variables": "($season: Int)",
    },
}
UNAUTHORIZED = (200, {}, json.dumps({"errors": [{"errorType": "Unauthorized"}]}).encode())


@pytest.mark.parametrize(
    "refusal",
    [(401, {}, b""), (403, {}, b""), (429, {"retry-after": "1"}, b""), UNAUTHORIZED],
)
@pytest.mark.parametrize("refuse_on_call", [1, 2])
def test_a_refusal_in_tier1b_sends_nothing_more_on_the_owner_session(
    tmp_path, refusal, refuse_on_call
):
    store = _store(tmp_path)
    before = _snapshot(store)
    ok_post, _ = _post_factory()
    calls, slept = [], []

    def post(url, headers, body, timeout):
        calls.append(body)
        if len(calls) == refuse_on_call:
            return refusal
        return ok_post(url, headers, body, timeout)

    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=store,
        http_get=_get_factory()[0],
        http_post=post,
        sleep=slept.append,
        monotonic=lambda: float(next(clock)),
        league_ops=LEAGUE_OPS,
        allow_league_footprint=True,
    )
    assert len(calls) == refuse_on_call  # nothing after the refusal: no 1c, no Tier 2
    assert slept == []
    assert rep["status"] == "STOPPED"
    assert rep["stop"]["tier"] == "tier1b"
    assert rep["tier1c"]["ran"] is False and rep["tier2"]["ran"] is False
    assert rep["appsyncRequests"] == refuse_on_call
    assert rep["decision"]["verdict"] != "ADMIT"
    assert _snapshot(store) == before
    pub = P.public_projection(rep)
    assert pub["status"] == "STOPPED" and pub["stop"]["tier"] == "tier1b"


def test_a_refusal_in_tier1c_skips_tier2(tmp_path):
    ok_post, _ = _post_factory()
    calls, slept = [], []

    def post(url, headers, body, timeout):
        calls.append(body)
        if "leagues" in json.loads(body)["query"]:
            return (429, {}, b"")
        return ok_post(url, headers, body, timeout)

    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=slept.append,
        monotonic=lambda: float(next(clock)),
        league_ops=LEAGUE_OPS,
        allow_league_footprint=True,
    )
    n = len(calls)
    assert json.loads(calls[-1])["query"].startswith("query L")
    assert rep["status"] == "STOPPED" and rep["stop"]["tier"] == "tier1c"
    assert rep["stop"]["reason"] == "rate_limited"
    assert rep["tier1c"]["ok"] is False and rep["tier2"]["ran"] is False
    assert slept == [] and rep["appsyncRequests"] == n


def test_the_cli_exit_code_marks_a_stopped_probe(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        P,
        "run_native_probe",
        lambda **k: {"mode": "native_probe", "status": "STOPPED", "stop": {"tier": "tier1b"}},
    )
    monkeypatch.setattr(SA.SignalsStore, "open", classmethod(lambda cls, d: None))
    assert P.main(["--mode", "native-probe", "--app-dir", str(tmp_path)]) == 4
    assert json.loads(capsys.readouterr().out)["status"] == "STOPPED"


# ── review findings: league-scoped reads are gated (owner decision 6) ────

LEAGUE_SHAPED_OPS = {
    "MyLeagueValues": "query MyLeagueValues { myLeagues { id teams { leagueValue } } }",
    "RosterValues": "query RosterValues($season: Int) { rosterValues(season: $season) { v } }",
    "UserDynasty": "query UserDynasty { me { dynastyValue } }",
    "AccountIdp": "query AccountIdp { account { idpValues { v } } }",
}


def test_league_scoped_queries_are_not_tier1b_candidates_without_the_gate():
    ops = P.analyse_bundle({"a": MAIN_JS, "b": CHUNK_JS} | LEAGUE_SHAPED_OPS)["_operations"]
    default = [n for n, _ in P.tier1b_candidates(ops)]
    assert default == ["SyntheticIdpDynasty"]
    gated = [n for n, _ in P.tier1b_candidates(ops, allow_league_footprint=True)]
    assert set(LEAGUE_SHAPED_OPS) | {"SyntheticLeagueValues"} <= set(gated)


def test_without_the_gate_no_league_shaped_document_is_ever_sent(tmp_path):
    post, calls = _post_factory()
    clock = iter(range(0, 10**6, 5))
    P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
    )
    assert calls and all("league" not in c["query"].lower() for c in calls)


# ── review findings: an incomplete crawl is UNKNOWN, never FAIL ──────────


def test_an_incomplete_bundle_crawl_leaves_condition_1_unknown():
    for t0 in (
        {"ran": True, "serverLeagueValueQuery": False, "crawlComplete": False},
        {"ran": True, "serverLeagueValueQuery": False},  # completeness unrecorded
    ):
        d = P.evaluate_decision({"tier0": t0})
        assert d["conditions"]["c1_server_observation"] == P.UNKNOWN
        assert d["verdict"] == "INSUFFICIENT"


@pytest.mark.parametrize("failure", ["status", "oserror"])
def test_a_failed_chunk_get_marks_the_crawl_incomplete(failure):
    get, _ = _get_factory()

    def flaky(url, headers, timeout):
        if url.endswith("/assets/chunk-a.js"):
            if failure == "oserror":
                raise OSError("synthetic")
            return (503, {}, b"")
        return get(url, headers, timeout)

    t0 = P.run_bundle_mode(flaky)["tier0"]
    assert t0["failedChunks"] == 1 and t0["crawlComplete"] is False
    assert t0["serverLeagueValueQuery"] is True  # main.js still carries one
    full = P.run_bundle_mode(get)["tier0"]
    assert full["failedChunks"] == 0 and full["crawlComplete"] is True
    assert P.run_bundle_mode(_get_factory(extra_chunks=80)[0])["tier0"]["crawlComplete"] is False


def test_relative_chunk_references_are_followed():
    files = {
        ORIGIN + "/": INDEX,
        ORIGIN + "/assets/main.js": b'import("./chunk-rel.js");',
        ORIGIN + "/assets/chunk-rel.js": CHUNK_JS.encode(),
    }
    seen = []

    def get(url, headers, timeout):
        seen.append(url)
        return (200, {}, files.get(url, b"//synthetic"))

    t0 = P.run_bundle_mode(get)["tier0"]
    assert ORIGIN + "/assets/chunk-rel.js" in seen
    assert t0["operationCounts"]["query"] == 2


def test_an_incomplete_crawl_skips_tier1c_with_its_own_reason(tmp_path):
    get, _ = _get_factory()
    post, _ = _post_factory()

    def no_league(url, headers, timeout):
        st, h, body = get(url, headers, timeout)
        body = body.replace(b"leagueValues", b"xValues").replace(b"LeagueValues", b"XValues")
        if url.endswith("/assets/chunk-a.js"):
            return (503, {}, b"")
        return st, h, body

    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=no_league,
        http_post=post,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
        league_ops=LEAGUE_OPS,
        allow_league_footprint=True,
    )
    assert rep["tier0"]["serverLeagueValueQuery"] is False
    assert rep["tier1c"] == {"ran": False, "skipped": "bundle_crawl_incomplete"}
    assert rep["decision"]["conditions"]["c1_server_observation"] == P.UNKNOWN


# ── review findings: Tier 2 determinism is about the candidate ───────────


def _many_value_queries(n: int) -> bytes:
    return "".join(
        f"const v{i}=`query SynVal{i:02d}($season: Int!) "
        f"{{ idpValues{i}(season: $season) {{ items {{ value }} }} }}`;"
        for i in range(n)
    ).encode()


def test_tier2_re_queries_every_candidate_op_even_after_a_full_tier1b(tmp_path):
    get, _ = _get_factory()

    def big(url, headers, timeout):
        st, h, body = get(url, headers, timeout)
        if url.endswith("/assets/chunk-a.js"):
            body += _many_value_queries(20)
        return st, h, body

    post, calls = _post_factory()
    ops = {f"SyntheticLeagueOp{i}": dict(LEAGUE_OPS["SyntheticLeagueValue"]) for i in range(8)}
    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=big,
        http_post=post,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
        league_ops=ops,
        allow_league_footprint=True,
    )
    assert rep["status"] == "COMPLETE"
    assert rep["tier1c"]["ok"] is True
    t2 = rep["tier2"]
    assert t2["candidateOps"] == 8 and t2["candidateCompared"] == 8
    assert t2["candidateEqual"] is True
    assert rep["appsyncRequests"] == len(calls) <= P.MAX_APPSYNC_REQUESTS


def test_c4_needs_the_candidate_re_compared_not_other_operations():
    base = {
        "tier0": {"ran": True, "serverLeagueValueQuery": True, "crawlComplete": True},
        "tier1c": {"ran": True, "ok": True},
    }
    only_1b = {"ran": True, "equal": True, "publicationBetween": False, "candidateEqual": None}
    d = P.evaluate_decision({**base, "tier2": only_1b})
    assert d["conditions"]["c4_deterministic"] == P.UNKNOWN
    legacy = {"ran": True, "equal": True, "publicationBetween": False}
    assert P.evaluate_decision({**base, "tier2": legacy})["conditions"]["c4_deterministic"] == (
        P.UNKNOWN
    )
    differs = {"ran": True, "equal": False, "publicationBetween": False, "candidateEqual": False}
    assert P.evaluate_decision({**base, "tier2": differs})["conditions"]["c4_deterministic"] == (
        P.FAIL
    )
    no_1c = {"tier0": base["tier0"], "tier2": {**only_1b, "candidateEqual": True}}
    assert P.evaluate_decision(no_1c)["conditions"]["c4_deterministic"] == P.UNKNOWN


def test_an_errored_tier2_answer_does_not_count_as_equal(tmp_path):
    ok_post, _ = _post_factory()
    phase = []

    def post(url, headers, body, timeout):
        if phase and "league" in json.loads(body)["query"].lower():
            return 200, {}, json.dumps({"data": None, "errors": [{"errorType": "X"}]}).encode()
        return ok_post(url, headers, body, timeout)

    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=lambda s: phase.append(s),
        monotonic=lambda: float(next(clock)),
        league_ops=LEAGUE_OPS,
        allow_league_footprint=True,
    )
    t2 = rep["tier2"]
    assert t2["candidateCompared"] == 0 and t2["candidateEqual"] is None
    assert rep["decision"]["conditions"]["c4_deterministic"] == P.UNKNOWN


def test_a_non_query_ops_file_stops_before_any_appsync_request(tmp_path):
    post, calls = _post_factory()
    bad = {"SyntheticLeagueList": {"document": "query L{a},mutation M{b}", "variables": ""}}
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=lambda s: None,
        league_ops=bad,
        allow_league_footprint=True,
    )
    assert calls == []
    assert rep["status"] == "STOPPED"
    assert rep["stop"] == {"tier": "tier1c", "reason": "refused_non_query_document"}
    assert rep["appsyncRequests"] == 0


# ── review round 2: completeness means every discovered script was read ──


def _bundle(index: bytes, files: dict[str, bytes] | None = None):
    seen: list[str] = []

    def get(url, headers, timeout):
        seen.append(url)
        if url == ORIGIN + "/":
            return (200, {}, index)
        if files and url in files:
            return (200, {}, files[url])
        raise AssertionError(f"unexpected GET {url}")

    return get, seen


@pytest.mark.parametrize(
    "index",
    [
        b'<html><script src="https://cdn.example.net/assets/index-abc.js"></script></html>',
        b"<html><body>no scripts at all</body></html>",
    ],
    ids=["cross_origin_only", "no_script"],
)
def test_a_crawl_that_read_no_script_is_incomplete_and_never_rejects(index):
    get, seen = _bundle(index)
    t0 = P.run_bundle_mode(get)["tier0"]
    assert seen == [ORIGIN + "/"]  # off-origin scripts are still never fetched
    assert t0["serverLeagueValueQuery"] is False
    assert t0["crawlComplete"] is False
    d = P.evaluate_decision({"tier0": t0})
    assert d["conditions"]["c1_server_observation"] == P.UNKNOWN
    assert d["verdict"] == "INSUFFICIENT"


def test_a_skipped_cross_origin_chunk_is_counted_and_makes_the_crawl_incomplete():
    get, seen = _bundle(
        b'<html><script src="/assets/main.js"></script>'
        b'<script src="https://cdn.example.net/assets/vendor.js"></script></html>',
        {ORIGIN + "/assets/main.js": b"const nothing=1;"},
    )
    t0 = P.run_bundle_mode(get)["tier0"]
    assert ORIGIN + "/assets/main.js" in seen
    assert all(u.startswith(ORIGIN) for u in seen)
    assert t0["skippedOffOrigin"] == 1
    assert t0["scriptsRead"] == 1
    assert t0["crawlComplete"] is False
    d = P.evaluate_decision({"tier0": t0})
    assert d["conditions"]["c1_server_observation"] == P.UNKNOWN


def test_every_discovered_script_is_accounted_for_on_a_complete_crawl():
    t0 = P.run_bundle_mode(_get_factory()[0])["tier0"]
    assert t0["crawlComplete"] is True
    assert t0["scriptsDiscovered"] == t0["scriptsRead"] > 0
    assert t0["skippedOffOrigin"] == 0 and t0["failedChunks"] == 0


def test_a_cross_origin_only_bundle_skips_tier1c_as_incomplete(tmp_path):
    get, _ = _bundle(
        b'<html><script src="https://cdn.example.net/assets/index-abc.js"></script></html>'
    )
    post, calls = _post_factory()
    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=get,
        http_post=post,
        sleep=lambda s: None,
        monotonic=lambda: float(next(clock)),
        league_ops=LEAGUE_OPS,
        allow_league_footprint=True,
    )
    assert rep["tier1c"] == {"ran": False, "skipped": "bundle_crawl_incomplete"}
    assert rep["decision"]["verdict"] != "REJECT"


# ── review round 2: a STOPPED (or otherwise unfinished) run never admits ─


def _all_pass_findings() -> dict:
    return {
        "tier0": {"ran": True, "serverLeagueValueQuery": True, "leagueValueModulePresent": True},
        "tier1c": {
            "ran": True,
            "ok": True,
            "scoringInputs": True,
            "rosterInputs": False,
            "settingsInputs": True,
            "idpCoverage": {"DT": 200, "DE": 200, "LB": 200, "CB": 200, "S": 200},
            "s1": {"familyTopsWithin5pct": False, "curvesWithin5pct": False},
        },
        "tier2": {
            "ran": True,
            "equal": True,
            "publicationBetween": False,
            "candidateEqual": True,
        },
    }


@pytest.mark.parametrize("status", ["STOPPED", "BLOCKED", None, "SOMETHING_NEW"])
def test_only_a_complete_run_can_be_admitted(status):
    findings = _all_pass_findings()
    if status is not None:
        findings["status"] = status
    review = dict.fromkeys(P.REVIEW_ONLY, P.PASS)
    d = P.evaluate_decision(findings, review)
    assert all(v == P.PASS for v in d["conditions"].values())
    assert d["verdict"] == "INSUFFICIENT"
    assert d["runComplete"] is False
    findings["status"] = "COMPLETE"
    done = P.evaluate_decision(findings, review)
    assert done["verdict"] == "ADMIT" and done["runComplete"] is True


def test_a_tier2_stop_after_the_candidate_matched_is_not_admitted(tmp_path):
    ok_post, _ = _post_factory()
    phase: list[float] = []

    def post(url, headers, body, timeout):
        if phase and "league" not in json.loads(body)["query"].lower():
            return 429, {}, b""
        return ok_post(url, headers, body, timeout)

    clock = iter(range(0, 10**6, 5))
    rep = P.run_native_probe(
        now_fn=lambda: NOW,
        show=_show(),
        auth_store=_store(tmp_path),
        http_get=_get_factory()[0],
        http_post=post,
        sleep=lambda s: phase.append(s),
        monotonic=lambda: float(next(clock)),
        league_ops=LEAGUE_OPS,
        allow_league_footprint=True,
        review=dict.fromkeys(P.REVIEW_ONLY, P.PASS),
    )
    assert rep["status"] == "STOPPED" and rep["stop"]["tier"] == "tier2"
    assert rep["tier2"]["candidateEqual"] is True
    assert rep["decision"]["runComplete"] is False
    assert rep["decision"]["verdict"] != "ADMIT"
