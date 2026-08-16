"""C1-ID-02 RED: the same real pick failing to round-trip across two
production representations — plus the other measured identity-failure
classes, each pinned against LIVE code paths and REAL league data.

The C1-U3 execution-map RED is "the same pick failing to round-trip
across two representations".  The fixture
(``tests/fixtures/pick_identity_live_subset.json``) is unedited
production data: the scraper's baked ``pickDetails`` (representation S2
in ``docs/identity/C1_ID_02_PICK_IDENTITY.md`` §2), the Sleeper
``/traded_picks`` rows they derive from (S1), and a stored trade-history
entry whose pick assets are bare display strings.

Every test here asserts CURRENT behavior — i.e. each one PASSES by
demonstrating the defect.  They are regression-locks on the measurement,
in the same style as ``test_matcher_disagreement_red.py`` (C1-U2): when
a representation is migrated onto the canonical owner and a defect
becomes unrepresentable, the corresponding RED assertion is updated in
the same commit with a pointer to the GREEN test that supersedes it.
The GREEN counterparts live in ``test_pick_identity.py``.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.api.sleeper_overlay import (
    _build_pick_ownership,
    _format_trade_pick_label,
    _slot_to_tier_label,
)
from src.intel.crawler import _events_from_tx

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pick_identity_live_subset.json"


def _fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _overlay_details_for(fx: dict, league_id: str) -> dict[int, list[dict]]:
    """Run the LIVE overlay ownership builder on the real traded-pick rows."""

    def getter(url: str):
        assert league_id in url
        return fx["sleeperTradedPicks"]

    roster_ids = list(range(1, 13))
    return _build_pick_ownership(league_id, roster_ids, getter=getter)


class TestRedSamePickTwoRepresentationsNoRoundTrip(unittest.TestCase):
    """THE execution-map RED.  One real asset — dynasty_main's 2027 R1
    originating from roster 12 (Blaine), currently owned by roster 1 —
    serialized by the two production Sleeper-side producers:

      S2 (scraper-baked contract):  {"season": 2027 (int), "round": 1,
          "fromRosterId": 12, ...,  "label": "2027 Mid 1st (from Blaine)"}
      S4 (overlay _build_pick_ownership): {"season": "2027" (str),
          "round": 1, "original_roster_id": 12, ..., "label": "2027 1st"}

    The two representations agree on NOTHING checkable: the natural-key
    tuple differs (int vs str season), the field names differ, and the
    labels differ.  Nothing in either dict round-trips to the other."""

    @classmethod
    def setUpClass(cls):
        cls.fx = _fx()
        cls.baked = next(
            pd
            for pd in cls.fx["scraperPickDetails"]
            if pd["season"] == 2027 and pd["round"] == 1 and pd["fromRosterId"] == 12
        )
        per_roster = _overlay_details_for(cls.fx, cls.fx["_provenance"]["sleeperLeagueId"])
        cls.overlay = next(
            pd
            for pd in per_roster.get(1, [])
            if pd["season"] == "2027" and pd["round"] == 1 and pd["original_roster_id"] == 12
        )

    def test_red_natural_key_join_fails_on_season_type(self):
        baked_key = (self.baked["season"], self.baked["round"], self.baked["fromRosterId"])
        overlay_key = (
            self.overlay["season"],
            self.overlay["round"],
            self.overlay["original_roster_id"],
        )
        # Same real pick.  The join a consumer would naturally write
        # fails: (2027, 1, 12) != ("2027", 1, 12).
        self.assertNotEqual(baked_key, overlay_key)

    def test_red_origin_field_is_named_differently_in_each_shape(self):
        self.assertIn("fromRosterId", self.baked)
        self.assertNotIn("fromRosterId", self.overlay)
        self.assertIn("original_roster_id", self.overlay)
        self.assertNotIn("original_roster_id", self.baked)

    def test_red_the_two_labels_for_one_asset_are_not_equal(self):
        self.assertEqual(self.baked["label"], "2027 Mid 1st (from Blaine)")
        self.assertEqual(self.overlay["label"], "2027 1st")
        self.assertNotEqual(self.baked["label"], self.overlay["label"])


class TestRedDistinctRealPicksCollapseToOneLabel(unittest.TestCase):
    """Roster 1 owns FIVE distinct 2027 firsts (its own plus origins 12,
    9, 10, 3) and roster 7 owns SEVEN distinct 2028 firsts.  Their
    overlay labels are all identical, and the scraper's ``baseLabel``
    (what trade-history valuation resolves through) is identical too —
    N real assets, one string."""

    @classmethod
    def setUpClass(cls):
        cls.fx = _fx()
        cls.per_roster = _overlay_details_for(cls.fx, cls.fx["_provenance"]["sleeperLeagueId"])

    def test_red_five_2027_firsts_serialize_to_one_overlay_label(self):
        labels = [
            pd["label"]
            for pd in self.per_roster.get(1, [])
            if pd["season"] == "2027" and pd["round"] == 1
        ]
        self.assertEqual(len(labels), 5)
        self.assertEqual(set(labels), {"2027 1st"})

    def test_red_seven_2028_firsts_share_one_base_label_in_the_baked_contract(self):
        base = {
            pd["baseLabel"]
            for pd in self.fx["scraperPickDetails"]
            if pd["season"] == 2028 and pd["round"] == 1
        }
        count = sum(
            1 for pd in self.fx["scraperPickDetails"] if pd["season"] == 2028 and pd["round"] == 1
        )
        self.assertEqual(count, 7)
        self.assertEqual(base, {"2028 Mid 1st"})


class TestRedSerializationDependsOnWallClockAndDisplayNames(unittest.TestCase):
    """The trade-history label for one unchanged asset changes when (a)
    the calendar year rolls, or (b) the origin team renames.  Historical
    trade records store these strings, so the same pick's stored
    reference and its freshly generated reference drift apart with zero
    data change to the pick itself."""

    PICK = {"season": "2027", "round": 1, "roster_id": 12}

    def test_red_year_rollover_changes_the_label_with_no_state_change(self):
        rid_to_name = {12: "Blaine"}
        slot_map = {(2027, 12): 5}
        before = _format_trade_pick_label(
            self.PICK, rid_to_name, slot_map, current_year=2026, league_size=12
        )
        after = _format_trade_pick_label(
            self.PICK, rid_to_name, slot_map, current_year=2027, league_size=12
        )
        self.assertEqual(before, "2027 Mid 1st (from Blaine)")
        self.assertEqual(after, "2027 1.05 (from Blaine)")
        self.assertNotEqual(before, after)

    def test_red_team_rename_changes_the_label_for_the_same_asset(self):
        slot_map: dict = {}
        before = _format_trade_pick_label(
            self.PICK, {12: "Blaine"}, slot_map, current_year=2026, league_size=12
        )
        after = _format_trade_pick_label(
            self.PICK, {12: "Blaine's Bruisers"}, slot_map, current_year=2026, league_size=12
        )
        self.assertNotEqual(before, after)

    def test_red_stored_trade_strings_are_bare_labels_beside_player_names(self):
        fx = _fx()
        gave = fx["storedTradeWithPickStrings"]["sides"][0]["gave"]
        # The persisted trade history carries pick assets as display
        # strings in the same list as player names — the only identity a
        # historical trade has for a pick is a grammar-dependent label.
        self.assertIn("2028 Mid 2nd (from Blaine)", gave)
        self.assertIn("Malachi Moore", gave)


class TestRedUnknownSlotIsFabricatedAsMid(unittest.TestCase):
    """An UNKNOWN slot and a KNOWN mid slot serialize identically.  Every
    future pick in the live contract carries ``slot: None`` and a label
    claiming "Mid" — including 2029 picks whose draft order cannot exist
    yet.  Missing is being represented as a value."""

    def test_red_none_slot_and_true_mid_slot_are_indistinguishable(self):
        self.assertEqual(_slot_to_tier_label(None, league_size=12), "Mid")
        self.assertEqual(_slot_to_tier_label(6, league_size=12), "Mid")

    def test_red_live_2029_pick_with_unknowable_order_is_labelled_mid(self):
        fx = _fx()
        pick_2029 = next(pd for pd in fx["scraperPickDetails"] if pd["season"] == 2029)
        self.assertIsNone(pick_2029["slot"])
        self.assertIn("Mid", pick_2029["label"])


class TestRedIntelAssetIdStripsOrigin(unittest.TestCase):
    """The intel ledger's asset id is ``pick:<season>:<round>`` — the
    event id keeps origin in a discriminator (repaired earlier), but the
    ASSET id two different real picks aggregate under is one string.
    Holdings and per-asset signals cannot distinguish two real assets."""

    def test_red_two_distinct_2027_seconds_share_one_asset_id(self):
        tx = {
            "status": "complete",
            "type": "trade",
            "transaction_id": "tx-red-1",
            "created": 1786818713561,
            "adds": {},
            "drops": {},
            "draft_picks": [
                {
                    "season": "2027",
                    "round": 2,
                    "roster_id": 9,
                    "owner_id": 1,
                    "previous_owner_id": 9,
                },
                {
                    "season": "2027",
                    "round": 2,
                    "roster_id": 4,
                    "owner_id": 1,
                    "previous_owner_id": 4,
                },
            ],
        }
        rid_to_owner = {"1": "u1", "9": "u9", "4": "u4"}
        pool = {"u1", "u9", "u4"}
        events = _events_from_tx(tx, "1312006700437352448", 1, rid_to_owner, pool, set())
        pick_adds = [e for e in events if e["assetType"] == "pick" and e["action"] == "add"]
        self.assertEqual(len(pick_adds), 2)
        asset_ids = {e["assetId"] for e in pick_adds}
        # Two real, separately tradeable assets — one asset id.
        self.assertEqual(asset_ids, {"pick:2027:2"})


class TestOverlayLeagueScoping(unittest.TestCase):
    """Was ``TestRedOverlayShapeCarriesNoLeague``: overlay rows carried
    no league component, so identical-looking picks from the two live
    leagues produced EQUAL dicts.  The canonical ``assetId`` stamp
    CLOSED that for registered leagues, so this class now pins all
    three facts: the residual legacy fields are still league-free
    (frontend consumers still key on them — the deferred half), a
    resolvable registry separates the two leagues by canonical id, and
    an unresolvable league id fails closed with NO id rather than an id
    minted under a wrong league.

    Note the pytest environment's registry is deliberately empty
    (``tests/conftest.py`` points it at a non-existent file), so the
    default runs here exercise the fail-closed branch."""

    def _rows(self):
        fx = _fx()
        main = _overlay_details_for(fx, fx["_provenance"]["sleeperLeagueId"])
        new = _overlay_details_for(fx, fx["secondLeague"]["sleeperLeagueId"])
        main_row = next(
            pd
            for pd in main[1]
            if pd["season"] == "2027" and pd["round"] == 1 and pd["original_roster_id"] == 12
        )
        new_row = next(
            pd
            for pd in new[1]
            if pd["season"] == "2027" and pd["round"] == 1 and pd["original_roster_id"] == 12
        )
        return main_row, new_row

    def test_red_residual_legacy_fields_are_still_league_free(self):
        main_row, new_row = self._rows()
        legacy_keys = ("season", "round", "slot", "original_roster_id", "owner_roster_id", "label")
        self.assertEqual(
            {k: main_row.get(k) for k in legacy_keys},
            {k: new_row.get(k) for k in legacy_keys},
        )

    def test_green_no_registry_fails_closed_with_no_asset_id(self):
        # The pytest registry is empty, so neither league resolves — and
        # the correct answer is NO id, never one under a wrong league.
        main_row, new_row = self._rows()
        self.assertNotIn("assetId", main_row)
        self.assertNotIn("assetId", new_row)

    def test_green_registered_leagues_get_distinct_canonical_ids(self):
        from unittest import mock

        fx = _fx()
        key_by_sid = {
            fx["_provenance"]["sleeperLeagueId"]: "dynasty_main",
            fx["secondLeague"]["sleeperLeagueId"]: "dynasty_new",
        }
        with mock.patch(
            "src.api.league_registry.league_key_for_sleeper_id",
            side_effect=lambda sid: key_by_sid.get(str(sid or "")),
        ):
            main_row, new_row = self._rows()
        self.assertEqual(main_row["assetId"], "pick:dynasty_main:2027:r1:o12")
        self.assertEqual(new_row["assetId"], "pick:dynasty_new:2027:r1:o12")
        self.assertNotEqual(main_row, new_row)


if __name__ == "__main__":
    unittest.main()
