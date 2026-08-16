"""C1-ID-02 GREEN: the canonical pick-identity contract.

Counterpart to ``test_pick_identity_red.py`` — every defect class pinned
there becomes unrepresentable through the owner
(``src/identity/picks.py``).  The headline GREEN is the execution-map
round-trip: the same real pick, entering from the scraper-baked shape
(S2) and the overlay shape (S4), resolves to ONE canonical id.

Coverage dimensions per the unit's testing strategy: round trips (exact
inverses, exhaustively enumerated over the full realistic domain — the
repo carries no property-testing dependency, and exhaustion is stronger
here), equality/identity-vs-state, the generic→exact-slot transition,
league safety, provider grammars, legacy formatter byte-parity against
the LIVE legacy implementations, determinism, duplicate rejection,
explicit-unknown honesty, and zero valuation involvement.
"""

from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path

from src.identity import picks as P

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pick_identity_live_subset.json"


def _fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


class TestCanonicalIdRoundTrip(unittest.TestCase):
    """format → parse is the identity function, exhaustively."""

    def test_league_pick_id_round_trips_exhaustively(self):
        for league in ("dynasty_main", "dynasty_new", "a-b_c2"):
            for season in (2026, 2029, 2035):
                for rnd in range(1, 7):
                    for origin in (1, 7, 12, 32):
                        ident = P.LeaguePickIdentity(
                            league_key=league,
                            season=season,
                            round_num=rnd,
                            origin_roster_id=origin,
                        )
                        parsed = P.parse_league_pick_id(ident.canonical_id)
                        self.assertEqual(parsed, ident)

    def test_market_pick_id_round_trips_exhaustively_all_grades(self):
        for year in (2026, 2029):
            for rnd in range(1, 7):
                refs = [P.MarketPickRef(year=year, round_num=rnd)]
                refs += [P.MarketPickRef(year=year, round_num=rnd, slot=s) for s in range(1, 15)]
                refs += [P.MarketPickRef(year=year, round_num=rnd, tier=t) for t in P.PICK_TIERS]
                for ref in refs:
                    self.assertEqual(P.parse_market_pick_id(ref.canonical_id), ref)

    def test_board_row_name_round_trips_where_a_row_form_exists(self):
        slot_ref = P.MarketPickRef(year=2026, round_num=1, slot=6)
        self.assertEqual(slot_ref.board_row_name(), "2026 Pick 1.06")
        self.assertEqual(P.parse_board_pick_name("2026 Pick 1.06"), slot_ref)
        tier_ref = P.MarketPickRef(year=2027, round_num=1, tier="early")
        self.assertEqual(tier_ref.board_row_name(), "2027 Early 1st")
        self.assertEqual(P.parse_board_pick_name("2027 Early 1st"), tier_ref)

    def test_generic_grade_has_no_board_row_and_says_so(self):
        # The board carries no generic rows today; inventing a name here
        # would fabricate a row the pipeline never made (C1-U6 owns
        # completeness).  None, not a guess.
        self.assertIsNone(P.MarketPickRef(year=2028, round_num=2).board_row_name())


class TestIdentityVersusState(unittest.TestCase):
    """Trades and slot realization are state transitions, never new assets."""

    IDENT = P.LeaguePickIdentity(
        league_key="dynasty_main", season=2027, round_num=1, origin_roster_id=12
    )

    def test_ownership_change_does_not_change_identity(self):
        before = P.OwnedLeaguePick(self.IDENT, P.LeaguePickState(owner_roster_id=12))
        after = P.OwnedLeaguePick(self.IDENT, P.LeaguePickState(owner_roster_id=1))
        self.assertEqual(before.identity, after.identity)
        self.assertEqual(before.identity.canonical_id, after.identity.canonical_id)

    def test_slot_realization_does_not_change_identity(self):
        unknown = P.OwnedLeaguePick(self.IDENT, P.LeaguePickState(slot=None))
        realized = P.OwnedLeaguePick(self.IDENT, P.LeaguePickState(slot=7))
        self.assertEqual(unknown.identity.canonical_id, realized.identity.canonical_id)

    def test_league_safety_identical_looking_picks_do_not_collide(self):
        main = P.LeaguePickIdentity("dynasty_main", 2027, 1, 12)
        new = P.LeaguePickIdentity("dynasty_new", 2027, 1, 12)
        self.assertNotEqual(main, new)
        self.assertNotEqual(main.canonical_id, new.canonical_id)

    def test_identity_construction_reads_no_clock(self):
        # Determinism guard: nothing in the identity/parse surface may
        # consult the wall clock.  (The RED suite pinned wall-clock
        # serialization drift in the legacy labels; the canonical layer
        # takes the clock as an argument or not at all.)
        source = inspect.getsource(P)
        for banned in ("datetime.now", "date.today", "time.time"):
            self.assertNotIn(banned, source)


class TestTheExecutionMapGreen(unittest.TestCase):
    """The same real pick from both production representations resolves
    to ONE canonical id — the round-trip the RED suite proves impossible
    today without the owner."""

    @classmethod
    def setUpClass(cls):
        cls.fx = _fx()

    def test_baked_and_overlay_shapes_converge_on_one_canonical_id(self):
        baked = next(
            pd
            for pd in self.fx["scraperPickDetails"]
            if pd["season"] == 2027 and pd["round"] == 1 and pd["fromRosterId"] == 12
        )
        # S2 (scraper-baked, int season, fromRosterId):
        from_baked = P.LeaguePickIdentity(
            league_key="dynasty_main",
            season=int(baked["season"]),
            round_num=int(baked["round"]),
            origin_roster_id=int(baked["fromRosterId"]),
        )
        # S1/S4 (Sleeper wire / overlay, str season, roster_id origin):
        tp = next(
            t
            for t in self.fx["sleeperTradedPicks"]
            if t["season"] == "2027" and t["round"] == 1 and t["roster_id"] == 12
        )
        from_wire = P.LeaguePickIdentity(
            league_key="dynasty_main",
            season=int(tp["season"]),
            round_num=int(tp["round"]),
            origin_roster_id=int(tp["roster_id"]),
        )
        self.assertEqual(from_baked, from_wire)
        self.assertEqual(from_baked.canonical_id, "pick:dynasty_main:2027:r1:o12")

    def test_five_real_2027_firsts_are_five_distinct_canonical_ids(self):
        details = [
            pd for pd in self.fx["scraperPickDetails"] if pd["season"] == 2027 and pd["round"] == 1
        ]
        ids = {
            P.LeaguePickIdentity(
                "dynasty_main", pd["season"], pd["round"], pd["fromRosterId"]
            ).canonical_id
            for pd in details
        }
        self.assertEqual(len(ids), len(details))

    def test_seven_real_2028_firsts_are_seven_distinct_canonical_ids(self):
        details = [
            pd for pd in self.fx["scraperPickDetails"] if pd["season"] == 2028 and pd["round"] == 1
        ]
        self.assertEqual(len(details), 7)
        ids = {
            P.LeaguePickIdentity(
                "dynasty_main", pd["season"], pd["round"], pd["fromRosterId"]
            ).canonical_id
            for pd in details
        }
        self.assertEqual(len(ids), 7)


class TestOwnershipFold(unittest.TestCase):
    """One fold replaces the four legacy copies; measured on real rows."""

    @classmethod
    def setUpClass(cls):
        cls.fx = _fx()
        cls.owned = P.build_pick_ownership(
            "dynasty_main",
            range(1, 13),
            cls.fx["sleeperTradedPicks"],
            seasons=(2027, 2028, 2029),
            rounds=6,
        )

    def test_seed_plus_diff_reproduces_real_ownership(self):
        r1_2027 = [
            o
            for o in self.owned
            if o.identity.season == 2027
            and o.identity.round_num == 1
            and o.state.owner_roster_id == 1
        ]
        # Roster 1's own 2027 R1 plus the four real traded-in origins.
        self.assertEqual({o.identity.origin_roster_id for o in r1_2027}, {1, 12, 9, 10, 3})

    def test_season_is_normalized_to_int_at_the_boundary(self):
        self.assertTrue(all(isinstance(o.identity.season, int) for o in self.owned))

    def test_no_duplicate_identities_emitted(self):
        ids = [o.identity.canonical_id for o in self.owned]
        self.assertEqual(len(ids), len(set(ids)))
        # 12 rosters x 3 seasons x 6 rounds, every asset exactly once.
        self.assertEqual(len(ids), 12 * 3 * 6)

    def test_unjoinable_traded_rows_are_skipped_not_guessed(self):
        owned = P.build_pick_ownership(
            "dynasty_main",
            range(1, 13),
            [
                {"season": "2027", "round": 1, "roster_id": 99, "owner_id": 1},
                {"season": "garbage", "round": 1, "roster_id": 2, "owner_id": 1},
                {"season": "2027", "round": None, "roster_id": 2, "owner_id": 1},
            ],
            seasons=(2027,),
            rounds=6,
        )
        moved = [o for o in owned if o.state.owner_roster_id != o.identity.origin_roster_id]
        self.assertEqual(moved, [])


class TestGenericToExactTransition(unittest.TestCase):
    """C1-ID-02's half of C1-PICK-02: the identity contract makes the
    transition a pure state change with a deterministic resolution —
    the valuation half (pricing the resolved row) stays C1-U6's."""

    def test_before_order_exists_resolution_is_generic_and_says_unknown(self):
        res = P.market_resolution(
            year=2028, round_num=1, slot=None, current_draft_year=2026, league_size=12
        )
        self.assertEqual(res.basis, "unknown_slot")
        self.assertEqual(res.ref, P.MarketPickRef(year=2028, round_num=1))
        self.assertIsNone(res.ref.slot)
        self.assertIsNone(res.ref.tier)

    def test_after_order_lands_same_identity_resolves_to_exact_slot(self):
        res = P.market_resolution(
            year=2028, round_num=1, slot=7, current_draft_year=2028, league_size=12
        )
        self.assertEqual(res.basis, "exact_slot")
        self.assertEqual(res.ref.board_row_name(), "2028 Pick 1.07")

    def test_future_year_with_known_slot_resolves_to_tier_not_slot(self):
        # The board only carries tier rows for out-years; the resolution
        # says so (basis) instead of pretending a slot row exists.
        res = P.market_resolution(
            year=2028, round_num=1, slot=2, current_draft_year=2026, league_size=12
        )
        self.assertEqual(res.basis, "tier_from_slot")
        self.assertEqual(res.ref.tier, "early")

    def test_unknown_slot_never_fabricates_a_tier_or_slot(self):
        for year in (2026, 2027, 2028, 2029):
            for cdy in (2026, 2027):
                res = P.market_resolution(year=year, round_num=3, slot=None, current_draft_year=cdy)
                self.assertEqual(res.basis, "unknown_slot")
                self.assertIsNone(res.ref.slot)
                self.assertIsNone(res.ref.tier)

    def test_slot_tier_is_league_size_aware_and_honest_about_unknown(self):
        self.assertIsNone(P.slot_tier(None))
        self.assertEqual(P.slot_tier(4, league_size=12), "early")
        # A 10-team league's slot 4 is MID under the backend rule —
        # the frontend's 12-team hardcode called it early (census §2.4).
        self.assertEqual(P.slot_tier(4, league_size=10), "mid")

    def test_resolution_is_deterministic_pure_function(self):
        a = P.market_resolution(year=2028, round_num=1, slot=7, current_draft_year=2027)
        b = P.market_resolution(year=2028, round_num=1, slot=7, current_draft_year=2027)
        self.assertEqual(a, b)


class TestLegacyLabelParsing(unittest.TestCase):
    """Every measured grammar parses to exactly what it proves."""

    @classmethod
    def setUpClass(cls):
        cls.fx = _fx()

    def test_every_real_baked_label_parses(self):
        for pd in self.fx["scraperPickDetails"]:
            parsed = P.parse_pick_label(pd["label"])
            self.assertIsNotNone(parsed, pd["label"])
            self.assertEqual(parsed.year, pd["season"])
            self.assertEqual(parsed.round_num, pd["round"])
            if pd["fromRosterId"] == pd["ownerRosterId"]:
                self.assertTrue(parsed.is_own)
            else:
                self.assertFalse(parsed.is_own)
                self.assertEqual(parsed.origin_team_name, pd["fromTeam"])

    def test_stored_trade_pick_strings_parse_with_origin_names(self):
        gave = self.fx["storedTradeWithPickStrings"]["sides"][0]["gave"]
        parsed = P.parse_pick_label("2028 Mid 2nd (from Blaine)")
        self.assertIn("2028 Mid 2nd (from Blaine)", gave)
        self.assertEqual(
            (parsed.year, parsed.round_num, parsed.tier, parsed.origin_team_name),
            (2028, 2, "mid", "Blaine"),
        )

    def test_grammar_matrix(self):
        cases = {
            "2026 Pick 1.06": (2026, 1, 6, None, "board_slot"),
            "2026 1.03": (2026, 1, 3, None, "bare_slot"),
            "2027 Early 1st": (2027, 1, None, "early", "tier"),
            "2027 1st": (2027, 1, None, None, "round_suffix"),
            "2027 R1": (2027, 1, None, None, "round_word"),
            "2027 Round 1": (2027, 1, None, None, "round_word"),
        }
        for label, (year, rnd, slot, tier, grammar) in cases.items():
            parsed = P.parse_pick_label(label)
            self.assertIsNotNone(parsed, label)
            self.assertEqual(
                (parsed.year, parsed.round_num, parsed.slot, parsed.tier, parsed.grammar),
                (year, rnd, slot, tier, grammar),
                label,
            )

    def test_player_names_and_garbage_do_not_parse(self):
        for not_a_pick in (
            "Malachi Moore",
            "Patrick Queen",
            "",
            None,
            "2027",
            "Pick 1.06",
            "Round 1",
            "20271st",
        ):
            self.assertIsNone(P.parse_pick_label(not_a_pick), not_a_pick)

    def test_a_bare_generic_label_proves_year_and_round_only(self):
        parsed = P.parse_pick_label("2027 1st")
        self.assertIsNone(parsed.slot)
        self.assertIsNone(parsed.tier)
        self.assertIsNone(parsed.is_own)
        self.assertIsNone(parsed.origin_team_name)


class TestBoardGrammarParityWithContract(unittest.TestCase):
    """The owner's board grammar is the contract's, verbatim — measured
    over the full board name space plus adversarial strings, against the
    live data_contract helpers."""

    CORPUS = (
        [f"{y} Pick {r}.{s:02d}" for y in (2026, 2027) for r in range(1, 7) for s in range(1, 13)]
        + [
            f"{y} {t} {r}{sfx}"
            for y in (2026, 2028)
            for t in ("Early", "Mid", "Late")
            for r, sfx in ((1, "st"), (2, "nd"), (3, "rd"), (4, "th"), (6, "th"))
        ]
        + [
            "2026 Pick 1.13",
            "2026 Pick 7.01",
            "2026 Pick 1.00",
            "2026 Early 7th",
            "2026 early 1ST",
            "2026 PICK 1.06",
            " 2026 Pick 1.06 ",
            "2026 Mid 1nd",
            "2026 1.06",
            "2027 1st",
            "Justin Jefferson",
            "",
            "2026 Round 1",
            "1999 Pick 1.06",
            "2026 Pick 1.6",
        ]
    )

    def test_slot_and_tier_parsers_agree_with_data_contract(self):
        from src.api import data_contract as DC

        for name in self.CORPUS:
            self.assertEqual(P.parse_board_slot_name(name), DC._parse_pick_slot(name), name)
            self.assertEqual(P.parse_board_tier_name(name), DC._parse_pick_tier(name), name)

    def test_pick_detector_and_year_extractor_agree_with_data_contract(self):
        from src.api import data_contract as DC

        detector_corpus = list(self.CORPUS) + [
            "2027 Mid 1st (from Blaine)",
            "2026 1.03 (own)",
            "pick:2027:2",
        ]
        for name in detector_corpus:
            self.assertEqual(P.is_pick_name(name), DC._is_pick_name(name), name)
            self.assertEqual(P.pick_year_from_name(name), DC._pick_year_from_name(name), name)


class TestLegacyFormatterParity(unittest.TestCase):
    """Routing the label producers through the owner changes no byte:
    parity against the LIVE legacy implementations across the input
    matrix (seasons past/current/future, slot known/unknown, missing
    fields, string/int roster keys)."""

    def test_trade_label_parity_with_live_overlay_implementation(self):
        from src.api.sleeper_overlay import _format_trade_pick_label as legacy

        rid_maps = [
            {12: "Blaine"},
            {"12": "Blaine's Bruisers"},
            {},
        ]
        slot_maps = [{}, {(2027, 12): 5}, {(2026, 12): 3}]
        picks = [
            {"season": "2027", "round": 1, "roster_id": 12},
            {"season": "2026", "round": 3, "roster_id": 12},
            {"season": "2029", "round": 6, "roster_id": 12},
            {"season": "2027", "round": 1, "origin_roster_id": 12},
            {"season": "2027", "round": 1},
            {"season": None, "round": None, "roster_id": 12},
            {"season": "bad", "round": "?", "roster_id": 12},
        ]
        for pick in picks:
            for rid_to_name in rid_maps:
                for slot_map in slot_maps:
                    for current_year in (2026, 2027):
                        for league_size in (10, 12):
                            self.assertEqual(
                                P.format_trade_pick_label(
                                    pick,
                                    rid_to_name,
                                    slot_map,
                                    current_year=current_year,
                                    league_size=league_size,
                                ),
                                legacy(
                                    pick,
                                    rid_to_name,
                                    slot_map,
                                    current_year=current_year,
                                    league_size=league_size,
                                ),
                                (pick, rid_to_name, slot_map, current_year, league_size),
                            )

    def test_overlay_roster_label_parity_with_live_implementation(self):
        from src.api.sleeper_overlay import _format_pick_label as legacy

        for season in ("2027", "2026"):
            for rnd in range(1, 7):
                for slot in (None, 1, 5, 12):
                    self.assertEqual(
                        P.format_pick_label_overlay(season, rnd, slot),
                        legacy(season, rnd, slot),
                    )

    def test_baked_label_grammar_reproduces_every_real_fixture_label(self):
        fx = _fx()
        for pd in fx["scraperPickDetails"]:
            base = P.format_pick_label_baked(
                season=pd["season"],
                round_num=pd["round"],
                slot=pd["slot"],
                current_year=2026,
                league_size=12,
            )
            self.assertEqual(base, pd["baseLabel"], pd)
            suffix = (
                "(own)" if pd["fromRosterId"] == pd["ownerRosterId"] else f"(from {pd['fromTeam']})"
            )
            self.assertEqual(f"{base} {suffix}", pd["label"], pd)


class TestPersistedIdGrades(unittest.TestCase):
    """Tagged dispatch across canonical + persisted id grades is
    unambiguous — the intel ledger's legacy generic grade cannot be
    mistaken for a league pick because a league key cannot be a year."""

    def test_intel_grade_round_trips(self):
        s = P.format_intel_pick_asset_id("2027", 2)
        self.assertEqual(s, "pick:2027:2")
        self.assertEqual(P.parse_intel_pick_asset_id(s), (2027, 2))

    def test_tagged_dispatch_across_all_grades(self):
        league_id = P.LeaguePickIdentity("dynasty_main", 2027, 1, 12).canonical_id
        market_id = P.MarketPickRef(year=2028, round_num=2).canonical_id
        self.assertEqual(P.parse_any_pick_asset_id(league_id)[0], "league")
        self.assertEqual(P.parse_any_pick_asset_id(market_id)[0], "market")
        self.assertEqual(P.parse_any_pick_asset_id("pick:2027:2"), ("intel_generic", (2027, 2)))
        self.assertIsNone(P.parse_any_pick_asset_id("player:1234"))
        self.assertIsNone(P.parse_any_pick_asset_id(""))

    def test_invalid_identity_components_are_rejected_not_normalized(self):
        with self.assertRaises(ValueError):
            P.LeaguePickIdentity("1312006700437352448", 2027, 1, 12)  # raw Sleeper id
        with self.assertRaises(ValueError):
            P.LeaguePickIdentity("dynasty_main", 1999, 1, 12)
        with self.assertRaises(ValueError):
            P.LeaguePickIdentity("dynasty_main", 2027, 0, 12)
        with self.assertRaises(ValueError):
            P.LeaguePickIdentity("dynasty_main", 2027, 1, 0)
        with self.assertRaises(ValueError):
            P.MarketPickRef(year=2027, round_num=1, slot=3, tier="mid")
        with self.assertRaises(ValueError):
            P.MarketPickRef(year=2027, round_num=1, tier="middle")


class TestNoValuationInvolvement(unittest.TestCase):
    """Identity says WHAT the asset is; valuation says what it is worth.
    The owner must be structurally unable to answer the second question."""

    def test_owner_module_carries_no_value_fields_or_reads(self):
        source = inspect.getsource(P)
        for banned in (
            "rankDerivedValue",
            "pickYearDiscount",
            "rookieKtcValue",
            "_pick_year_discount",
            "auctionDollars",
        ):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
