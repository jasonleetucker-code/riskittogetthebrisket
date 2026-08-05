"""One Python pick resolver, and it behaves like the JS one.

``src/utils/pick_labels`` is the Python port of
``frontend/lib/trade-logic.js::resolvePickRow``.  Before it existed the
server-side trade engines looked a Sleeper pick label up verbatim in a
board keyed by canonical name, which never matched — audit finding
W09-F003.

These tests pin the two rules that make the JS resolver correct, both
of which are easy to "simplify" away:

* the alias map is applied to the INPUT label only, never to a
  synthesized candidate;
* a suppressed generic-tier row is skipped so the walk reaches the
  slot-specific sibling.
"""

from __future__ import annotations

from src.utils.pick_labels import (
    parse_pick_token,
    pick_anchor_key,
    pick_lookup_candidates,
    resolve_pick_name,
)

# The live board's pick row names, reduced to what these cases need.
BOARD = [
    "2026 Early 1st",
    "2026 Mid 1st",
    "2026 Late 1st",
    "2026 Pick 1.02",
    "2026 Pick 1.04",
    "2026 Pick 1.06",
    "2027 Mid 1st",
    "2027 Early 1st",
]

# The contract's real alias shape: generic tier -> current-year slot.
ALIASES = {
    "2026 Early 1st": "2026 Pick 1.02",
    "2026 Mid 1st": "2026 Pick 1.06",
}

# The generic current-year rows the pipeline cleared of ranking fields.
SUPPRESSED = ["2026 Early 1st", "2026 Mid 1st", "2026 Late 1st"]


class TestParse:
    def test_slot_form(self):
        assert parse_pick_token("2026 1.04") == {
            "year": "2026",
            "round": "1st",
            "tier": "early",
            "slot": 4,
        }

    def test_tier_form(self):
        assert parse_pick_token("2027 Mid 2nd") == {
            "year": "2027",
            "round": "2nd",
            "tier": "mid",
            "slot": None,
        }

    def test_round_only_form(self):
        assert parse_pick_token("2027 1st") == {
            "year": "2027",
            "round": "1st",
            "tier": None,
            "slot": None,
        }

    def test_rounds_five_and_six_parse(self):
        # Every round-word map in the tree covers 1-6; a 5th/6th that
        # fails to parse is what W13-F004 was.
        assert parse_pick_token("2026 Mid 6th")["round"] == "6th"

    def test_non_pick_is_none(self):
        assert parse_pick_token("Bijan Robinson") is None


class TestAnchorKey:
    def test_slot_row_drops_the_pick_token(self):
        assert pick_anchor_key("2026 Pick 1.01") == "2026 1.01"

    def test_tier_row_is_its_own_key(self):
        assert pick_anchor_key("2027 Mid 1st") == "2027 Mid 1st"


class TestCandidates:
    def test_sleeper_annotation_is_stripped(self):
        assert "2026 1.04" in pick_lookup_candidates("2026 1.04 (own)")

    def test_slot_input_offers_the_canonical_slot_row(self):
        assert "2026 pick 1.04" in pick_lookup_candidates("2026 1.04")

    def test_round_only_input_falls_back_to_the_tier_centre(self):
        cands = pick_lookup_candidates("2027 1st")
        assert "2027 mid 1st" in cands
        assert "2027 pick 1.06" in cands


class TestResolve:
    def test_round_only_label_resolves_to_the_priced_future_tier_row(self):
        # Sleeper's /traded_picks emits "2027 1st"; the board names it
        # "2027 Mid 1st".
        assert resolve_pick_name("2027 1st", BOARD) == "2027 Mid 1st"

    def test_current_year_round_only_label_reaches_a_slot_row(self):
        # The current-year board is priced on the slot rows, and the
        # generic tier rows are suppressed.
        assert (
            resolve_pick_name("2026 1st", BOARD, ALIASES, suppressed=SUPPRESSED)
            == "2026 Pick 1.06"
        )

    def test_alias_redirects_a_generic_tier_label_onto_its_slot(self):
        assert (
            resolve_pick_name("2026 Early 1st", BOARD, ALIASES, suppressed=SUPPRESSED)
            == "2026 Pick 1.02"
        )

    def test_alias_is_not_applied_to_a_synthesized_candidate(self):
        # "2026 1.04" derives the tier candidate "2026 Early 1st", which
        # the alias map would rewrite to the tier-CENTRE slot 1.02.
        # Applying aliases to derived candidates therefore misroutes
        # every slot pick; the resolver must land on 1.04 itself.
        assert (
            resolve_pick_name("2026 1.04", BOARD, ALIASES, suppressed=SUPPRESSED)
            == "2026 Pick 1.04"
        )

    def test_suppressed_row_is_skipped_without_an_alias_map(self):
        # Robustness against a stale contract that ships no aliases.
        assert (
            resolve_pick_name("2026 Early 1st", BOARD, None, suppressed=SUPPRESSED)
            == "2026 Pick 1.02"
        )

    def test_sleeper_own_suffix_resolves(self):
        assert resolve_pick_name("2027 1st (own)", BOARD) == "2027 Mid 1st"

    def test_a_pick_the_board_does_not_carry_stays_unresolved(self):
        # No board row means no value to show.  Inventing one here is
        # the failure this codebase already had with a flat
        # 7000/4000/2000/1200 table.
        assert resolve_pick_name("2029 Early 1st", BOARD, ALIASES) is None

    def test_a_player_name_never_resolves_as_a_pick(self):
        assert resolve_pick_name("Bijan Robinson", BOARD) is None
