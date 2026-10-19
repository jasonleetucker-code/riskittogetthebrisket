"""Brisket Trade Advisor — privacy and abuse controls (design §11 group D).

Directive Phase 10 / test group D: no public endpoint may return a value, an
adjusted value, a source valuation, a weight, a package adjustment, a fairness
score, an engine object, a snapshot or a credential — through a body, a
header, an error, or a log line.  Board values in this league are SENTINELS
(987654 / 876543): any appearance of either string anywhere is a leak.
"""

from __future__ import annotations

import ast
import copy
import json
import logging
from pathlib import Path
from typing import Any

import pytest

import server
from src.api import public_trade_advisor_api as api
from src.api import rate_limit
from src.trade import public_advisor
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

REPO = Path(__file__).resolve().parents[2]

#: The ONLY integer-valued keys any advisor body may carry (design §4.5).
ALLOWED_INT_KEYS = {
    "rosterId",
    "perspectiveRosterId",
    "teamCount",
    "season",
    "round",
    "originRosterId",
    "from",
    "to",
    "minTeams",
    "maxTeams",
    "maxLegs",
    "maxBytes",
    "retryAfterSeconds",
    # Error extras: the roster ids the caller sent (design §4.4).
    "rosterIds",
}


@pytest.fixture
def sentinel_client(advisor_client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", S.with_sentinels(S.contract()))
    return advisor_client


def _walk_numbers(obj: Any, path: str = "$", key: str = "$"):
    """``(key, number, path)`` for every number; a list item reports its
    list's key (``rosterIds: [3]`` is a ``rosterIds`` number)."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield key, obj, path
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_numbers(v, f"{path}.{k}", k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_numbers(v, f"{path}[{i}]", key)


def _assert_clean(res) -> None:
    text = res.text
    for s in S.SENTINELS:
        assert str(s) not in text, f"sentinel {s} leaked in body"
        for hk, hv in res.headers.items():
            assert str(s) not in hv, f"sentinel {s} leaked in header {hk}"
    assert "server-timing" not in {k.lower() for k in res.headers}
    body = res.json()
    for key, value, where in _walk_numbers(body):
        assert isinstance(value, int), f"float at {where}"
        assert key in ALLOWED_INT_KEYS, f"non-allowlisted number at {where}"
    lowered = text.lower()
    for word in (
        "rankderivedvalue",
        'value"',
        "vaadjustedgap",
        "netgap",
        "fairness",
        '"band"',
        "confidence",
        "whatwouldchange",
        "leaning",
        "posture",
        "sourceranks",
        "packagemodel",
        "traceback",
    ):
        assert word not in lowered, f"{word!r} in a public advisor body"


def _every_response(client) -> list:
    """One request per path class, success and error, with sentinels loaded."""
    out = [
        client.get(S.TEAMS_URL),
        client.get(S.assets_url(1)),
        client.get(S.assets_url(2, "value_asc")),
        client.get(S.assets_url(3, "alpha")),
        client.get(S.assets_url("x")),
        client.get(S.assets_url(1, "rank")),
        client.get(S.assets_url(9)),
        client.get(S.TEAMS_URL + "?leagueKey=nope"),
        client.get(S.TEAMS_URL + "?leagueKey=side"),
        client.get(S.TEAMS_URL + "?leagueKey=retired"),
    ]
    for legs, teams in (
        ([("p:101", 1, 2), ("p:201", 2, 1)], (1, 2)),
        ([("p:201", 2, 1), ("p:101", 1, 2)], (1, 2)),
        ([("p:103", 1, 2), ("p:102", 1, 2), ("p:201", 2, 1)], (1, 2)),
        ([("pick:main:2027:r1:o1", 1, 2), ("p:204", 2, 1)], (1, 2)),
        ([("p:104", 1, 2), ("p:203", 2, 1)], (1, 2)),
        ([("p:9999", 1, 2), ("p:202", 2, 1)], (1, 2)),
        ([("p:205", 2, 1), ("p:102", 1, 2)], (1, 2)),
        ([("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 1)], (1, 2, 3)),
        ([("p:201", 1, 2), ("p:202", 2, 1)], (1, 2)),
        ([("p:101", 1, 2)], (1, 2)),
    ):
        body = S.two_team_body(*legs, teams=teams)
        out.append(client.post(S.ANALYZE, json=body))
        body = S.two_team_body(*legs, teams=teams, perspective=2)
        out.append(client.post(S.ANALYZE, json=body))
    out.append(
        client.post(S.ANALYZE, content=b"{bad", headers={"Content-Type": "application/json"})
    )
    out.append(client.post(S.ANALYZE, content=b"{}", headers={"Content-Type": "text/plain"}))
    return out


def test_no_value_or_engine_vocabulary_in_any_body_or_header(sentinel_client):
    responses = _every_response(sentinel_client)
    assert {r.status_code for r in responses} >= {200, 400, 404, 409, 415}
    for res in responses:
        _assert_clean(res)


def test_every_error_is_no_store_and_success_gets_are_public(sentinel_client):
    for res in _every_response(sentinel_client):
        cc = res.headers.get("cache-control", "")
        if res.status_code >= 400:
            assert cc == "no-store", (res.status_code, res.text, cc)
        elif res.request.method == "POST":
            assert cc == "no-store"
        else:
            assert cc.startswith("public, max-age=60"), cc


def test_outbound_models_have_no_float_type_anywhere():
    for name in dir(api):
        obj = getattr(api, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, api.BaseModel)
            and obj.__module__ == api.__name__
        ):
            for fname, field in obj.model_fields.items():
                assert "float" not in repr(field.annotation).lower(), (name, fname)


def test_a_forced_exception_returns_fixed_text_and_logs_type_and_frames_only(
    sentinel_client, monkeypatch, caplog
):
    secret = "SECRET-SENTINEL-do-not-leak-7781"
    monkeypatch.setenv("RISKIT_TEST_SECRET", secret)

    def boom(*_a, **_k):
        raise RuntimeError(f"engine exploded with {secret} and value {S.SENTINELS[0]}")

    monkeypatch.setattr(public_advisor, "_engine_analyze", boom)
    with caplog.at_level(logging.ERROR):
        res = sentinel_client.post(
            S.ANALYZE, json=S.two_team_body(("p:101", 1, 2), ("p:201", 2, 1))
        )
    assert res.status_code == 503
    assert res.json() == {
        "error": "advisor_unavailable",
        "message": "The trade advisor is temporarily unavailable. Try again shortly.",
        "reason": "upstream_unavailable",
    }
    assert res.headers["cache-control"] == "no-store"
    assert secret not in res.text
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged
    assert secret not in logged
    assert str(S.SENTINELS[0]) not in logged


def test_streamed_body_over_the_cap_is_413_without_buffering(sentinel_client):
    def gen():
        for _ in range(40):
            yield b" " * 1024

    res = sentinel_client.post(
        S.ANALYZE, content=gen(), headers={"Content-Type": "application/json"}
    )
    assert res.status_code == 413
    assert res.json()["error"] == "payload_too_large"
    assert res.json()["maxBytes"] == 16384


def test_deeply_nested_json_is_a_400_not_a_crash(sentinel_client):
    raw = b"[" * 5000 + b"]" * 5000
    res = sentinel_client.post(S.ANALYZE, content=raw, headers={"Content-Type": "application/json"})
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_request"


def test_non_integer_roster_id_path_is_our_400_never_fastapi_422(sentinel_client):
    for bad in ("x", "-1", "0", "100", "1.5", "%20"):
        res = sentinel_client.get(S.assets_url(bad))
        assert res.status_code == 400, (bad, res.text)
        assert res.json() == {
            "error": "invalid_request",
            "message": "That team identifier is not valid.",
            "reason": "invalid_roster_id",
            "field": "rosterId",
        }


def test_picks_are_ordered_by_season_round_origin_never_by_value(advisor_client, monkeypatch):
    c = S.contract()
    # Invert pick values: 2027 2nd now far above the 2027 1st.
    for row in c["playersArray"]:
        if row["displayName"] == "2027 Mid 2nd":
            row["rankDerivedValue"] = 9000.0
    monkeypatch.setattr(server, "latest_contract_data", c)
    for sort in ("value_desc", "value_asc", "alpha"):
        assets = advisor_client.get(S.assets_url(1, sort)).json()["assets"]
        picks = [a for a in assets if a["kind"] == "pick"]
        assert [(p["season"], p["round"]) for p in picks] == [(2027, 1), (2027, 2)], sort
        if sort != "alpha":
            # The pick segment always follows every player.
            kinds = [a["kind"] for a in assets]
            assert kinds == sorted(kinds, key=lambda k: k == "pick")


def test_value_asc_is_the_exact_reverse_of_the_priced_players(advisor_client):
    desc = advisor_client.get(S.assets_url(1, "value_desc")).json()["assets"]
    asc = advisor_client.get(S.assets_url(1, "value_asc")).json()["assets"]
    priced_desc = [a["id"] for a in desc if a["kind"] == "player" and a["evaluable"]]
    priced_asc = [a["id"] for a in asc if a["kind"] == "player" and a["evaluable"]]
    assert priced_asc == list(reversed(priced_desc))
    # Server-side order follows the board: QB 6000 > WR 4000 > RB 3000 > DL > LB.
    assert priced_desc == ["p:101", "p:103", "p:102", "p:104", "p:105"]


def test_counterfactual_search_never_runs_on_the_public_path(advisor_client, monkeypatch):
    from src.trade import trade_decision

    calls = []
    real = trade_decision._what_would_change

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(trade_decision, "_what_would_change", spy)
    res = advisor_client.post(S.ANALYZE, json=S.two_team_body(("p:101", 1, 2), ("p:201", 2, 1)))
    assert res.status_code == 200
    assert res.json()["category"] != "UNAVAILABLE"
    assert calls == []


def test_response_floor_holds_for_fast_answers(advisor_client, monkeypatch):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["responseFloorMs"] = 250
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(api, "_sleep", fake_sleep)
    clock = iter([100.0, 100.01])
    monkeypatch.setattr(api, "_clock", lambda: next(clock))
    res = advisor_client.post(S.ANALYZE, json=S.two_team_body(("p:9999", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 200
    assert slept and abs(slept[0] - 0.24) < 1e-6


# ── Limiter ────────────────────────────────────────────────────────────────


def _cfg_with(monkeypatch, **limits):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["rateLimits"].update(limits)
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)


BODY = S.two_team_body(("p:9999", 1, 2), ("p:202", 2, 1))


def test_per_key_burst_429_with_retry_after(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 2, "windowSeconds": 600})
    codes = [advisor_client.post(S.ANALYZE, json=BODY).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    res = advisor_client.post(S.ANALYZE, json=BODY)
    assert res.headers["retry-after"] == str(res.json()["retryAfterSeconds"])
    assert res.headers["cache-control"] == "no-store"


def _ip_from_test_header(monkeypatch):
    monkeypatch.setattr(
        server, "_client_ip_from_request", lambda request: request.headers.get("x-test-ip", "")
    )


def test_neighbourhood_bucket_spans_addresses_in_one_slash_24(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, neighbourhoodBurst={"capacity": 2, "windowSeconds": 600})
    _ip_from_test_header(monkeypatch)
    ips = ["203.0.113.1", "203.0.113.2", "203.0.113.3", "198.51.100.9"]
    codes = [
        advisor_client.post(S.ANALYZE, json=BODY, headers={"X-Test-IP": ip}).status_code
        for ip in ips
    ]
    assert codes == [200, 200, 429, 200]


def test_ipv6_clients_key_on_their_slash_64(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 2, "windowSeconds": 600})
    _ip_from_test_header(monkeypatch)
    ips = ["2001:db8:1:2::1", "2001:db8:1:2::ffff", "2001:db8:1:2:abcd::9", "2001:db8:1:3::1"]
    codes = [
        advisor_client.post(S.ANALYZE, json=BODY, headers={"X-Test-IP": ip}).status_code
        for ip in ips
    ]
    assert codes == [200, 200, 429, 200]


def test_global_ceiling_limits_everyone_and_is_never_evicted(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, globalCeiling={"capacity": 3, "windowSeconds": 3600})
    _ip_from_test_header(monkeypatch)
    codes = [
        advisor_client.post(S.ANALYZE, json=BODY, headers={"X-Test-IP": f"10.{i}.0.1"}).status_code
        for i in range(4)
    ]
    assert codes == [200, 200, 200, 429]


def test_spoofed_real_ip_from_an_untrusted_peer_does_not_get_a_fresh_bucket(
    advisor_client, monkeypatch
):
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 2, "windowSeconds": 600})
    monkeypatch.delenv("RATE_LIMIT_TRUSTED_PROXIES", raising=False)
    codes = [
        advisor_client.post(
            S.ANALYZE, json=BODY, headers={"X-Real-IP": f"198.51.100.{i}"}
        ).status_code
        for i in range(3)
    ]
    # TestClient's peer ("testclient") is not a trusted proxy, so every
    # request keys on the peer, not on the rotated header.
    assert codes == [200, 200, 429]


def test_the_limiter_is_charged_before_any_evaluation(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 1, "windowSeconds": 600})
    advisor_client.post(S.ANALYZE, json=BODY)
    calls = []
    monkeypatch.setattr(public_advisor, "evaluate_trade", lambda *a, **k: calls.append(1))
    res = advisor_client.post(S.ANALYZE, json=BODY)
    assert res.status_code == 429
    assert calls == []


def test_advisor_keys_cannot_evict_another_limiters_buckets(monkeypatch):
    rate_limit.reset_for_tests()
    other = rate_limit.KeyedLimiter("other", max_keys=10)
    advisor = rate_limit.KeyedLimiter("advisor", max_keys=10)
    other.charge([rate_limit.KeyedCharge("victim", 1, 600)])
    for i in range(100):
        advisor.charge([rate_limit.KeyedCharge(f"k{i}", 5, 600)])
    # The victim bucket is still there and still empty.
    assert other.charge([rate_limit.KeyedCharge("victim", 1, 600)])[0] is True
    # And the shared private keyed store is untouched by either.
    assert rate_limit._keyed_buckets == {}


def test_a_ceiling_bucket_survives_eviction(monkeypatch):
    lim = rate_limit.KeyedLimiter("t", max_keys=10)
    now = [1000.0]
    monkeypatch.setattr(rate_limit, "_keyed_now", lambda: now[0])
    lim.charge([rate_limit.KeyedCharge("global", 2, 3600, ceiling=True)])
    lim.charge([rate_limit.KeyedCharge("global", 2, 3600, ceiling=True)])
    for i in range(200):
        now[0] += 1
        lim.charge([rate_limit.KeyedCharge(f"k{i}", 5, 600)])
    assert lim.charge([rate_limit.KeyedCharge("global", 2, 3600, ceiling=True)])[0] is True


def test_a_refused_request_debits_no_bucket(monkeypatch):
    lim = rate_limit.KeyedLimiter("t2")
    monkeypatch.setattr(rate_limit, "_keyed_now", lambda: 5.0)
    full = rate_limit.KeyedCharge("a", 1, 600)
    lim.charge([full])
    other = rate_limit.KeyedCharge("b", 2, 600)
    assert lim.charge([full, other])[0] is True
    # "b" kept both tokens.
    assert lim.charge([other]) == (False, 0)
    assert lim.charge([other]) == (False, 0)
    assert lim.charge([other])[0] is True


# ── Structural guards ──────────────────────────────────────────────────────


def test_private_routes_still_401_anonymously(advisor_client):
    for path in ("/api/data", "/api/trade/analyze", "/api/trade/simulate"):
        res = (
            advisor_client.get(path) if path == "/api/data" else advisor_client.post(path, json={})
        )
        assert res.status_code == 401, path


def test_the_router_serializes_only_validated_models():
    """Every JSONResponse in the API module is built from ``_safe_dump`` of a
    model (or the fixed error helper) — never from an engine object."""
    src = (REPO / "src" / "api" / "public_trade_advisor_api.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "JSONResponse":
            content = next((k.value for k in node.keywords if k.arg == "content"), None)
            assert content is not None
            ok = (
                isinstance(content, ast.Name)
                and content.id in ("body", "content")
                or isinstance(content, ast.Call)
                and getattr(content.func, "id", None) == "_safe_dump"
            )
            assert ok, ast.unparse(node)


def test_advisor_result_holds_public_fields_only():
    fields = set(public_advisor.AdvisorResult.__dataclass_fields__)
    assert fields == {
        "category",
        "reason_code",
        "unavailable_asset_ids",
        "legs",
        "team_count",
        "perspective",
    }


def test_no_analyze_result_cache_exists():
    src = (REPO / "src" / "trade" / "public_advisor.py").read_text()
    src += (REPO / "src" / "api" / "public_trade_advisor_api.py").read_text()
    # The one lru_cache memoizes the committed CONFIG file, nothing else.
    assert src.count("@lru_cache") == 1
    assert "@lru_cache(maxsize=1)\ndef advisor_config" in src
    assert "record_decision" not in src
    assert "comparable_trades" not in src


def test_fixtures_carry_no_number_outside_the_allowlist():
    for path in S.FIXTURE_DIR.glob("*.json"):
        if path.name == "index.json":
            continue
        body = json.loads(path.read_text())
        for key, value, where in _walk_numbers(body):
            assert key in ALLOWED_INT_KEYS, (path.name, where)
