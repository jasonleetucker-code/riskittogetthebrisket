"""HTTP surface for the intel endpoints: auth gates, league scoping
(partitioned snapshots + 503 data_not_ready), 202/409 refresh
semantics, staleness stamping, and payload hygiene (no raw Sleeper
league IDs)."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.intel import service, store
from tests.intel.conftest import DAY_MS, HOUR_MS

LEAGUE_KEY = "dynasty_main"


@pytest.fixture
def authed(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "jason"})
    # POST /api/intel/refresh now gates its session path on the admin
    # allowlist (W22-F007), so the stub identity is allowlisted
    # explicitly rather than depending on the env default.  Read-only
    # intel endpoints ignore this.
    monkeypatch.setattr(server, "PRIVATE_APP_ALLOWED_USERNAMES", frozenset({"jason"}))


@pytest.fixture
def league_stub(monkeypatch):
    cfg = SimpleNamespace(
        key=LEAGUE_KEY,
        sleeper_league_id="999",
        active=True,
        roster_settings={"starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1}},
    )
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda *a, **k: cfg)
    return cfg


def _seed_snapshot(
    now_ms: int | None = None,
    league_key: str = LEAGUE_KEY,
    asset_ids: tuple[str, str] = ("1234", "5678"),
    traded_asset: str | None = None,
    member_id: str = "A",
) -> None:
    """Write a small snapshot into one league's partition (the store's
    DATA_DIR is monkeypatched by ``intel_data_dir``)."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    add_asset, drop_asset = asset_ids
    # Distinct from the waiver/FA assets so a test can tell which
    # transaction type a row came from.
    traded_asset = traded_asset or f"tr{add_asset}"
    state = store.default_state("2026")
    state["members"] = {
        member_id: {
            "leagues": ["L1", "L2"],
            "truncated": False,
            "lastCrawledAt": "2026-07-25T00:00:00+00:00",
            "lastError": None,
        }
    }
    state["memberNames"] = {member_id: "Alice"}
    state["leagues"] = {
        "L1": {
            "name": "Alpha League",
            "memberOwnerIds": [member_id],
            "holdings": {member_id: [add_asset]},
            "fetchState": {},
        },
        "L2": {
            "name": "Beta League",
            "memberOwnerIds": [member_id],
            "holdings": {},
            "fetchState": {},
        },
    }
    state["events"] = [
        {
            "eventId": f"t1:{member_id}:add:{add_asset}",
            "txId": "t1",
            "leagueId": "L1",
            "ownerId": member_id,
            "assetId": add_asset,
            "assetType": "player",
            "action": "add",
            "txType": "waiver",
            "ts": now_ms - HOUR_MS,
            "week": 1,
            "faabBid": 5,
        },
        {
            "eventId": f"t2:{member_id}:drop:{drop_asset}",
            "txId": "t2",
            "leagueId": "L1",
            "ownerId": member_id,
            "assetId": drop_asset,
            "assetType": "player",
            "action": "drop",
            "txType": "free_agent",
            "ts": now_ms - DAY_MS,
            "week": 1,
            "faabBid": None,
        },
        # A real TRADE.  The two events above are waiver / free-agent and
        # must NOT reach the buy/sell board — only this one may.  Keeping
        # all three in the fixture pins both directions at once.
        {
            "eventId": f"t3:{member_id}:add:{traded_asset}",
            "txId": "t3",
            "leagueId": "L1",
            "ownerId": member_id,
            "assetId": traded_asset,
            "assetType": "player",
            "action": "add",
            "txType": "trade",
            "ts": now_ms - HOUR_MS,
            "week": 1,
            "faabBid": None,
        },
    ]
    store.save_state(state, league_key, now_ms=now_ms)
    service.invalidate_cache()


class TestAuthGates:
    def test_summary_requires_auth(self, intel_data_dir):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/summary")
        assert res.status_code == 401

    def test_refresh_requires_auth_or_bearer(self, intel_data_dir, monkeypatch):
        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post("/api/intel/refresh")
            assert res.status_code == 401
            res = c.post(
                "/api/intel/refresh",
                headers={"Authorization": "Bearer wrong"},
            )
            assert res.status_code == 401

    def test_status_accepts_bearer_token(self, intel_data_dir, monkeypatch):
        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get(
                "/api/intel/refresh/status",
                headers={"Authorization": "Bearer sekrit"},
            )
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-store"


class TestBearerAuthHygiene:
    def test_non_ascii_bearer_is_401_not_500(self, intel_data_dir, monkeypatch):
        # Starlette decodes header values as latin-1, and
        # hmac.compare_digest(str, str) raises TypeError on non-ASCII
        # input — which used to surface as an unhandled 500.  Raw
        # bytes header so the client can't "helpfully" re-encode.
        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        monkeypatch.setattr(server, "_intel_auth_log_last_monotonic", 0.0)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get(
                "/api/intel/refresh/status",
                headers={b"Authorization": "Bearer sekrït".encode("utf-8")},
            )
        assert res.status_code == 401

    def test_mismatch_log_never_leaks_configured_token_metadata(
        self, intel_data_dir, monkeypatch, caplog
    ):
        import logging

        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        monkeypatch.setattr(server, "_intel_auth_log_last_monotonic", 0.0)
        with caplog.at_level(logging.WARNING):
            with TestClient(server.app, raise_server_exceptions=True) as c:
                res = c.get(
                    "/api/intel/refresh/status",
                    headers={"Authorization": "Bearer totally-wrong"},
                )
        assert res.status_code == 401
        rejects = [r.getMessage() for r in caplog.records if "intel bearer auth" in r.getMessage()]
        assert rejects, "mismatch should log a (rate-limited) warning"
        joined = " ".join(rejects)
        # The journal gets quoted in ops issues — no secret material,
        # not even the configured token's length.
        assert "sekrit" not in joined
        assert "len configured" not in joined
        assert "lengths match: False" in joined

    def test_reject_warnings_are_rate_limited(self, intel_data_dir, monkeypatch, caplog):
        import logging

        monkeypatch.setattr(server, "INTEL_REFRESH_TOKEN", "sekrit")
        monkeypatch.setattr(server, "_intel_auth_log_last_monotonic", 0.0)
        with caplog.at_level(logging.WARNING):
            with TestClient(server.app, raise_server_exceptions=True) as c:
                for _ in range(5):
                    res = c.get(
                        "/api/intel/refresh/status",
                        headers={"Authorization": "Bearer totally-wrong"},
                    )
                    assert res.status_code == 401
        rejects = [r for r in caplog.records if "intel bearer auth" in r.getMessage()]
        # Journal-spam guard: unauthenticated rejects log at most once
        # per interval, no matter how many requests arrive.
        assert len(rejects) == 1


class TestLeagueScoping:
    def test_reads_go_through_the_league_resolver(
        self, intel_data_dir, authed, tmp_path, monkeypatch
    ):
        # Defect D-5 (docs/python-coverage-audit.md).  This used to run
        # with no registry setup at all and a comment claiming "the test
        # env's empty registry" — i.e. it depended on AMBIENT state.
        # Serially that held, because nothing had loaded a registry yet.
        # Under ``-n 4 --dist loadfile`` another file's registry landed
        # on the same xdist worker first and the assertion flipped from
        # 404 ``no_leagues_configured`` to 503 ``data_not_ready``.
        #
        # An empty registry is a PRECONDITION of this test, so it
        # establishes one instead of hoping for it.  That also makes the
        # test honest about what it proves: the resolver is reached and
        # reports "no leagues", not "some other file left the world in a
        # state where this happens to pass".
        empty = tmp_path / "empty_registry.json"
        empty.write_text(json.dumps({"leagues": []}), encoding="utf-8")
        monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(empty))
        league_registry.reload_registry()

        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/summary")
        assert res.status_code == 404
        assert res.json()["error"] == "no_leagues_configured"

        league_registry.reload_registry()

    def test_no_snapshot_for_league_returns_503_data_not_ready(
        self, intel_data_dir, authed, league_stub
    ):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            for url in (
                "/api/intel/summary",
                "/api/intel/player?playerId=1234",
                "/api/intel/member/A",
            ):
                res = c.get(url)
                assert res.status_code == 503, url
                body = res.json()
                assert body["error"] == "data_not_ready"
                assert body["leagueKey"] == LEAGUE_KEY

    def test_summary_serves_the_requested_leagues_partition(
        self, intel_data_dir, authed, league_stub
    ):
        # Two leagues, two disjoint snapshots.  The resolved league's
        # partition is served — switching leagues switches data, and
        # neither refresh clobbered the other (distinct files).
        # DISTINCT members per league.  A manager who really is in both
        # leagues legitimately appears on both boards (their trades are
        # relevant to both) — see
        # tests/intel/test_read_path.py::TestLeagueScoping.  To test
        # ISOLATION the pools must actually differ.
        _seed_snapshot(league_key="dynasty_main", asset_ids=("1111", "2222"), member_id="A")
        _seed_snapshot(league_key="dynasty_new", asset_ids=("3333", "4444"), member_id="Z")
        with TestClient(server.app, raise_server_exceptions=True) as c:
            league_stub.key = "dynasty_main"
            res_main = c.get("/api/intel/summary")
            league_stub.key = "dynasty_new"
            res_new = c.get("/api/intel/summary")
        assert res_main.status_code == res_new.status_code == 200
        main_assets = {a["assetId"] for a in res_main.json()["assets"]}
        new_assets = {a["assetId"] for a in res_new.json()["assets"]}
        # Only the TRADED asset reaches the board; the waiver/FA assets
        # ("1111"/"2222") are correctly absent.
        assert main_assets == {"tr1111"}
        assert new_assets == {"tr3333"}
        assert res_main.json()["leagueKey"] == "dynasty_main"
        assert res_new.json()["leagueKey"] == "dynasty_new"


class TestWaiverInterestIsSeparate:
    """Waiver activity gets its OWN endpoint and its OWN vocabulary.

    A flag on the board would have been enough to render the numbers,
    but not to prevent the defect: the whole failure was waiver churn
    reading as trade "buys".  Separate route, separate field names.
    """

    def test_waiver_endpoint_serves_the_waiver_assets(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/waiver-interest")
        assert res.status_code == 200
        body = res.json()
        assert body["activityType"] == "waiver_and_free_agent"
        ids = {a["assetId"] for a in body["assets"]}
        # The waiver add and the free-agent drop; NOT the traded asset.
        assert ids == {"1234", "5678"}
        assert "tr1234" not in ids

    def test_waiver_rows_say_adds_not_buys(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            body = c.get("/api/intel/waiver-interest").json()
        win = body["assets"][0]["windows"]["30d"]
        assert "adds" in win and "drops" in win
        assert "buys" not in win and "sells" not in win

    def test_board_and_waiver_endpoints_do_not_overlap(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            board = {a["assetId"] for a in c.get("/api/intel/summary").json()["assets"]}
            waiver = {a["assetId"] for a in c.get("/api/intel/waiver-interest").json()["assets"]}
        assert board and waiver
        assert board.isdisjoint(waiver)


class TestWindowAndSortParams:
    def test_window_param_is_honoured(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            body = c.get("/api/intel/summary?window=7d").json()
        assert body["window"] == "7d"

    def test_unknown_window_falls_back_to_the_default(self, intel_data_dir, authed, league_stub):
        """An arbitrary window name must not reach signals.window_bounds,
        which raises on unknown values."""
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/summary?window=13d")
        assert res.status_code == 200
        assert res.json()["window"] == "30d"

    def test_unknown_sort_falls_back(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/summary?sort=nonsense")
        assert res.status_code == 200
        assert res.json()["sort"] == "net"


class TestSummary:
    def test_summary_stamps_staleness_and_sorts(
        self, intel_data_dir, authed, league_stub, monkeypatch
    ):
        two_hours_ago = int(time.time() * 1000) - 2 * HOUR_MS
        _seed_snapshot(now_ms=two_hours_ago)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            # Patch AFTER startup — the app lifespan primes
            # ``latest_contract_data`` and would overwrite an
            # earlier patch.
            monkeypatch.setattr(
                server,
                "latest_contract_data",
                {"sleeper": {"idToPlayer": {"tr1234": "Test Guy"}}},
            )
            res = c.get("/api/intel/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["leagueKey"] == LEAGUE_KEY
        assert body["staleHours"] == pytest.approx(2.0, abs=0.2)
        assert body["memberCount"] == 1
        assert body["leagueCount"] == 2
        assets = body["assets"]
        # Trades only: the waiver add ("1234") and free-agent drop
        # ("5678") must not appear as buys/sells.  trendScore is retired,
        # so ordering is net with a volume tiebreak.
        assert [a["assetId"] for a in assets] == ["tr1234"]
        assert "trendScore" not in assets[0]
        assert body["countedTxTypes"] == ["trade"]
        assert body["window"] == "30d"
        assert assets[0]["displayName"] == "Test Guy"
        # trendScore is retired.  The row carries volume and a
        # confidence tier instead, and a single observation must never
        # read as confident.
        win = assets[0]["windows"]["30d"]
        assert win["buys"] == 1 and win["volume"] == 1
        assert assets[0]["confidence"] == "low"
        # Private endpoint — never a public cache header.
        assert "private" in res.headers["cache-control"]
        # No raw Sleeper league IDs anywhere in the payload.
        assert "L1" not in json.dumps(body)


class TestPlayerAndMember:
    def test_player_intel_by_id(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player", params={"playerId": "1234"})
        assert res.status_code == 200
        body = res.json()
        assert body["assetId"] == "1234"
        assert body["leagueKey"] == LEAGUE_KEY
        assert body["staleHours"] is not None
        exposure = body["memberExposure"]
        assert exposure[0]["ownerId"] == "A"
        assert exposure[0]["displayName"] == "Alice"
        assert exposure[0]["heldLeagueCount"] == 1
        assert "L1" not in json.dumps(body)

    def test_player_movements_carry_no_league_identifiers(
        self, intel_data_dir, authed, league_stub
    ):
        """The league-ID assertion above is VACUOUS on asset "1234".

        That asset's only event is a waiver add, and ``asset_movements_for``
        defaults to trades-only, so ``movements`` comes back empty and
        ``"L1" not in json.dumps(body)`` passes without ever inspecting a
        movement row.  That is how raw Sleeper ``league_id`` values shipped
        to production in the first place.  This test queries the TRADED
        asset, asserts the list is non-empty FIRST so it can never silently
        go vacuous the same way, and only then checks the invariant.
        """
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player", params={"playerId": "tr1234"})
        assert res.status_code == 200
        body = res.json()

        movements = body["movements"]
        assert movements, "fixture must produce a trade movement or this test proves nothing"

        # The ledger is global and filtered by pool membership, not by
        # league, so these rows can describe leagues the caller is not in.
        for mv in movements:
            assert "leagueId" not in mv
            assert "counterpartyUserId" not in mv
        # The fields the UI actually renders must survive the projection.
        assert movements[0]["movementId"]
        assert movements[0]["userId"] == "A"
        assert movements[0]["action"] == "add"
        assert "L1" not in json.dumps(body)
        assert "L2" not in json.dumps(body)

    def test_player_drilldown_honours_the_requested_window(
        self, intel_data_dir, authed, league_stub
    ):
        """A 90d board row must not expand to an empty 30d drill-down.

        The drill-down used to be hard-wired to INSIDER_DEFAULT_WINDOW
        while the board offered 7d/30d/90d, so a row reading "Buys 1" on
        the 90d board expanded to "no league-mate holds or traded this
        asset" — the receipts contradicted the count they were receipts for.
        """
        # 40 days back: outside the 30d window, inside both the 90d window
        # and the snapshot's 45-day event retention.
        _seed_snapshot(now_ms=int(time.time() * 1000) - 40 * DAY_MS)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            wide = c.get("/api/intel/player", params={"playerId": "tr1234", "window": "90d"})
            narrow = c.get("/api/intel/player", params={"playerId": "tr1234", "window": "30d"})

        assert wide.status_code == 200
        wide_body = wide.json()
        assert wide_body["window"] == "90d"
        # The whole point: the receipts are present at the window the row
        # was rendered from.
        assert wide_body["movements"], "90d drill-down must surface the 40-day-old trade"
        assert wide_body["memberExposure"]

        # And the 30d view is legitimately empty — the trade really is
        # outside it. This half pins that the window is being APPLIED
        # rather than ignored in the permissive direction.
        assert narrow.status_code == 200
        narrow_body = narrow.json()
        assert narrow_body["window"] == "30d"
        assert narrow_body["movements"] == []

    def test_player_drilldown_rejects_unknown_window(self, intel_data_dir, authed, league_stub):
        """Unknown windows fall back to the default, never reach SQL."""
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get(
                "/api/intel/player",
                params={"playerId": "1234", "window": "1) OR 1=1 --"},
            )
        assert res.status_code == 200
        assert res.json()["window"] == "30d"

    def test_player_drilldown_accepts_the_all_window(self, intel_data_dir, authed, league_stub):
        """``all`` is in the endpoint allow-list but NOT in INSIDER_WINDOWS.

        Before the window was threaded through, the param was ignored, so
        this value never reached ``build_player_payload`` and the mismatch
        was invisible.  It reaches it now: ``window_bounds`` special-cases
        ``all`` to an open-ended range, and the builder has to add it to
        ``window_names`` or ``primary_window`` would select a window that
        was never aggregated.
        """
        _seed_snapshot(now_ms=int(time.time() * 1000) - 40 * DAY_MS)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player", params={"playerId": "tr1234", "window": "all"})
        assert res.status_code == 200
        body = res.json()
        assert body["window"] == "all"
        assert body["windows"]["all"]["volume"] == 1
        assert body["movements"], "an unbounded window must surface the 40-day-old trade"

    def test_player_intel_unknown_asset_404(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player", params={"playerId": "does-not-exist"})
        assert res.status_code == 404

    def test_player_intel_missing_params_400(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/player")
        assert res.status_code == 400

    def test_member_payload(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/member/A")
        assert res.status_code == 200
        body = res.json()
        assert body["displayName"] == "Alice"
        assert body["leagueKey"] == LEAGUE_KEY
        assert body["leagueCount"] == 2
        assert body["leagueNames"] == ["Alpha League", "Beta League"]
        assert body["truncated"] is False
        # "eventCount30d" became movement/trade counts with the unit
        # named explicitly (see docs/intel/METRICS.md).  Only the trade
        # counts — the waiver add and FA drop do not.
        assert body["movementCount"] == 1
        assert body["tradeCount"] == 1
        assert body["window"] == "30d"
        assert "L1" not in json.dumps(body)

    def test_member_unknown_404(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/member/nobody")
        assert res.status_code == 404


class TestRefreshLifecycle:
    def test_refresh_202_then_409_while_running(
        self, intel_data_dir, authed, league_stub, monkeypatch
    ):
        gate = threading.Event()
        started = threading.Event()
        seen_kwargs = {}

        def slow_refresh(**kwargs):
            seen_kwargs.update(kwargs)
            started.set()
            gate.wait(timeout=10)
            return {"ok": True, "callsUsed": 0}

        monkeypatch.setattr(service, "_refresh_locked", slow_refresh)
        try:
            with TestClient(server.app, raise_server_exceptions=True) as c:
                res = c.post("/api/intel/refresh")
                assert res.status_code == 202
                assert res.json()["status"]["isRunning"] is True
                assert started.wait(timeout=5)

                res2 = c.post("/api/intel/refresh")
                assert res2.status_code == 409
                assert res2.json()["alreadyRunning"] is True

                status = c.get("/api/intel/refresh/status")
                assert status.status_code == 200
                assert status.json()["isRunning"] is True
        finally:
            gate.set()
        # Wait for the daemon worker to release the lock.
        for _ in range(100):
            if not service.refresh_status()["isRunning"]:
                break
            time.sleep(0.02)
        final = service.refresh_status()
        assert final["isRunning"] is False
        assert final["lastResult"] == {"ok": True, "callsUsed": 0}
        assert final["lastError"] is None
        # The resolved league was threaded into the refresh worker.
        assert seen_kwargs["league_key"] == LEAGUE_KEY

    def test_refresh_all_mode_refreshes_every_active_league(
        self, intel_data_dir, authed, monkeypatch
    ):
        # ``leagueKey=all`` bypasses the per-request resolver and
        # iterates the registry's ACTIVE leagues — this is the cron's
        # path (bearer requests have no session, so without it the
        # resolver would silently fall back to the default league).
        actives = [
            SimpleNamespace(key="dynasty_main", sleeper_league_id="111"),
            SimpleNamespace(key="dynasty_new", sleeper_league_id="222"),
        ]
        monkeypatch.setattr(server._league_registry, "active_leagues", lambda: actives)

        seen = []
        done = threading.Event()

        def fake_refresh(**kwargs):
            seen.append((kwargs.get("league_key"), kwargs.get("sleeper_league_id")))
            if len(seen) == 2:
                done.set()
            return {"leagueKey": kwargs.get("league_key")}

        monkeypatch.setattr(service, "_refresh_locked", fake_refresh)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post("/api/intel/refresh?leagueKey=all")
        assert res.status_code == 202
        body = res.json()
        assert body["leagueKey"] == "all"
        assert body["leagueKeys"] == ["dynasty_main", "dynasty_new"]
        assert done.wait(timeout=5)
        assert seen == [("dynasty_main", "111"), ("dynasty_new", "222")]
        for _ in range(100):
            if not service.refresh_status()["isRunning"]:
                break
            time.sleep(0.02)
        final = service.refresh_status()
        assert final["lastResult"]["mode"] == "all"
        assert [lg["leagueKey"] for lg in final["lastResult"]["leagues"]] == [
            "dynasty_main",
            "dynasty_new",
        ]
        assert final["lastError"] is None

    def test_refresh_all_mode_with_no_active_leagues_404(self, intel_data_dir, authed, monkeypatch):
        monkeypatch.setattr(server._league_registry, "active_leagues", lambda: [])
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post("/api/intel/refresh?leagueKey=all")
        assert res.status_code == 404
        assert res.json()["error"] == "no_leagues_configured"

    def test_refresh_error_surfaces_in_status(
        self, intel_data_dir, authed, league_stub, monkeypatch
    ):
        def broken_refresh(**kwargs):
            raise RuntimeError("sleeper exploded")

        monkeypatch.setattr(service, "_refresh_locked", broken_refresh)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.post("/api/intel/refresh")
            assert res.status_code == 202
        for _ in range(100):
            if not service.refresh_status()["isRunning"]:
                break
            time.sleep(0.02)
        status = service.refresh_status()
        assert status["isRunning"] is False
        assert "sleeper exploded" in status["lastError"]

    def test_refresh_status_stamps_snapshot_staleness(self, intel_data_dir, authed, league_stub):
        two_hours_ago = int(time.time() * 1000) - 2 * HOUR_MS
        _seed_snapshot(now_ms=two_hours_ago)
        with TestClient(server.app, raise_server_exceptions=True) as c:
            res = c.get("/api/intel/refresh/status")
        assert res.status_code == 200
        body = res.json()
        assert body["snapshotStaleHours"] == pytest.approx(2.0, abs=0.2)
        assert body["snapshotLeagueKey"] == LEAGUE_KEY


class TestLeads:
    """POST /api/intel/leads — the sell/buy mode surface.

    The endpoint composes three optional inputs (ledger observations,
    the loaded contract's rosters, the league's starter settings) and
    must produce a usable ranking when any of them is missing, because
    a missing contract is the normal state of a fresh process.
    """

    def test_requires_auth(self, intel_data_dir):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "1234"})
        assert r.status_code == 401

    def test_missing_asset_is_a_400_not_an_empty_list(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={})
        assert r.status_code == 400
        assert r.json()["error"] == "missing_asset"

    def test_no_snapshot_for_league_returns_503(self, intel_data_dir, authed, league_stub):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "1234"})
        assert r.status_code == 503
        assert r.json()["error"] == "data_not_ready"

    def test_sell_mode_is_the_default_and_is_stamped(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234"})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "sell"
        assert body["assetId"] == "tr1234"
        assert body["leagueKey"] == LEAGUE_KEY

    def test_buy_mode_is_honoured(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234", "mode": "buy"})
        assert r.json()["mode"] == "buy"

    def test_unknown_mode_falls_back_rather_than_erroring(
        self, intel_data_dir, authed, league_stub
    ):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234", "mode": "sideways"})
        assert r.status_code == 200
        assert r.json()["mode"] == "sell"

    def test_the_trade_shows_up_as_demonstrated_interest(self, intel_data_dir, authed, league_stub):
        """Member A acquired ``tr1234`` by TRADE in league L1, which is
        not this league (``sleeper_league_id`` is 999), so it counts."""
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234"})
        body = r.json()
        assert body["leadsWithObservedInterest"] == 1
        lead = next(x for x in body["leads"] if x["ownerId"] == "A")
        assert lead["interest"]["buys"] == 1
        assert lead["leadScore"] > 0

    def test_waiver_activity_is_never_demonstrated_interest(
        self, intel_data_dir, authed, league_stub
    ):
        """``1234`` was a WAIVER add.  The whole point of the split is
        that a claim is not a trade — it must not create a lead."""
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "1234"})
        body = r.json()
        assert body["leadsWithObservedInterest"] == 0
        assert all(x["interest"] is None for x in body["leads"])

    def test_payload_carries_its_limitations(self, intel_data_dir, authed, league_stub):
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234"})
        lim = r.json()["limitations"]
        assert lim["isNotAProbability"] is True

    def test_no_acceptance_probability_anywhere_in_the_payload(
        self, intel_data_dir, authed, league_stub
    ):
        """Sleeper never records a declined offer, so an acceptance rate
        is unobservable — the payload must not imply one."""
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234"})
        blob = json.dumps(r.json()).lower()
        assert "acceptanceprobability" not in blob

    def test_body_league_key_reaches_the_resolver(self, intel_data_dir, authed, monkeypatch):
        """POST convention: the body is parsed BEFORE the resolver so a
        body ``leagueKey`` is not silently ignored."""
        seen = {}

        def _resolve(request, body=None, **kwargs):
            seen["body"] = body
            return SimpleNamespace(
                key=LEAGUE_KEY, sleeper_league_id="999", active=True, roster_settings={}
            )

        monkeypatch.setattr(server, "_resolve_league_for_request", _resolve)
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            c.post("/api/intel/leads", json={"assetId": "tr1234", "leagueKey": LEAGUE_KEY})
        assert (seen["body"] or {}).get("leagueKey") == LEAGUE_KEY

    def test_a_missing_contract_degrades_rather_than_500ing(
        self, intel_data_dir, authed, league_stub, monkeypatch
    ):
        """No loaded contract means no rosters, no positions and no
        values — the fit terms must abstain, not take the route down."""
        monkeypatch.setattr(server, "latest_contract_data", None)
        _seed_snapshot()
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post("/api/intel/leads", json={"assetId": "tr1234"})
        assert r.status_code == 200
        assert all(x["partnerFitScore"] is None for x in r.json()["leads"])

    def test_malformed_body_is_a_clean_400_not_a_crash(self, intel_data_dir, authed, league_stub):
        with TestClient(server.app, raise_server_exceptions=True) as c:
            r = c.post(
                "/api/intel/leads",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
        assert r.status_code == 400


class TestSyncRefreshLock:
    def test_concurrent_sync_refresh_rejected(self, intel_data_dir, monkeypatch):
        gate = threading.Event()
        entered = threading.Event()

        def slow_refresh(**kwargs):
            entered.set()
            gate.wait(timeout=10)
            return {}

        monkeypatch.setattr(service, "_refresh_locked", slow_refresh)
        t = threading.Thread(target=lambda: service.refresh_intel(member_ids=["A"]), daemon=True)
        t.start()
        assert entered.wait(timeout=5)
        with pytest.raises(service.RefreshAlreadyRunning):
            service.refresh_intel(member_ids=["A"])
        gate.set()
        t.join(timeout=5)
