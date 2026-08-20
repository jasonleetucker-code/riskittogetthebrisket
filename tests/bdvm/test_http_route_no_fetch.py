"""HTTP-level zero-network proof for every ``/api/bdvm/*`` route.

THE GAP THIS FILE CLOSES.

``tests/bdvm/test_request_path_is_local.py`` (TEST A onward) proves
``bdvm_api.get_bdvm_values`` itself never fetches — but every one of its tests
calls that function directly, bypassing ``server.py``'s actual routing:
``run_in_threadpool``, ``_bdvm_gate_and_league`` (roster/trades/trade-eval), and
``/api/bdvm/values``'s own inline gate. ``tests/bdvm/test_endpoint.py`` drives the
real routes through a ``TestClient``, but only for auth/flag/error-shape — it never
patches the network layer, so it cannot see a fetch either way.

Nothing, until this file, proves the zero-network property at the layer the routes
actually live at. And two of the four routes — ``/api/bdvm/roster`` and
``/api/bdvm/trades`` — have **no HTTP-level test coverage of any kind**, anywhere
in the repo (confirmed by grep before writing this file).

NON-VACUITY, STATED PRECISELY.  An empty ``_NetworkRecorder`` alone is not proof
the request path was exercised: a request refused before it ever reaches
``get_bdvm_values`` (feature disabled, unknown league, no contract) shows the
identical empty recorder, for the wrong reason — exactly the trap TEST A's own
docstring warns about for its narrower case. So every test here ALSO spies on
``bdvm_api._context_for`` / ``_schedule_for`` — the two calls ``get_bdvm_values``
makes unconditionally, before ``run_valuation``, regardless of whether a BDVM
projection snapshot exists (confirmed by reading ``get_bdvm_values`` directly) —
and asserts BOTH were actually invoked. Zero fetches AND real invocation, or the
test does not count.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import server
from src.api import bdvm_api, feature_flags, league_registry, user_kv
from src.bdvm import context_store
from src.bdvm import projections as bdvm_projections
from src.bdvm.projections import ProjectionRecord, write_snapshot
from src.nfl_data import cache as nfl_cache
from src.nfl_data import ingest
from tests.bdvm.test_request_path_is_local import _NetworkRecorder

_LEAGUE_KEY = "dynasty_main"


def _contract() -> dict:
    """Complete enough to reach ``get_bdvm_values``'s real body.

    Deliberately the SAME field set ``test_request_path_is_local.py``'s
    ``_contract()`` uses, plus ``meta.leagueKey`` — the route-level gate
    (``server.py``) additionally requires the loaded contract to be stamped for
    the resolved league, which the function-level tests never had to satisfy.
    """
    return {
        "meta": {"leagueKey": _LEAGUE_KEY},
        "generatedAt": "2026-08-20T00:00:00Z",
        "currentDraftYear": 2026,
        "players": {},
        "playersArray": [],
        "sleeper": {
            "teams": [{"ownerId": "oA", "name": "Team A", "players": []}],
            "scoringSettings": {"rec": 1.0, "pass_td": 4.0},
            "rosterPositions": ["QB", "WR", "WR", "LB", "BN", "BN"],
            "leagueSettings": {"num_teams": 12},
        },
    }


class TestBdvmRoutesNeverFetch(unittest.TestCase):
    """One test per route, all sharing one rig.

    Every request in this class is COLD by construction: the raw feed cache and
    the context snapshot directory are both redirected to an empty temp root —
    same two roots TEST A redirects, and for the same reason (leaving either
    alone would read this sandbox's real ``data/`` and make the test warm on one
    machine, cold in CI).
    """

    @classmethod
    def setUpClass(cls):
        # Deliberately NOT ``with TestClient(server.app) as client`` /
        # explicit ``__enter__()``/``__exit__()``. That form runs the ASGI
        # app's REAL lifespan startup — cache warming, a background
        # public-league refresh thread against the LIVE registry's real
        # Sleeper league, an uptime watchdog — and holds it open for the
        # whole class, racing whatever test file runs next in the same
        # process. Bare construction (the pattern every other BDVM/public-
        # league TestClient test in this repo already uses, e.g.
        # ``tests/bdvm/test_endpoint.py``) does not trigger it. Caught by
        # running this file immediately before
        # ``tests/public_league/test_server_routes.py``: with the context-
        # manager form, 9 of its tests failed on a real, uncontrolled
        # background refresh clobbering the module-level
        # ``server._public_league_cache`` that test file explicitly seeds;
        # with bare construction, 0.
        cls.client = TestClient(server.app)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp_path = Path(self._tmp.name)

        registry_path = tmp_path / "registry.json"
        registry_path.write_text(
            json.dumps(
                {
                    "defaultLeagueKey": _LEAGUE_KEY,
                    "leagues": [
                        {
                            "key": _LEAGUE_KEY,
                            "displayName": "Main",
                            "sleeperLeagueId": "L-MAIN",
                            "active": True,
                            "rosterSettings": {"teamCount": 12},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        # ``tests/conftest.py`` sets LEAGUE_REGISTRY_PATH to a deliberately
        # NONEXISTENT path for the whole test session, precisely so
        # league_registry falls through to synthesising from
        # SLEEPER_LEAGUE_ID -- which is what lets OTHER test files
        # (test_server_routes.py among them) point the registry at a
        # stubbed league by setting that one env var in their own
        # setUpClass, with no reload_registry() call of their own needed.
        # Popping this var instead of restoring it to THAT value left it
        # unset, so the next accessor fell through to the REAL
        # config/leagues/registry.json on disk instead -- a real registry
        # that exists in this checkout, which silently wins over
        # SLEEPER_LEAGUE_ID once loaded. Caught by running this file
        # immediately before tests/public_league/test_server_routes.py:
        # its stub client is keyed to "L2025"/"L2024", the real registry
        # resolves a different id entirely, and every route asking for
        # league data got "zero seasons" back. Capture-and-restore-exactly,
        # never assume unset is the safe default to pop to.
        _prior_registry_path = os.environ.get("LEAGUE_REGISTRY_PATH")
        os.environ["LEAGUE_REGISTRY_PATH"] = str(registry_path)
        league_registry.reload_registry()

        def _restore_registry():
            if _prior_registry_path is None:
                os.environ.pop("LEAGUE_REGISTRY_PATH", None)
            else:
                os.environ["LEAGUE_REGISTRY_PATH"] = _prior_registry_path
            league_registry.reload_registry()

        self.addCleanup(_restore_registry)

        # Isolate user_kv so the session/activeLeagueKey lookup in pass 3 of
        # ``_resolve_league_for_request`` doesn't touch the real DB file.
        self.addCleanup(setattr, user_kv, "USER_KV_PATH", user_kv.USER_KV_PATH)
        user_kv.USER_KV_PATH = tmp_path / "user_kv.sqlite"
        user_kv._SETUP_DONE.clear()

        # Same capture-and-restore-exactly discipline as the registry path
        # above, applied on principle even though no other test file was
        # found to depend on a specific prior value of this one.
        _prior_bdvm_flag = os.environ.get("RISKIT_FEATURE_BDVM_ENGINE")
        os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = "1"
        feature_flags.reload()

        def _restore_feature_flags():
            if _prior_bdvm_flag is None:
                os.environ.pop("RISKIT_FEATURE_BDVM_ENGINE", None)
            else:
                os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = _prior_bdvm_flag
            feature_flags.reload()

        self.addCleanup(_restore_feature_flags)

        self._auth_patch = mock.patch.object(server, "_is_authenticated", lambda request: True)
        self._auth_patch.start()
        self.addCleanup(self._auth_patch.stop)

        self._contract_patch = mock.patch.object(server, "latest_contract_data", _contract())
        self._contract_patch.start()
        self.addCleanup(self._contract_patch.stop)

        bdvm_api.reset_cache()
        self.addCleanup(bdvm_api.reset_cache)

        # ``_actuals_for`` derives its OWN season from ``current_nfl_season()``
        # — the calendar NFL season, never the contract's draft year — and
        # returns ``(None, {})`` immediately outside the Sept-Jan window,
        # never even reaching ``fetch_current_season_actuals``. Outside that
        # window (this repo's test-suite dates included) that makes the
        # actuals call site UNREACHABLE from here, silently, unless pinned to
        # a real in-season date — caught by running the mutation matrix, not
        # assumed: a first draft trusted the spy alone and missed this.
        from src.bdvm import actuals as bdvm_actuals

        self._season_patch = mock.patch.object(
            bdvm_actuals, "current_nfl_season", return_value=2025
        )
        self._season_patch.start()
        self.addCleanup(self._season_patch.stop)

        # Cold: empty artifact roots, same two TEST A redirects.
        cache_dir = tmp_path / "cold_cache"
        self._cache_dir_patch = mock.patch.object(
            nfl_cache, "_default_cache_dir", return_value=cache_dir
        )
        self._cache_dir_patch.start()
        self.addCleanup(self._cache_dir_patch.stop)
        self._snapshot_dir_patch = mock.patch.object(
            context_store, "SNAPSHOT_DIR", cache_dir / "ctx"
        )
        self._snapshot_dir_patch.start()
        self.addCleanup(self._snapshot_dir_patch.stop)

        # A real BDVM projection snapshot, so ``get_bdvm_values`` takes the
        # branch that also calls ``_actuals_for`` (``if snapshot else
        # (None, {})``) — without one, ``_actuals_for`` is never reached at
        # all and its own ``cache_only=True`` call site would be untested
        # here, silently.  This is not incidental: a first draft of this file
        # mutation-tested only the schedule call site and the actuals one
        # passed vacuously — caught by running the mutation, not assumed.
        from src.bdvm.actuals import nfl_projection_season

        season = nfl_projection_season()
        self._snapshot_root_patch = mock.patch.object(
            bdvm_projections, "SNAPSHOT_DIR", tmp_path / "bdvm_projections"
        )
        self._snapshot_root_patch.start()
        self.addCleanup(self._snapshot_root_patch.stop)
        write_snapshot(
            [
                ProjectionRecord(
                    source="clayProjections",
                    player_key="test player",
                    position="WR",
                    season=season,
                    as_of="2026-07-20",
                    games=17.0,
                    fpg=10.0,
                    scoring_native=True,
                )
            ],
            season=season,
            as_of="2026-07-20",
        )

        # The network recorder — the SAME one TEST A uses, at the same two
        # choke points (``ingest._try_fetch_with_fallback`` covers everything
        # under ``src.nfl_data.ingest``; ``urllib.request.urlopen`` is the
        # retired-downloader catch-all).
        self.recorder = _NetworkRecorder()
        self._fetch_patch = mock.patch.object(
            ingest, "_try_fetch_with_fallback", side_effect=self.recorder.ingest_fetch
        )
        self._fetch_patch.start()
        self.addCleanup(self._fetch_patch.stop)
        self._urlopen_patch = mock.patch.object(
            urllib.request, "urlopen", side_effect=self.recorder.urlopen
        )
        self._urlopen_patch.start()
        self.addCleanup(self._urlopen_patch.stop)

        # The non-vacuity spies: capture the REAL functions before patching,
        # so the mock still calls through and returns the genuine result while
        # recording that it was invoked. All three of ``get_bdvm_values``'s
        # data inputs are spied — including ``_actuals_for``, which is ONLY
        # reached when a projection snapshot exists (seeded above); without
        # that seed this spy would never fire and the mutation below would
        # pass vacuously.
        real_context_for = bdvm_api._context_for
        real_schedule_for = bdvm_api._schedule_for
        real_actuals_for = bdvm_api._actuals_for
        self._context_spy = mock.patch.object(
            bdvm_api, "_context_for", side_effect=real_context_for
        )
        self._context_for_mock = self._context_spy.start()
        self.addCleanup(self._context_spy.stop)
        self._schedule_spy = mock.patch.object(
            bdvm_api, "_schedule_for", side_effect=real_schedule_for
        )
        self._schedule_for_mock = self._schedule_spy.start()
        self.addCleanup(self._schedule_spy.stop)
        self._actuals_spy = mock.patch.object(
            bdvm_api, "_actuals_for", side_effect=real_actuals_for
        )
        self._actuals_for_mock = self._actuals_spy.start()
        self.addCleanup(self._actuals_spy.stop)

    def _assert_no_fetch_and_really_ran(self) -> None:
        self.assertEqual(
            self.recorder.attempts,
            [],
            "an interactive BDVM route started a remote nflverse fetch:\n  "
            + "\n  ".join(self.recorder.attempts),
        )
        self._context_for_mock.assert_called_once()
        self._schedule_for_mock.assert_called_once()
        self._actuals_for_mock.assert_called_once()

    def test_values_route_attempts_no_remote_fetch(self):
        resp = self.client.get("/api/bdvm/values")
        self.assertLess(resp.status_code, 500, resp.text)
        body = resp.json()
        self.assertNotEqual(body.get("error"), "feature_disabled")
        self.assertNotEqual(body.get("error"), "data_not_ready")
        self._assert_no_fetch_and_really_ran()

    def test_roster_route_attempts_no_remote_fetch(self):
        resp = self.client.get("/api/bdvm/roster")
        self.assertLess(resp.status_code, 500, resp.text)
        body = resp.json()
        self.assertNotEqual(body.get("error"), "feature_disabled")
        self.assertNotEqual(body.get("error"), "data_not_ready")
        self._assert_no_fetch_and_really_ran()

    def test_trades_route_attempts_no_remote_fetch(self):
        resp = self.client.get("/api/bdvm/trades")
        self.assertLess(resp.status_code, 500, resp.text)
        body = resp.json()
        self.assertNotEqual(body.get("error"), "feature_disabled")
        self.assertNotEqual(body.get("error"), "data_not_ready")
        self._assert_no_fetch_and_really_ran()

    def test_trade_eval_route_attempts_no_remote_fetch(self):
        resp = self.client.post(
            "/api/bdvm/trade-eval",
            json={"sideA": [{"name": "Someone"}], "sideB": [{"name": "Someone Else"}]},
        )
        self.assertLess(resp.status_code, 500, resp.text)
        body = resp.json()
        self.assertNotEqual(body.get("error"), "feature_disabled")
        self.assertNotEqual(body.get("error"), "data_not_ready")
        self._assert_no_fetch_and_really_ran()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
