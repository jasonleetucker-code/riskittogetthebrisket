"""
Tests for src/trade/finder.py — the Trade Finder engine.

Tests the core scoring logic, candidate generation, and filtering
for board-arbitrage trades (good for me on our model, plausible
for the opponent on KTC).
"""

import pytest

from src.trade.finder import (
    Asset,
    TradeCandidate,
    build_asset_pool,
    find_trades,
    _score_trade,
    _generate_1for1,
    _generate_2for1,
    _generate_1for2,
    _deduplicate,
    _norm_pos,
    _resolve_roster,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_asset(name, model, ktc=None, pos="WR", team="NYJ", is_pick=False):
    return Asset(
        name=name,
        position=pos,
        team=team,
        model_value=model,
        ktc_value=ktc,
        is_pick=is_pick,
    )


def _make_player_data(model, ktc=None, pos="WR", team="NYJ"):
    """Build a raw player data dict matching the live payload shape."""
    d = {
        "_finalAdjusted": model,
        "_rawComposite": model,
        "_composite": model,
        "position": pos,
        "team": team,
    }
    if ktc is not None:
        d["_canonicalSiteValues"] = {"ktc": ktc}
    return d


def _make_sleeper_teams(teams_dict):
    """teams_dict: {team_name: [player_names]}"""
    return [{"name": name, "players": players} for name, players in teams_dict.items()]


# ── Position normalization ───────────────────────────────────────────────

class TestNormPos:
    def test_basic(self):
        assert _norm_pos("QB") == "QB"
        assert _norm_pos("WR") == "WR"

    def test_aliases(self):
        assert _norm_pos("DE") == "DL"
        assert _norm_pos("DT") == "DL"
        assert _norm_pos("CB") == "DB"
        assert _norm_pos("SS") == "DB"
        assert _norm_pos("OLB") == "LB"

    def test_none(self):
        assert _norm_pos(None) == ""
        assert _norm_pos("") == ""


# ── Asset construction ───────────────────────────────────────────────────

class TestBuildAssetPool:
    def test_basic_pool(self):
        players = {
            "Josh Allen": _make_player_data(9000, ktc=8500, pos="QB", team="BUF"),
            "Garrett Wilson": _make_player_data(5000, ktc=4800, pos="WR", team="NYJ"),
        }
        pool = build_asset_pool(players)
        assert len(pool) == 2
        names = {a.name for a in pool}
        assert "Josh Allen" in names
        assert "Garrett Wilson" in names

    def test_skips_zero_value(self):
        players = {
            "Nobody": _make_player_data(0),
        }
        pool = build_asset_pool(players)
        assert len(pool) == 0

    def test_ktc_from_canonical_site_values(self):
        players = {
            "Player A": {
                "_finalAdjusted": 5000,
                "_canonicalSiteValues": {"ktc": 4500},
                "position": "WR",
            },
        }
        pool = build_asset_pool(players)
        assert len(pool) == 1
        assert pool[0].ktc_value == 4500

    def test_ktc_from_direct_field(self):
        players = {
            "Player B": {
                "_finalAdjusted": 5000,
                "ktc": 4200,
                "position": "RB",
            },
        }
        pool = build_asset_pool(players)
        assert pool[0].ktc_value == 4200

    def test_pick_detection(self):
        players = {
            "2026 1.01": _make_player_data(3000, ktc=2800),
        }
        pool = build_asset_pool(players)
        assert pool[0].is_pick is True
        assert pool[0].position == "PICK"

    def test_model_value_fallback_chain(self):
        # _finalAdjusted first
        p = {"_finalAdjusted": 5000, "_rawComposite": 4000, "_composite": 3000, "position": "WR"}
        pool = build_asset_pool({"A": p})
        assert pool[0].model_value == 5000

        # _rawComposite next
        p2 = {"_rawComposite": 4000, "_composite": 3000, "position": "WR"}
        pool2 = build_asset_pool({"B": p2})
        assert pool2[0].model_value == 4000

        # _composite last
        p3 = {"_composite": 3000, "position": "WR"}
        pool3 = build_asset_pool({"C": p3})
        assert pool3[0].model_value == 3000


# ── Trade scoring ────────────────────────────────────────────────────────

class TestScoreTrade:
    def test_positive_board_arbitrage_with_ktc_appeal(self):
        """I give lower model value but higher KTC → good arbitrage."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4000)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.board_delta == 1000  # I gain 1000 on our board
        assert tc.opponent_ktc_appeal > 0  # Opponent gains on KTC
        assert tc.arbitrage_score > 0

    def test_negative_board_delta_rejected(self):
        """If I lose too much on our board, trade is rejected."""
        give = [_make_asset("A", model=5000, ktc=5000)]
        recv = [_make_asset("B", model=4500, ktc=5500)]
        tc = _score_trade(give, recv)
        # board_delta = -500, which is worse than MAX_BOARD_LOSS (-200)
        assert tc is None

    def test_opponent_extreme_ktc_loss_rejected(self):
        """If opponent loses too much on KTC, trade is rejected."""
        give = [_make_asset("A", model=3000, ktc=3000)]
        recv = [_make_asset("B", model=5000, ktc=5000)]
        tc = _score_trade(give, recv)
        # Opponent gets 3000 KTC for 5000 KTC → -40% loss → rejected
        assert tc is None

    def test_self_trade_rejected(self):
        give = [_make_asset("Same", model=5000, ktc=5000)]
        recv = [_make_asset("Same", model=5000, ktc=5000)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_empty_sides_rejected(self):
        assert _score_trade([], [_make_asset("A", 5000, 5000)]) is None
        assert _score_trade([_make_asset("A", 5000, 5000)], []) is None

    def test_no_ktc_coverage(self):
        """Trades work with no KTC but have 'none' coverage."""
        give = [_make_asset("A", model=4000, ktc=None)]
        recv = [_make_asset("B", model=5000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.ktc_coverage == "none"
        assert tc.board_delta == 1000

    def test_partial_ktc_coverage(self):
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.ktc_coverage == "partial"

    def test_junk_trade_rejected(self):
        """Both sides below junk threshold → rejected."""
        give = [_make_asset("A", model=300, ktc=300)]
        recv = [_make_asset("B", model=350, ktc=200)]
        assert _score_trade(give, recv) is None

    def test_to_dict(self):
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4000)]
        tc = _score_trade(give, recv)
        d = tc.to_dict()
        assert "give" in d
        assert "receive" in d
        assert d["boardDelta"] == 1000
        assert d["packageSize"] == "1-for-1"
        assert isinstance(d["arbitrageScore"], float)


# ── Candidate generation ─────────────────────────────────────────────────

class TestGenerate1for1:
    def test_generates_viable_trades(self):
        my = [_make_asset("Mine1", 4000, 5500), _make_asset("Mine2", 3000, 4000)]
        opp = [_make_asset("Theirs1", 5000, 4500), _make_asset("Theirs2", 4000, 3500)]
        trades = _generate_1for1(my, opp)
        assert len(trades) > 0
        for t in trades:
            assert len(t.give) == 1
            assert len(t.receive) == 1

    def test_skips_low_value(self):
        my = [_make_asset("Low", 100, 100)]
        opp = [_make_asset("Also Low", 200, 200)]
        trades = _generate_1for1(my, opp)
        assert len(trades) == 0


class TestGenerate2for1:
    def test_generates_packages(self):
        my = [
            _make_asset("A", 2500, 3500),
            _make_asset("B", 2000, 3000),
            _make_asset("C", 1500, 2000),
        ]
        opp = [_make_asset("Star", 5000, 4500)]
        trades = _generate_2for1(my, opp)
        # At least some 2-for-1 combos should be viable
        for t in trades:
            assert len(t.give) == 2
            assert len(t.receive) == 1


class TestGenerate1for2:
    def test_generates_packages(self):
        my = [_make_asset("BigPiece", 6000, 7000)]
        opp = [
            _make_asset("Part1", 3500, 3000),
            _make_asset("Part2", 3000, 2500),
        ]
        trades = _generate_1for2(my, opp)
        for t in trades:
            assert len(t.give) == 1
            assert len(t.receive) == 2


# ── Deduplication ────────────────────────────────────────────────────────

class TestDeduplicate:
    def test_removes_duplicates(self):
        a = _make_asset("A", 4000, 5000)
        b = _make_asset("B", 5000, 4000)
        tc1 = TradeCandidate(give=[a], receive=[b], arbitrage_score=10)
        tc2 = TradeCandidate(give=[a], receive=[b], arbitrage_score=10)
        result = _deduplicate([tc1, tc2])
        assert len(result) == 1

    def test_keeps_different_trades(self):
        a = _make_asset("A", 4000, 5000)
        b = _make_asset("B", 5000, 4000)
        c = _make_asset("C", 3000, 3500)
        tc1 = TradeCandidate(give=[a], receive=[b], arbitrage_score=10)
        tc2 = TradeCandidate(give=[a], receive=[c], arbitrage_score=8)
        result = _deduplicate([tc1, tc2])
        assert len(result) == 2


# ── Roster resolution ────────────────────────────────────────────────────

class TestResolveRoster:
    def test_resolves_team(self):
        pool_by_name = {
            "P1": _make_asset("P1", 5000, 5000),
            "P2": _make_asset("P2", 3000, 3000),
        }
        teams = [{"name": "Team A", "players": ["P1", "P2"]}]
        result = _resolve_roster("Team A", teams, pool_by_name)
        assert len(result) == 2

    def test_returns_empty_for_unknown_team(self):
        result = _resolve_roster("Unknown", [], {})
        assert result == []

    def test_case_insensitive_fallback(self):
        pool_by_name = {"Josh Allen": _make_asset("Josh Allen", 9000, 8500)}
        teams = [{"name": "T", "players": ["josh allen"]}]
        result = _resolve_roster("T", teams, pool_by_name)
        assert len(result) == 1


# ── End-to-end find_trades ───────────────────────────────────────────────

class TestFindTrades:
    def _sample_players(self):
        return {
            "Star QB": _make_player_data(9000, ktc=8000, pos="QB"),
            "Solid RB": _make_player_data(6000, ktc=7000, pos="RB"),
            "Value WR": _make_player_data(5000, ktc=4000, pos="WR"),
            "Depth TE": _make_player_data(2500, ktc=3500, pos="TE"),
            "Opp Star": _make_player_data(8000, ktc=7500, pos="WR"),
            "Opp Depth": _make_player_data(3000, ktc=4500, pos="RB"),
            "Opp Value": _make_player_data(4500, ktc=3800, pos="QB"),
            "Opp Piece": _make_player_data(2000, ktc=3000, pos="TE"),
        }

    def _sample_teams(self):
        return [
            {"name": "My Team", "players": ["Star QB", "Solid RB", "Value WR", "Depth TE"]},
            {"name": "Rival", "players": ["Opp Star", "Opp Depth", "Opp Value", "Opp Piece"]},
        ]

    def test_returns_structure(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        assert "trades" in result
        assert "metadata" in result
        assert isinstance(result["trades"], list)
        assert result["metadata"]["myTeam"] == "My Team"

    def test_no_self_trades(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        for t in result["trades"]:
            give_names = {a["name"] for a in t["give"]}
            recv_names = {a["name"] for a in t["receive"]}
            assert not (give_names & recv_names), "Self-trade detected"

    def test_board_delta_always_positive(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        for t in result["trades"]:
            assert t["boardDelta"] > 0, f"Non-positive board delta: {t}"

    def test_unknown_team_returns_error(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="Nonexistent",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        assert "error" in result

    def test_multiple_opponents(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        assert result["metadata"]["opponentsAnalyzed"] >= 1

    def test_deterministic(self):
        """Same inputs produce same outputs."""
        p = self._sample_players()
        t = self._sample_teams()
        r1 = find_trades(p, "My Team", ["Rival"], t)
        r2 = find_trades(p, "My Team", ["Rival"], t)
        assert r1["trades"] == r2["trades"]

    def test_arbitrage_score_descending(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        scores = [t["arbitrageScore"] for t in result["trades"]]
        assert scores == sorted(scores, reverse=True)

    def test_ktc_coverage_reported(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["Rival"],
            sleeper_teams=self._sample_teams(),
        )
        assert "ktcCoveragePercent" in result["metadata"]

    def test_skips_self_as_opponent(self):
        result = find_trades(
            players=self._sample_players(),
            my_team="My Team",
            opponent_teams=["My Team"],
            sleeper_teams=self._sample_teams(),
        )
        assert result["metadata"]["opponentsAnalyzed"] == 0
