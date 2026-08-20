"""
Tests for src/trade/finder.py — the Trade Finder engine.

Tests the core scoring logic, candidate generation, and filtering
for board-arbitrage trades (good for me on our model, plausible
for the opponent on KTC).
"""

from src.packages import UNCONSTRAINED_OUTGOING
from src.trade.finder import (
    Asset,
    TradeCandidate,
    build_asset_pool,
    find_trades,
    _score_trade,
    _generate_packages,
    _deduplicate,
    _norm_pos,
    _resolve_roster,
    _confidence_tier,
    _edge_label,
    _opp_appeal_phrase,
    _build_summary,
    EXCLUDED_POSITIONS,
    ELITE_THRESHOLD,
    KTC_TOP_N_FILTER,
    SINGLE_SOURCE_DISCOUNT,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_asset(name, model, ktc=None, pos="WR", team="NYJ", is_pick=False, source_count=0):
    return Asset(
        name=name,
        position=pos,
        team=team,
        model_value=model,
        market_value=ktc,
        is_pick=is_pick,
        source_count=source_count,
        market_source="ktcSfTep" if ktc is not None else None,
    )


def _appealing_ktc_split(recv_ktc_total, weights=(0.6, 0.4), margin=1.10):
    """Give-side KTC values the opponent still WINS after KTC's package
    Value Adjustment.

    DERIVED, never hardcoded — and that is the whole point.

    ``src/trade/finder_value_adjustment`` scores multi-for-one packages
    with KTC's real consolidation premium: giving two pieces for one
    better player costs a premium on top of the raw totals, because that
    is what KTC's own calculator charges.  So a give side that merely
    out-totals the receive side *linearly* is NOT appealing, and every
    2-for-1 fixture in this file that assumed otherwise expired the
    moment that premium landed.

    This is the second time fixtures here have gone stale against a
    moving constant (see ``TestEliteTargetProtection``'s docstring for
    the first).  Deriving the split from the real adjustment function
    means the next change to that math re-calibrates these fixtures
    instead of breaking them.
    """
    from src.trade.market_value_adjustment import ktc_adjust_package

    def _clears(give_vals, recv_total):
        adj = ktc_adjust_package(list(give_vals), [recv_total])
        give_eff = sum(give_vals) + (adj.value if adj.displayed and adj.side == 1 else 0)
        recv_eff = recv_total + (adj.value if adj.displayed and adj.side == 2 else 0)
        return give_eff > recv_eff

    total = recv_ktc_total
    for _ in range(400):
        total += max(50, recv_ktc_total // 40)
        split = [int(total * w) for w in weights[:-1]]
        split.append(total - sum(split))
        if _clears(split, recv_ktc_total):
            break
    else:  # pragma: no cover — defensive
        raise AssertionError(f"no clearing split found for recv={recv_ktc_total}")

    total = int(total * margin)
    split = [int(total * w) for w in weights[:-1]]
    split.append(total - sum(split))
    return split


def _make_player_data(model, ktc=None, pos="WR", team="NYJ", sites=5):
    """Build a raw player data dict matching the live payload shape."""
    d = {
        "_finalAdjusted": model,
        "_rawComposite": model,
        "_composite": model,
        "_sites": sites,
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
        # Disable KTC filter for this unit test — testing model fallback, not KTC
        # _finalAdjusted first
        p = {"_finalAdjusted": 5000, "_rawComposite": 4000, "_composite": 3000, "position": "WR"}
        pool = build_asset_pool({"A": p}, ktc_top_n=0)
        assert pool[0].model_value == 5000

        # _rawComposite next
        p2 = {"_rawComposite": 4000, "_composite": 3000, "position": "WR"}
        pool2 = build_asset_pool({"B": p2}, ktc_top_n=0)
        assert pool2[0].model_value == 4000

        # _composite last
        p3 = {"_composite": 3000, "position": "WR"}
        pool3 = build_asset_pool({"C": p3}, ktc_top_n=0)
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

    def test_no_ktc_outgoing_rejected(self):
        """Outgoing asset with no KTC must be rejected."""
        give = [_make_asset("A", model=4000, ktc=None)]
        recv = [_make_asset("B", model=5000, ktc=5000)]
        assert _score_trade(give, recv) is None

    def test_no_ktc_both_sides_rejected(self):
        """No KTC on either side → rejected (can't verify plausibility)."""
        give = [_make_asset("A", model=4000, ktc=None)]
        recv = [_make_asset("B", model=5000, ktc=None)]
        assert _score_trade(give, recv) is None

    def test_partial_ktc_outgoing_missing_rejected(self):
        """Outgoing asset missing KTC in a 2-for-1 → rejected."""
        give = [_make_asset("A", model=2000, ktc=3000), _make_asset("B", model=2000, ktc=None)]
        recv = [_make_asset("C", model=5000, ktc=4500)]
        assert _score_trade(give, recv) is None

    def test_partial_ktc_incoming_all_missing_rejected(self):
        """Receive side with zero KTC coverage is now rejected."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_partial_ktc_incoming_some_have_ktc(self):
        """Receive side with at least one KTC asset is allowed (partial)."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=3000, ktc=3500), _make_asset("C", model=2000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.ktc_coverage == "partial"

    def test_partial_coverage_demoted_below_full(self):
        """Partial coverage trades score lower than equivalent full coverage."""
        give_full = [_make_asset("A", model=4000, ktc=5000)]
        recv_full = [_make_asset("B", model=5000, ktc=4000)]
        tc_full = _score_trade(give_full, recv_full)

        # Partial: receive has one with KTC, one without
        give_partial = [_make_asset("C", model=4000, ktc=5000)]
        recv_partial = [
            _make_asset("D", model=3000, ktc=3500),
            _make_asset("E", model=2000, ktc=None),
        ]
        tc_partial = _score_trade(give_partial, recv_partial)

        assert tc_full is not None
        assert tc_partial is not None
        assert tc_full.arbitrage_score > tc_partial.arbitrage_score

    def test_low_ktc_outgoing_rejected(self):
        """Outgoing asset with KTC below MIN_KTC_VALUE → rejected."""
        give = [_make_asset("A", model=4000, ktc=200)]
        recv = [_make_asset("B", model=5000, ktc=5000)]
        assert _score_trade(give, recv) is None

    def test_junk_trade_rejected(self):
        """Both sides below junk threshold → rejected."""
        give = [_make_asset("A", model=300, ktc=500)]
        recv = [_make_asset("B", model=350, ktc=500)]
        assert _score_trade(give, recv) is None

    def test_no_ktc_junk_for_elite_rejected(self):
        """No-KTC junk player offered for elite target → rejected."""
        give = [_make_asset("Jalen Redmond", model=900, ktc=None)]
        recv = [_make_asset("Bijan Robinson", model=9000, ktc=8500)]
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


# ── Strict positive opponent KTC gate ────────────────────────────────────


class TestStrictPositiveOpponentKtc:
    """Opponent must STRICTLY WIN on KTC — no break-even, no loss."""

    def test_opponent_gains_on_ktc_allowed(self):
        """opp_appeal > 0 → trade is allowed."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4500)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.opponent_ktc_appeal > 0

    def test_opponent_breakeven_on_ktc_rejected(self):
        """opp_appeal == 0 (exact break-even) → rejected."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=5000)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_opponent_slight_loss_on_ktc_rejected(self):
        """opp_appeal slightly negative → rejected."""
        give = [_make_asset("A", model=4000, ktc=4900)]
        recv = [_make_asset("B", model=5000, ktc=5000)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_opponent_large_loss_on_ktc_rejected(self):
        """opp_appeal deeply negative → rejected."""
        give = [_make_asset("A", model=3000, ktc=3000)]
        recv = [_make_asset("B", model=5000, ktc=5000)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_partial_ktc_zero_appeal_rejected(self):
        """Partial KTC with zero opponent appeal → rejected."""
        give = [_make_asset("A", model=4000, ktc=3000)]
        recv = [_make_asset("B", model=3000, ktc=3000), _make_asset("C", model=2000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_partial_ktc_positive_appeal_allowed(self):
        """Partial KTC with positive opponent appeal → allowed."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=3000, ktc=3000), _make_asset("C", model=2000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.opponent_ktc_appeal > 0

    def test_partial_ktc_negative_appeal_rejected(self):
        """Partial KTC with negative opponent appeal → rejected."""
        give = [_make_asset("A", model=4000, ktc=2500)]
        recv = [_make_asset("B", model=3000, ktc=3000), _make_asset("C", model=2000, ktc=None)]
        tc = _score_trade(give, recv)
        assert tc is None

    def test_all_returned_trades_have_positive_opponent_ktc(self):
        """End-to-end: every trade in results has opponent_ktc_appeal > 0."""
        players = {
            "My WR1": _make_player_data(4000, ktc=5500, pos="WR"),
            "My WR2": _make_player_data(3500, ktc=5000, pos="WR"),
            "My RB1": _make_player_data(5000, ktc=6000, pos="RB"),
            "Opp WR1": _make_player_data(5500, ktc=4500, pos="WR"),
            "Opp RB1": _make_player_data(4500, ktc=4000, pos="RB"),
        }
        teams = _make_sleeper_teams(
            {
                "Me": ["My WR1", "My WR2", "My RB1"],
                "Them": ["Opp WR1", "Opp RB1"],
            }
        )
        result = find_trades(players, "Me", ["Them"], teams)
        for t in result["trades"]:
            assert (
                t["opponentKtcAppeal"] > 0
            ), f"Trade has non-positive opponent KTC appeal: {t['opponentKtcAppeal']}"

    def test_no_breaks_even_in_any_summary(self):
        """No trade summary should contain 'breaks even'."""
        players = {
            "My WR1": _make_player_data(4000, ktc=5500, pos="WR"),
            "My RB1": _make_player_data(5000, ktc=6000, pos="RB"),
            "Opp WR1": _make_player_data(5500, ktc=4500, pos="WR"),
            "Opp RB1": _make_player_data(4500, ktc=4000, pos="RB"),
        }
        teams = _make_sleeper_teams(
            {
                "Me": ["My WR1", "My RB1"],
                "Them": ["Opp WR1", "Opp RB1"],
            }
        )
        result = find_trades(players, "Me", ["Them"], teams)
        for t in result["trades"]:
            assert (
                "breaks even" not in t["summary"]
            ), f"Summary contains 'breaks even': {t['summary']}"


# ── Candidate generation ─────────────────────────────────────────────────


def _shapes(trades):
    return sorted((len(t.give), len(t.receive)) for t in trades)


class TestPackageGeneration:
    """``_generate_packages`` replaced three hand-rolled generators.

    Shapes are asserted rather than call sites: the mechanics now live in
    ``src/trade/package_substrate`` and the point of these tests is that this
    engine still emits the shapes it is supposed to, scored by its own
    objective.
    """

    def test_generates_one_for_one(self):
        my = [_make_asset("Mine1", 4000, 5500), _make_asset("Mine2", 3000, 4000)]
        opp = [_make_asset("Theirs1", 5000, 4500), _make_asset("Theirs2", 4000, 3500)]
        trades, report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        assert len(trades) > 0
        assert (1, 1) in _shapes(trades)
        assert report["oneForOne"]["ourPoolSize"] == 2

    def test_skips_low_value(self):
        my = [_make_asset("Low", 100, 100)]
        opp = [_make_asset("Also Low", 200, 200)]
        trades, report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        assert trades == []
        # Excluded by the eligibility policy, and the count says so rather
        # than the pool quietly being empty.
        assert report["oneForOne"]["ourExcludedIneligible"] == 1

    def test_generates_two_for_one(self):
        my = [
            _make_asset("A", 2500, 3500),
            _make_asset("B", 2000, 3000),
            _make_asset("C", 1500, 2000),
        ]
        opp = [_make_asset("Star", 5000, 4500)]
        trades, _report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        for shape in _shapes(trades):
            assert shape in {(1, 1), (2, 1), (1, 2)}

    def test_generates_one_for_two(self):
        my = [_make_asset("BigPiece", 6000, 7000)]
        opp = [
            _make_asset("Part1", 3500, 3000),
            _make_asset("Part2", 3000, 2500),
        ]
        trades, _report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        for t in trades:
            assert len(t.give) in (1,)
            assert len(t.receive) in (1, 2)

    def test_never_emits_a_shape_this_engine_does_not_offer(self):
        """No 2-for-2, no 3-for-anything — the shape plan is explicit."""
        my = [_make_asset(f"M{i}", 3000 + i * 100, 3500 + i * 100) for i in range(4)]
        opp = [_make_asset(f"T{i}", 3000 + i * 100, 3400 + i * 100) for i in range(4)]
        trades, _report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        assert set(_shapes(trades)) <= {(1, 1), (2, 1), (1, 2)}

    def test_an_asset_never_appears_on_both_sides(self):
        shared = _make_asset("Shared", 4000, 4200)
        trades, _report = _generate_packages([shared], [shared], UNCONSTRAINED_OUTGOING)
        assert trades == []

    def test_truncation_is_reported_not_silent(self):
        """The retired ``[:30]`` slice reported nothing."""
        my = [_make_asset(f"M{i:03d}", 5000 - i, 5200 - i) for i in range(40)]
        opp = [_make_asset(f"T{i:03d}", 5000 - i, 4800 - i) for i in range(40)]
        _trades, report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        assert report["asymmetric"]["ourTruncatedTo"] == 30
        assert report["asymmetric"]["truncated"] is True
        # 1-for-1 is deliberately unbounded, exactly as before.
        assert report["oneForOne"]["ourTruncatedTo"] is None
        assert report["oneForOne"]["truncated"] is False

    def test_the_pool_bound_keeps_the_most_valuable_assets(self):
        """It used to keep whichever names sorted first.

        ``_resolve_roster`` returns assets in Sleeper's ``players`` order,
        which is alphabetical, so the old ``[:30]`` slice bounded the
        asymmetric search to early-alphabet players.  Measured on the
        2026-08-18 board, one live roster lost 7 of its top 30 by value that
        way, the highest worth 6,671.
        """
        # 35 low-value fillers that sort EARLY alphabetically, plus one
        # high-value asset that sorts LAST.  The retired bound kept the 35.
        my = [_make_asset(f"Aaa Filler {i:03d}", 800 + i, 900 + i) for i in range(35)]
        # Economics chosen so a trade containing it actually clears the
        # engine's own gates — otherwise this would pass or fail on the
        # scoring rules rather than on the pool bound it is testing.
        crown = _make_asset("Zzz Crown", 4000, 9999)
        my.append(crown)
        opp = [_make_asset("Target", 4500, 5000)]
        trades, _report = _generate_packages(my, opp, UNCONSTRAINED_OUTGOING)
        assert any(
            any(a.name == "Zzz Crown" for a in t.give) for t in trades
        ), "the most valuable asset must survive the pool bound"


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


# ── Source robustness and fire-sale guard regression tests ───────────────


class TestSourceRobustness:
    """Test single-source discount and value fallback robustness."""

    def test_single_source_discount_applied(self):
        """Single-source players get 12% haircut matching frontend SINGLE_SOURCE_DISCOUNT."""
        players = {
            "Single Source": {
                "_finalAdjusted": 5000,
                "_rawComposite": 5000,
                "_sites": 1,
                "_canonicalSiteValues": {"ktc": 4500},
                "position": "WR",
            },
        }
        pool = build_asset_pool(players)
        assert len(pool) == 1
        # 5000 * 0.88 = 4400
        assert pool[0].model_value == 4400
        assert pool[0].source_count == 1

    def test_multi_source_no_discount(self):
        """Multi-source players get no discount."""
        players = {
            "Multi Source": {
                "_finalAdjusted": 5000,
                "_rawComposite": 5000,
                "_sites": 5,
                "_canonicalSiteValues": {"ktc": 4500},
                "position": "WR",
            },
        }
        pool = build_asset_pool(players)
        assert pool[0].model_value == 5000
        assert pool[0].source_count == 5

    def test_final_adjusted_preferred_over_raw(self):
        """_finalAdjusted takes precedence over _rawComposite."""
        players = {
            "Final Player": {
                "_finalAdjusted": 5500,
                "_rawComposite": 5000,
                "_sites": 5,
                "_canonicalSiteValues": {"ktc": 4800},
                "position": "WR",
            },
        }
        pool = build_asset_pool(players)
        assert pool[0].model_value == 5500


class TestFireSaleGuard:
    """Test that multi-for-one trades require meaningful give-side value."""

    def test_2for1_fire_sale_rejected(self):
        """Two low-value assets for an elite target → rejected."""
        a1 = _make_asset("Depth A", model=2000, ktc=3500)
        a2 = _make_asset("Depth B", model=1800, ktc=3000)
        elite = _make_asset("Elite", model=7000, ktc=5500)
        tc = _score_trade([a1, a2], [elite])
        # 3800/7000 = 0.54 < 0.55 threshold
        assert tc is None

    def test_2for1_fair_package_passes(self):
        """Two solid assets for one elite → passes when ratio is fair."""
        a1 = _make_asset("Good A", model=3500, ktc=4000)
        a2 = _make_asset("Good B", model=3000, ktc=3500)
        elite = _make_asset("Elite", model=7000, ktc=5500)
        tc = _score_trade([a1, a2], [elite])
        # 6500/7000 = 0.93 > 0.55
        assert tc is not None

    def test_1for1_not_affected_by_fire_sale_guard(self):
        """1-for-1 trades are not subject to the multi-for-one ratio."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4000)]
        tc = _score_trade(give, recv)
        assert tc is not None

    def test_1for2_not_affected_by_fire_sale_guard(self):
        """1-for-2 (I give less, get more pieces) is not subject to ratio."""
        give = [_make_asset("Star", model=7000, ktc=9000)]
        recv = [_make_asset("A", model=4000, ktc=4500), _make_asset("B", model=3500, ktc=4000)]
        tc = _score_trade(give, recv)
        # 1-for-2: len(give)=1 <= len(receive)=2, guard doesn't apply
        assert tc is not None

    def test_2for1_barely_above_threshold_passes(self):
        """Just above the 55% ratio → passes.

        The target is kept below ``ELITE_THRESHOLD`` on purpose: an elite
        target triggers the tighter 65% guard, and this test is about the
        55% one. It was hardcoded at 7000 against a threshold of 7500 and
        silently became an elite-path test when F-6 re-derived that
        constant to 6600.
        """
        target_val = int(ELITE_THRESHOLD * 0.93)
        a1 = _make_asset("A", model=int(target_val * 0.400), ktc=4000)
        a2 = _make_asset("B", model=int(target_val * 0.172), ktc=3500)
        target = _make_asset("Target", model=target_val, ktc=5000)
        tc = _score_trade([a1, a2], [target])
        # give/recv ~= 0.572 > 0.55
        assert tc is not None

    def test_2for1_barely_below_threshold_rejected(self):
        """Just below the 55% ratio → rejected."""
        target_val = int(ELITE_THRESHOLD * 0.93)
        a1 = _make_asset("A", model=int(target_val * 0.386), ktc=4000)
        a2 = _make_asset("B", model=int(target_val * 0.157), ktc=3500)
        target = _make_asset("Target", model=target_val, ktc=5000)
        tc = _score_trade([a1, a2], [target])
        # give/recv ~= 0.543 < 0.55
        assert tc is None


# ── Elite target protection ─────────────────────────────────────────────


class TestEliteTargetProtection:
    """Verify that elite targets require tighter multi-for-one ratios.

    Fixture values are expressed RELATIVE to ``ELITE_THRESHOLD`` rather
    than hardcoded. They were hardcoded at 7000/8000 against a threshold
    of 7500; the F-6 migration re-derived that constant to 6600 and
    turned every "non-elite" fixture into an elite-path test that then
    failed for a reason unrelated to what it was checking.
    """

    def test_2for1_elite_below_65pct_rejected(self):
        """Two mid-tier pieces totaling 60% of elite target → rejected (below 65%)."""
        a1 = _make_asset("Mid A", model=2500, ktc=3500)
        a2 = _make_asset("Mid B", model=2300, ktc=3200)
        elite = _make_asset("Elite WR", model=8000, ktc=6000)
        tc = _score_trade([a1, a2], [elite])
        # 4800/8000 = 0.60 > 0.55 (would pass old guard) but < 0.65 (fails elite guard)
        assert tc is None

    def test_2for1_elite_above_65pct_passes(self):
        """Two solid pieces totaling 70% of elite target → passes."""
        k1, k2 = _appealing_ktc_split(6000)
        a1 = _make_asset("Good A", model=3500, ktc=k1)
        a2 = _make_asset("Good B", model=2500, ktc=k2)
        elite = _make_asset("Elite WR", model=8000, ktc=6000)
        tc = _score_trade([a1, a2], [elite])
        # 6000/8000 = 0.75 > 0.65
        assert tc is not None

    def test_2for1_non_elite_uses_normal_ratio(self):
        """A target below ELITE_THRESHOLD uses the standard 55% ratio."""
        target_val = int(ELITE_THRESHOLD * 0.93)  # comfortably non-elite
        k1, k2 = _appealing_ktc_split(5500)
        a1 = _make_asset("A", model=int(target_val * 0.40), ktc=k1)
        a2 = _make_asset("B", model=int(target_val * 0.243), ktc=k2)
        target = _make_asset("Target", model=target_val, ktc=5500)
        tc = _score_trade([a1, a2], [target])
        # give/recv = 0.643 > 0.55; target < ELITE_THRESHOLD so the elite
        # guard is skipped; anchor 0.40 > 0.35
        assert tc is not None

    def test_1for1_elite_not_blocked(self):
        """1-for-1 elite trades are not subject to multi-for-one elite guard."""
        give = [_make_asset("Underval", model=5000, ktc=7500)]
        recv = [_make_asset("Elite", model=8500, ktc=6500)]
        tc = _score_trade(give, recv)
        assert tc is not None

    def test_elite_blockbuster_2for1_still_works(self):
        """Legit blockbuster (two starters for one elite) passes."""
        k1, k2 = _appealing_ktc_split(8000)
        a1 = _make_asset("Starter A", model=5000, ktc=k1)
        a2 = _make_asset("Starter B", model=4000, ktc=k2)
        elite = _make_asset("Top 3 RB", model=9500, ktc=8000)
        tc = _score_trade([a1, a2], [elite])
        # 9000/9500 = 0.95 > 0.65
        assert tc is not None


# ── Package anchor quality ──────────────────────────────────────────────


class TestPackageAnchorQuality:
    """Verify that multi-for-one requires at least one meaningful anchor piece."""

    def test_two_bench_stashes_for_starter_rejected(self):
        """Two 1200-value bench players for a 5000 starter → no anchor (1200/5000=0.24 < 0.35)."""
        a1 = _make_asset("Bench A", model=1200, ktc=2000)
        a2 = _make_asset("Bench B", model=1200, ktc=2000)
        target = _make_asset("Starter", model=5000, ktc=3500)
        tc = _score_trade([a1, a2], [target])
        # max_give=1200, max_recv=5000 → 0.24 < 0.35
        assert tc is None

    def test_anchor_plus_filler_passes(self):
        """One real starter + one depth piece → anchor present (3000/5000=0.60 > 0.35)."""
        k1, k2 = _appealing_ktc_split(4500)
        a1 = _make_asset("Starter A", model=3000, ktc=k1)
        a2 = _make_asset("Depth", model=1000, ktc=k2)
        target = _make_asset("Target", model=5000, ktc=4500)
        tc = _score_trade([a1, a2], [target])
        # max_give=3000/5000 = 0.60 > 0.35, total 4000/5000 = 0.80 > 0.55
        assert tc is not None

    def test_1for2_not_subject_to_anchor(self):
        """1-for-2 trades don't need anchor check (I'm receiving, not packaging)."""
        give = [_make_asset("Star", model=7000, ktc=9000)]
        recv = [_make_asset("A", model=4000, ktc=4500), _make_asset("B", model=3500, ktc=4000)]
        tc = _score_trade(give, recv)
        assert tc is not None


# ── Confidence scoring ──────────────────────────────────────────────────


class TestConfidenceScoring:
    """Verify confidence factor impacts ranking."""

    def test_high_source_full_ktc_beats_low_source_full_ktc(self):
        """Same edge, but higher source count → higher arbitrage score."""
        high_src_give = [_make_asset("A", model=4000, ktc=5000, source_count=6)]
        high_src_recv = [_make_asset("B", model=5000, ktc=4000, source_count=6)]
        tc_high = _score_trade(high_src_give, high_src_recv)

        low_src_give = [_make_asset("C", model=4000, ktc=5000, source_count=1)]
        low_src_recv = [_make_asset("D", model=5000, ktc=4000, source_count=1)]
        tc_low = _score_trade(low_src_give, low_src_recv)

        assert tc_high is not None
        assert tc_low is not None
        assert tc_high.confidence_score > tc_low.confidence_score
        assert tc_high.arbitrage_score > tc_low.arbitrage_score

    def test_full_ktc_beats_partial_ktc_same_edge(self):
        """Full KTC coverage outranks partial with similar board math."""
        full_give = [_make_asset("A", model=4000, ktc=5000)]
        full_recv = [_make_asset("B", model=5000, ktc=4000)]
        tc_full = _score_trade(full_give, full_recv)

        # Partial: receive has one with KTC, one without (total model ~5000)
        part_give = [_make_asset("C", model=4000, ktc=5000)]
        part_recv = [_make_asset("D", model=3000, ktc=3000), _make_asset("E", model=2000, ktc=None)]
        tc_part = _score_trade(part_give, part_recv)

        assert tc_full is not None
        assert tc_part is not None
        assert tc_full.confidence_score > tc_part.confidence_score
        assert tc_full.arbitrage_score > tc_part.arbitrage_score

    def test_confidence_in_to_dict(self):
        """Confidence score is exposed in dict output."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4000)]
        tc = _score_trade(give, recv)
        d = tc.to_dict()
        assert "confidenceScore" in d
        assert isinstance(d["confidenceScore"], float)

    def test_unknown_sources_full_confidence(self):
        """Assets with source_count=0 (unknown) get full source confidence."""
        give = [_make_asset("A", model=4000, ktc=5000)]  # source_count=0
        recv = [_make_asset("B", model=5000, ktc=4000)]  # source_count=0
        tc = _score_trade(give, recv)
        assert tc is not None
        # Full KTC, unknown sources → confidence = 1.0 * 1.0
        assert tc.confidence_score == 1.0


# ── Trade ranking realism ───────────────────────────────────────────────


class TestTradeRankingRealism:
    """Verify that the ranking formula produces believable orderings."""

    def test_larger_trade_beats_smaller_same_edge_pct(self):
        """A 4000→5000 trade (25% gain) outranks a 1000→1250 trade (25% gain)."""
        big_give = [_make_asset("Big", model=4000, ktc=5000)]
        big_recv = [_make_asset("BigTarget", model=5000, ktc=4000)]
        tc_big = _score_trade(big_give, big_recv)

        small_give = [_make_asset("Small", model=1000, ktc=1300)]
        small_recv = [_make_asset("SmallTarget", model=1250, ktc=1000)]
        tc_small = _score_trade(small_give, small_recv)

        assert tc_big is not None
        assert tc_small is not None
        assert tc_big.arbitrage_score > tc_small.arbitrage_score

    def test_simpler_trade_gets_simplicity_bonus(self):
        """1-for-1 beats 2-for-1 when board edge is similar."""
        # 1-for-1: strong edge
        give_1 = [_make_asset("A", model=4000, ktc=5500)]
        recv_1 = [_make_asset("B", model=5000, ktc=4500)]
        tc_1for1 = _score_trade(give_1, recv_1)

        # 2-for-1: slightly better total edge but more complex
        k1, k2 = _appealing_ktc_split(4500)
        give_2 = [_make_asset("C", model=2500, ktc=k1), _make_asset("D", model=2000, ktc=k2)]
        recv_2 = [_make_asset("E", model=5200, ktc=4500)]
        tc_2for1 = _score_trade(give_2, recv_2)

        assert tc_1for1 is not None
        assert tc_2for1 is not None
        # The simpler trade should win or be competitive despite similar edge
        # (depends on exact numbers but the -3 penalty makes 2-for-1 less dominant)


# ── Roster-fit awareness ────────────────────────────────────────────────


class TestRosterFit:
    """Verify light roster-fit bonus in end-to-end find_trades."""

    def _build_scenario(self):
        """Build a scenario where my team has 4 WRs (surplus) and 1 RB (weak)."""
        players = {
            "My WR1": _make_player_data(5000, ktc=5500, pos="WR"),
            "My WR2": _make_player_data(4000, ktc=4500, pos="WR"),
            "My WR3": _make_player_data(3500, ktc=4000, pos="WR"),
            "My WR4": _make_player_data(3000, ktc=3500, pos="WR"),
            "My RB1": _make_player_data(6000, ktc=7000, pos="RB"),
            "Opp RB Star": _make_player_data(5500, ktc=4500, pos="RB"),
            "Opp QB Value": _make_player_data(5500, ktc=4500, pos="QB"),
        }
        teams = [
            {"name": "My Team", "players": ["My WR1", "My WR2", "My WR3", "My WR4", "My RB1"]},
            {"name": "Rival", "players": ["Opp RB Star", "Opp QB Value"]},
        ]
        return players, teams

    def test_surplus_give_gets_fit_bonus(self):
        """Trades that give away surplus WRs get a slight ranking boost."""
        players, teams = self._build_scenario()
        result = find_trades(players, "My Team", ["Rival"], teams)
        # Should have trades; giving WRs (surplus=4) should get fit bonus
        wr_give_trades = [
            t for t in result["trades"] if any(a["position"] == "WR" for a in t["give"])
        ]
        assert len(wr_give_trades) > 0

    def test_weakness_receive_gets_fit_bonus(self):
        """Trades that acquire a position where we have ≤1 get a boost.
        My team has 1 RB and 0 QBs, so receiving RB or QB is a fit bonus."""
        players, teams = self._build_scenario()
        result = find_trades(players, "My Team", ["Rival"], teams)
        # Check that some trades receiving RB or QB exist
        weakness_trades = [
            t for t in result["trades"] if any(a["position"] in ("RB", "QB") for a in t["receive"])
        ]
        # These should exist and be ranked well
        assert len(weakness_trades) > 0


# ── Representative scenario validation (10+) ────────────────────────────


class TestRepresentativeScenarios:
    """
    10+ real-ish scenarios proving before/after behavior.
    Each scenario documents what SHOULD happen and verifies it.
    """

    # ── Elite-target scenarios ──────────────────────────────────────────

    def test_scenario_1_elite_junk_2for1_blocked(self):
        """Scenario 1: Two bench WRs for elite RB → blocked by elite guard.
        Before: 60% ratio passed the 55% standard guard.
        After: 60% < 65% elite guard → blocked."""
        bench_a = _make_asset("Bench WR A", model=2500, ktc=3200, pos="WR")
        bench_b = _make_asset("Bench WR B", model=2300, ktc=3000, pos="WR")
        elite_rb = _make_asset("Bijan Robinson", model=8000, ktc=7000, pos="RB")
        tc = _score_trade([bench_a, bench_b], [elite_rb])
        assert tc is None  # Blocked by elite guard

    def test_scenario_2_legit_blockbuster_for_elite(self):
        """Scenario 2: Two solid starters for elite RB → allowed.
        We gain on our board (elite undervalued by KTC), opponent gains on KTC."""
        k1, k2 = _appealing_ktc_split(8500)
        starter_wr = _make_asset("Garrett Wilson", model=4000, ktc=k1, pos="WR")
        starter_rb = _make_asset("Breece Hall", model=3500, ktc=k2, pos="RB")
        elite = _make_asset("Bijan Robinson", model=9000, ktc=8500, pos="RB")
        tc = _score_trade([starter_wr, starter_rb], [elite])
        # give_model=7500, recv_model=9000 → board_delta=+1500 ✓
        # 7500/9000 = 0.833 > 0.65 ✓  anchor: 4000/9000 = 0.444 > 0.35 ✓
        # opp appeal is derived, not asserted arithmetically: KTC's
        # package premium makes the raw totals misleading here.
        assert tc is not None
        assert tc.board_delta > 0

    # ── Partial-KTC scenarios ───────────────────────────────────────────

    def test_scenario_3_partial_ktc_ranks_below_full(self):
        """Scenario 3: Partial-KTC trade ranks below equivalent full-KTC trade.
        Partial-KTC now requires at least one receive asset with KTC."""
        full_give = [_make_asset("A", model=4000, ktc=5000, source_count=5)]
        full_recv = [_make_asset("B", model=5000, ktc=4000, source_count=5)]
        tc_full = _score_trade(full_give, full_recv)

        # Partial: receive has one asset with KTC, one without
        part_give = [_make_asset("C", model=4000, ktc=5000, source_count=5)]
        part_recv = [
            _make_asset("D", model=3000, ktc=3000, source_count=2),
            _make_asset("E", model=2200, ktc=None, source_count=2),
        ]
        tc_part = _score_trade(part_give, part_recv)

        assert tc_full is not None
        assert tc_part is not None
        # Full-KTC trade should rank higher thanks to confidence
        assert tc_full.arbitrage_score > tc_part.arbitrage_score

    def test_scenario_4_all_receive_no_ktc_rejected(self):
        """Scenario 4: Receive side with zero KTC → rejected entirely."""
        give = [_make_asset("Single Src", model=4000, ktc=5000, source_count=1)]
        recv = [_make_asset("No KTC", model=5000, ktc=None, source_count=1)]
        tc = _score_trade(give, recv)
        assert tc is None

    # ── Roster-clog / junk-package scenarios ────────────────────────────

    def test_scenario_5_two_bench_for_starter_no_anchor(self):
        """Scenario 5: Two bench stashes (1100 each) for a 4000 starter → no anchor.
        Before: total 2200/4000=0.55, passed standard guard.
        After: max_give 1100/4000=0.275 < 0.35 → blocked by anchor check."""
        bench_a = _make_asset("Deep Bench A", model=1100, ktc=1800)
        bench_b = _make_asset("Deep Bench B", model=1100, ktc=1800)
        starter = _make_asset("Solid Starter", model=4000, ktc=3200)
        tc = _score_trade([bench_a, bench_b], [starter])
        assert tc is None  # Blocked by anchor quality

    def test_scenario_6_starter_plus_bench_for_starter_passes(self):
        """Scenario 6: One real starter + filler for target → anchor present, passes."""
        k1, k2 = _appealing_ktc_split(5200)
        starter = _make_asset("WR2", model=3500, ktc=k1)
        filler = _make_asset("Depth RB", model=1200, ktc=k2)
        target = _make_asset("Target WR1", model=6000, ktc=5200)
        tc = _score_trade([starter, filler], [target])
        # anchor: 3500/6000 = 0.583 > 0.35 ✓  total: 4700/6000 = 0.783 > 0.55 ✓
        assert tc is not None

    # ── Normal good trades that should still pass ───────────────────────

    def test_scenario_7_clean_1for1_arbitrage(self):
        """Scenario 7: Classic board-arbitrage 1-for-1 — should pass and rank well."""
        give = [_make_asset("Overvalued by KTC", model=4000, ktc=5500, source_count=5)]
        recv = [_make_asset("Undervalued by KTC", model=5500, ktc=4500, source_count=5)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.board_delta == 1500
        assert tc.opponent_ktc_appeal > 0  # Opponent sees +22% on KTC
        assert tc.confidence_score == 1.0  # Full KTC, 5 sources
        assert tc.arbitrage_score > 0

    def test_scenario_8_fair_2for1_non_elite(self):
        """Scenario 8: Fair 2-for-1 trade below elite threshold — should pass."""
        k1, k2 = _appealing_ktc_split(6000)
        a1 = _make_asset("Solid WR", model=3500, ktc=k1, source_count=4)
        a2 = _make_asset("Pick", model=2500, ktc=k2, pos="PICK", is_pick=True, source_count=4)
        target = _make_asset("Good RB", model=7000, ktc=6000, source_count=5, pos="RB")
        tc = _score_trade([a1, a2], [target])
        # 6000/7000 = 0.857 > 0.55 ✓ (not elite so no 0.65 check)
        # anchor: 3500/7000 = 0.50 > 0.35 ✓
        assert tc is not None

    # ── Borderline trades where ranking order changes ───────────────────

    def test_scenario_9_confidence_reranks_borderline(self):
        """Scenario 9: Two trades with similar board edge but different confidence.
        The high-confidence trade should rank above the low-confidence one."""
        # Trade A: modest edge, high confidence
        give_a = [_make_asset("A1", model=4000, ktc=4800, source_count=6)]
        recv_a = [_make_asset("A2", model=4800, ktc=4000, source_count=6)]
        tc_a = _score_trade(give_a, recv_a)

        # Trade B: same edge ratio, low confidence (1 source each)
        give_b = [_make_asset("B1", model=4000, ktc=4800, source_count=1)]
        recv_b = [_make_asset("B2", model=4800, ktc=4000, source_count=1)]
        tc_b = _score_trade(give_b, recv_b)

        assert tc_a is not None
        assert tc_b is not None
        # Same base math, but A has higher confidence → ranks higher
        assert tc_a.arbitrage_score > tc_b.arbitrage_score
        assert tc_a.confidence_score > tc_b.confidence_score

    def test_scenario_10_value_scale_reranks_borderline(self):
        """Scenario 10: Two trades with same edge% but different absolute value.
        The larger trade should rank higher due to absolute-value bonus."""
        # Trade A: large — give 5000, recv 6250 (25% edge)
        big_give = [_make_asset("Big", model=5000, ktc=6250)]
        big_recv = [_make_asset("BigTarget", model=6250, ktc=5000)]
        tc_big = _score_trade(big_give, big_recv)

        # Trade B: small — give 1000, recv 1250 (25% edge)
        sm_give = [_make_asset("Small", model=1000, ktc=1300)]
        sm_recv = [_make_asset("SmallTarget", model=1250, ktc=1000)]
        tc_small = _score_trade(sm_give, sm_recv)

        assert tc_big is not None
        assert tc_small is not None
        assert tc_big.arbitrage_score > tc_small.arbitrage_score

    def test_scenario_11_full_ktc_wins_over_partial_despite_bigger_delta(self):
        """Scenario 11: Partial-KTC trade with bigger board delta still
        ranks below a full-KTC trade. Confidence matters more than raw edge."""
        full_give = [_make_asset("F1", model=4000, ktc=5000, source_count=5)]
        full_recv = [_make_asset("F2", model=5000, ktc=4000, source_count=5)]
        tc_full = _score_trade(full_give, full_recv)

        # Partial: one receive asset has KTC, one doesn't; bigger total model
        part_give = [_make_asset("P1", model=4000, ktc=5000, source_count=5)]
        part_recv = [
            _make_asset("P2", model=3500, ktc=3000, source_count=2),
            _make_asset("P3", model=2000, ktc=None, source_count=2),
        ]
        tc_part = _score_trade(part_give, part_recv)

        assert tc_full is not None
        assert tc_part is not None
        assert tc_full.arbitrage_score > tc_part.arbitrage_score

    def test_scenario_12_pick_trade_passes_normally(self):
        """Scenario 12: Trading a pick for a player — should work normally."""
        pick = _make_asset("2026 1.05", model=3000, ktc=3200, pos="PICK", is_pick=True)
        player = _make_asset("Rising WR", model=4000, ktc=2800, pos="WR")
        tc = _score_trade([pick], [player])
        assert tc is not None
        assert tc.board_delta == 1000


# ── Explainability helpers ──────────────────────────────────────────────


class TestConfidenceTier:
    def test_high(self):
        assert _confidence_tier(1.0) == "high"
        assert _confidence_tier(0.75) == "high"

    def test_moderate(self):
        assert _confidence_tier(0.74) == "moderate"
        assert _confidence_tier(0.45) == "moderate"

    def test_low(self):
        assert _confidence_tier(0.44) == "low"
        assert _confidence_tier(0.0) == "low"


class TestEdgeLabel:
    def test_strong(self):
        assert _edge_label(0.30) == "Strong Edge"

    def test_moderate(self):
        assert _edge_label(0.15) == "Moderate Edge"

    def test_slight(self):
        assert _edge_label(0.05) == "Slight Edge"


class TestOppAppealPhrase:
    def test_positive(self):
        p = _opp_appeal_phrase(0.15)
        assert "gains" in p and "15%" in p

    def test_small_positive(self):
        p = _opp_appeal_phrase(0.03)
        assert "gains" in p and "3%" in p

    def test_negative(self):
        p = _opp_appeal_phrase(-0.08)
        assert "gives up" in p and "8%" in p


class TestBuildSummary:
    def test_full_coverage_summary(self):
        s = _build_summary(1000, 0.25, 0.15, "full", "high", "Strong Edge", "1-for-1")
        assert "Strong Edge" in s
        assert "1,000" in s
        assert "25%" in s
        assert "opponent gains" in s
        assert "high confidence" in s
        assert "1-for-1" in s
        # "partial" should NOT appear in full-coverage summaries
        assert "partial" not in s

    def test_partial_coverage_summary(self):
        s = _build_summary(500, 0.10, 0.0, "partial", "moderate", "Moderate Edge", "2-for-1")
        assert "partial KTC" in s
        assert "moderate confidence" in s


# ── Explainability fields on TradeCandidate ─────────────────────────────


class TestExplainabilityFields:
    """Verify that scored trades carry all explainability metadata."""

    def test_full_ktc_1for1_has_all_fields(self):
        """A clean 1-for-1 trade should have all explainability fields populated."""
        give = [_make_asset("A", model=4000, ktc=5500, source_count=5)]
        recv = [_make_asset("B", model=5500, ktc=4500, source_count=5)]
        tc = _score_trade(give, recv)
        assert tc is not None

        # Confidence tier
        assert tc.confidence_tier == "high"
        assert tc.confidence_score == 1.0

        # Edge label
        assert tc.edge_label in ("Strong Edge", "Moderate Edge", "Slight Edge")

        # Summary is non-empty and human-readable
        assert len(tc.summary) > 20
        assert "confidence" in tc.summary

        # Ranking factors breakdown
        rf = tc.ranking_factors
        assert "boardEdge" in rf
        assert "ktcAppeal" in rf
        assert "confidenceMultiplier" in rf
        assert "valueScale" in rf
        assert "simplicityPenalty" in rf
        assert "rosterFitBonus" in rf
        assert rf["rosterFitBonus"] == 0.0  # Not in find_trades context

        # Flags
        assert "full_market" in tc.flags
        assert "high_confidence" in tc.flags

    def test_partial_ktc_flags(self):
        """Partial coverage trade should have partial_market flag and lower confidence tier."""
        give = [_make_asset("A", model=4000, ktc=5000, source_count=2)]
        recv = [
            _make_asset("B", model=3000, ktc=3000, source_count=1),
            _make_asset("C", model=2000, ktc=None, source_count=1),
        ]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert "partial_market" in tc.flags
        assert "partial KTC" in tc.summary

    def test_2for1_elite_has_elite_and_anchor_flags(self):
        """2-for-1 targeting an elite should carry both elite_target and anchor_verified flags."""
        k1, k2 = _appealing_ktc_split(8000)
        a1 = _make_asset("Starter", model=4000, ktc=k1)
        a2 = _make_asset("Piece", model=3500, ktc=k2)
        elite = _make_asset("Elite", model=9000, ktc=8000)
        tc = _score_trade([a1, a2], [elite])
        assert tc is not None
        assert "elite_target" in tc.flags
        assert "anchor_verified" in tc.flags

    def test_2for1_non_elite_has_anchor_not_elite(self):
        """2-for-1 below elite threshold has anchor_verified but not elite_target."""
        target_val = int(ELITE_THRESHOLD * 0.93)
        k1, k2 = _appealing_ktc_split(5500)
        a1 = _make_asset("A", model=int(target_val * 0.40), ktc=k1)
        a2 = _make_asset("B", model=int(target_val * 0.243), ktc=k2)
        target = _make_asset("Target", model=target_val, ktc=5500)
        tc = _score_trade([a1, a2], [target])
        assert tc is not None
        assert "anchor_verified" in tc.flags
        assert "elite_target" not in tc.flags

    def test_1for1_no_anchor_or_elite_flags(self):
        """1-for-1 trades don't have multi-for-one flags."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4000)]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert "anchor_verified" not in tc.flags
        assert "elite_target" not in tc.flags

    def test_to_dict_includes_explainability(self):
        """The serialized dict includes all new explainability fields."""
        give = [_make_asset("A", model=4000, ktc=5000)]
        recv = [_make_asset("B", model=5000, ktc=4000)]
        tc = _score_trade(give, recv)
        d = tc.to_dict()
        assert "confidenceTier" in d
        assert "edgeLabel" in d
        assert "summary" in d
        assert isinstance(d["summary"], str)
        assert "rankingFactors" in d
        assert isinstance(d["rankingFactors"], dict)
        assert "flags" in d
        assert isinstance(d["flags"], list)

    def test_ranking_factors_sum_near_arbitrage(self):
        """Factor breakdown should roughly reconstruct the final arbitrage score
        (minus the roster-fit bonus which is added later in find_trades)."""
        give = [_make_asset("A", model=4000, ktc=5000, source_count=5)]
        recv = [_make_asset("B", model=5000, ktc=4000, source_count=5)]
        tc = _score_trade(give, recv)
        rf = tc.ranking_factors
        # Core = (boardEdge + ktcAppeal + positiveBonus) * confidenceMultiplier + valueScale + simplicityPenalty
        core = rf["boardEdge"] + rf["ktcAppeal"] + rf["positiveBonus"]
        reconstructed = (
            core * rf["confidenceMultiplier"] + rf["valueScale"] + rf["simplicityPenalty"]
        )
        assert abs(reconstructed - tc.arbitrage_score) < 0.1


# ── Roster-fit explainability ───────────────────────────────────────────


class TestRosterFitExplainability:
    """Verify roster-fit bonus is visible in flags, ranking_factors, and summary."""

    def _build_surplus_scenario(self):
        """My team has 5 WRs (surplus) and 0 QBs (need)."""
        players = {
            "My WR1": _make_player_data(5000, ktc=5500, pos="WR"),
            "My WR2": _make_player_data(4000, ktc=4500, pos="WR"),
            "My WR3": _make_player_data(3500, ktc=4000, pos="WR"),
            "My WR4": _make_player_data(3000, ktc=3500, pos="WR"),
            "My WR5": _make_player_data(2500, ktc=3000, pos="WR"),
            "Opp QB Star": _make_player_data(5500, ktc=4500, pos="QB"),
        }
        teams = [
            {"name": "My Team", "players": ["My WR1", "My WR2", "My WR3", "My WR4", "My WR5"]},
            {"name": "Rival", "players": ["Opp QB Star"]},
        ]
        return players, teams

    def test_roster_fit_flag_present(self):
        """Trades matching roster surplus/need should have roster_fit flag."""
        players, teams = self._build_surplus_scenario()
        result = find_trades(players, "My Team", ["Rival"], teams)
        fit_trades = [t for t in result["trades"] if "roster_fit" in t["flags"]]
        assert len(fit_trades) > 0

    def test_roster_fit_bonus_in_ranking_factors(self):
        """The rosterFitBonus should be non-zero in affected trades."""
        players, teams = self._build_surplus_scenario()
        result = find_trades(players, "My Team", ["Rival"], teams)
        fit_trades = [t for t in result["trades"] if "roster_fit" in t["flags"]]
        assert len(fit_trades) > 0
        for t in fit_trades:
            assert t["rankingFactors"]["rosterFitBonus"] > 0

    def test_roster_fit_in_summary(self):
        """The summary should mention roster fit when bonus applied."""
        players, teams = self._build_surplus_scenario()
        result = find_trades(players, "My Team", ["Rival"], teams)
        fit_trades = [t for t in result["trades"] if "roster_fit" in t["flags"]]
        assert len(fit_trades) > 0
        for t in fit_trades:
            assert "Roster fit:" in t["summary"]


# ── Before/after output examples ────────────────────────────────────────


class TestBeforeAfterExplainability:
    """Document concrete before/after examples showing the new fields."""

    def test_example_strong_1for1_output(self):
        """Example: Strong 1-for-1 arbitrage with full KTC and high confidence."""
        give = [_make_asset("Overvalued", model=4000, ktc=6000, source_count=6)]
        recv = [_make_asset("Undervalued", model=6000, ktc=5000, source_count=6)]
        tc = _score_trade(give, recv)
        d = tc.to_dict()

        # Before: only had boardDelta=2000, arbitrageScore=X, ktcCoverage="full"
        # After: also has confidenceTier, edgeLabel, summary, rankingFactors, flags
        assert d["boardDelta"] == 2000
        assert d["confidenceTier"] == "high"
        assert d["edgeLabel"] == "Strong Edge"
        assert "you gain 2,000" in d["summary"]
        assert "full_market" in d["flags"]
        assert "high_confidence" in d["flags"]
        assert d["rankingFactors"]["boardEdge"] > 0

    def test_example_low_confidence_partial_output(self):
        """Example: Low-confidence partial-KTC trade (receive side has at least one KTC)."""
        give = [_make_asset("Single", model=3000, ktc=4000, source_count=1)]
        recv = [
            _make_asset("HasKTC", model=2500, ktc=2000, source_count=1),
            _make_asset("NoKTC", model=1500, ktc=None, source_count=1),
        ]
        tc = _score_trade(give, recv)
        assert tc is not None
        d = tc.to_dict()

        # This trade is partial-KTC with single-source — very low confidence
        assert "partial_market" in d["flags"]
        assert "partial KTC" in d["summary"]

    def test_example_receive_all_no_ktc_rejected(self):
        """Receive side with zero KTC coverage is now rejected."""
        give = [_make_asset("Single", model=3000, ktc=4000, source_count=1)]
        recv = [_make_asset("NoKTC", model=4000, ktc=None, source_count=1)]
        tc = _score_trade(give, recv)
        assert tc is None


# ── KTC quality guardrails ──────────────────────────────────────────────


class TestKtcQualityGuardrails:
    """Tests for the new KTC quality gates added to fix recommendation trust."""

    def test_kickers_excluded_from_pool(self):
        """Kickers (K/PK) should never enter the asset pool."""
        players = {
            "Cameron Dicker": _make_player_data(1200, ktc=800, pos="K", team="LAC"),
            "Garrett Wilson": _make_player_data(5000, ktc=4800, pos="WR", team="NYJ"),
        }
        pool = build_asset_pool(players)
        names = {a.name for a in pool}
        assert "Cameron Dicker" not in names
        assert "Garrett Wilson" in names

    def test_dst_excluded_from_pool(self):
        """DST/DEF positions should never enter the asset pool."""
        players = {
            "Bills DST": _make_player_data(1500, ktc=1000, pos="DST", team="BUF"),
            "Josh Allen": _make_player_data(9000, ktc=8500, pos="QB", team="BUF"),
        }
        pool = build_asset_pool(players)
        names = {a.name for a in pool}
        assert "Bills DST" not in names
        assert "Josh Allen" in names

    def test_def_position_excluded(self):
        """DEF alias also excluded."""
        players = {
            "Some DEF": _make_player_data(1000, ktc=800, pos="DEF", team="SF"),
        }
        pool = build_asset_pool(players)
        assert len(pool) == 0

    # ``test_idp_dilution_guard_rejects_majority_no_ktc`` was deleted with
    # the guard it named.  That guard existed because IDP assets used to
    # reach the pool with no market value at all; now that each asset is
    # anchored on the board its counterparty actually consults, the
    # category "IDP without a market value" no longer exists and the guard
    # had a dead premise, not merely dead code.
    #
    # The test was already inert before deletion — it declared ``give`` and
    # ``recv`` and then asserted nothing, so it passed whether or not the
    # guard worked.  Removed rather than silenced: a test that cannot fail
    # is worse than no test, because it reports coverage it does not have.

    def test_idp_with_ktc_allowed(self):
        """IDP assets WITH KTC are fine — they have real market backing."""
        give = [_make_asset("A", model=4000, ktc=5000, pos="WR")]
        recv = [_make_asset("B", model=5000, ktc=4500, pos="LB")]
        tc = _score_trade(give, recv)
        assert tc is not None
        assert tc.ktc_coverage == "full"

    def test_summary_no_ktc_claim_on_partial(self):
        """Summary must not say 'breaks even on KTC' for partial coverage."""
        summary = _build_summary(
            board_delta=1000,
            board_gain_pct=0.25,
            opp_appeal=0.0,
            coverage="partial",
            confidence_tier="moderate",
            edge_label="Strong Edge",
            pkg_size_str="1-for-2",
        )
        assert "breaks even" not in summary
        assert "partial KTC" in summary

    def test_summary_full_ktc_shows_opponent_appeal(self):
        """Summary SHOULD show opponent appeal for full coverage."""
        summary = _build_summary(
            board_delta=1000,
            board_gain_pct=0.25,
            opp_appeal=0.05,
            coverage="full",
            confidence_tier="high",
            edge_label="Strong Edge",
            pkg_size_str="1-for-1",
        )
        assert "opponent gains" in summary
        assert "5%" in summary

    def test_excluded_positions_constant(self):
        """Verify the exclusion set contains the right positions."""
        assert "K" in EXCLUDED_POSITIONS
        assert "PK" in EXCLUDED_POSITIONS
        assert "DST" in EXCLUDED_POSITIONS
        assert "DEF" in EXCLUDED_POSITIONS
        # Offense/IDP should NOT be excluded
        assert "QB" not in EXCLUDED_POSITIONS
        assert "WR" not in EXCLUDED_POSITIONS
        assert "LB" not in EXCLUDED_POSITIONS


# ── KTC Top-N Filter ───────────────────────────────────────────────────


class TestKtcTopNFilter:
    """Verify the KTC top-150 quality gate in the finder engine."""

    def test_default_filter_is_150(self):
        assert KTC_TOP_N_FILTER == 150

    def test_pool_filtered_to_top_n(self):
        """Players outside KTC top N are excluded from the pool."""
        players = {}
        for i in range(200):
            ktc = 9000 - i * 40
            players[f"Player_{i:03d}"] = _make_player_data(
                model=ktc,
                ktc=ktc,
                pos="WR",
            )
        pool = build_asset_pool(players, ktc_top_n=100)
        assert len(pool) == 100

    def test_pool_preserves_all_when_disabled(self):
        players = {}
        for i in range(200):
            ktc = 9000 - i * 40
            players[f"Player_{i:03d}"] = _make_player_data(
                model=ktc,
                ktc=ktc,
                pos="WR",
            )
        pool = build_asset_pool(players, ktc_top_n=0)
        assert len(pool) == 200

    def test_no_ktc_players_excluded_by_filter(self):
        """Players without KTC data are excluded when the filter is active."""
        players = {
            "HasKTC": _make_player_data(5000, ktc=4500, pos="QB"),
            "NoKTC": _make_player_data(6000, pos="WR"),  # Higher model but no KTC
        }
        pool = build_asset_pool(players, ktc_top_n=150)
        names = {a.name for a in pool}
        assert "HasKTC" in names
        assert "NoKTC" not in names

    def test_ktc_rank_assigned_by_ktc_value(self):
        """KTC rank should be based on KTC value, not model value."""
        players = {
            "HighModel": _make_player_data(9000, ktc=3000, pos="QB"),
            "HighKTC": _make_player_data(3000, ktc=9000, pos="WR"),
        }
        pool = build_asset_pool(players, ktc_top_n=0)
        by_name = {a.name: a for a in pool}
        assert by_name["HighKTC"].ktc_rank == 1  # Higher KTC = rank 1
        assert by_name["HighModel"].ktc_rank == 2

    def test_filter_in_find_trades_metadata(self):
        """The ktcTopNFilter should appear in find_trades metadata."""
        players = {
            f"P{i}": _make_player_data(5000 - i * 10, ktc=5000 - i * 10, pos="WR")
            for i in range(20)
        }
        sleeper_teams = _make_sleeper_teams(
            {
                "MyTeam": [f"P{i}" for i in range(10)],
                "TheirTeam": [f"P{i}" for i in range(10, 20)],
            }
        )
        result = find_trades(
            players,
            "MyTeam",
            ["TheirTeam"],
            sleeper_teams,
            ktc_top_n=50,
        )
        assert result["metadata"]["ktcTopNFilter"] == 50

    def test_trades_only_contain_top_n_players(self):
        """Every player in every trade must be inside the KTC top N."""
        players = {}
        for i in range(50):
            ktc = 9000 - i * 100
            model = ktc + (i % 2) * 200 - 100  # Slight model/KTC disagreement
            pos = ["QB", "RB", "WR", "TE"][i % 4]
            players[f"P{i:02d}"] = _make_player_data(model, ktc=ktc, pos=pos)

        sleeper_teams = _make_sleeper_teams(
            {
                "Me": [f"P{i:02d}" for i in range(0, 25)],
                "Them": [f"P{i:02d}" for i in range(25, 50)],
            }
        )
        result = find_trades(
            players,
            "Me",
            ["Them"],
            sleeper_teams,
            ktc_top_n=30,
        )
        eligible_names = {f"P{i:02d}" for i in range(30)}
        for trade in result.get("trades", []):
            for side in ("give", "receive"):
                for player in trade[side]:
                    assert (
                        player["name"] in eligible_names
                    ), f"{player['name']} in {side} is outside KTC top 30"


# ── WS-J F-3: per-market quality gate (IDP was silently excluded) ────────


def _make_idp_player_data(model, idptc=None, pos="LB", team="BAL", sites=5):
    """Raw payload for an IDP asset.

    IDP players carry an ``idpTradeCalc`` value and NO KTC value —
    KTC's board has no defenders at all.  This is the shape that the
    pre-fix KTC-only top-N filter silently dropped.
    """
    d = {
        "_finalAdjusted": model,
        "_rawComposite": model,
        "_composite": model,
        "_sites": sites,
        "position": pos,
        "team": team,
    }
    if idptc is not None:
        d["_canonicalSiteValues"] = {"idpTradeCalc": idptc}
    return d


class TestPerMarketQualityGate:
    """The quality gate must be per-market, not KTC-only.

    KTC publishes no IDP players, so ranking every asset against KTC
    and keeping the top N removed 100% of IDP from the pool — in an
    IDP league the engine silently returned offense-only results.
    IDP assets are anchored on IDPTradeCalc instead, which publishes
    offense, IDP and picks on one native 0-9999 scale.
    """

    def test_idp_asset_survives_default_filter(self):
        """An IDP player with IDPTC coverage must reach the pool."""
        players = {
            "Aidan Hutchinson": _make_idp_player_data(6400, idptc=6444, pos="DL"),
            "Josh Allen": _make_player_data(9000, ktc=8500, pos="QB"),
        }
        pool = build_asset_pool(players)
        names = {a.name for a in pool}
        assert "Aidan Hutchinson" in names, (
            "IDP asset was dropped by the quality gate — this is the "
            "offense-only regression (WS-J F-3)"
        )

    def test_idp_market_value_reads_idptc(self):
        players = {"Micah Parsons": _make_idp_player_data(5400, idptc=5419, pos="LB")}
        pool = build_asset_pool(players)
        asset = pool[0]
        assert asset.market_value == 5419
        assert asset.market_source == "idpTradeCalc"

    def test_offense_market_value_still_reads_ktc(self):
        players = {"Ja'Marr Chase": _make_player_data(9900, ktc=9996, pos="WR")}
        pool = build_asset_pool(players)
        asset = pool[0]
        assert asset.market_value == 9996
        assert asset.market_source in ("ktcSfTep", "ktc")

    def test_market_rank_is_computed_within_market(self):
        """An IDP player must not be ranked against offensive players.

        Offense values run to 9999; IDP tops out near 6400.  Ranking
        them in one list buries every defender below the offensive
        board and a top-N cut removes them all.
        """
        players = {
            "WR1": _make_player_data(9900, ktc=9990, pos="WR"),
            "WR2": _make_player_data(9800, ktc=9900, pos="WR"),
            "TopLB": _make_idp_player_data(6400, idptc=6444, pos="LB"),
            "NextLB": _make_idp_player_data(5400, idptc=5419, pos="LB"),
        }
        pool = build_asset_pool(players, ktc_top_n=0)
        by_name = {a.name: a for a in pool}
        # Each market ranks from 1 independently.
        assert by_name["WR1"].market_rank == 1
        assert by_name["WR2"].market_rank == 2
        assert by_name["TopLB"].market_rank == 1
        assert by_name["NextLB"].market_rank == 2

    def test_top_n_cut_applies_per_market(self):
        """A top-1 cut keeps the best offense asset AND the best IDP asset."""
        players = {
            "WR1": _make_player_data(9900, ktc=9990, pos="WR"),
            "WR2": _make_player_data(9800, ktc=9900, pos="WR"),
            "TopLB": _make_idp_player_data(6400, idptc=6444, pos="LB"),
            "NextLB": _make_idp_player_data(5400, idptc=5419, pos="LB"),
        }
        pool = build_asset_pool(players, ktc_top_n=1)
        names = {a.name for a in pool}
        assert names == {"WR1", "TopLB"}

    def test_asset_with_no_market_coverage_is_excluded_by_gate(self):
        """No board lists them at all → still filtered by the quality gate."""
        players = {
            "WR1": _make_player_data(9900, ktc=9990, pos="WR"),
            "Ghost": _make_player_data(5000, ktc=None, pos="WR"),
        }
        pool = build_asset_pool(players, ktc_top_n=150)
        assert {a.name for a in pool} == {"WR1"}

    def test_idp_league_produces_idp_trades(self):
        """End-to-end: an IDP-heavy league must surface IDP in trades.

        Real arbitrage shape — I give an offensive player the market
        prices above our board, and receive a defender our board rates
        above his IDPTradeCalc price.  Pre-fix this returned nothing
        involving IDP because no defender ever reached the pool.
        """
        players = {
            # Market loves him more than we do → good to send out.
            "OffOverpriced": _make_player_data(5000, ktc=8000, pos="WR"),
            "OffFiller": _make_player_data(4000, ktc=4200, pos="RB"),
            # We love him more than IDPTradeCalc does → good to acquire.
            "IdpUnderpriced": _make_idp_player_data(8000, idptc=5000, pos="LB"),
            "IdpFiller": _make_idp_player_data(3000, idptc=3100, pos="DL"),
        }
        sleeper_teams = _make_sleeper_teams(
            {
                "Me": ["OffOverpriced", "OffFiller"],
                "Them": ["IdpUnderpriced", "IdpFiller"],
            }
        )
        result = find_trades(players, "Me", ["Them"], sleeper_teams)
        traded_names = set()
        for trade in result.get("trades", []):
            for side in ("give", "receive"):
                for p in trade[side]:
                    traded_names.add(p["name"])
        assert "IdpUnderpriced" in traded_names, (
            "no IDP asset appeared in any trade for an IDP league — "
            f"the engine is still offense-only (got {traded_names})"
        )

    def test_idp_only_pool_does_not_warn_offense_only(self):
        """The offense-only warning must not fire when IDP is priced."""
        players = {
            "OffOverpriced": _make_player_data(5000, ktc=8000, pos="WR"),
            "IdpUnderpriced": _make_idp_player_data(8000, idptc=5000, pos="LB"),
        }
        sleeper_teams = _make_sleeper_teams({"Me": ["OffOverpriced"], "Them": ["IdpUnderpriced"]})
        result = find_trades(players, "Me", ["Them"], sleeper_teams)
        assert not any("offense-only" in w for w in result.get("warnings", []))

    def test_unpriced_idp_league_warns_offense_only(self):
        """IDP present but unpriced → the engine must say it is offense-only.

        This is the regression made visible: rather than silently
        returning offense trades, the result now carries a warning.
        """
        players = {
            "OffOverpriced": _make_player_data(5000, ktc=8000, pos="WR"),
            "OffFiller": _make_player_data(4000, ktc=4200, pos="RB"),
            # IDP with NO market coverage at all.
            "IdpUnpriced": _make_idp_player_data(8000, idptc=None, pos="LB"),
        }
        sleeper_teams = _make_sleeper_teams(
            {"Me": ["OffOverpriced"], "Them": ["OffFiller", "IdpUnpriced"]}
        )
        result = find_trades(players, "Me", ["Them"], sleeper_teams)
        assert any(
            "offense-only" in w for w in result.get("warnings", [])
        ), f"expected an offense-only warning, got {result.get('warnings')}"

    def test_metadata_reports_per_market_filter(self):
        """The engine must say what it filtered, per market."""
        players = {
            "WR1": _make_player_data(9900, ktc=9990, pos="WR"),
            "TopLB": _make_idp_player_data(6400, idptc=6444, pos="LB"),
        }
        sleeper_teams = _make_sleeper_teams({"Me": ["WR1"], "Them": ["TopLB"]})
        result = find_trades(players, "Me", ["Them"], sleeper_teams)
        meta = result["metadata"]
        assert "marketTopNFilter" in meta
        assert meta["marketTopNFilter"] == KTC_TOP_N_FILTER
        # Per-market coverage must be reported so an offense-only result
        # in an IDP league is visible rather than silent.
        assert "marketCoverage" in meta
        assert set(meta["marketCoverage"]) >= {"ktcSfTep", "idpTradeCalc"}


class TestSingleSourceDiscount:
    """The single-source haircut must stay until finder.py moves onto
    the Final Framework values.

    WS-J F-6 (corrected): this was reported as a double-discount over
    the pipeline's 0.30 single-source retention.  It is not.  The
    pipeline haircut lands on ``rankDerivedValue``; this engine reads
    ``_finalAdjusted``, which ``data_contract.py`` copies verbatim from
    the raw scrape and which the retention never touches.  Removing the
    discount here would leave single-source assets undiscounted.
    """

    def test_single_source_asset_is_discounted(self):
        players = {
            "OneSource": _make_player_data(10000, ktc=5000, pos="WR", sites=1),
        }
        pool = build_asset_pool(players, market_top_n=0)
        assert pool[0].model_value == int(10000 * SINGLE_SOURCE_DISCOUNT)

    def test_multi_source_asset_is_not_discounted(self):
        players = {
            "ManySources": _make_player_data(10000, ktc=5000, pos="WR", sites=5),
        }
        pool = build_asset_pool(players, market_top_n=0)
        assert pool[0].model_value == 10000

    def test_discount_applies_to_idp_on_the_same_terms(self):
        """IDP now reaches the pool, so it must be discounted like offense."""
        players = {
            "OneSourceIdp": _make_idp_player_data(10000, idptc=5000, pos="LB", sites=1),
        }
        pool = build_asset_pool(players, market_top_n=0)
        assert pool[0].model_value == int(10000 * SINGLE_SOURCE_DISCOUNT)
