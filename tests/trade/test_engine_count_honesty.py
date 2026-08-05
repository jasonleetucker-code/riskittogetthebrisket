"""Two counts that were being reported as one.

Audit findings W09-F010 and W09-F013 (root cause R7).

* `finder.metadata.myRosterSize` was `len(_resolve_roster(...))`, taken
  against the ALREADY gated pool — measured live, 34 for a 57-man roster
  and 12 for a 44-man one.  Nothing else in the payload carried the true
  roster size, so the engine's coverage ratio could not be recovered
  from its own response.

* `suggestions.totalSuggestions` counted framings, not ideas: sell-high
  and buy-low search the same surplus/need axes from opposite
  directions, so the same (give, receive) pair could be emitted by both.
  One live feed reported 9 suggestions containing 7 distinct pairs.
"""

from __future__ import annotations

from src.trade.finder import _roster_entry_count
from src.trade.suggestions import PlayerAsset, TradeSuggestion, _apply_quality_filters

_TEAMS = [
    {
        "name": "Mine",
        "ownerId": "me",
        "players": [f"P{i}" for i in range(50)],
        "picks": ["2026 1st", "2027 1st"],
    },
    {"name": "Theirs", "ownerId": "them", "players": ["Q1"], "picks": []},
]


class TestRosterSizeIsTheRoster:
    def test_it_counts_players_and_picks_from_sleeper(self):
        assert _roster_entry_count("Mine", _TEAMS) == 52

    def test_a_team_with_no_picks_key_still_counts(self):
        assert _roster_entry_count("Theirs", _TEAMS) == 1

    def test_an_unknown_team_is_zero_not_an_error(self):
        assert _roster_entry_count("Nobody", _TEAMS) == 0


def _asset(name: str, value: int = 5000, position: str = "WR") -> PlayerAsset:
    return PlayerAsset(
        name=name,
        position=position,
        display_value=value,
        calibrated_value=value,
    )


def _sugg(kind: str, give: str, receive: str, rationale: str) -> TradeSuggestion:
    return TradeSuggestion(
        type=kind,
        # Different positions and a wide gap, so the same-tier-swap and
        # near-miss filters above this one do not eat the fixture.
        give=[_asset(give)],
        receive=[_asset(receive, 8000, position="RB")],
        give_total=5000,
        receive_total=8000,
        gap=3000,
        fairness="even",
        rationale=rationale,
        why_this_helps="",
        confidence="high",
        strategy="neutral",
    )


class TestOneIdeaCountsOnce:
    def test_the_same_pair_in_two_categories_survives_once(self):
        cats = {
            "sell_high": [_sugg("sell_high", "Mine", "Theirs", "you have surplus here")],
            "buy_low": [_sugg("buy_low", "Mine", "Theirs", "they are cheap there")],
            "consolidation": [],
            "positional_upgrade": [],
        }
        out = _apply_quality_filters(cats)
        total = sum(len(v) for v in out.values())
        assert total == 1
        assert len(out["sell_high"]) == 1
        assert out["buy_low"] == []

    def test_the_other_framing_is_carried_not_discarded(self):
        """Both readings are true of that trade; only the double count is wrong."""
        cats = {
            "sell_high": [_sugg("sell_high", "Mine", "Theirs", "you have surplus here")],
            "buy_low": [_sugg("buy_low", "Mine", "Theirs", "they are cheap there")],
            "consolidation": [],
            "positional_upgrade": [],
        }
        out = _apply_quality_filters(cats)
        kept = out["sell_high"][0]
        assert kept.__dict__["also_categories"] == ["buy_low"]
        assert kept.__dict__["alternate_rationales"] == ["they are cheap there"]

    def test_distinct_pairs_are_untouched(self):
        cats = {
            "sell_high": [_sugg("sell_high", "MineA", "TheirsA", "a")],
            "buy_low": [_sugg("buy_low", "MineB", "TheirsB", "b")],
            "consolidation": [],
            "positional_upgrade": [],
        }
        out = _apply_quality_filters(cats)
        assert sum(len(v) for v in out.values()) == 2
        assert "also_categories" not in out["sell_high"][0].__dict__
