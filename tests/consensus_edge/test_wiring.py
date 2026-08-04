"""The served board must actually receive its inputs.

This file exists because the previous test suite could not see the
feature's largest defect. `test_endpoint.py` defined an `_enable()`
helper and never called it, so every endpoint test ran with the flag
OFF; no test anywhere set `latest_contract_data`; and nothing referenced
`build_board`. `service.build_board` could have raised on its first line
and CI would have stayed green.

The specific defect that hid there: `api.py` called
`build_board(contract, params=params)` and passed none of `hours_stale`,
`movements_by_asset` or `rank_history_by_player`. Every served row
therefore had coverage 1/3 and freshness 0.5 — pinning the confidence
ceiling at 55.03 against a Strong threshold of 70, which made Strong
Buy, Strong Sell and Conflicted **mathematically unreachable** in
production while the unit tests for those labels passed happily.

So these tests assert the *seam*, not the arithmetic: that the board is
built at all, and that each input reaches it. Unit correctness is
covered in `test_scoring.py`; it was never the problem.
"""

from __future__ import annotations

import json
import os
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

import server
from src.api import feature_flags

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive"


def _load_contract() -> dict | None:
    """A real built contract, the same shape `latest_contract_data` holds.

    Built from a tracked archive payload rather than a fixture so the
    test exercises the real pipeline. Returns None if the archive is
    unavailable, in which case these tests skip rather than pass
    vacuously.
    """
    if not ARCHIVE.is_dir():
        return None
    zips = sorted(ARCHIVE.glob("dynasty_export_*.zip"))
    if not zips:
        return None
    with zipfile.ZipFile(zips[-1]) as zf:
        names = [n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")]
        if not names:
            return None
        raw = json.loads(zf.read(names[0]))
    from src.api.data_contract import build_api_data_contract

    return build_api_data_contract(raw)


_CONTRACT = _load_contract()
_needs_contract = unittest.skipIf(_CONTRACT is None, "no archived payload to build a contract from")


class _Enabled(unittest.TestCase):
    """Flag ON and a real contract loaded — the state production runs in."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)

    def setUp(self):
        self._auth = mock.patch.object(server, "_is_authenticated", lambda request: True)
        self._auth.start()
        os.environ["RISKIT_FEATURE_CONSENSUS_EDGE"] = "1"
        feature_flags.reload()
        self._contract = mock.patch.object(server, "latest_contract_data", _CONTRACT)
        self._contract.start()
        # The board is cached on (scrapeTimestamp, paramSetId); clear it
        # so one test's board cannot satisfy another's assertions.
        from src.consensus_edge import api as ce_api

        ce_api._CACHE.clear()

    def tearDown(self):
        self._contract.stop()
        self._auth.stop()
        os.environ.pop("RISKIT_FEATURE_CONSENSUS_EDGE", None)
        feature_flags.reload()


@_needs_contract
class TestTheBoardIsActuallyBuilt(_Enabled):
    """The happy path, which nothing previously exercised."""

    def test_players_returns_a_populated_board(self):
        response = self.client.get("/api/consensus-edge/players")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertGreater(len(body["players"]), 100, "board is implausibly thin")

    def test_the_board_actually_scores_players(self):
        body = self.client.get("/api/consensus-edge/players").json()
        scored = [r for r in body["players"] if r.get("score") is not None]
        self.assertGreater(len(scored), 100, "no player received a score")

    def test_both_offense_and_idp_are_covered(self):
        # An IDP league whose defenders all fell out is the failure mode
        # that made trade/finder.py silently offense-only for months.
        body = self.client.get("/api/consensus-edge/players").json()
        classes = {r.get("assetClass") for r in body["players"] if r.get("score") is not None}
        self.assertIn("offense", classes)
        self.assertIn("idp", classes)

    def test_every_row_carries_provenance(self):
        body = self.client.get("/api/consensus-edge/players").json()
        self.assertTrue(body.get("modelVersion"))
        self.assertTrue(body.get("paramSetId"))
        self.assertTrue(body.get("experimental"))

    def test_top_returns_buys_and_sells(self):
        body = self.client.get("/api/consensus-edge/top?limit=10").json()
        self.assertLessEqual(len(body["buys"]), 10)
        self.assertTrue(body["buys"] or body["sells"], "no qualifying movers at all")
        for row in body["buys"]:
            self.assertGreater(row["score"], 0)
        for row in body["sells"]:
            self.assertLess(row["score"], 0)

    def test_health_reports_real_counts(self):
        body = self.client.get("/api/consensus-edge/health").json()
        self.assertGreater(body["playersTotal"], 100)
        self.assertGreater(body["playersScored"], 100)
        self.assertTrue(body["labelDistribution"])

    def test_a_single_player_can_be_fetched(self):
        board = self.client.get("/api/consensus-edge/players").json()
        key = next(r["playerKey"] for r in board["players"] if r.get("score") is not None)
        response = self.client.get(f"/api/consensus-edge/player/{key}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["player"]["playerKey"], key)

    def test_an_unknown_player_404s_rather_than_500s(self):
        response = self.client.get("/api/consensus-edge/player/Definitely%20Not%20A%20Player")
        self.assertEqual(response.status_code, 404)


@_needs_contract
class TestFreshnessReachesTheBoard(_Enabled):
    """Staleness must degrade confidence on the SERVED path.

    The contract carries `dataFreshness.sourceTimestamps` with real
    `ageHours` per source, and the market anchors are routinely stale
    against their own thresholds. Before this fix the API passed no
    `hours_stale`, so `score.confidence` took its "unknown staleness"
    branch and pinned freshness at exactly 0.5 for every player forever
    — meaning stale data was not visibly degraded anywhere.
    """

    def test_freshness_is_not_the_unknown_default(self):
        body = self.client.get("/api/consensus-edge/players").json()
        scored = [r for r in body["players"] if r.get("score") is not None]
        self.assertTrue(scored)
        freshness = {round(r["confidenceFactors"]["freshness"], 6) for r in scored}
        self.assertNotEqual(
            freshness,
            {0.5},
            "every row reports freshness exactly 0.5 — the 'unknown staleness' "
            "default. The contract's dataFreshness is not reaching build_board.",
        )

    def test_the_board_reports_the_staleness_it_used(self):
        body = self.client.get("/api/consensus-edge/players").json()
        self.assertIn("inputs", body, "board does not report which inputs it received")
        self.assertIn("hoursStale", body["inputs"])


@_needs_contract
class TestComponentAvailabilityIsReported(_Enabled):
    """A dark component must be visibly dark.

    Sharp Flow and Opportunity are absent whenever their data is. That
    is legitimate — but it must be legible, because it silently caps the
    confidence ceiling and therefore suppresses every Strong label. The
    previous build gave a reader no way to distinguish "no lean detected"
    from "this component never ran".
    """

    def test_health_states_which_components_are_live(self):
        body = self.client.get("/api/consensus-edge/health").json()
        self.assertIn("componentAvailability", body)
        availability = body["componentAvailability"]
        for name in ("mispricing", "sharpFlow", "opportunity"):
            self.assertIn(name, availability)
            self.assertIn("available", availability[name])

    def test_health_publishes_the_confidence_ceiling(self):
        # Whether Strong labels are reachable at all is a property of how
        # many components are live. It must be answerable without
        # reading source.
        body = self.client.get("/api/consensus-edge/health").json()
        self.assertIn("confidenceCeiling", body)
        self.assertIn("strongLabelsReachable", body)

    def test_absent_components_are_named_on_every_row(self):
        body = self.client.get("/api/consensus-edge/players").json()
        for row in body["players"]:
            if row.get("score") is None:
                continue
            self.assertIn("componentsAbsent", row)


@_needs_contract
class TestQualificationIsBackendOwned(_Enabled):
    """The frontend must not re-derive who qualifies.

    `positionLeaders` in `lib/consensus-edge.js` hardcoded its own copy
    of the qualification label set, matching Python constants by English
    string. That is the same duplication the client-side
    `computeUnifiedRanks` fallback caused, and the fix is the same: the
    backend states the answer and the client reads it.
    """

    def test_every_row_carries_a_qualified_flag(self):
        body = self.client.get("/api/consensus-edge/players").json()
        for row in body["players"]:
            self.assertIn("qualified", row)
            self.assertIsInstance(row["qualified"], bool)

    def test_qualified_matches_the_directional_labels(self):
        body = self.client.get("/api/consensus-edge/players").json()
        directional = {"Strong Buy", "Buy", "Sell", "Strong Sell"}
        for row in body["players"]:
            self.assertEqual(
                row["qualified"],
                row["label"] in directional,
                f"{row['displayName']}: qualified={row['qualified']} label={row['label']}",
            )

    def test_top_movers_only_contains_qualified_rows(self):
        body = self.client.get("/api/consensus-edge/top?limit=20").json()
        for row in body["buys"] + body["sells"]:
            self.assertTrue(row["qualified"])


@_needs_contract
class TestRefusalStatesAreReachable(_Enabled):
    """The refusal states are the feature's honesty claim.

    They were computed and then filtered out before the only endpoint
    the page called, so no user could ever see one.
    """

    def test_the_full_board_exposes_refusal_states(self):
        body = self.client.get("/api/consensus-edge/players").json()
        labels = {r["label"] for r in body["players"]}
        self.assertTrue(
            labels & {"Insufficient Evidence", "No Market Price", "Conflicted"},
            f"no refusal state present on the whole board; labels were {labels}",
        )

    def test_unpriced_rows_say_why(self):
        body = self.client.get("/api/consensus-edge/players").json()
        for row in body["players"]:
            if row["label"] == "No Market Price":
                self.assertTrue(row.get("unpricedReason"))


class TestServiceSignature(unittest.TestCase):
    """The dead `_rawPayload` key documented an architecture that never existed."""

    def test_no_vestigial_raw_payload_lookup(self):
        # Checks for the LOOKUP, not the string: the comment explaining
        # why the lookup was removed legitimately names the key.
        source = (REPO / "src" / "consensus_edge" / "service.py").read_text()
        self.assertNotIn(
            'get("_rawPayload")',
            source,
            "service.py still reads a key nothing in the repo ever writes",
        )


if __name__ == "__main__":
    unittest.main()
