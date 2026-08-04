"""The board cache must invalidate on everything that can move the board.

The cache key was `scrapeTimestamp|paramSetId`, and `api._board`'s
docstring said "nothing else invalidates it" — which states the bug as
though it were the design. Three things move a board between scrapes:

* the **sharp ledger**, which moves per trade;
* the **playerctx snapshot**, refreshed weekly by its own timer;
* the **model version**, which moves on deploy.

None was in the key, so a box could serve a board built before its
inputs arrived, or before the code that changed the maths, until the
next scrape. `test_wiring.py` clears `_CACHE` in `setUp`, so that suite
structurally could not see this — hence a file that does the opposite
and asserts on the key itself.

Also pinned here: `leagueKey` is not accepted-and-ignored anywhere. The
frontend used to send it through four bridge routes and the API never
read it, while `scoring_fit.py` claimed to have closed that gap. It had
not — `_scoring_cards()` loads the one canonical league config. A
parameter that is accepted and ignored tells a caller the answer is
league-specific when it is not.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from src.consensus_edge import MODEL_VERSION, api as ce_api, inputs as inputs_mod

REPO = Path(__file__).resolve().parents[2]


def _key_for(contract, fingerprint):
    """The key `_board` would compute, without building a board.

    Reaching for the private `_board` and asserting on `_CACHE["key"]`
    would need a real contract and three pipeline passes. The key
    construction is the thing under test.
    """
    from src.consensus_edge import params as params_mod

    with mock.patch.object(inputs_mod, "fingerprint", return_value=fingerprint):
        with mock.patch.object(ce_api.service, "build_board", return_value={"status": "ok"}):
            with mock.patch.object(
                inputs_mod,
                "resolve",
                return_value={
                    "movements_by_asset": None,
                    "rank_history_by_player": None,
                    "player_context_by_player": None,
                },
            ):
                ce_api._CACHE.clear()
                ce_api._board(contract)
    params_mod.load()  # keep the param cache warm for the next call
    return ce_api._CACHE["key"]


class TestTheCacheKey(unittest.TestCase):
    def setUp(self):
        ce_api._CACHE.clear()
        self.addCleanup(ce_api._CACHE.clear)
        self.contract = {"scrapeTimestamp": "2026-08-04T00:00:00Z"}

    def test_a_new_ledger_invalidates_the_board(self):
        first = _key_for(self.contract, "ledger:1:1|playerctx:-")
        second = _key_for(self.contract, "ledger:2:9|playerctx:-")
        self.assertNotEqual(first, second, "a new trade did not invalidate the cached board")

    def test_a_new_playerctx_snapshot_invalidates_the_board(self):
        first = _key_for(self.contract, "ledger:1:1|playerctx:1:1")
        second = _key_for(self.contract, "ledger:1:1|playerctx:2:2")
        self.assertNotEqual(first, second)

    def test_the_model_version_is_in_the_key(self):
        # A deploy that changes the maths must not keep serving the
        # pre-change board until the next scrape.
        self.assertIn(MODEL_VERSION, _key_for(self.contract, "ledger:-|playerctx:-"))

    def test_identical_inputs_still_hit_the_cache(self):
        # The point of the key is to invalidate on change, not to defeat
        # caching: three pipeline passes per request would be the cure
        # being worse than the disease.
        first = _key_for(self.contract, "ledger:1:1|playerctx:-")
        second = _key_for(self.contract, "ledger:1:1|playerctx:-")
        self.assertEqual(first, second)

    def test_a_new_scrape_still_invalidates(self):
        first = _key_for(self.contract, "ledger:1:1|playerctx:-")
        second = _key_for({"scrapeTimestamp": "2026-08-05T00:00:00Z"}, "ledger:1:1|playerctx:-")
        self.assertNotEqual(first, second)


class TestTheFingerprintIsTotal(unittest.TestCase):
    """A dark input is a state, not an error — and must not churn the key."""

    def test_it_returns_a_stable_string_when_nothing_is_present(self):
        with mock.patch.dict("sys.modules", {"src.intel.ledger": None}):
            first = inputs_mod.fingerprint()
            second = inputs_mod.fingerprint()
        self.assertEqual(first, second)

    def test_it_never_raises(self):
        self.assertIsInstance(inputs_mod.fingerprint(), str)


class TestLeagueKeyIsNotAcceptedAndIgnored(unittest.TestCase):
    """Read from source, because the defect was a caller/callee mismatch.

    A runtime assertion would pass either way: sending a parameter the
    backend ignores produces exactly the same response as not sending
    it. What has to be checked is that nobody is sending it.
    """

    def test_the_backend_still_does_not_read_it(self):
        source = (REPO / "src" / "consensus_edge" / "api.py").read_text()
        self.assertNotIn("leagueKey", source)
        self.assertNotIn("league_key", source)

    def test_no_bridge_route_forwards_it(self):
        routes = sorted((REPO / "frontend" / "app" / "api" / "consensus-edge").glob("*/route.js"))
        self.assertTrue(routes, "no bridge routes found — has the directory moved?")
        for route in routes:
            body = route.read_text()
            code = "\n".join(
                line for line in body.splitlines() if not line.strip().startswith("//")
            )
            self.assertNotIn("leagueKey", code, route.name)

    def test_the_hook_does_not_send_it(self):
        body = (REPO / "frontend" / "components" / "useConsensusEdge.js").read_text()
        code = "\n".join(line for line in body.splitlines() if not line.strip().startswith("//"))
        self.assertNotIn('set("leagueKey"', code)

    def test_the_hook_still_refetches_when_the_league_changes(self):
        # Not sending the parameter must not become "ignore the league
        # entirely": a league switch changes which rosters a user cares
        # about even when the board itself is shared.
        body = (REPO / "frontend" / "components" / "useConsensusEdge.js").read_text()
        self.assertIn("league:changed", body)
        self.assertIn("${league}", body)


if __name__ == "__main__":
    unittest.main()
