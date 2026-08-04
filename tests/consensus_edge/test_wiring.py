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

    def test_offense_is_covered(self):
        body = self.client.get("/api/consensus-edge/players").json()
        classes = {r.get("assetClass") for r in body["players"] if r.get("score") is not None}
        self.assertIn("offense", classes)

    def test_an_unscored_asset_class_is_declared_not_merely_absent(self):
        # This test used to assert ``"idp" in classes``, because an IDP
        # league whose defenders all fell out is the failure mode that
        # made trade/finder.py silently offense-only for months. IDP now
        # legitimately carries no score — the anchor-free board has no
        # IDP scale once the only backbone source is excluded — so the
        # old assertion would be satisfied only by publishing wrong
        # numbers.
        #
        # The failure mode was never "IDP is unscored". It was "the
        # response looks the same either way". So: an unscored class must
        # be counted, named, and given a reason in the payload itself.
        body = self.client.get("/api/consensus-edge/players").json()
        coverage = body.get("assetClassCoverage") or {}
        self.assertTrue(coverage, "board does not report per-asset-class coverage at all")

        scored_classes = {c for c, m in coverage.items() if m.get("scored")}
        self.assertIn("offense", scored_classes)

        for cls, meta in coverage.items():
            self.assertEqual(
                meta["rows"],
                meta["scored"] + sum(meta["unpricedReasons"].values()),
                f"{cls} rows are unaccounted for",
            )
            if meta["scored"] or not meta["rows"]:
                continue
            # Wholly unscored: the payload must say why, and the caveats
            # must say it in a sentence a reader will actually see.
            self.assertTrue(meta["unpricedReasons"], f"{cls} is unscored with no stated reason")
            self.assertTrue(
                any(cls.upper() in c for c in body.get("caveats") or []),
                f"{cls} carries no score and no caveat mentions it",
            )

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

    def test_served_order_is_the_measured_order(self):
        # The study that justified turning the flag on measures
        # ``service.top_movers``, which ranks by conviction. ``/players``
        # — the ONLY endpoint the page fetches — sorted by raw score, so
        # the measurement described an ordering no user ever saw. The two
        # must be one list read two ways.
        body = self.client.get("/api/consensus-edge/players").json()
        rows = body["players"]

        convictions = [r["conviction"] for r in rows if r.get("score") is not None]
        self.assertGreater(len(convictions), 50)
        self.assertEqual(
            convictions,
            sorted(convictions, reverse=True),
            "/players is not in conviction order",
        )

        served_buys = [
            r["playerKey"] for r in rows if r.get("qualified") and (r.get("score") or 0) > 0
        ][:10]
        measured = self.client.get("/api/consensus-edge/top?limit=10").json()
        self.assertEqual(
            served_buys,
            [r["playerKey"] for r in measured["buys"]],
            "the top of the served board is not the list the study measures",
        )

    def test_conviction_is_stamped_not_left_to_the_client(self):
        body = self.client.get("/api/consensus-edge/players").json()
        for row in body["players"]:
            if row.get("score") is None:
                continue
            self.assertIsInstance(row.get("conviction"), float, row["playerKey"])
            expected = float(row["score"]) * float(row["confidence"]) / 100.0
            self.assertAlmostEqual(row["conviction"], expected, places=9)

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


@_needs_contract
class TestOpportunityReachesRealBoardRows(unittest.TestCase):
    """The axis must match real board keys, not just hand-made fixtures.

    Everything about this component was correct in isolation and dead in
    aggregate: the service indexed rank history by bare `displayName`
    while the log files players under `{name}::{assetClass}`, so the
    lookup matched **zero of 973** rows in every environment including
    production. A unit test cannot see that — its fixture supplies both
    sides of the join.

    So this builds real history through the real producer, reads it back
    through the real loader, and asserts the service's key finds it on
    the real contract. Nothing here is hand-shaped.
    """

    @classmethod
    def setUpClass(cls):
        import json
        import tempfile

        from src.api import rank_history

        cls.history_path = Path(tempfile.mkdtemp()) / "rank_history.jsonl"
        # Three snapshots with a deterministic per-player drift, so both
        # directions of the momentum axis are exercised on real rows.
        for step, day in enumerate(("2026-07-01", "2026-07-02", "2026-07-03")):
            snapshot = json.loads(json.dumps(_CONTRACT))
            for i, row in enumerate(snapshot["playersArray"]):
                value = row.get("rankDerivedValue")
                if isinstance(value, (int, float)):
                    row["rankDerivedValue"] = value * (1 + (0.04 if i % 2 else -0.04) * step)
            rank_history.append_snapshot(snapshot, path=cls.history_path, date=day)
        cls.history = rank_history.load_history(days=30, path=cls.history_path)

    def test_history_was_actually_written(self):
        self.assertGreater(len(self.history), 100, "producer wrote nothing to replay")

    def test_the_service_key_finds_real_rows(self):
        from src.consensus_edge import service as svc

        rows = _CONTRACT["playersArray"]
        hits = sum(
            1
            for r in rows
            if svc.rank_history_key(str(r.get("displayName") or ""), r.get("assetClass"))
            in self.history
        )
        self.assertGreater(
            hits / len(rows),
            0.5,
            "the service's history key matches under half the board — this is "
            "the composite-key bug, which matched exactly zero rows",
        )

    def test_a_bare_name_lookup_would_still_match_nothing(self):
        # Pins the bug itself: if this ever starts matching, the log's
        # key format changed and `rank_history_key` must change with it.
        rows = _CONTRACT["playersArray"]
        bare = sum(1 for r in rows if str(r.get("displayName") or "") in self.history)
        self.assertEqual(bare, 0)

    def test_opportunity_produces_values_on_the_real_board(self):
        """It must compute. Whether it *counts* is a separate question.

        Before the key fix this measured zero rows in every environment.
        It now measures hundreds — and carries zero weight, because the
        backtest that became possible once board history turned out to
        be reconstructable returned a null. Both facts are asserted
        here, separately, because collapsing them is how a
        measured-and-rejected component becomes indistinguishable from
        a broken one.
        """
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT, rank_history_by_player=self.history)
        availability = board["componentAvailability"]["opportunity"]
        self.assertGreater(
            availability["rowsWithValue"],
            100,
            "opportunity produced no value on any row despite real history",
        )

    def test_a_zero_weight_component_is_not_counted_as_live(self):
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT, rank_history_by_player=self.history)
        availability = board["componentAvailability"]["opportunity"]
        if availability["weight"] > 0:
            self.skipTest("opportunity carries weight again; this guard does not apply")
        self.assertFalse(availability["available"])
        self.assertEqual(availability["unavailableReason"], "zero_weight")
        self.assertEqual(
            sum(1 for v in board["componentAvailability"].values() if v["available"]),
            1,
            "a component contributing nothing to any score was counted toward "
            "the confidence ceiling",
        )

    def test_a_zero_weight_component_cannot_raise_confidence(self):
        """The specific way this would go wrong, pinned.

        Confidence is a geometric mean over coverage. If a zero-weight
        component entered `componentsPresent`, every row it valued would
        gain coverage — and therefore confidence, and therefore possibly
        a Strong label — from a signal contributing exactly zero to its
        score.

        Note what this does NOT assert. It used to end on
        `assertFalse(strongLabelsReachable)`, which was never the point:
        that followed from the denominator ALSO counting the zero-weight
        component, which was the other half of the same inconsistency
        and has since been fixed. Excluding it from both sides is what
        makes the treatment coherent — the invariant here is that the
        component earns no weight on any row, not that the board is
        forbidden a Strong label.
        """
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT, rank_history_by_player=self.history)
        checked = 0
        for row in board["players"]:
            if "opportunity" not in (row.get("componentsZeroWeight") or []):
                continue
            checked += 1
            self.assertNotIn("opportunity", row["effectiveWeights"])
            self.assertNotIn(
                "opportunity", row["componentsPresent"] if "componentsPresent" in row else []
            )
        self.assertGreater(checked, 100, "no row exercised the zero-weight path")

    def test_no_real_row_gets_a_buy_ward_push_from_price_alone(self):
        """The direction guarantee, on every row of a real board.

        Half these players' values rise across the replayed snapshots.
        Under the previous axis each of those was a positive
        contribution — momentum-chasing worth up to 20% of the
        composite. Not one may be positive now.
        """
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT, rank_history_by_player=self.history)
        checked = 0
        for row in board["players"]:
            for axis in (row.get("opportunity") or {}).get("axes") or []:
                if axis["axis"] != "boardMomentumRisk" or axis["score"] is None:
                    continue
                checked += 1
                self.assertLessEqual(
                    axis["score"],
                    0.0,
                    f"{row['displayName']}: a board-value move produced a buy-ward "
                    f"contribution of {axis['score']}",
                )
        self.assertGreater(checked, 100, "no row exercised the momentum axis at all")


@_needs_contract
class TestPlayerContextUnlocksASecondComponent(unittest.TestCase):
    """Two live components is what makes Strong labels reachable at all.

    Confidence is a geometric mean over coverage, so with one live
    component the ceiling sits at 69.3 against a Strong threshold of 70
    — Strong Buy and Strong Sell are not rare, they are *impossible*.
    The second component moves the ceiling to 87.4.

    The playerctx snapshot is gitignored, so this synthesises one in the
    store's real shape. What that proves is the JOIN and the ceiling
    arithmetic; the snap numbers themselves come from production.
    """

    @classmethod
    def setUpClass(cls):
        from src.consensus_edge import identity_join

        index, players = {}, {}
        for i, row in enumerate(_CONTRACT["playersArray"]):
            sleeper_id = identity_join.row_sleeper_id(row)
            if not sleeper_id or row.get("assetClass") == "pick":
                continue
            gsis = f"00-{i:07d}"
            index[sleeper_id] = gsis
            players[gsis] = {
                "gsisId": gsis,
                "sleeperId": sleeper_id,
                "snaps": {
                    "season": 2025,
                    "games": 12,
                    "side": "offense",
                    "pct": 55.0,
                    "recentPct": 55.0 + (6.0 if i % 3 else -6.0),
                    "trend": 6.0 if i % 3 else -6.0,
                },
            }
        cls.snapshot = {"schemaVersion": "playerctx.v1", "sleeperIndex": index, "players": players}
        cls.context = identity_join.player_context_index(_CONTRACT, cls.snapshot)

    def test_the_join_reaches_most_of_the_board(self):
        rows = len(_CONTRACT["playersArray"])
        self.assertGreater(
            len(self.context) / rows,
            0.5,
            f"playerctx join reached only {len(self.context)} of {rows} rows",
        )

    def test_one_live_component_out_of_two_weighted_ones_still_reaches_strong(self):
        """The ceiling is a ratio, and the denominator is what changed.

        This asserted that one live component made Strong labels
        impossible. That was true while the denominator counted all
        three components — including one carrying zero weight, which is
        not evidence we are missing but evidence we measured and
        declined. Coverage is now 1 of 2, the ceiling is 79.37, and the
        rows this had been suppressing turned out to be the best group
        on the board (+8.83% cohort-excess, 6 of 6 folds).
        """
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT, hours_stale=svc.resolve_hours_stale(_CONTRACT))
        live = sum(1 for v in board["componentAvailability"].values() if v["available"])
        self.assertEqual(live, 1, "expected only mispricing live with no inputs supplied")
        self.assertTrue(board["strongLabelsReachable"])
        self.assertIn("Strong Buy", {r["label"] for r in board["players"]})

    def test_unknown_staleness_still_suppresses_strong_labels(self):
        """The ceiling must not promise what the board cannot deliver.

        With no `hours_stale`, `score.confidence` pins freshness at 0.5
        — the safe reading of "we don't know how old this is". The
        published ceiling assumed freshness 1.0 and so advertised 79.37
        while every row was capped at 62.996 and none could reach a
        Strong label. Freshness is board-wide and known, so the ceiling
        now uses it.
        """
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT)  # deliberately no hours_stale
        self.assertLess(board["confidenceCeiling"], board["strongLabelThreshold"])
        self.assertFalse(board["strongLabelsReachable"])
        self.assertNotIn("Strong Buy", {r["label"] for r in board["players"]})

    def test_a_second_WEIGHTED_component_is_what_unlocks_strong_labels(self):
        """Weight, not mere presence, is what makes a component count.

        This test used to assert that supplying player context made
        Strong labels reachable, and it passed. Then the composite
        backtest returned a null for the opportunity axis and its weight
        went to zero — at which point the old assertion was measuring
        the wrong thing entirely: a component that contributes nothing
        to any score was raising the confidence ceiling and unlocking
        the strongest labels the board can emit.

        So the ceiling arithmetic is asserted directly, against the
        component count it is a function of, rather than through a
        component whose weight is a live decision.
        """
        from src.consensus_edge import service as svc

        board = svc.build_board(
            _CONTRACT,
            hours_stale=svc.resolve_hours_stale(_CONTRACT),
            player_context_by_player=self.context,
        )
        weights = (svc.params_mod.load().get("composite") or {}).get("weights") or {}
        expected_live = sum(
            1
            for name, meta in board["componentAvailability"].items()
            if meta["rowsWithValue"] > 0 and float(weights.get(name) or 0.0) > 0
        )
        live = sum(1 for v in board["componentAvailability"].values() if v["available"])
        self.assertEqual(live, expected_live)

        # The ceiling's denominator is the WEIGHTED component count, not
        # the total — a component carrying zero weight is excluded from
        # both sides of the coverage ratio or the treatment is
        # incoherent.
        weighted = max(1, sum(1 for v in weights.values() if float(v or 0.0) > 0.0))
        threshold = board["strongLabelThreshold"]
        # Freshness is board-wide and known, so it is a factor of the
        # published ceiling rather than an assumed 1.0 — otherwise the
        # ceiling promises Strong labels a stale board cannot deliver.
        freshness = max(
            r["confidenceFactors"]["freshness"]
            for r in board["players"]
            if r.get("confidenceFactors")
        )
        self.assertAlmostEqual(
            board["confidenceCeiling"],
            svc.confidence_ceiling(live, weighted, freshness),
            places=6,
        )
        self.assertEqual(board["strongLabelsReachable"], board["confidenceCeiling"] >= threshold)
        # The arithmetic itself, independent of today's weights.
        self.assertLess(svc.confidence_ceiling(1, 3), 70.0)
        self.assertGreater(svc.confidence_ceiling(1, 2), 70.0)
        self.assertGreaterEqual(svc.confidence_ceiling(2, 3), 70.0)

    def test_the_board_reports_the_context_it_received(self):
        from src.consensus_edge import service as svc

        board = svc.build_board(_CONTRACT, player_context_by_player=self.context)
        self.assertEqual(board["inputs"]["playerContextPlayers"], len(self.context))


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
