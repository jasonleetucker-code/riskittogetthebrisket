"""Brisket Trade Advisor — privacy, value-free contract and abuse controls
(spec §4.6 / privacy findings M1-M10).

No public endpoint may return a value, an adjusted value, a gap, a band level,
a percentage, a decision category or headline, a Team Context inference, an
engine object or a credential — through a body, a header, an error, an
ordering, or a log line, from ANY perspective.  Board values in this league
are SENTINELS (987654 / 876543): any appearance of either string anywhere is a
leak.
"""

from __future__ import annotations

import ast
import copy
import inspect
import itertools
import json
import logging
import random
import re
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
ALLOWED_INT_KEYS = public_advisor.ALLOWED_INT_KEYS

#: Trades exercised from EVERY participating perspective.
TRADES: list[tuple[list[tuple[str, int, int]], tuple[int, ...]]] = [
    (S.NOT_FAIR_TWO, (1, 2)),
    (S.FAIR_TWO, (1, 3)),
    ([("p:103", 1, 2), ("p:102", 1, 2), ("p:201", 2, 1)], (1, 2)),
    ([("pick:main:2027:r1:o1", 1, 2), ("p:204", 2, 1)], (1, 2)),
    ([("p:104", 1, 2), ("p:203", 2, 1)], (1, 2)),
    ([("p:9999", 1, 2), ("p:202", 2, 1)], (1, 2)),
    ([("p:205", 2, 1), ("p:102", 1, 2)], (1, 2)),
    (S.FAIR_THREE, (1, 3, 4)),
    ([("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 1)], (1, 2, 3)),
    (S.MIXED_FOUR, (1, 2, 3, 4)),
    (
        [("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 4), ("p:401", 4, 1)],
        (1, 2, 3, 4),
    ),
]


@pytest.fixture(autouse=True)
def _roomy_limits(monkeypatch):
    """These tests send many requests from one client; the limiter itself is
    pinned below with its own (tight) limits."""
    cfg = copy.deepcopy(api.advisor_config())
    for spec in cfg["rateLimits"].values():
        spec["capacity"] = 100000
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)


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


_VOCAB = (
    "rankderivedvalue",
    '"value"',
    "vaadjustedgap",
    "netgap",
    '"gap"',
    '"band"',
    '"level"',
    "slight",
    "lopsided",
    "relativepct",
    "confidence",
    "whatwouldchange",
    "leaning",
    "posture",
    "headline",
    "category",
    "sourceranks",
    "packagemodel",
    "traceback",
    "accept",
    "decline",
    "favorable",
    "roster_limit",
)


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
    for word in _VOCAB:
        assert word not in lowered, f"{word!r} in a public advisor body"


def _every_response(client) -> list:
    """One request per path class, success and error, from every perspective."""
    out = [
        client.get(S.TEAMS_URL),
        client.get(S.assets_url(1)),
        client.get(S.assets_url(2, "position_alpha")),
        client.get(S.assets_url(3)),
        client.get(S.assets_url(4)),
        client.get(S.assets_url("x")),
        client.get(S.assets_url(1, "value_desc")),
        client.get(S.assets_url(9)),
        client.get(S.TEAMS_URL + "?leagueKey=nope"),
        client.get(S.TEAMS_URL + "?leagueKey=side"),
        client.get(S.TEAMS_URL + "?leagueKey=retired"),
    ]
    for legs, teams in TRADES:
        for p in teams:
            out.append(client.post(S.ANALYZE, json=S.trade_body(*legs, teams=teams, perspective=p)))
    for bad in (
        S.trade_body(("p:201", 1, 2), ("p:202", 2, 1)),  # 409
        S.trade_body(("p:101", 1, 2)),  # one-sided
        S.trade_body(*S.NOT_FAIR_TWO, perspective=4),
    ):
        out.append(client.post(S.ANALYZE, json=bad))
    out.append(
        client.post(S.ANALYZE, content=b"{bad", headers={"Content-Type": "application/json"})
    )
    out.append(client.post(S.ANALYZE, content=b"{}", headers={"Content-Type": "text/plain"}))
    return out


def test_no_value_or_engine_vocabulary_in_any_body_or_header_from_any_perspective(
    sentinel_client,
):
    responses = _every_response(sentinel_client)
    assert {r.status_code for r in responses} >= {200, 400, 404, 409, 415}
    for res in responses:
        _assert_clean(res)


def test_every_response_is_no_store(sentinel_client):
    for res in _every_response(sentinel_client):
        assert res.headers.get("cache-control") == "no-store", (res.status_code, res.text)


def test_the_body_is_the_same_from_every_perspective(advisor_client):
    """Privacy M6 / P1: all team results ship in ONE response, so switching
    perspective reveals nothing new; the bodies differ only in the echo."""
    for legs, teams in TRADES:
        bodies = []
        for p in teams:
            out = advisor_client.post(
                S.ANALYZE, json=S.trade_body(*legs, teams=teams, perspective=p)
            ).json()
            assert out["perspectiveRosterId"] == p
            out.pop("perspectiveRosterId")
            bodies.append(out)
        assert all(b == bodies[0] for b in bodies), teams


def test_team_and_asset_order_never_change_the_body(advisor_client):
    rng = random.Random(1861)
    for legs, teams in TRADES:
        base = advisor_client.post(S.ANALYZE, json=S.trade_body(*legs, teams=teams)).json()
        for _ in range(3):
            t = list(teams)
            lg = list(legs)
            rng.shuffle(t)
            rng.shuffle(lg)
            out = advisor_client.post(
                S.ANALYZE, json=S.trade_body(*lg, teams=t, perspective=teams[0])
            ).json()
            assert out == base, (teams, t, lg)
        assert [x["rosterId"] for x in base["teams"]] == sorted(teams)
        assert [x["id"] for x in base["trade"]] == sorted(a for a, _f, _t in legs)


def test_team_context_inputs_never_change_the_public_body(advisor_client, monkeypatch):
    """Privacy M1 / I11: posture, projections and roster capacity are not
    inputs of the public answer."""
    from src.api import trade_simulator
    from src.roster_intel import best_ball_utility as bbu

    before = [
        advisor_client.post(S.ANALYZE, json=S.trade_body(*legs, teams=teams)).json()
        for legs, teams in TRADES
    ]
    rebuild = dict(S.POSTURE, label="REBUILD", probabilities={"REBUILD": 0.9, "PUSH": 0.1})
    monkeypatch.setattr(
        trade_simulator,
        "competitive_posture_for",
        lambda contract, league_key, team, *, build_if_missing: dict(rebuild),
    )
    monkeypatch.setattr(
        bbu,
        "league_scored_ppg_by_id",
        lambda ids, season, scoring_settings: ({i: 0.1 for i in ids}, {"state": "available"}),
    )
    # Roster capacity is never computed on this path at all
    # (test_market_fairness_writes_nothing_on_the_public_path).
    monkeypatch.setattr(server, "latest_contract_data", S.contract())
    after = [
        advisor_client.post(S.ANALYZE, json=S.trade_body(*legs, teams=teams)).json()
        for legs, teams in TRADES
    ]
    for b, a in zip(before, after):
        b.pop("generation"), a.pop("generation")
        b.pop("rosters"), a.pop("rosters")
        assert a == b


def test_asset_order_is_a_pure_function_of_identity(advisor_client, monkeypatch):
    """Privacy M2 / SD-8: ``position_alpha`` never reads a board value."""
    first = {rid: advisor_client.get(S.assets_url(rid)).json()["assets"] for rid in (1, 2, 3, 4)}
    c = S.contract()
    rng = random.Random(7)
    for row in c["playersArray"]:
        if row.get("rankDerivedValue"):
            v = float(rng.randint(100, 9000))
            row["rankDerivedValue"] = v
            row["values"] = {"full": v}
    monkeypatch.setattr(server, "latest_contract_data", c)
    for rid in (1, 2, 3, 4):
        again = advisor_client.get(S.assets_url(rid)).json()["assets"]
        assert [a["id"] for a in again] == [a["id"] for a in first[rid]], rid
    # And the order is exactly the documented key.
    assets = first[1]
    players = [a for a in assets if a["kind"] == "player"]
    picks = [a for a in assets if a["kind"] == "pick"]
    assert assets == players + picks
    side = {"offense": 0, "defense": 1, "other": 2}
    pos = {p: i for i, p in enumerate(("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"))}
    key = [
        (
            side[a["side"]],
            pos.get(a["position"] or "", 8),
            a["position"] or "",
            a["label"].casefold(),
        )
        for a in players
    ]
    assert key == sorted(key)
    assert [(p["season"], p["round"], p["originRosterId"]) for p in picks] == sorted(
        (p["season"], p["round"], p["originRosterId"]) for p in picks
    )


def test_order_assets_ignores_input_order():
    rng = random.Random(3)
    assets = [
        public_advisor.PublicAsset(f"p:{i}", "player", f"N{i % 5}", s, pos)
        for i, (s, pos) in enumerate(
            itertools.product(("offense", "defense", "other"), ("QB", "WR", "LB", None))
        )
    ] + [
        public_advisor.PublicAsset(
            f"pick:main:{y}:r{r}:o{o}", "pick", "x", "pick", season=y, round=r, origin_roster_id=o
        )
        for y, r, o in itertools.product((2027, 2028), (1, 2), (1, 3))
    ]
    base = public_advisor.order_assets(assets)
    for _ in range(5):
        shuffled = list(assets)
        rng.shuffle(shuffled)
        assert public_advisor.order_assets(shuffled) == base


def test_only_position_alpha_is_accepted(advisor_client):
    assert advisor_client.get(S.assets_url(1)).json()["sort"] == "position_alpha"
    for sort in ("value_desc", "value_asc", "alpha", "rank"):
        res = advisor_client.get(S.assets_url(1, sort))
        assert res.status_code == 400 and res.json()["reason"] == "unsupported_sort"


# ── Value-free enforcement (spec §4.6) ─────────────────────────────────────


def test_value_free_assertion_catches_each_leak_class():
    ok = S.load_fixture("analyze.four-team-mixed.json")
    public_advisor.assert_advisor_payload_value_free(ok, kind="analyze")
    leaks = [
        {**ok, "teams": [{**ok["teams"][0], "value": 5000}]},
        {**ok, "overall": {**ok["overall"], "gap": 12}},
        {**ok, "teamCount": 2.5},
        {**ok, "extra": 3},
        {**ok, "overall": {**ok["overall"], "reasonText": "Team 2 wins by a mile."}},
        {**ok, "teams": [{**ok["teams"][0], "label": "ACCEPT"}]},
        {**ok, "analysis": {}},
        {**ok, "category": "FAVORABLE"},
    ]
    for body in leaks:
        with pytest.raises(public_advisor.PayloadNotValueFree):
            public_advisor.assert_advisor_payload_value_free(body, kind="analyze")


def test_value_free_assertion_runs_on_every_dump(advisor_client, monkeypatch):
    calls = []
    real = public_advisor.assert_advisor_payload_value_free

    def spy(body, *, kind):
        calls.append(kind)
        return real(body, kind=kind)

    monkeypatch.setattr(public_advisor, "assert_advisor_payload_value_free", spy)
    advisor_client.get(S.TEAMS_URL)
    advisor_client.get(S.assets_url(1))
    advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    advisor_client.get(S.assets_url(1, "nope"))
    assert calls == ["list", "list", "analyze", "error"]


def test_a_failed_value_free_assertion_is_a_fixed_503(advisor_client, monkeypatch):
    def leak(*_a, **_k):
        raise public_advisor.PayloadNotValueFree("boom")

    real = public_advisor.assert_advisor_payload_value_free
    monkeypatch.setattr(
        public_advisor,
        "assert_advisor_payload_value_free",
        lambda body, *, kind: leak() if kind == "analyze" else real(body, kind=kind),
    )
    res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    assert res.status_code == 503
    assert res.json()["reason"] == "upstream_unavailable"


def _annotation_leaves(ann: Any) -> list[Any]:
    args = getattr(ann, "__args__", None)
    if not args:
        return [ann]
    out = []
    for a in args:
        out.extend(_annotation_leaves(a))
    return out


_ALLOWED_STR_FIELDS = {
    "leagueKey",
    "generation",
    "fairnessVersion",
    "status",
    "state",
    "asOf",
    "displayName",
    "teamName",
    "id",
    "kind",
    "label",
    "side",
    "position",
    "nflTeam",
    "projection",
    "sort",
    "pickOwnership",
    "result",
    "reasonCode",
    "reasonText",
    "note",
    "unavailableAssetIds",
    "error",
    "message",
    "reason",
    "field",
    "assetIds",
}


def test_schema_introspection_every_outbound_field_is_allowlisted():
    """Spec §4.6 item 4: no outbound model may carry a numeric or free-text
    field outside the allowlist, and no float type at all."""
    for name in dir(api):
        obj = getattr(api, name)
        if not (
            isinstance(obj, type)
            and issubclass(obj, api.BaseModel)
            and obj.__module__ == api.__name__
            and obj is not api.AdvisorAnalyzeRequest
            and obj is not api._LegIn
        ):
            continue
        for fname, field in obj.model_fields.items():
            key = field.alias or fname
            leaves = _annotation_leaves(field.annotation)
            text = repr(field.annotation).lower()
            assert "float" not in text, (name, fname)
            if "int" in text:
                assert key in ALLOWED_INT_KEYS, (name, key)
            if any(leaf is str for leaf in leaves):
                assert key in _ALLOWED_STR_FIELDS, (name, key)


def test_copy_tables_carry_no_advice_or_magnitude_wording():
    words = (
        "accept",
        "decline",
        "approve",
        "deny",
        "reject",
        "should",
        "recommend",
        "advice",
        "favorable",
        "unfavorable",
        "win",
        "lose",
        "smash",
        "fleece",
        "your roster",
        "your lineup",
        "narrowly",
        "by a lot",
        "close",
    )
    for text in public_advisor.FIXED_TEXT:
        for w in words:
            assert not re.search(rf"\b{re.escape(w)}\b", text, re.IGNORECASE), (w, text)


def test_reducer_sees_only_the_four_public_inputs():
    """P1a: ``reduce_fairness`` cannot receive ``analysis`` / ``simulation``."""
    sig = inspect.signature(public_advisor.reduce_fairness)
    assert list(sig.parameters) == ["teams", "overall_state", "legs"]
    assert set(public_advisor.TeamFairnessInput.__dataclass_fields__) == {
        "roster_id",
        "state",
        "reason_code",
        "unavailable_asset_ids",
    }
    assert set(public_advisor.FairnessResult.__dataclass_fields__) == {
        "overall",
        "teams",
        "legs",
        "team_count",
    }
    src = inspect.getsource(public_advisor.team_fairness_input)
    for forbidden in ('"analysis"', '"simulation"', '"category"', '"decision"', '"value"'):
        assert forbidden not in src, forbidden


def test_reducer_fails_closed_on_unknown_states_and_disagreeing_overall():
    from src.trade.trade_ledger import Leg

    legs = [Leg("p:1", 1, 2), Leg("p:2", 2, 1)]
    out = public_advisor.reduce_fairness(
        [
            public_advisor.TeamFairnessInput(1, "MAYBE", "within_fairness_threshold"),
            public_advisor.TeamFairnessInput(2, "FAIR", "outside_fairness_threshold"),
        ],
        overall_state="UNABLE",
        legs=legs,
    )
    assert [t.result for t in out.teams] == ["UNABLE_TO_DETERMINE"] * 2
    assert {t.reason_code for t in out.teams} == {"evaluation_unavailable"}
    with pytest.raises(public_advisor.InvariantViolation):
        public_advisor.reduce_fairness(
            [
                public_advisor.TeamFairnessInput(1, "FAIR", "within_fairness_threshold"),
                public_advisor.TeamFairnessInput(2, "NOT_FAIR", "outside_fairness_threshold"),
            ],
            overall_state="FAIR",
            legs=legs,
        )


def test_market_fairness_writes_nothing_on_the_public_path(advisor_client, monkeypatch):
    """P1: no decision receipt, no progress, no posture bundle, no roster
    utility / capacity cache from a public analyze."""

    def boom(*_a, **_k):
        raise AssertionError("public analyze touched a shared writer/cache")

    import src.api.gameplan as gameplan
    import src.roster_intel.best_ball_utility as bbu
    import src.trade.roster_capacity as rc
    import src.trade.trade_decision_log as log
    from src.api import trade_analyze_runtime as rt
    from src.api import trade_simulator

    monkeypatch.setattr(log, "record_decision", boom)
    monkeypatch.setattr(rt.PROGRESS, "begin", boom)
    monkeypatch.setattr(gameplan, "league_competitive_postures", boom)
    monkeypatch.setattr(trade_simulator, "competitive_posture_for", boom)
    monkeypatch.setattr(bbu, "evaluate_trade_utility", boom)
    monkeypatch.setattr(rc, "build_capacity_context", boom)
    monkeypatch.setattr(rc, "evaluate_final_roster_utility", boom)
    for legs, teams in TRADES:
        res = advisor_client.post(S.ANALYZE, json=S.trade_body(*legs, teams=teams))
        assert res.status_code == 200, res.text


def test_counterfactual_search_never_runs_on_the_public_path(advisor_client, monkeypatch):
    from src.trade import trade_decision

    calls = []
    real = trade_decision._what_would_change
    monkeypatch.setattr(
        trade_decision, "_what_would_change", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    assert res.status_code == 200
    assert calls == []


def test_a_forced_exception_returns_fixed_text_and_logs_type_and_frames_only(
    sentinel_client, monkeypatch, caplog
):
    from src.trade import analyze_service

    secret = "SECRET-SENTINEL-do-not-leak-7781"

    def boom(*_a, **_k):
        raise RuntimeError(f"engine exploded with {secret} and value {S.SENTINELS[0]}")

    monkeypatch.setattr(analyze_service, "analyze_trade_n", boom)
    with caplog.at_level(logging.ERROR):
        res = sentinel_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
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


def test_a_conservation_violation_is_never_published(advisor_client, monkeypatch):
    from src.trade import analyze_service

    def violate(*_a, **_k):
        raise analyze_service.ConservationViolation("p:101 carries two values")

    monkeypatch.setattr(analyze_service, "analyze_trade_n", violate)
    res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    assert res.status_code == 503
    assert res.json()["reason"] == "upstream_unavailable"
    assert "p:101" not in res.text


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
    # %C2%B9 / %D9%A1 are non-ASCII digits that str.isdigit() accepts.
    for bad in ("x", "-1", "0", "100", "1.5", "%20", "%C2%B9", "%D9%A1"):
        res = sentinel_client.get(S.assets_url(bad))
        assert res.status_code == 400, (bad, res.text)
        assert res.json() == {
            "error": "invalid_request",
            "message": "That team identifier is not valid.",
            "reason": "invalid_roster_id",
            "field": "rosterId",
        }


def test_error_echo_is_bounded_and_never_names_the_owner(advisor_client, monkeypatch):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["limits"]["maxLegs"] = 2
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    res = advisor_client.post(
        S.ANALYZE,
        json=S.trade_body(("p:201", 1, 2), ("p:202", 2, 1)),
    )
    assert res.status_code == 409
    body = res.json()
    assert body["assetIds"] == ["p:201"]
    assert "rosterIds" not in body  # the actual holder (2) is never named


# ── Response floor (spec §4.3 step 2) ──────────────────────────────────────


def _floor(monkeypatch, floor):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["responseFloorMs"] = floor
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(api, "_sleep", fake_sleep)
    monkeypatch.setattr(api, "_clock", lambda: 100.0)
    return cfg, slept


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        ("success", 200),
        ("schema", 400),
        ("invalid_trade", 400),
        ("stale", 409),
        ("too_large", 413),
        ("media", 415),
        ("rate", 429),
        ("engine", 503),
    ],
)
def test_floor_holds_every_outcome_after_the_limiter_charge(
    advisor_client, monkeypatch, kind, status
):
    cfg, slept = _floor(monkeypatch, 250)
    body: Any = S.trade_body(*S.NOT_FAIR_TWO)
    headers = {"Content-Type": "application/json"}
    if kind == "schema":
        body = {"perspectiveRosterId": "x"}
    elif kind == "invalid_trade":
        body = S.trade_body(("p:101", 1, 2))
    elif kind == "stale":
        body = S.trade_body(("p:201", 1, 2), ("p:202", 2, 1))
    elif kind == "rate":
        cfg["rateLimits"]["perKeyBurst"] = {"capacity": 1, "windowSeconds": 600}
        advisor_client.post(S.ANALYZE, json=body)
        slept.clear()
    elif kind == "engine":
        from src.trade import analyze_service

        monkeypatch.setattr(
            analyze_service, "analyze_trade_n", lambda *a, **k: (_ for _ in ()).throw(KeyError())
        )
    if kind == "too_large":
        res = advisor_client.post(S.ANALYZE, content=b"{" + b" " * 20000 + b"}", headers=headers)
    elif kind == "media":
        res = advisor_client.post(S.ANALYZE, content=b"{}", headers={"Content-Type": "text/plain"})
    else:
        res = advisor_client.post(S.ANALYZE, json=body)
    assert res.status_code == status, res.text
    assert slept == [0.25], kind


def test_floor_does_not_apply_before_the_limiter_charge(advisor_client, monkeypatch):
    from src.api import feature_flags

    _cfg, slept = _floor(monkeypatch, 250)
    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "0")
    feature_flags.reload()
    res = advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    assert res.status_code == 503 and res.json()["reason"] == "disabled"
    assert slept == []


def test_per_team_count_floor_table(advisor_client, monkeypatch):
    _cfg, slept = _floor(monkeypatch, {2: 400, 3: 600, 4: 800})
    advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    advisor_client.post(S.ANALYZE, json=S.trade_body(*S.FAIR_THREE, teams=(1, 3, 4)))
    advisor_client.post(S.ANALYZE, json=S.trade_body(*S.MIXED_FOUR, teams=(1, 2, 3, 4)))
    # A malformed request is never faster than the slowest valid one.
    advisor_client.post(S.ANALYZE, content=b"{bad", headers={"Content-Type": "application/json"})
    assert slept == [0.4, 0.6, 0.8, 0.8]


def test_an_over_floor_response_is_logged(advisor_client, monkeypatch, caplog):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["responseFloorMs"] = 250
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    clock = iter([100.0, 101.0])
    monkeypatch.setattr(api, "_clock", lambda: next(clock))
    with caplog.at_level(logging.WARNING):
        advisor_client.post(S.ANALYZE, json=S.trade_body(*S.NOT_FAIR_TWO))
    assert any("exceeded the floor" in r.getMessage() for r in caplog.records)


# ── Single-flight ──────────────────────────────────────────────────────────


def test_public_flight_key_excludes_perspective_and_is_separate_from_private():
    src = inspect.getsource(api._flight_key)
    assert "perspective" not in src.lower()
    assert '"public-advisor"' in src and '"market_fairness"' in src
    assert api._flights() is not server._TRADE_ANALYZE_MULTI_FLIGHTS
    assert api._flights() is not server._TRADE_ANALYZE_FLIGHTS


# ── Limiter ────────────────────────────────────────────────────────────────


def _cfg_with(monkeypatch, **limits):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["rateLimits"].update(limits)
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)


BODY = S.trade_body(("p:9999", 1, 2), ("p:202", 2, 1))


def test_per_key_burst_429_with_retry_after(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 2, "windowSeconds": 600})
    codes = [advisor_client.post(S.ANALYZE, json=BODY).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    res = advisor_client.post(S.ANALYZE, json=BODY)
    assert res.headers["retry-after"] == str(res.json()["retryAfterSeconds"])
    assert res.headers["cache-control"] == "no-store"


def test_a_malformed_body_still_spends_a_unit(advisor_client, monkeypatch):
    """The limiter is charged BEFORE the body is read, so garbage is not a
    free probe."""
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 2, "windowSeconds": 600})
    bad = {"Content-Type": "application/json"}
    assert advisor_client.post(S.ANALYZE, content=b"{bad", headers=bad).status_code == 400
    assert (
        advisor_client.post(S.ANALYZE, content=b"{}", headers={"Content-Type": "x"}).status_code
        == 415
    )
    assert advisor_client.post(S.ANALYZE, json=BODY).status_code == 429


def _ip_from_test_header(monkeypatch):
    monkeypatch.setattr(
        server, "_client_ip_from_request", lambda request: request.headers.get("x-test-ip", "")
    )


@pytest.mark.parametrize(
    ("limit", "ips", "expected"),
    [
        (
            {"neighbourhoodBurst": {"capacity": 2, "windowSeconds": 600}},
            ["203.0.113.1", "203.0.113.2", "203.0.113.3", "198.51.100.9"],
            [200, 200, 429, 200],
        ),
        (
            {"regionDaily": {"capacity": 2, "windowSeconds": 86400}},
            ["2001:db8:1::1", "2001:db8:2::1", "2001:db8:3::1", "2001:db9:1::1"],
            [200, 200, 429, 200],
        ),
        (
            {"neighbourhoodDaily": {"capacity": 2, "windowSeconds": 86400}},
            ["203.0.113.1", "203.0.113.2", "203.0.113.3", "198.51.100.9"],
            [200, 200, 429, 200],
        ),
        (
            {"perKeyBurst": {"capacity": 2, "windowSeconds": 600}},
            ["2001:db8:1:2::1", "2001:db8:1:2::ffff", "2001:db8:1:2:abcd::9", "2001:db8:1:3::1"],
            [200, 200, 429, 200],
        ),
        (
            {"globalCeiling": {"capacity": 3, "windowSeconds": 3600}},
            ["10.0.0.1", "10.1.0.1", "10.2.0.1", "10.3.0.1"],
            [200, 200, 200, 429],
        ),
    ],
)
def test_keyed_buckets(advisor_client, monkeypatch, limit, ips, expected):
    _cfg_with(monkeypatch, **limit)
    _ip_from_test_header(monkeypatch)
    codes = [
        advisor_client.post(S.ANALYZE, json=BODY, headers={"X-Test-IP": ip}).status_code
        for ip in ips
    ]
    assert codes == expected


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
    assert codes == [200, 200, 429]


def test_the_limiter_is_charged_before_any_evaluation(advisor_client, monkeypatch):
    _cfg_with(monkeypatch, perKeyBurst={"capacity": 1, "windowSeconds": 600})
    advisor_client.post(S.ANALYZE, json=BODY)
    calls = []
    monkeypatch.setattr(public_advisor, "evaluate", lambda *a, **k: calls.append(1))
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
    assert other.charge([rate_limit.KeyedCharge("victim", 1, 600)])[0] is True
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


def test_no_business_logic_or_second_owner_in_the_public_layer():
    """Spec §0.1 / §10: the public layer computes no value, applies no package
    model, classifies no band and keeps no private ledger, freshness or
    valuation routine."""
    src = (REPO / "src" / "trade" / "public_advisor.py").read_text()
    src += (REPO / "src" / "api" / "public_trade_advisor_api.py").read_text()
    for forbidden in (
        "fairness_bands.classify",
        "adjusted_pair_totals",
        "package_model.",
        "rankDerivedValue",
        "_what_would_change",
        "def validate_trade",
        "def roster_freshness",
        "_engine_resolve",
        "_player_row_for",
        "multi_team_unsupported",
        "value_desc",
        "record_decision(",
        "comparable_trades",
        "public_category_from",
    ):
        assert forbidden not in src, forbidden
    # The one lru_cache memoizes the committed CONFIG file, nothing else.
    assert src.count("@lru_cache") == 1
    assert "@lru_cache(maxsize=1)\ndef advisor_config" in src


def test_fixtures_carry_no_number_outside_the_allowlist():
    for path in S.FIXTURE_DIR.glob("*.json"):
        if path.name == "index.json":
            continue
        body = json.loads(path.read_text())
        for key, _value, where in _walk_numbers(body):
            assert key in ALLOWED_INT_KEYS, (path.name, where)
