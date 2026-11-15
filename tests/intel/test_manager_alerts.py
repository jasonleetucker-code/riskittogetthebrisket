"""Manager Intelligence Batch F — saved-manager new-activity alerts
(``src/intel/manager_alerts.py``): baseline seeding, idempotence by event id,
per-league seeding, unread-is-not-empty, and the bounded sweep."""

from __future__ import annotations

import pytest

from src.api import user_kv
from src.intel import manager_alerts as mal
from src.intel import manager_saved as ms

DAY_MS = 86_400_000
T0 = 1_700_000_000.0


class Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def ev(eid: str, league: str = "L1", kind: str = "trade", uncertain: bool = False) -> dict:
    return {
        "id": eid,
        "kind": kind,
        "leagueId": league,
        "leagueName": f"League {league}",
        "occurredAt": int(T0 * 1000),
        "added": [{"name": f"Player {eid}"}],
        "dropped": [],
        "faabBid": None,
        "partners": [],
        "attribution": {"uncertain": uncertain},
    }


def cov(league: str, tx: str = "complete", drafts: str = "complete", held=True) -> dict:
    return {"leagueId": league, "rosterHeld": held, "transactions": tx, "drafts": drafts}


def payload(events, coverage=None, status="ok", calls=10, manager=None, picks=None) -> dict:
    coverage = coverage if coverage is not None else [cov("L1")]
    return {
        "status": status,
        "manager": manager or {"userId": "111", "username": "alpha", "displayName": "Alpha"},
        "windowApplied": "7d",
        "leagues": [{"leagueId": c["leagueId"]} for c in coverage],
        "coverage": {"leagues": coverage, "callsSpent": calls},
        "feed": list(events),
        "trades": [e for e in events if e["kind"] == "trade"],
        "acquisitions": [],
        "draftCapital": {
            "available": True,
            "totals": picks
            if picks is not None
            else {"picksHeld": 6, "pricedValue": 1500, "leaguesUnavailable": 0},
        },
    }


# ── pure evaluation ─────────────────────────────────────────────────────


def test_first_evaluation_seeds_silently_then_alerts_once_per_event():
    fresh, mode, state = mal.evaluate(None, payload([ev("tx:1"), ev("tx:2")]), 1)
    assert (fresh, mode) == ([], mal.MODE_BASELINE)
    assert set(state["seenIds"]) == {"tx:1", "tx:2"} and state["seededLeagues"] == ["L1"]

    fresh, mode, state = mal.evaluate(state, payload([ev("tx:1"), ev("tx:2")]), 2)
    assert (fresh, mode) == ([], mal.MODE_OK)

    p = payload([ev("tx:3"), ev("tx:1"), ev("tx:2")])
    fresh, mode, state = mal.evaluate(state, p, 3)
    assert [f["id"] for f in fresh] == ["tx:3"] and state["lastNewCount"] == 1
    assert fresh[0]["added"] == ["Player tx:3"]

    # Idempotent: the same activity again reports nothing.
    fresh, _mode, state = mal.evaluate(state, p, 4)
    assert fresh == [] and state["lastAlertAt"] == 3


def test_a_league_seen_for_the_first_time_is_seeded_silently():
    _f, _m, state = mal.evaluate(None, payload([ev("tx:1")]), 1)
    p = payload([ev("tx:1"), ev("tx:9", "L2")], coverage=[cov("L1"), cov("L2")])
    fresh, mode, state = mal.evaluate(state, p, 2)
    assert mode == mal.MODE_OK and fresh == []
    assert state["seededLeagues"] == ["L1", "L2"]
    p2 = payload([ev("tx:10", "L2"), ev("tx:9", "L2")], coverage=[cov("L1"), cov("L2")])
    fresh, _m, _s = mal.evaluate(state, p2, 3)
    assert [f["id"] for f in fresh] == ["tx:10"]


@pytest.mark.parametrize(
    "bad", [cov("L2", tx="partial"), cov("L2", drafts="rate_limited"), cov("L2", held=None)]
)
def test_a_partially_read_league_is_neither_recorded_nor_alerted(bad):
    _f, _m, state = mal.evaluate(None, payload([ev("tx:1")]), 1)
    p = payload([ev("tx:1"), ev("tx:5", "L2")], coverage=[cov("L1"), bad], status="partial")
    fresh, _m, state = mal.evaluate(state, p, 2)
    assert fresh == [] and "tx:5" not in state["seenIds"] and "L2" not in state["seededLeagues"]
    # Once readable, its events are a baseline for that league, not "new".
    p2 = payload([ev("tx:1"), ev("tx:5", "L2")], coverage=[cov("L1"), cov("L2")])
    fresh, _m, state = mal.evaluate(state, p2, 3)
    assert fresh == [] and "tx:5" in state["seenIds"]


def test_unreadable_activity_leaves_seen_state_and_keeps_the_baseline():
    fresh, mode, state = mal.evaluate(None, payload([], status="rate_limited"), 1)
    assert (fresh, mode) == ([], mal.MODE_UNREAD)
    assert "seededAt" not in state and state["lastStatus"] == "rate_limited"
    fresh, mode, _s = mal.evaluate(state, payload([ev("tx:1")]), 2)
    assert (fresh, mode) == ([], mal.MODE_BASELINE)


def test_uncertain_attribution_is_recorded_but_never_alerted():
    _f, _m, state = mal.evaluate(None, payload([]), 1)
    fresh, _m, state = mal.evaluate(state, payload([ev("tx:7", uncertain=True)]), 2)
    assert fresh == [] and "tx:7" in state["seenIds"]


def test_seen_ids_are_kept_while_visible_and_pruned_after_retention():
    now = 100 * DAY_MS
    old = now - mal.SEEN_RETENTION_MS - 1
    prior = {
        "seededAt": 1,
        "seededLeagues": ["L1"],
        "seenIds": {"tx:visible": old, "tx:gone": old, "tx:recent": now - DAY_MS},
    }
    fresh, _m, state = mal.evaluate(prior, payload([ev("tx:visible")]), now)
    assert fresh == []  # an old but still-visible id never re-fires
    assert set(state["seenIds"]) == {"tx:visible", "tx:recent"}


def test_snapshot_counts_only_a_fully_read_stream():
    _f, _m, state = mal.evaluate(None, payload([ev("tx:1"), ev("tx:2", kind="waiver")]), 5)
    snap = state["snapshot"]
    assert snap["asOf"] == 5 and snap["metrics"]["trades"] == 1 and snap["metrics"]["events"] == 2
    assert snap["metrics"]["picksHeld"] == 6 and snap["metrics"]["pickValue"] == 1500

    partial = payload(
        [ev("tx:1")],
        coverage=[cov("L1"), cov("L2", tx="partial")],
        status="partial",
        picks={"picksHeld": 3, "pricedValue": 900, "leaguesUnavailable": 1},
    )
    _f, _m, state = mal.evaluate(None, partial, 6)
    snap = state["snapshot"]
    assert snap["metrics"]["trades"] is None
    assert snap["reasons"]["trades"] == "activity_partially_read"
    assert snap["metrics"]["picksHeld"] is None
    assert snap["reasons"]["picksHeld"] == "pick_ownership_unavailable"


# ── user_kv-backed detection ────────────────────────────────────────────


@pytest.fixture
def kv(tmp_path):
    return tmp_path / "kv.sqlite"


def _save(kv, user="owner", uid="111", name="alpha", alerts=None, email=None):
    ms.save_manager(user, {"user_id": uid, "username": name}, alerts=alerts, path=kv)
    if email:
        user_kv.merge_user_state(
            user, {"notificationsEnabled": True, "notificationsEmail": email}, path=kv
        )


def test_detect_skips_a_manager_no_longer_saved(kv):
    fresh, mode = mal.detect_for_user("owner", "111", payload([ev("tx:1")]), path=kv)
    assert (fresh, mode) == ([], "not_saved")


def test_detect_refreshes_the_saved_name_from_the_read(kv):
    _save(kv)
    p = payload([], manager={"userId": "111", "username": "renamed", "displayName": "Ren"})
    mal.detect_for_user("owner", "111", p, path=kv)
    (entry,) = ms.entries_from_state(user_kv.get_user_state("owner", path=kv))
    assert entry["username"] == "renamed" and entry["previousUsernames"] == ["alpha"]


# ── sweep ───────────────────────────────────────────────────────────────


class Provider:
    def __init__(self, answers: dict[str, dict]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, handle, **kwargs):
        self.calls.append((handle, kwargs))
        return self.answers[handle]


class Mailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, to, subject, body):
        self.sent.append((to, subject, body))
        return True


def _sweep(kv, provider, mailer, **kw):
    return mal.run_sweep(
        contract={}, delivery=mailer, enabled=True, activity_provider=provider, path=kv, **kw
    )


def test_sweep_baselines_then_emails_once_and_is_idempotent(kv):
    _save(kv, "owner", email="o@example.com")
    _save(kv, "friend")  # no email: evaluated, never sent
    provider = Provider({"111": payload([ev("tx:1")])})
    mailer = Mailer()

    first = _sweep(kv, provider, mailer)
    assert len(provider.calls) == 1  # one read shared by both followers
    assert provider.calls[0][1]["window"] == mal.ALERT_WINDOW
    assert provider.calls[0][1]["call_budget"] == mal.SWEEP_CALL_BUDGET_PER_MANAGER
    assert mailer.sent == [] and first["managersRead"] == 1
    assert {u["username"]: u["managers"][0]["mode"] for u in first["users"]} == {
        "owner": mal.MODE_BASELINE,
        "friend": mal.MODE_BASELINE,
    }

    provider.answers["111"] = payload([ev("tx:2"), ev("tx:1")])
    second = _sweep(kv, provider, mailer)
    assert len(mailer.sent) == 1 and mailer.sent[0][0] == "o@example.com"
    assert "Player tx:2" in mailer.sent[0][2] and "Alpha" in mailer.sent[0][2]
    reasons = {u["username"]: u["reason"] for u in second["users"]}
    assert reasons == {"owner": "ok", "friend": "no_email"}

    third = _sweep(kv, provider, mailer)
    assert len(mailer.sent) == 1  # nothing new, nothing re-sent
    assert {u["reason"] for u in third["users"]} == {"no_new_activity"}


def test_sweep_skips_managers_with_alerts_off(kv):
    _save(kv, alerts=False)
    provider = Provider({})
    out = _sweep(kv, provider, Mailer())
    assert provider.calls == [] and out["managersEligible"] == 0


def test_sweep_reads_stalest_first_and_respects_the_cap(kv):
    for uid in ("301", "302", "303"):
        _save(kv, uid=uid, name=f"m{uid}")
    user_kv.mutate_user_state(
        "owner",
        lambda s: s.update(
            {ms.ALERT_FIELD: {"301": {"lastCheckedAt": 50}, "302": {"lastCheckedAt": 10}}}
        ),
        path=kv,
    )
    provider = Provider({u: payload([]) for u in ("301", "302", "303")})
    out = _sweep(kv, provider, Mailer(), max_managers=2)
    assert [c[0] for c in provider.calls] == ["303", "302"]  # never-read, then oldest
    assert out["skipped"] == {"301": "sweep_manager_cap"}


def test_sweep_stops_at_the_first_rate_limit_and_records_nothing_for_it(kv):
    for uid in ("401", "402"):
        _save(kv, uid=uid, name=f"m{uid}")
    provider = Provider({"401": {"status": "rate_limited"}, "402": payload([])})
    out = _sweep(kv, provider, Mailer())
    assert [c[0] for c in provider.calls] == ["401"]
    assert out["rateLimited"] is True
    assert out["skipped"] == {"401": "rate_limited", "402": "rate_limited"}
    assert ms.alert_states(user_kv.get_user_state("owner", path=kv)) == {}


def test_sweep_honours_call_and_time_budgets(kv):
    for uid in ("501", "502"):
        _save(kv, uid=uid, name=f"m{uid}")
    provider = Provider({"501": payload([], calls=300), "502": payload([])})
    out = _sweep(kv, provider, Mailer(), total_call_budget=300)
    assert out["skipped"] == {"502": "sweep_call_budget"} and out["callsSpent"] == 300

    ticks = iter([0.0, 0.0, 999.0, 999.0])
    provider2 = Provider({"501": payload([]), "502": payload([])})
    out2 = _sweep(kv, provider2, Mailer(), clock=lambda: next(ticks), wall_seconds=10)
    assert len(provider2.calls) == 1 and "sweep_time_budget" in out2["skipped"].values()


def test_sweep_disabled_reads_nothing(kv):
    _save(kv)
    out = mal.run_sweep(
        contract={}, delivery=None, enabled=False, activity_provider=Provider({}), path=kv
    )
    assert out == {"enabled": False}


def test_refresh_for_user_reports_in_app_and_marks_seen(kv):
    _save(kv, email="o@example.com")
    provider = Provider({"111": payload([ev("tx:1")])})
    first = mal.refresh_for_user("owner", contract={}, activity_provider=provider, path=kv)
    assert first["checked"][0]["mode"] == mal.MODE_BASELINE
    assert first["checked"][0]["newEvents"] == []
    provider.answers["111"] = payload([ev("tx:2"), ev("tx:1")])
    second = mal.refresh_for_user("owner", contract={}, activity_provider=provider, path=kv)
    assert [e["id"] for e in second["checked"][0]["newEvents"]] == ["tx:2"]
    # The sweep does not email what the user already saw in-app.
    mailer = Mailer()
    _sweep(kv, provider, mailer)
    assert mailer.sent == []


def test_email_digest_names_each_manager_and_move():
    msg = mal.format_email(
        "owner",
        [
            (
                {"userId": "1", "username": "alpha", "displayName": "Alpha"},
                [mal._event_summary(ev("tx:1"))],  # noqa: SLF001 — what evaluate reports
            )
        ],
    )
    assert msg["subject"] == "[Brisket] 1 new move by managers you follow"
    assert "Alpha (@alpha)" in msg["body"]
    assert "Trade in League L1 — added Player tx:1" in msg["body"]


# ── wiring into the daily sweep ─────────────────────────────────────────


def _server_sweep(monkeypatch, run_sweep):
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(mal, "run_sweep", run_sweep)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(server, "latest_contract_data", {"players": {}})
        monkeypatch.setattr(server, "SIGNAL_ALERT_CRON_TOKEN", "test-token-mi")
        monkeypatch.setattr(server._user_kv, "all_user_states", lambda: {})
        res = c.post("/api/signal-alerts/run", headers={"Authorization": "Bearer test-token-mi"})
    return server, res


def test_daily_sweep_runs_the_saved_manager_alerts(monkeypatch):
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return {"enabled": kwargs["enabled"], "managersRead": 0}

    server, res = _server_sweep(monkeypatch, fake)
    assert res.status_code == 200, res.text
    assert res.json()["managerIntelAlerts"] == {"enabled": True, "managersRead": 0}
    assert seen["delivery"] is server._deliver_email_smtp
    assert 0 <= seen["wall_seconds"] <= mal.SWEEP_WALL_SECONDS


def test_a_failing_saved_manager_leg_never_fails_the_sweep(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("kaput")

    _server, res = _server_sweep(monkeypatch, boom)
    assert res.status_code == 200
    assert res.json()["managerIntelAlerts"] == {"error": "kaput"}


# ── missing stamps are unknown, never 0 ─────────────────────────────────


def test_a_seen_id_with_a_missing_stamp_never_refires_and_ages_out_only_when_gone():
    prior = {
        "seededAt": 1,
        "seededLeagues": ["L1"],
        "seenIds": {"tx:visible": None, "tx:gone": "bad", "tx:recent": 5 * DAY_MS},
    }
    fresh, _m, state = mal.evaluate(prior, payload([ev("tx:visible")]), 6 * DAY_MS)
    assert fresh == []  # still seen, whatever its stamp
    # Unknown age: kept while visible, never proven young enough afterwards.
    assert state["seenIds"] == {"tx:visible": None, "tx:recent": 5 * DAY_MS}


def test_stalest_first_sorts_never_checked_before_any_date():
    keys = [
        mal.stalest_first_key(10, "b"),
        mal.stalest_first_key(None, "z"),
        mal.stalest_first_key(None, "a"),
        mal.stalest_first_key(5, "c"),
    ]
    assert [k[2] for k in sorted(keys)] == ["a", "z", "c", "b"]
    assert mal.last_checked_at({"lastCheckedAt": None}) is None
    assert mal.last_checked_at({"lastCheckedAt": True}) is None
    assert mal.last_checked_at(None) is None


def test_reads_without_a_call_count_are_counted_apart_not_as_zero(kv):
    for uid in ("601", "602", "603"):
        _save(kv, uid=uid, name=f"m{uid}")
    no_count = payload([])
    no_count["coverage"].pop("callsSpent")
    provider = Provider({"601": no_count, "602": payload([], calls=40), "603": payload([])})
    out = _sweep(kv, provider, Mailer(), total_call_budget=230, call_budget_per_manager=200)
    assert out["callsSpent"] == 40 and out["readsWithoutCallCount"] == 1
    # The unreported read is charged its whole allowance for the budget only.
    assert out["skipped"] == {"603": "sweep_call_budget"}
