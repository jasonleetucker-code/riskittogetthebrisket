"""Depth-note SHADOW COUNTERS (LVA Package 4, owner decision 2026-10-21).

What is pinned here:

* flag OFF -> nothing runs, nothing is written, the read route is invisible
  (404), and the calculator / War Room payloads are byte-identical;
* flag ON -> the payloads are STILL byte-identical (shadow, no display), the
  counters record the would-fire answer and its false-positive proxies, and
  the store holds aggregate counts only -- no player name, no value;
* the read route is private: allowlisted admin AND a member of the requested
  league in the loaded contract's rosters; never under ``/api/public`` and no
  frontend bridge route reaches it.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags, league_registry
from src.trade import depth_disclosure as dd
from src.trade import depth_disclosure_shadow as shadow
from tests.trade import depth_disclosure_fixture as F

REPO = Path(__file__).resolve().parents[2]
_ENV = "RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW"


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "shadow"
    monkeypatch.setattr(shadow, "SHADOW_DIR", root)
    shadow.reset_for_tests()
    yield root
    shadow.flush()
    shadow.reset_for_tests()


@pytest.fixture
def flag(monkeypatch):
    def _set(on: bool):
        monkeypatch.setenv(_ENV, "1" if on else "0")
        feature_flags.reload()

    yield _set
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()


def _record(**kw):
    args = dict(
        contract=F.contract(),
        league_key="main",
        roster_settings=F.SETTINGS,
        surface="calculator",
    )
    args.update(kw)
    return shadow.record_evaluation(F.HURTS_FOR_EGBUKA_HODGINS, **args)


# ── the flag ──────────────────────────────────────────────────────────────


def test_flag_is_registered_default_off_and_live():
    assert feature_flags._DEFAULTS["low_value_depth_disclosure_shadow"] is False
    assert feature_flags.gate_status("low_value_depth_disclosure_shadow") == feature_flags.LIVE


def test_flag_off_records_nothing(store, flag):
    flag(False)
    assert _record() is None
    assert not store.exists()


# ── the counters ──────────────────────────────────────────────────────────


def test_flag_on_counts_the_would_fire_answer(store, flag):
    flag(True)
    out = _record()
    assert out is not None and out["trade"] == {"requests": 1, "trades": 1, "trades.anyFire": 1}
    data = shadow.read_counters("main", root=store)
    me = data["totals"]["calculator"]["self"]
    assert me["evaluations"] == 1 and me["fires"] == 1 and me["candidates"] == 1
    assert me["transition:fair>against"] == 1
    assert me["bandPair:fair>unfair"] == 1
    assert me["fire.pieces:offense"] == 1 and me["fire.mix:offense"] == 1
    assert me["fire.extraCount:1"] == 1 and me["fire.shape:2for1"] == 1
    partner = data["totals"]["calculator"]["partner"]
    assert partner == {"evaluations": 1, "outcome:not_shown:no_low_value_depth": 1}
    assert data["config"]["threshold"] == "floor" and data["config"]["rule"] == "A_guarded"


def test_counters_accumulate_per_day_and_surface(store, flag):
    flag(True)
    now = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    _record(now=now)
    _record(now=now, surface="war_room")
    _record(now=now + timedelta(days=1), surface="war_room")
    data = shadow.read_counters("main", root=store)
    assert sorted(data["days"]) == ["2026-10-21", "2026-10-22"]
    assert data["totals"]["war_room"]["trade"]["trades"] == 2
    assert data["totals"]["calculator"]["trade"]["trades"] == 1
    assert shadow.read_counters("main", days=1, root=store)["totals"]["war_room"]["trade"] == {
        "requests": 1,
        "trades": 1,
        "trades.anyFire": 1,
    }


def test_a_repeated_trade_counts_once_per_day_and_surface(store, flag):
    """The War Room re-posts on every debounce and toggle: the counting unit
    is the distinct trade, and repeats are visible only as requests."""
    flag(True)
    now = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    for _ in range(3):
        _record(now=now, surface="war_room")
    _record(now=now + timedelta(days=1), surface="war_room")
    data = shadow.read_counters("main", root=store)
    day1 = data["days"]["2026-10-21"]["war_room"]
    assert day1["trade"] == {
        "requests": 3,
        "repeatRequests": 2,
        "trades": 1,
        "trades.anyFire": 1,
    }
    assert day1["self"]["evaluations"] == 1 and day1["self"]["fires"] == 1
    assert data["days"]["2026-10-22"]["war_room"]["trade"]["trades"] == 1
    other = F.simulation(
        F.HURTS_FOR_EGBUKA_HODGINS["receiving"][:1], F.HURTS_FOR_EGBUKA_HODGINS["sending"]
    )
    assert shadow.trade_signature(other) != shadow.trade_signature(F.HURTS_FOR_EGBUKA_HODGINS)


def test_retention_prunes_old_days(store, flag):
    flag(True)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _record(now=old)
    _record(now=old + timedelta(days=400))
    assert list(shadow.read_counters("main", root=store)["days"]) == ["2027-02-05"]


def _write_store(store, days):
    store.mkdir(parents=True, exist_ok=True)
    blob = {"version": shadow.COUNTERS_VERSION, "leagueKey": "main", "aggregateOnly": True}
    blob["days"] = {d: {"calculator": {"trade": {"trades": 1}}} for d in days}
    (store / "main.json").write_text(json.dumps(blob), encoding="utf-8")


def test_read_never_serves_and_deletes_expired_days_with_no_writes(store, flag):
    """Retention holds with the flag OFF: nothing writes, yet an expired day is
    neither served nor kept (owner-requested retention protection)."""
    flag(False)
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    _write_store(store, ["2026-01-01", "2026-04-23", "2026-04-24", "2026-10-20"])
    data = shadow.read_counters("main", root=store, now=now)
    assert sorted(data["days"]) == ["2026-04-24", "2026-10-20"]  # 180-day window
    assert data["totals"]["calculator"]["trade"]["trades"] == 2
    kept = json.loads((store / "main.json").read_text(encoding="utf-8"))
    assert sorted(kept["days"]) == ["2026-04-24", "2026-10-20"]


def test_prune_expired_runs_with_the_flag_off_across_leagues(store, flag):
    flag(False)
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    _write_store(store, ["2025-01-01", "2026-10-20"])
    (store / "side.json").write_text(
        json.dumps({"days": {"2025-02-02": {}, "2026-10-01": {}}}), encoding="utf-8"
    )
    assert shadow.prune_expired(now=now, root=store) == 2
    assert list(json.loads((store / "main.json").read_text("utf-8"))["days"]) == ["2026-10-20"]
    assert list(json.loads((store / "side.json").read_text("utf-8"))["days"]) == ["2026-10-01"]
    assert shadow.prune_expired(now=now, root=store) == 0  # idempotent
    assert shadow.prune_expired(now=now, root=store / "absent") == 0  # never raises


def test_the_post_scrape_pass_prunes_the_shadow_store():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    block = src[src.index("_ret = prune_data_dir(BASE_DIR)") :]
    block = block[: block.index("return result")]
    assert "_depth_shadow.prune_expired()" in block
    assert "is_enabled" not in block  # retention never depends on the flag


def test_unavailable_lines_are_counted_never_guessed(store, flag):
    flag(True)
    _record(contract=F.contract(lineups=False))
    me = shadow.read_counters("main", root=store)["totals"]["calculator"]["self"]
    assert me == {"evaluations": 1, "outcome:not_evaluated:lines_unavailable:no_lineups": 1}


def test_store_is_aggregate_only(store, flag):
    """No player name, no value and no line ever reaches the store."""
    flag(True)
    now = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)  # no stray digits
    _record(now=now)
    _record(now=now, surface="war_room")
    text = next(store.glob("*.json")).read_text(encoding="utf-8")
    for name in (r["displayName"] for r in F.contract()["playersArray"]):
        assert name not in text, name
    for number in ("897", "5197", "5919", "1802", "1231"):
        assert number not in text, number


def test_unknown_surface_is_not_counted(store, flag):
    flag(True)
    assert _record(surface="public_advisor") is None
    assert not store.exists()


def test_a_failing_counter_never_raises(store, flag, monkeypatch):
    flag(True)

    def boom(*_a, **_k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(dd, "evaluate_two_team", boom)
    assert _record() is None


@pytest.mark.parametrize(
    "extra",
    [
        {"unresolvedIn": ["Nobody"]},
        {"unresolvedOut": ["Nobody"]},
        {"ownedPickChecks": {"notOwnedBySender": [{"label": "2027 Pick 1.04"}]}},
        {"ownedPickChecks": {"hypotheticalPicksOut": ["2027 Round 1"]}},
        {"pickOwnership": {"state": "unavailable"}},
        {"ownershipEvidence": {"unverifiableAssetIds": ["p:1"]}},
    ],
)
def test_signature_changes_when_evaluability_changes(extra):
    """A trade whose evidence gates differ is a different trade to count: fixing
    an off-board name or dropping an unheld pick must be evaluated again."""
    base = F.HURTS_FOR_EGBUKA_HODGINS
    assert shadow.trade_signature({**base, **extra}) != shadow.trade_signature(base)


def test_signature_changes_with_piece_state():
    base = F.HURTS_FOR_EGBUKA_HODGINS
    stale = copy.deepcopy(base)
    stale["receiving"][1]["valueFreshness"] = "low"
    quarantined = copy.deepcopy(base)
    quarantined["receiving"][1]["quarantined"] = True
    for variant in (stale, quarantined):
        assert shadow.trade_signature(variant) != shadow.trade_signature(base)


def test_a_corrected_trade_is_evaluated_again(store, flag):
    flag(True)
    now = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    broken = {**F.HURTS_FOR_EGBUKA_HODGINS, "unresolvedIn": ["Nobody"]}
    common = dict(contract=F.contract(), league_key="main", roster_settings=F.SETTINGS)
    shadow.record_evaluation(broken, surface="war_room", now=now, **common)
    shadow.record_evaluation(F.HURTS_FOR_EGBUKA_HODGINS, surface="war_room", now=now, **common)
    block = shadow.read_counters("main", root=store)["days"]["2026-10-21"]["war_room"]
    assert block["trade"]["trades"] == 2 and "repeatRequests" not in block["trade"]
    assert block["self"]["outcome:not_evaluated:unknown_piece:off_board_assets"] == 1
    assert block["self"]["fires"] == 1


def test_a_failed_evaluation_is_not_marked_counted(store, flag, monkeypatch):
    flag(True)
    now = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)
    real = dd.evaluate_two_team

    def boom(*_a, **_k):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(dd, "evaluate_two_team", boom)
    assert _record(now=now) is None
    monkeypatch.setattr(dd, "evaluate_two_team", real)
    out = _record(now=now)
    assert out is not None and out["trade"].get("trades") == 1


def test_an_older_day_never_resets_a_newer_days_dedup(store, flag):
    flag(True)
    day2 = datetime(2026, 10, 22, 1, 0, tzinfo=timezone.utc)
    _record(now=day2)
    _record(now=day2 - timedelta(hours=3))  # a job queued before midnight
    out = _record(now=day2)
    assert out["trade"] == {"requests": 1, "repeatRequests": 1}


def test_submit_stamps_the_request_time(store, flag, monkeypatch):
    flag(True)
    seen = {}
    monkeypatch.setattr(
        shadow, "record_evaluation", lambda sim, **kw: seen.setdefault("now", kw.get("now"))
    )
    before = datetime.now(timezone.utc)
    shadow.submit_evaluation(F.HURTS_FOR_EGBUKA_HODGINS, league_key="main", surface="calculator")
    shadow.flush()
    assert seen["now"] is not None and seen["now"] >= before


def test_a_full_queue_drops_and_counts_never_blocks(store, flag, monkeypatch):
    import queue as _queue

    flag(True)
    monkeypatch.setattr(shadow, "_QUEUE", _queue.Queue(maxsize=1))
    monkeypatch.setattr(shadow, "_ensure_worker", lambda: None)  # nothing drains
    for _ in range(3):
        shadow.submit_evaluation(F.HURTS_FOR_EGBUKA_HODGINS, league_key="main", surface="x")
    assert shadow._dropped == 2
    monkeypatch.undo()
    flag(True)
    monkeypatch.setattr(shadow, "SHADOW_DIR", store)
    shadow._dropped = 2
    _record(now=datetime(2026, 10, 21, tzinfo=timezone.utc))
    data = shadow.read_counters("main", root=store)
    assert data["days"]["2026-10-21"]["_queue"] == {"dropped": 2}
    assert shadow._dropped == 0


def test_submit_runs_off_the_request_path_and_snapshots(store, flag):
    flag(True)
    sim = copy.deepcopy(F.HURTS_FOR_EGBUKA_HODGINS)
    shadow.submit_evaluation(
        sim,
        contract=F.contract(),
        league_key="main",
        roster_settings=F.SETTINGS,
        surface="calculator",
    )
    sim["receiving"].clear()  # the route may keep mutating its result
    shadow.flush()
    me = shadow.read_counters("main", root=store)["totals"]["calculator"]["self"]
    assert me["fires"] == 1


def test_submit_with_the_flag_off_does_nothing(store, flag):
    flag(False)
    shadow.submit_evaluation(F.HURTS_FOR_EGBUKA_HODGINS, league_key="main", surface="calculator")
    shadow.flush()
    assert not store.exists()


def test_unstamped_board_is_never_cached(store, flag):
    c = F.contract()
    c.pop("generatedAt")
    a = shadow.lines_for(c, "main", F.SETTINGS)
    assert shadow.lines_for(c, "main", F.SETTINGS) is not a


def test_lines_cache_keys_on_rosters(store, flag):
    flag(True)
    c = F.contract()
    a = shadow.lines_for(c, "main", F.SETTINGS)
    assert shadow.lines_for(c, "main", F.SETTINGS) is a
    c2 = F.contract()
    c2["sleeper"]["teams"][1]["optimalLineup"]["starters"] = ["Qb Them"]
    assert shadow.lines_for(c2, "main", F.SETTINGS) is not a


# ── routes: byte identity and the private read path ───────────────────────


@pytest.fixture
def league(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": F.SETTINGS,
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "L-SIDE",
                        "active": True,
                        "rosterSettings": F.SETTINGS,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    from src.trade import comparable_trades as ct

    monkeypatch.setattr(
        ct, "comparable_trades", lambda *_a, **_k: {"state": "unavailable", "reason": "test"}
    )
    yield
    league_registry.reload_registry()


def _session(username="jasonleetucker", sleeper_user_id="o1"):
    return lambda _request: {
        "username": username,
        "auth_method": "sleeper",
        "sleeper_user_id": sleeper_user_id,
    }


def _call(monkeypatch, method, path, *, body=None, session=None, contract=None):
    with TestClient(server.app, raise_server_exceptions=True) as client:
        monkeypatch.setattr(server, "latest_contract_data", contract or F.contract())
        monkeypatch.setattr(server, "_get_auth_session", session or _session())
        if method == "post":
            return client.post(path, json=body)
        return client.get(path)


def _stable(res) -> bytes:
    """The response body without the fields that differ between ANY two
    identical Analyze requests: the per-request decision run id and the
    request's own stage timings (wall-clock milliseconds)."""
    data = res.json()
    data.pop("analysisTiming", None)
    if isinstance(data.get("analysis"), dict):
        data["analysis"].pop("decisionRunId", None)
    return json.dumps(data, sort_keys=True).encode("utf-8")


@pytest.mark.parametrize(
    "path,surface", [("/api/trade/simulate", "calculator"), ("/api/trade/analyze", "war_room")]
)
def test_payload_is_byte_identical_with_the_flag_off_and_on(
    league, store, flag, monkeypatch, path, surface
):
    flag(False)
    off = _call(monkeypatch, "post", path, body=F.TRADE_BODY)
    assert off.status_code == 200, off.text
    shadow.flush()
    assert not store.exists(), "flag OFF must write nothing"
    flag(True)
    contract = F.contract()
    pristine = copy.deepcopy(contract)
    on = _call(monkeypatch, "post", path, body=F.TRADE_BODY, contract=contract)
    assert on.status_code == 200, on.text
    shadow.flush()
    assert contract == pristine, "the shadow must never mutate the served contract"
    assert _stable(on) == _stable(off)
    if path == "/api/trade/simulate":
        assert on.content == off.content  # literally byte-identical
    for marker in ("depthDisclosure", "depthNote", "private.depth", "lvd_disclosure"):
        assert marker not in on.text, marker  # no depth field, copy key or note
    totals = shadow.read_counters("main", root=store)["totals"]
    assert list(totals) == [surface]
    assert totals[surface]["self"]["fires"] == 1  # the counter really ran


def test_read_route_is_invisible_with_the_flag_off(league, store, flag, monkeypatch):
    flag(False)
    url = "/api/trade/depth-disclosure-shadow?leagueKey=main"
    # Only an admin learns the flag state: anyone else is refused first.
    assert _call(monkeypatch, "get", url, session=lambda _r: None).status_code == 401
    assert _call(monkeypatch, "get", url, session=_session(username="alice")).status_code == 403
    assert _call(monkeypatch, "get", url).status_code == 404


def test_a_non_admin_cannot_tell_whether_the_window_is_running(league, store, flag, monkeypatch):
    """Flag-state oracle: anyone but an admin gets the identical response with
    the flag OFF and ON."""
    url = "/api/trade/depth-disclosure-shadow?leagueKey=main"
    for session in (lambda _r: None, _session(username="alice")):
        answers = []
        for on in (False, True):
            flag(on)
            res = _call(monkeypatch, "get", url, session=session)
            answers.append((res.status_code, res.content))
        assert answers[0] == answers[1], answers


def test_read_route_requires_admin_and_league_membership(league, store, flag, monkeypatch):
    flag(True)
    _record()
    url = "/api/trade/depth-disclosure-shadow?leagueKey=main"
    assert _call(monkeypatch, "get", url, session=lambda _r: None).status_code == 401
    assert _call(monkeypatch, "get", url, session=_session(username="alice")).status_code == 403
    res = _call(monkeypatch, "get", url, session=_session(sleeper_user_id="o9"))
    assert res.status_code == 403 and res.json()["error"] == "league_membership_required"
    # Another league's contract loaded: membership is unprovable -> refused.
    res = _call(monkeypatch, "get", url, contract=F.contract(league_key="side"))
    assert res.status_code == 403
    res = _call(monkeypatch, "get", url)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["aggregateOnly"] is True and body["leagueKey"] == "main"
    assert body["totals"]["calculator"]["self"]["fires"] == 1
    assert res.headers["cache-control"] == "no-store"
    assert F.FILLER not in res.text


def test_read_route_is_private_and_has_no_bridge():
    paths = [getattr(r, "path", "") for r in server.app.routes]
    hits = [p for p in paths if "depth-disclosure" in p]
    assert hits == ["/api/trade/depth-disclosure-shadow"]
    assert not any(p.startswith("/api/public") for p in hits)
    frontend = REPO / "frontend"
    for f in [*frontend.glob("app/**/*.js"), *frontend.glob("app/**/*.jsx")]:
        assert "depth-disclosure" not in f.read_text(encoding="utf-8"), f
    for f in [*frontend.glob("components/**/*.js*"), *frontend.glob("lib/**/*.js")]:
        assert "depth-disclosure" not in f.read_text(encoding="utf-8"), f
