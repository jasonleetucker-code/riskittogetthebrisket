"""The suggestion engine sees the picks a roster holds.

Audit finding W09-F003, suggestions half.  ``analyze_roster`` looked
each roster entry up by exact lowercased name in a pool keyed by the
board's canonical name.  Picks arrive in the SOURCE's spelling —
Sleeper says "2026 1st" or "2026 1.04 (own)" where the board row is
"2026 Pick 1.04" — so every pick a roster held was silently dropped and
the analysis became player-only, for the caller's roster and for every
opponent.
"""

from __future__ import annotations

from src.trade.suggestions import PlayerAsset, _analyze_opponent_rosters, analyze_roster


def _pool() -> list[PlayerAsset]:
    return [
        PlayerAsset(name="Star WR", position="WR", display_value=7000, calibrated_value=7000),
        PlayerAsset(
            name="2026 Pick 1.06", position="PICK", display_value=4987, calibrated_value=4987
        ),
        PlayerAsset(
            name="2027 Mid 1st", position="PICK", display_value=5606, calibrated_value=5606
        ),
    ]


class TestRosterPicks:
    def test_a_sleeper_pick_label_resolves_onto_the_board(self):
        r = analyze_roster(["Star WR", "2027 1st"], _pool())
        assert [a.name for a in r.by_position.get("PICK", [])] == ["2027 Mid 1st"]

    def test_a_current_year_label_reaches_the_slot_row(self):
        r = analyze_roster(["2026 1st"], _pool())
        assert [a.name for a in r.by_position.get("PICK", [])] == ["2026 Pick 1.06"]

    def test_the_sleeper_slot_and_own_spelling_resolves(self):
        r = analyze_roster(["2026 1.06 (own)"], _pool())
        assert [a.name for a in r.by_position.get("PICK", [])] == ["2026 Pick 1.06"]

    def test_players_still_resolve_verbatim(self):
        r = analyze_roster(["Star WR"], _pool())
        assert [a.name for a in r.by_position.get("WR", [])] == ["Star WR"]

    def test_a_pick_the_pool_does_not_carry_is_simply_absent(self):
        # No board row means no asset.  Nothing is substituted for it.
        r = analyze_roster(["2029 1st"], _pool())
        assert r.by_position.get("PICK", []) == []

    def test_a_name_that_is_neither_is_still_dropped(self):
        r = analyze_roster(["Nobody At All"], _pool())
        assert all(not v for v in r.by_position.values())


class TestOpponentPicks:
    def test_an_opponents_picks_join_their_analysis(self):
        out = _analyze_opponent_rosters(
            [{"team_name": "Them", "players": ["Star WR"], "picks": ["2027 1st"]}], _pool()
        )
        assert [a.name for a in out["Them"].by_position.get("PICK", [])] == ["2027 Mid 1st"]

    def test_an_entry_with_no_picks_key_behaves_as_before(self):
        out = _analyze_opponent_rosters(
            [{"team_name": "Them", "players": ["Star WR"]}], _pool()
        )
        assert [a.name for a in out["Them"].by_position.get("WR", [])] == ["Star WR"]
        assert out["Them"].by_position.get("PICK", []) == []
