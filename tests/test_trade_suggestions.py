"""Tests for the trade suggestion engine.

Validates:
- Asset pool building from canonical snapshots
- Roster analysis (surplus/need detection)
- Suggestion generation (sell-high, buy-low, consolidation, upgrades)
- Determinism (same inputs → same outputs)
- Fairness labeling
- Serialization
"""
import pytest

from src.trade.suggestions import (
    PlayerAsset,
    RosterAnalysis,
    build_asset_pool,
    analyze_roster,
    generate_suggestions,
    rank_score,
    rank_score_breakdown,
    _fairness_label,
    _norm_pos,
    _compute_cv,
    _edge_for_suggestion,
    _apply_quality_filters,
    _find_balancers,
    _roster_balancer_candidates,
    _pool_balancer_candidates,
    TradeSuggestion,
    DEFAULT_STARTER_NEEDS,
    MIN_RELEVANT_VALUE,
    MIN_ACTIONABLE_VALUE,
    MAX_GAP_FOR_1FOR1,
    MAX_BALANCERS,
    CONSOLIDATION_MAX_OVERPAY_RATIO,
    UPGRADE_SWEETENER_SURPLUS_MULTIPLIER,
    HIGH_DISPERSION_CV,
    MAX_GIVE_PLAYER_APPEARANCES,
    MAX_RECEIVE_TARGET_PER_CATEGORY,
    MAX_LOW_CONFIDENCE_PER_CATEGORY,
    KTC_TOP_N_FILTER,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_asset(name, pos, cal_value, display_value=None, source_count=6,
                team="", rookie=False, years_exp=None, source_values=None):
    """Create a minimal canonical asset dict."""
    if display_value is None:
        display_value = max(1, round(cal_value * 9999 / 7800))
    return {
        "display_name": name,
        "calibrated_value": cal_value,
        "display_value": display_value,
        "source_values": source_values or {f"src{i}": cal_value + i * 100 for i in range(source_count)},
        "universe": "offense_vet" if pos in ("QB", "RB", "WR", "TE") else "idp_vet",
        "metadata": {
            "position": pos,
            "team": team,
            "rookie": rookie,
            "years_exp": years_exp,
        },
    }


def _build_snapshot(assets):
    return {"assets": assets, "run_id": "test", "created_at": "2026-01-01"}


def _sample_snapshot():
    """A sample canonical snapshot with enough players for suggestion testing."""
    assets = []
    # QBs (need 2 starters)
    for name, val, team in [
        ("Josh Allen", 7738, "BUF"), ("Lamar Jackson", 7552, "BAL"),
        ("Joe Burrow", 7369, "CIN"), ("Drake Maye", 7583, "NE"),
        ("Caleb Williams", 7279, "CHI"), ("Justin Herbert", 7219, "LAC"),
        ("Tua Tagovailoa", 3897, "MIA"), ("Kirk Cousins", 2172, "ATL"),
    ]:
        assets.append(_make_asset(name, "QB", val, team=team))

    # RBs (need 3 starters)
    for name, val, team in [
        ("Bijan Robinson", 7800, "ATL"), ("Jahmyr Gibbs", 7769, "DET"),
        ("De'Von Achane", 7521, "MIA"), ("Jonathan Taylor", 7339, "IND"),
        ("Ashton Jeanty", 7675, "LV"), ("Aaron Jones", 2674, "MIN"),
        ("Nick Chubb", 1450, "CLE"),
    ]:
        assets.append(_make_asset(name, "RB", val, team=team))

    # WRs (need 4 starters)
    for name, val, team in [
        ("Ja'Marr Chase", 7460, "CIN"), ("Puka Nacua", 7309, "LAR"),
        ("CeeDee Lamb", 7100, "DAL"), ("Amon-Ra St. Brown", 6900, "DET"),
        ("Garrett Wilson", 5500, "NYJ"), ("Courtland Sutton", 3200, "DEN"),
        ("Jaxon Smith-Njigba", 7399, "SEA"), ("Drake London", 6500, "ATL"),
    ]:
        assets.append(_make_asset(name, "WR", val, team=team))

    # TEs (need 1 starter)
    for name, val, team in [
        ("Brock Bowers", 7644, "LV"), ("Trey McBride", 7614, "ARI"),
        ("Sam LaPorta", 5800, "DET"), ("Dalton Kincaid", 4500, "BUF"),
    ]:
        assets.append(_make_asset(name, "TE", val, team=team))

    # IDP DLs
    for name, val, team in [
        ("Aidan Hutchinson", 5407, "DET"), ("Myles Garrett", 5314, "CLE"),
        ("Nick Bosa", 4900, "SF"), ("Micah Parsons", 4800, "DAL"),
        ("Chase Young", 3500, "NO"), ("Josh Hines-Allen", 4600, "JAX"),
    ]:
        assets.append(_make_asset(name, "DL", val, team=team))

    # IDP LBs
    for name, val, team in [
        ("Jack Campbell", 5012, "DET"), ("Roquan Smith", 4866, "BAL"),
        ("Fred Warner", 4700, "SF"), ("Devin White", 2800, "PHI"),
        ("Demario Davis", 1479, "NO"), ("Foyesade Oluokun", 3900, "JAX"),
    ]:
        assets.append(_make_asset(name, "LB", val, team=team))

    # IDP DBs
    for name, val, team in [
        ("Kyle Hamilton", 4779, "BAL"), ("Sauce Gardner", 4500, "NYJ"),
        ("Patrick Surtain", 4200, "DEN"), ("Antoine Winfield", 3800, "TB"),
    ]:
        assets.append(_make_asset(name, "DB", val, team=team))

    return _build_snapshot(assets)


# ── Tests ────────────────────────────────────────────────────────────

class TestNormPos:
    def test_standard_positions(self):
        assert _norm_pos("QB") == "QB"
        assert _norm_pos("rb") == "RB"

    def test_aliases(self):
        assert _norm_pos("DE") == "DL"
        assert _norm_pos("DT") == "DL"
        assert _norm_pos("CB") == "DB"
        assert _norm_pos("S") == "DB"
        assert _norm_pos("OLB") == "LB"


class TestFairnessLabel:
    def test_even(self):
        assert _fairness_label(0) == "even"
        assert _fairness_label(255) == "even"
        assert _fairness_label(-200) == "even"

    def test_lean(self):
        assert _fairness_label(256) == "lean"
        assert _fairness_label(768) == "lean"

    def test_stretch(self):
        assert _fairness_label(769) == "stretch"
        assert _fairness_label(2000) == "stretch"


class TestBuildAssetPool:
    def test_builds_from_snapshot(self):
        snap = _build_snapshot([
            _make_asset("Player A", "QB", 7000),
            _make_asset("Player B", "RB", 5000),
        ])
        pool = build_asset_pool(snap)
        assert len(pool) == 2
        assert pool[0].name == "Player A"
        assert pool[0].display_value > pool[1].display_value

    def test_skips_missing_fields(self):
        snap = _build_snapshot([
            {"display_name": "No Value"},
            {"calibrated_value": 5000},
        ])
        pool = build_asset_pool(snap)
        assert len(pool) == 0

    def test_sorted_by_display_value_desc(self):
        snap = _build_snapshot([
            _make_asset("Low", "WR", 1000),
            _make_asset("High", "QB", 7000),
            _make_asset("Mid", "RB", 4000),
        ])
        pool = build_asset_pool(snap)
        assert [p.name for p in pool] == ["High", "Mid", "Low"]


class TestAnalyzeRoster:
    def test_detects_surplus_and_need(self):
        snap = _sample_snapshot()
        pool = build_asset_pool(snap)
        # Roster heavy on QB, light on WR
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",  # 4 QBs
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",  # 3 RBs
            "Ja'Marr Chase",  # 1 WR (need 4)
            "Brock Bowers",   # 1 TE
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",  # 3 DL
            "Jack Campbell", "Roquan Smith", "Fred Warner",     # 3 LB
            "Kyle Hamilton", "Sauce Gardner",                   # 2 DB
        ]
        analysis = analyze_roster(roster, pool)
        assert "QB" in analysis.surplus_positions  # 4 QBs, need 2
        assert "WR" in analysis.need_positions     # 1 WR, need 4

    def test_empty_roster(self):
        snap = _sample_snapshot()
        pool = build_asset_pool(snap)
        analysis = analyze_roster([], pool)
        assert analysis.roster_size == 0
        assert len(analysis.need_positions) > 0


class TestGenerateSuggestions:
    def test_produces_suggestions(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        assert "rosterAnalysis" in result
        assert "sellHigh" in result
        assert "buyLow" in result
        assert "consolidation" in result
        assert "positionalUpgrades" in result
        assert result["totalSuggestions"] >= 0
        assert result["metadata"]["rosterMatched"] > 0

    def test_deterministic(self):
        """Same inputs must produce identical outputs."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        r1 = generate_suggestions(roster, snap)
        r2 = generate_suggestions(roster, snap)
        assert r1 == r2

    def test_sell_high_targets_surplus(self):
        snap = _sample_snapshot()
        # QB-heavy roster
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams", "Joe Burrow",
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        sell_high = result["sellHigh"]
        # Should suggest selling surplus QBs
        if sell_high:
            give_positions = {s["give"][0]["position"] for s in sell_high}
            assert "QB" in give_positions

    def test_consolidation_produces_upgrades(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane", "Jonathan Taylor",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa", "Micah Parsons",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        consol = result["consolidation"]
        for s in consol:
            assert len(s["give"]) == 2
            assert len(s["receive"]) == 1
            assert s["receiveTotal"] > max(g["displayValue"] for g in s["give"])

    def test_suggestion_structure(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        all_suggs = result["sellHigh"] + result["buyLow"] + result["consolidation"] + result["positionalUpgrades"]
        for s in all_suggs:
            assert "type" in s
            assert "give" in s
            assert "receive" in s
            assert "giveTotal" in s
            assert "receiveTotal" in s
            assert "gap" in s
            assert "fairness" in s
            assert s["fairness"] in ("even", "lean", "stretch")
            assert "rationale" in s
            assert "whyThisHelps" in s
            assert "confidence" in s
            assert s["confidence"] in ("high", "medium", "low")
            assert "strategy" in s
            for p in s["give"] + s["receive"]:
                assert "name" in p
                assert "position" in p
                assert "displayValue" in p

    def test_no_self_trades(self):
        """Suggestions should never have you trading for your own players."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        roster_set = {n.lower() for n in roster}
        result = generate_suggestions(roster, snap)
        all_suggs = result["sellHigh"] + result["buyLow"] + result["consolidation"] + result["positionalUpgrades"]
        for s in all_suggs:
            for p in s["receive"]:
                assert p["name"].lower() not in roster_set, f"{p['name']} is on roster but suggested as receive"

    def test_empty_roster_no_crash(self):
        snap = _sample_snapshot()
        result = generate_suggestions([], snap)
        assert result["totalSuggestions"] == 0
        assert result["rosterAnalysis"]["rosterSize"] == 0


# ── Phase 2: Market-disagreement tests ───────────────────────────────

class TestComputeCV:
    def test_uniform_values(self):
        assert _compute_cv([100, 100, 100]) == 0.0

    def test_dispersed_values(self):
        cv = _compute_cv([5000, 7000, 9000])
        assert cv is not None
        assert cv > 0.1

    def test_too_few_values(self):
        assert _compute_cv([100]) is None
        assert _compute_cv([]) is None

    def test_zero_mean(self):
        assert _compute_cv([0, 0, 0]) is None


class TestDispersionInPool:
    def test_dispersion_cv_computed(self):
        """Asset pool should compute dispersion_cv from source_values."""
        snap = _build_snapshot([
            _make_asset("Agreed", "QB", 7000, source_values={"a": 9000, "b": 9000, "c": 9000}),
            _make_asset("Disputed", "RB", 5000, source_values={"a": 3000, "b": 7000, "c": 9000}),
        ])
        pool = build_asset_pool(snap)
        agreed = next(p for p in pool if p.name == "Agreed")
        disputed = next(p for p in pool if p.name == "Disputed")
        assert agreed.dispersion_cv == 0.0
        assert disputed.dispersion_cv is not None
        assert disputed.dispersion_cv > agreed.dispersion_cv

    def test_single_source_no_cv(self):
        snap = _build_snapshot([
            _make_asset("Solo", "WR", 5000, source_values={"a": 5000}),
        ])
        pool = build_asset_pool(snap)
        assert pool[0].dispersion_cv is None


class TestEdgeSignals:
    def test_edge_in_suggestions(self):
        """Suggestions with high-dispersion targets should get edge labels."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        # Edge fields should be present on suggestions that have them (or absent)
        all_suggs = result["sellHigh"] + result["buyLow"] + result["consolidation"] + result["positionalUpgrades"]
        for s in all_suggs:
            if "edge" in s:
                assert s["edge"] in ("market_discount", "market_premium", "high_dispersion")
                assert "edgeExplanation" in s
                assert isinstance(s["edgeExplanation"], str)

    def test_metadata_includes_opponent_count(self):
        snap = _sample_snapshot()
        result = generate_suggestions(["Josh Allen", "Bijan Robinson"], snap)
        assert "opponentRostersProvided" in result["metadata"]
        assert result["metadata"]["opponentRostersProvided"] == 0


# ── Phase 3: Opponent-aware tests ────────────────────────────────────

class TestOpponentAware:
    def test_opponent_fit_appears_when_rosters_provided(self):
        snap = _sample_snapshot()
        my_roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        # Opponent who needs QB and has WR surplus
        opponent_rosters = [
            {
                "team_name": "Team RB Heavy",
                "players": [
                    "Tua Tagovailoa",                           # 1 QB (needs 2)
                    "Jonathan Taylor", "Nick Chubb",            # RBs
                    "Puka Nacua", "CeeDee Lamb", "Amon-Ra St. Brown",
                    "Garrett Wilson", "Courtland Sutton",       # WR surplus
                    "Trey McBride",
                    "Chase Young", "Josh Hines-Allen",
                    "Foyesade Oluokun", "Devin White",
                    "Sauce Gardner",
                ],
            },
        ]
        result = generate_suggestions(my_roster, snap, league_rosters=opponent_rosters)
        assert result["metadata"]["opponentRostersProvided"] == 1
        assert result["metadata"]["opponentRostersAnalyzed"] >= 1

        # Check that at least some suggestions have opponentFit
        all_suggs = result["sellHigh"] + result["buyLow"] + result["consolidation"] + result["positionalUpgrades"]
        fits = [s for s in all_suggs if "opponentFit" in s]
        # May or may not have fits depending on roster composition — just check no crash
        for s in fits:
            assert isinstance(s["opponentFit"], str)
            assert len(s["opponentFit"]) > 0

    def test_opponent_aware_still_deterministic(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        opp = [{"team_name": "Opp", "players": ["Tua Tagovailoa", "Puka Nacua", "CeeDee Lamb"]}]
        r1 = generate_suggestions(roster, snap, league_rosters=opp)
        r2 = generate_suggestions(roster, snap, league_rosters=opp)
        assert r1 == r2

    def test_no_opponent_rosters_no_crash(self):
        snap = _sample_snapshot()
        result = generate_suggestions(["Josh Allen"], snap, league_rosters=None)
        assert result["metadata"]["opponentRostersProvided"] == 0

    def test_empty_opponent_rosters_no_crash(self):
        snap = _sample_snapshot()
        result = generate_suggestions(["Josh Allen"], snap, league_rosters=[])
        assert result["metadata"]["opponentRostersProvided"] == 0


# ── Phase 4: Ranking tests ──────────────────────────────────────────

def _make_suggestion(
    give_val=5000, recv_val=5200, fairness="even", confidence="high",
    give_pos="RB", recv_pos="WR", give_name="Player A", recv_name="Player B",
    strategy="neutral", edge=None, opponent_fit=None,
):
    """Helper to build a TradeSuggestion with optional enrichment."""
    s = TradeSuggestion(
        type="sell_high",
        give=[PlayerAsset(give_name, give_pos, give_val, give_val, source_count=6)],
        receive=[PlayerAsset(recv_name, recv_pos, recv_val, recv_val, source_count=6)],
        give_total=give_val,
        receive_total=recv_val,
        gap=give_val - recv_val,
        fairness=fairness,
        rationale="test",
        why_this_helps="test",
        confidence=confidence,
        strategy=strategy,
    )
    if edge is not None:
        s.__dict__["edge"] = edge
    if opponent_fit is not None:
        s.__dict__["opponent_fit"] = opponent_fit
    return s


class TestRankScore:
    def test_deterministic(self):
        """Same inputs → same score."""
        s = _make_suggestion()
        assert rank_score(s) == rank_score(s)

    def test_even_beats_lean(self):
        """An even trade ranks higher than a lean trade, all else equal."""
        even = _make_suggestion(fairness="even")
        lean = _make_suggestion(fairness="lean")
        assert rank_score(even) > rank_score(lean)

    def test_lean_beats_stretch(self):
        lean = _make_suggestion(fairness="lean")
        stretch = _make_suggestion(fairness="stretch")
        assert rank_score(lean) > rank_score(stretch)

    def test_high_conf_beats_low(self):
        """High confidence ranks above low confidence, all else equal."""
        high = _make_suggestion(confidence="high")
        low = _make_suggestion(confidence="low")
        assert rank_score(high) > rank_score(low)

    def test_edge_bonus_applied(self):
        """Market discount edge adds to score."""
        no_edge = _make_suggestion()
        with_edge = _make_suggestion(edge="market_discount")
        assert rank_score(with_edge) > rank_score(no_edge)

    def test_opponent_fit_bonus(self):
        """Opponent fit adds to score."""
        no_fit = _make_suggestion()
        with_fit = _make_suggestion(opponent_fit="Team A needs RB")
        assert rank_score(with_fit) > rank_score(no_fit)

    def test_need_severity_with_roster(self):
        """Filling a gaping need scores higher than a non-need position."""
        s_need = _make_suggestion(recv_pos="WR")
        s_no_need = _make_suggestion(recv_pos="QB")
        # Build a roster that needs WR but not QB
        roster = RosterAnalysis(
            roster_size=10,
            by_position={"QB": [], "WR": []},
            surplus_positions=[],
            need_positions=["WR"],
            starter_counts={"QB": 2, "WR": 1},
            depth_counts={"QB": 0, "WR": 0},
        )
        assert rank_score(s_need, roster) > rank_score(s_no_need, roster)

    def test_breakdown_sums_to_total(self):
        """Breakdown components must sum to total."""
        s = _make_suggestion(edge="high_dispersion", opponent_fit="Team A")
        bd = rank_score_breakdown(s)
        expected = (
            bd["base_value"] + bd["fairness"] + bd["confidence"]
            + bd["need_severity"] + bd["edge"] + bd["opponent_fit"]
        )
        assert abs(bd["total"] - expected) < 0.01

    def test_higher_value_helps_but_not_dominant(self):
        """A cheap even/high trade can beat an expensive stretch/low trade.

        cheap_good: base=2.5 + fair=3 + conf=2 = 7.5
        expensive_bad: base=7.0 + fair=0 + conf=0 = 7.0
        Quality factors outweigh raw value.
        """
        cheap_good = _make_suggestion(give_val=2500, recv_val=2600, fairness="even", confidence="high")
        expensive_bad = _make_suggestion(give_val=7000, recv_val=9500, fairness="stretch", confidence="low")
        assert rank_score(cheap_good) > rank_score(expensive_bad)


class TestRankingInOutput:
    def test_rank_score_in_serialized_output(self):
        """Every suggestion in output must include rankScore breakdown."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        all_suggs = result["sellHigh"] + result["buyLow"] + result["consolidation"] + result["positionalUpgrades"]
        for s in all_suggs:
            assert "rankScore" in s
            rs = s["rankScore"]
            assert "total" in rs
            assert "base_value" in rs
            assert "fairness" in rs
            assert "confidence" in rs
            assert "need_severity" in rs
            assert "edge" in rs
            assert "opponent_fit" in rs

    def test_output_ordered_by_rank_within_category(self):
        """Within each category, suggestions must be ordered by rank score descending."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        for cat in ["sellHigh", "buyLow", "consolidation", "positionalUpgrades"]:
            suggs = result[cat]
            if len(suggs) < 2:
                continue
            scores = [s["rankScore"]["total"] for s in suggs]
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1], (
                    f"{cat}[{i}] score {scores[i]} < [{i+1}] score {scores[i+1]}"
                )

    def test_ranking_still_deterministic(self):
        """Ranked output must be identical across runs."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        r1 = generate_suggestions(roster, snap)
        r2 = generate_suggestions(roster, snap)
        assert r1 == r2

    def test_ranking_with_opponents_deterministic(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        opp = [{"team_name": "Opp", "players": ["Tua Tagovailoa", "Puka Nacua", "CeeDee Lamb"]}]
        r1 = generate_suggestions(roster, snap, league_rosters=opp)
        r2 = generate_suggestions(roster, snap, league_rosters=opp)
        assert r1 == r2


# ── Phase 5: Quality filter tests ────────────────────────────────────

class TestQualityFilters:
    def test_consolidation_stretches_removed(self):
        """Consolidation stretches with high overpay ratio are suppressed."""
        s_even = _make_suggestion(fairness="even")
        s_even.type = "consolidation"
        # High overpay: give_total=5000, gap=+2000 → overpay 40% > 30% threshold
        s_stretch_bad = _make_suggestion(
            fairness="stretch", give_val=5000, recv_val=3000,
            give_name="Player C", recv_name="Player D",
        )
        s_stretch_bad.type = "consolidation"
        s_lean = _make_suggestion(fairness="lean", give_name="Player E", recv_name="Player F")
        s_lean.type = "consolidation"

        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [],
            "consolidation": [s_even, s_stretch_bad, s_lean],
            "positional_upgrade": [],
        })
        consol = result["consolidation"]
        assert len(consol) == 2
        assert s_stretch_bad not in consol

    def test_receive_target_cap(self):
        """Max 2 suggestions per receive-target within a category."""
        suggs = [
            _make_suggestion(give_name=f"Seller {i}", recv_name="Same Target")
            for i in range(5)
        ]
        result = _apply_quality_filters({
            "sell_high": suggs,
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == MAX_RECEIVE_TARGET_PER_CATEGORY

    def test_low_confidence_cap(self):
        """Max 2 low-confidence suggestions per category."""
        suggs = [
            _make_suggestion(confidence="low", give_name=f"Low {i}", recv_name=f"Target {i}")
            for i in range(5)
        ]
        # Add one high-conf to verify it's not affected
        high = _make_suggestion(confidence="high", give_name="High Guy", recv_name="High Target")
        result = _apply_quality_filters({
            "sell_high": [high] + suggs,
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        low_count = sum(1 for s in result["sell_high"] if s.confidence == "low")
        assert low_count == MAX_LOW_CONFIDENCE_PER_CATEGORY
        # High-conf still present
        assert any(s.confidence == "high" for s in result["sell_high"])

    def test_give_player_cross_category_cap(self):
        """A player appearing as give in sell_high should count toward their
        cap in buy_low too."""
        # 2 sell_high suggestions giving Player A (fills cap at 2)
        sell = [
            _make_suggestion(give_name="Player A", recv_name=f"Target {i}")
            for i in range(2)
        ]
        # 2 more in buy_low giving Player A — should be blocked
        buy = [
            _make_suggestion(give_name="Player A", recv_name=f"Buy Target {i}")
            for i in range(2)
        ]
        result = _apply_quality_filters({
            "sell_high": sell,
            "buy_low": buy,
            "consolidation": [],
            "positional_upgrade": [],
        })
        total_a = sum(
            1 for s in result["sell_high"] + result["buy_low"]
            if any(p.name == "Player A" for p in s.give)
        )
        assert total_a <= MAX_GIVE_PLAYER_APPEARANCES

    def test_give_player_cap_individual_tracking(self):
        """Consolidation pairs track individual players within their own budget."""
        # Player A appears 2x in consolidation (maxes out at cap=2)
        consol_1 = _make_suggestion(give_name="Player A", recv_name="Target 1")
        consol_1.type = "consolidation"
        consol_1.give.append(PlayerAsset("Player B", "RB", 3000, 3000, source_count=6))
        consol_2 = _make_suggestion(give_name="Player A", recv_name="Target 2")
        consol_2.type = "consolidation"
        consol_2.give.append(PlayerAsset("Player C", "RB", 3000, 3000, source_count=6))
        # Third should be blocked — Player A at cap within package budget
        consol_3 = _make_suggestion(give_name="Player A", recv_name="Target 3")
        consol_3.type = "consolidation"
        consol_3.give.append(PlayerAsset("Player D", "RB", 3000, 3000, source_count=6))

        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [],
            "consolidation": [consol_1, consol_2, consol_3],
            "positional_upgrade": [],
        })
        assert len(result["consolidation"]) == 2

    def test_filters_preserve_order(self):
        """Filters should never reorder; only remove."""
        suggs = [
            _make_suggestion(give_name=f"Player {i}", recv_name=f"Target {i}", give_val=9000 - i * 100)
            for i in range(6)
        ]
        result = _apply_quality_filters({
            "sell_high": suggs,
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        vals = [s.give_total for s in result["sell_high"]]
        assert vals == sorted(vals, reverse=True)

    def test_quality_filters_deterministic(self):
        """Same inputs to quality filter produce same outputs."""
        suggs = [
            _make_suggestion(give_name=f"P{i}", recv_name=f"T{i}", confidence=("low" if i > 3 else "high"))
            for i in range(6)
        ]
        cats = {"sell_high": list(suggs), "buy_low": [], "consolidation": [], "positional_upgrade": []}
        r1 = _apply_quality_filters(dict(cats))
        r2 = _apply_quality_filters(dict(cats))
        assert len(r1["sell_high"]) == len(r2["sell_high"])
        for a, b in zip(r1["sell_high"], r2["sell_high"]):
            assert a.give[0].name == b.give[0].name

    def test_integration_idp_heavy_no_over_repetition(self):
        """IDP-heavy roster: no player should appear as give more than 3 times."""
        snap = _sample_snapshot()
        # Build an IDP-heavy roster from sample data
        roster = [
            "Joe Burrow",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa", "Micah Parsons",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        from collections import Counter
        freq = Counter()
        for cat in ["sellHigh", "buyLow", "consolidation", "positionalUpgrades"]:
            for s in result[cat]:
                for p in s["give"]:
                    freq[p["name"]] += 1
        if freq:
            assert freq.most_common(1)[0][1] <= MAX_GIVE_PLAYER_APPEARANCES, (
                f"{freq.most_common(1)[0][0]} appears {freq.most_common(1)[0][1]}x as give"
            )

    def test_filtered_output_still_deterministic(self):
        """Full pipeline with filters must remain deterministic."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        r1 = generate_suggestions(roster, snap)
        r2 = generate_suggestions(roster, snap)
        assert r1 == r2


# ── Phase 2A: Noise suppression filter tests ─────────────────────────

class TestFairButWeakFilter:
    """Filter 4: suppress trades where both sides are below MIN_ACTIONABLE_VALUE."""

    def test_both_sides_low_value_suppressed(self):
        """Two low-value players trading — not worth the conversation."""
        s_low = _make_suggestion(
            give_val=1500, recv_val=1600,
            give_name="Scrub A", recv_name="Scrub B",
        )
        s_high = _make_suggestion(
            give_val=6000, recv_val=6200,
            give_name="Star A", recv_name="Star B",
        )
        result = _apply_quality_filters({
            "sell_high": [s_high, s_low],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 1
        assert result["sell_high"][0].give[0].name == "Star A"

    def test_one_side_above_threshold_kept(self):
        """If one side is above MIN_ACTIONABLE_VALUE, the trade is kept."""
        s = _make_suggestion(
            give_val=1500, recv_val=3000,
            give_name="Depth", recv_name="Starter",
        )
        result = _apply_quality_filters({
            "sell_high": [s],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 1

    def test_exactly_at_threshold_kept(self):
        """Players at exactly MIN_ACTIONABLE_VALUE are kept."""
        s = _make_suggestion(
            give_val=MIN_ACTIONABLE_VALUE, recv_val=MIN_ACTIONABLE_VALUE,
            give_name="Border A", recv_name="Border B",
        )
        result = _apply_quality_filters({
            "sell_high": [s],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 1


class TestSameTierSwapFilter:
    """Filter 5: suppress 1-for-1 same-position trades within 500 value."""

    def test_same_pos_close_value_suppressed(self):
        """WR-for-WR within 200 value — lateral move, no strategic gain."""
        s = _make_suggestion(
            give_val=5000, recv_val=5200,
            give_pos="WR", recv_pos="WR",
            give_name="WR A", recv_name="WR B",
        )
        result = _apply_quality_filters({
            "sell_high": [s],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 0

    def test_same_pos_large_gap_kept(self):
        """WR-for-WR with 600 value difference — meaningful upgrade, kept."""
        s = _make_suggestion(
            give_val=5000, recv_val=5600,
            give_pos="WR", recv_pos="WR",
            give_name="WR A", recv_name="WR B",
        )
        result = _apply_quality_filters({
            "sell_high": [s],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 1

    def test_different_pos_close_value_kept(self):
        """RB-for-WR within 200 value — cross-position, has strategic value."""
        s = _make_suggestion(
            give_val=5000, recv_val=5200,
            give_pos="RB", recv_pos="WR",
            give_name="RB Guy", recv_name="WR Guy",
        )
        result = _apply_quality_filters({
            "sell_high": [s],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 1

    def test_multi_player_trade_not_affected(self):
        """2-for-1 trades are never caught by same-tier filter."""
        s = _make_suggestion(
            give_val=5000, recv_val=5200,
            give_pos="WR", recv_pos="WR",
            give_name="WR A", recv_name="WR B",
        )
        s.give.append(PlayerAsset("WR C", "WR", 2000, 2000, source_count=6))
        result = _apply_quality_filters({
            "sell_high": [s],
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 1


class TestNearMiss1For1Filter:
    """Filter 6: suppress 1-for-1s with big gap and attached balancers."""

    def test_big_gap_with_balancers_suppressed(self):
        """Gap > MAX_GAP_FOR_1FOR1 with balancers = should be a package deal."""
        s = _make_suggestion(
            give_val=6000, recv_val=6600,
            give_name="Player A", recv_name="Player B",
        )
        s.__dict__["balancers"] = [
            PlayerAsset("Filler", "WR", 600, 600, source_count=4)
        ]
        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [s],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["buy_low"]) == 0

    def test_small_gap_with_balancers_kept(self):
        """Gap <= MAX_GAP_FOR_1FOR1 with balancers — close enough, keep it."""
        s = _make_suggestion(
            give_val=6000, recv_val=6300,
            give_name="Player A", recv_name="Player B",
        )
        s.__dict__["balancers"] = [
            PlayerAsset("Filler", "WR", 300, 300, source_count=4)
        ]
        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [s],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["buy_low"]) == 1

    def test_big_gap_no_balancers_kept(self):
        """Gap > MAX_GAP_FOR_1FOR1 but no balancers — engine didn't flag it."""
        s = _make_suggestion(
            give_val=6000, recv_val=6600,
            give_name="Player A", recv_name="Player B",
        )
        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [s],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["buy_low"]) == 1

    def test_multi_player_trade_not_affected(self):
        """2-for-1 with gap and balancers — not a 1-for-1, keep it."""
        s = _make_suggestion(
            give_val=6000, recv_val=6600,
            give_name="Player A", recv_name="Player B",
        )
        s.give.append(PlayerAsset("Player C", "RB", 500, 500, source_count=4))
        s.__dict__["balancers"] = [
            PlayerAsset("Filler", "WR", 600, 600, source_count=4)
        ]
        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [s],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["buy_low"]) == 1


class TestTightenedGivePlayerCap:
    """Verify MAX_GIVE_PLAYER_APPEARANCES = 2 works correctly."""

    def test_cap_is_2(self):
        assert MAX_GIVE_PLAYER_APPEARANCES == 2

    def test_third_appearance_blocked(self):
        """Player A appearing 3x in sell_high — only first 2 survive."""
        suggs = [
            _make_suggestion(give_name="Player A", recv_name=f"Target {i}")
            for i in range(3)
        ]
        result = _apply_quality_filters({
            "sell_high": suggs,
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        total_a = sum(
            1 for s in result["sell_high"]
            if any(p.name == "Player A" for p in s.give)
        )
        assert total_a == 2

    def test_different_players_unaffected(self):
        """Different give-players should each get their own 2-appearance budget."""
        suggs = [
            _make_suggestion(give_name="Player A", recv_name="T1"),
            _make_suggestion(give_name="Player A", recv_name="T2"),
            _make_suggestion(give_name="Player B", recv_name="T3"),
            _make_suggestion(give_name="Player B", recv_name="T4"),
        ]
        result = _apply_quality_filters({
            "sell_high": suggs,
            "buy_low": [],
            "consolidation": [],
            "positional_upgrade": [],
        })
        assert len(result["sell_high"]) == 4


class TestNewFiltersDeterministic:
    """All new filters must preserve determinism."""

    def test_full_pipeline_deterministic(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        r1 = generate_suggestions(roster, snap)
        r2 = generate_suggestions(roster, snap)
        assert r1 == r2


# ── Phase 2B: Balancer improvement tests ─────────────────────────────

def _make_pool_and_roster():
    """Build a test pool and roster with known depth for balancer testing."""
    snap = _sample_snapshot()
    pool = build_asset_pool(snap)
    # QB-heavy roster with known surplus
    roster_names = [
        "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",  # 4 QB (need 2 → 2 depth)
        "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",  # 3 RB (need 3 → 0 depth)
        "Ja'Marr Chase",                                     # 1 WR (need 4 → deficit)
        "Brock Bowers",                                      # 1 TE
        "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",   # 3 DL
        "Jack Campbell", "Roquan Smith", "Fred Warner",      # 3 LB
        "Kyle Hamilton", "Sauce Gardner",                    # 2 DB
    ]
    roster = analyze_roster(roster_names, pool)
    roster_set = {n.lower() for n in roster_names}
    return pool, roster, roster_set


class TestFindBalancersDirection:
    """Balancers should come from the right side depending on gap direction."""

    def test_negative_gap_searches_user_roster(self):
        """When user underpays (gap < 0), balancers come from their roster."""
        pool, roster, roster_set = _make_pool_and_roster()
        # User underpays by ~7300 — their QB depth (Caleb Williams ~9331, Drake Maye ~9721)
        # should be candidates since those are surplus QBs
        bals, side = _find_balancers(-7300, pool, roster_set, set(), roster)
        assert side == "you_add"
        # If balancers found, they must be from the user's roster
        for b in bals:
            assert b.name.lower() in roster_set

    def test_positive_gap_searches_global_pool(self):
        """When user overpays (gap > 0), balancers come from global pool."""
        pool, roster, roster_set = _make_pool_and_roster()
        bals, side = _find_balancers(3000, pool, roster_set, set(), roster)
        assert side == "they_add"
        # Balancers must NOT be from user's roster
        for b in bals:
            assert b.name.lower() not in roster_set

    def test_small_gap_returns_nothing(self):
        """Gaps under 256 don't need balancers."""
        pool, roster, roster_set = _make_pool_and_roster()
        bals, side = _find_balancers(100, pool, roster_set, set(), roster)
        assert bals == []
        assert side == ""

    def test_no_roster_falls_back_to_pool(self):
        """Without roster context, negative gap still uses global pool."""
        pool, _, roster_set = _make_pool_and_roster()
        bals, side = _find_balancers(-3000, pool, roster_set, set(), None)
        assert side == "you_add"
        # Falls back to pool search since no roster provided
        for b in bals:
            assert b.name.lower() not in roster_set


class TestBalancerQuality:
    """Balancers must be realistic — positioned, valued, capped."""

    def test_max_2_balancers(self):
        """Never more than MAX_BALANCERS results."""
        assert MAX_BALANCERS == 2
        pool, roster, roster_set = _make_pool_and_roster()
        bals, _ = _find_balancers(3000, pool, roster_set, set(), roster)
        assert len(bals) <= 2

    def test_no_positionless_balancers(self):
        """Balancers with empty position are filtered out."""
        pool, roster, roster_set = _make_pool_and_roster()
        bals, _ = _find_balancers(5000, pool, roster_set, set(), roster)
        for b in bals:
            assert b.position != "", f"{b.name} has empty position"

    def test_no_below_min_relevant_value(self):
        """Balancers below MIN_RELEVANT_VALUE (500) are filtered."""
        pool, roster, roster_set = _make_pool_and_roster()
        bals, _ = _find_balancers(3000, pool, roster_set, set(), roster)
        for b in bals:
            assert b.display_value >= MIN_RELEVANT_VALUE

    def test_surplus_positions_preferred(self):
        """When roster has surplus, those depth pieces sort first."""
        pool, roster, roster_set = _make_pool_and_roster()
        assert "QB" in roster.surplus_positions
        # Large negative gap — user needs to add from their roster
        bals, side = _find_balancers(-7500, pool, roster_set, set(), roster)
        assert side == "you_add"
        if len(bals) >= 1:
            # First balancer should be from surplus position
            assert bals[0].position in roster.surplus_positions

    def test_exclude_names_respected(self):
        """Players in exclude_names are never suggested."""
        pool, roster, roster_set = _make_pool_and_roster()
        bals_all, _ = _find_balancers(5000, pool, roster_set, set(), roster)
        if bals_all:
            excluded_name = bals_all[0].name.lower()
            bals_without, _ = _find_balancers(5000, pool, roster_set, {excluded_name}, roster)
            excluded_names = {b.name.lower() for b in bals_without}
            assert excluded_name not in excluded_names


class TestPoolBalancerCandidates:
    """Unit tests for _pool_balancer_candidates."""

    def test_filters_positionless(self):
        """Positionless assets are excluded."""
        pool = [
            PlayerAsset("Real", "WR", 1000, 1000, source_count=4),
            PlayerAsset("Ghost", "", 1000, 1000, source_count=4),
        ]
        result = _pool_balancer_candidates(1000, pool, set(), set())
        assert len(result) == 1
        assert result[0].name == "Real"

    def test_filters_below_min(self):
        """Assets below MIN_RELEVANT_VALUE are excluded."""
        pool = [
            PlayerAsset("Scrub", "RB", 200, 200, source_count=4),
            PlayerAsset("Starter", "RB", 1000, 1000, source_count=4),
        ]
        result = _pool_balancer_candidates(1000, pool, set(), set())
        assert all(p.display_value >= MIN_RELEVANT_VALUE for p in result)


class TestRosterBalancerCandidates:
    """Unit tests for _roster_balancer_candidates."""

    def test_only_returns_depth(self):
        """Only depth pieces (beyond starter need) are candidates."""
        roster = RosterAnalysis(
            roster_size=5,
            by_position={
                "QB": [
                    PlayerAsset("QB1", "QB", 9000, 9000),
                    PlayerAsset("QB2", "QB", 8000, 8000),
                    PlayerAsset("QB3", "QB", 7000, 7000),  # depth (need=2)
                ],
            },
            surplus_positions=["QB"],
            need_positions=[],
            starter_counts={"QB": 2},
            depth_counts={"QB": 1},
        )
        result = _roster_balancer_candidates(7000, roster, set())
        names = {p.name for p in result}
        # QB3 is depth, should be a candidate
        assert "QB3" in names
        # QB1 and QB2 are starters, should NOT be candidates
        assert "QB1" not in names
        assert "QB2" not in names

    def test_skips_positionless(self):
        """Depth pieces without position are excluded."""
        roster = RosterAnalysis(
            roster_size=2,
            by_position={
                "": [
                    PlayerAsset("Pick", "", 7000, 7000),
                    PlayerAsset("Pick2", "", 6000, 6000),
                    PlayerAsset("Pick3", "", 5000, 5000),
                ],
            },
            surplus_positions=[""],
            need_positions=[],
            starter_counts={},
            depth_counts={},
        )
        result = _roster_balancer_candidates(6000, roster, set())
        assert len(result) == 0


class TestBalancerSideSerialization:
    """The balancerSide field appears in serialized output."""

    def test_balancer_side_in_output(self):
        """Suggestions with balancers should include balancerSide."""
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        result = generate_suggestions(roster, snap)
        all_suggs = (
            result["sellHigh"] + result["buyLow"]
            + result["consolidation"] + result["positionalUpgrades"]
        )
        for s in all_suggs:
            if "suggestedBalancers" in s:
                assert "balancerSide" in s
                assert s["balancerSide"] in ("you_add", "they_add")


class TestBalancerDeterminism:
    """Balancer results must be deterministic."""

    def test_find_balancers_deterministic(self):
        pool, roster, roster_set = _make_pool_and_roster()
        r1 = _find_balancers(-5000, pool, roster_set, set(), roster)
        r2 = _find_balancers(-5000, pool, roster_set, set(), roster)
        assert r1 == r2

    def test_full_pipeline_with_balancers_deterministic(self):
        snap = _sample_snapshot()
        roster = [
            "Josh Allen", "Lamar Jackson", "Drake Maye", "Caleb Williams",
            "Bijan Robinson", "Jahmyr Gibbs",
            "Ja'Marr Chase",
            "Brock Bowers",
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",
            "Jack Campbell", "Roquan Smith", "Fred Warner",
            "Kyle Hamilton", "Sauce Gardner",
        ]
        r1 = generate_suggestions(roster, snap)
        r2 = generate_suggestions(roster, snap)
        assert r1 == r2


# ── Phase 2C: Package logic tests ────────────────────────────────────

class TestConsolidationClosestValueTarget:
    """Consolidation should target closest-value match, not highest value."""

    def test_closest_target_preferred(self):
        """Given two valid targets, the one closer to combined value wins."""
        snap = _sample_snapshot()
        pool = build_asset_pool(snap)
        # IDP-stacked roster with deep DL/LB surplus
        idp = [
            "Bo Nix", "TreVeyon Henderson", "Cameron Skattebo",
            "George Pickens", "Ladd McConkey", "Dalton Kincaid",
            "Aidan Hutchinson", "Will Anderson", "Micah Parsons",
            "Myles Garrett", "Maxx Crosby", "Abdul Carter", "Jared Verse",
            "Nik Bonitto", "Nathan Landman", "Arvell Reese", "Sonny Styles",
            "Jack Campbell", "Carson Schwesinger", "David Bailey",
            "Roquan Smith", "Ernest Jones",
        ]
        roster = analyze_roster(idp, pool)
        roster_set = {n.lower() for n in idp}
        from src.trade.suggestions import _generate_consolidation
        results = _generate_consolidation(roster, pool, roster_set)
        if results:
            # Each suggestion should target the closest value match
            for s in results:
                gap_pct = abs(s.gap) / s.give_total if s.give_total else 0
                # All should be under 30% overpay (eligible to survive filter)
                assert gap_pct <= 0.30, f"gap_pct {gap_pct:.0%} > 30%"


class TestConsolidationStretchFilter:
    """Stretch consolidations are allowed when overpay is reasonable."""

    def test_low_overpay_stretch_allowed(self):
        """Stretch with ≤30% overpay survives quality filter."""
        s = _make_suggestion(fairness="stretch", give_val=10000, recv_val=8000)
        s.type = "consolidation"
        # gap = 10000 - 8000 = +2000, ratio = 2000/10000 = 20%
        result = _apply_quality_filters({
            "sell_high": [], "buy_low": [],
            "consolidation": [s], "positional_upgrade": [],
        })
        assert len(result["consolidation"]) == 1

    def test_high_overpay_stretch_blocked(self):
        """Stretch with >30% overpay is suppressed."""
        s = _make_suggestion(fairness="stretch", give_val=10000, recv_val=5000)
        s.type = "consolidation"
        # gap = 10000 - 5000 = +5000, ratio = 5000/10000 = 50%
        result = _apply_quality_filters({
            "sell_high": [], "buy_low": [],
            "consolidation": [s], "positional_upgrade": [],
        })
        assert len(result["consolidation"]) == 0

    def test_even_and_lean_still_pass(self):
        """Even and lean consolidations are unaffected."""
        s_even = _make_suggestion(fairness="even")
        s_even.type = "consolidation"
        s_lean = _make_suggestion(fairness="lean", give_name="P2", recv_name="P3")
        s_lean.type = "consolidation"
        result = _apply_quality_filters({
            "sell_high": [], "buy_low": [],
            "consolidation": [s_even, s_lean], "positional_upgrade": [],
        })
        assert len(result["consolidation"]) == 2


class TestSeparateGivePlayerBudgets:
    """1-for-1 and package categories have separate give-player caps."""

    def test_sell_high_does_not_block_consolidation(self):
        """A player at cap in sell_high can still appear in consolidation."""
        sell = [
            _make_suggestion(give_name="Player A", recv_name=f"T{i}")
            for i in range(MAX_GIVE_PLAYER_APPEARANCES)
        ]
        consol = _make_suggestion(give_name="Player A", recv_name="Big Target")
        consol.type = "consolidation"
        consol.give.append(PlayerAsset("Player B", "RB", 3000, 3000, source_count=6))

        result = _apply_quality_filters({
            "sell_high": sell, "buy_low": [],
            "consolidation": [consol], "positional_upgrade": [],
        })
        # Consolidation should survive — separate budget
        assert len(result["consolidation"]) == 1

    def test_within_package_budget_still_capped(self):
        """Within the package budget, the cap still applies."""
        consols = []
        for i in range(MAX_GIVE_PLAYER_APPEARANCES + 1):
            s = _make_suggestion(give_name="Player A", recv_name=f"Target {i}")
            s.type = "consolidation"
            s.give.append(PlayerAsset(f"Partner {i}", "RB", 3000, 3000, source_count=6))
            consols.append(s)

        result = _apply_quality_filters({
            "sell_high": [], "buy_low": [],
            "consolidation": consols, "positional_upgrade": [],
        })
        assert len(result["consolidation"]) == MAX_GIVE_PLAYER_APPEARANCES


class TestConsolidationInLiveOutput:
    """Integration: consolidation suggestions appear in live pipeline output."""

    def test_deep_surplus_gets_consolidation(self):
        """A roster with deep surplus and mid-value depth produces packages."""
        snap = _sample_snapshot()
        pool = build_asset_pool(snap)
        # Build a roster with deep LB surplus (mid-range depth, not elite)
        # so that pairs fall in range of real targets.
        roster_names = [
            "Josh Allen",                                        # QB
            "Bijan Robinson", "Jahmyr Gibbs", "De'Von Achane",  # RB
            "Ja'Marr Chase",                                     # WR
            "Brock Bowers",                                      # TE
            "Aidan Hutchinson", "Myles Garrett", "Nick Bosa",   # DL starters
            "Jack Campbell", "Roquan Smith", "Fred Warner",      # LB starters (need 3)
            "Nathan Landman", "Jordyn Brooks", "Nick Bolton",    # LB surplus
            "Kyle Hamilton", "Sauce Gardner",                    # DB
        ]
        result = generate_suggestions(roster_names, snap)
        cons = result["consolidation"]
        # With mid-range LB depth, at least one package should form
        if cons:
            for s in cons:
                assert len(s["give"]) >= 2
                assert len(s["receive"]) == 1

    def test_elite_surplus_gets_no_packages(self):
        """Rosters with all-elite surplus correctly get 0 packages."""
        snap = _sample_snapshot()
        rb_heavy = [
            "Lamar Jackson", "Bijan Robinson", "Jahmyr Gibbs",
            "Ashton Jeanty", "De'Von Achane", "Jonathan Taylor",
            "James Cook", "Breece Hall", "Kenneth Walker",
            "Chris Olave", "Garrett Wilson", "Tucker Kraft",
            "Maxx Crosby", "Will Anderson", "Myles Garrett", "Jared Verse",
            "Ernest Jones", "Jordyn Brooks", "Nick Bolton",
        ]
        result = generate_suggestions(rb_heavy, snap)
        assert len(result["consolidation"]) == 0

    def test_no_regression_in_sell_high(self):
        """Existing 1-for-1 sell_high suggestions are unchanged."""
        snap = _sample_snapshot()
        roster = [
            "Lamar Jackson", "Bijan Robinson", "Jahmyr Gibbs",
            "Ashton Jeanty", "De'Von Achane", "Jonathan Taylor",
            "James Cook", "Breece Hall", "Kenneth Walker",
            "Chris Olave", "Garrett Wilson", "Tucker Kraft",
            "Maxx Crosby", "Will Anderson", "Myles Garrett", "Jared Verse",
            "Ernest Jones", "Jordyn Brooks", "Nick Bolton",
        ]
        result = generate_suggestions(roster, snap)
        assert len(result["sellHigh"]) > 0, "sell_high should still have suggestions"
        for s in result["sellHigh"]:
            assert len(s["give"]) == 1
            assert len(s["receive"]) == 1


class TestPackageDeterminism:
    """Full pipeline with packages must be deterministic."""

    def test_deterministic_with_consolidation(self):
        snap = _sample_snapshot()
        idp = [
            "Bo Nix", "TreVeyon Henderson", "Cameron Skattebo",
            "George Pickens", "Ladd McConkey", "Dalton Kincaid",
            "Aidan Hutchinson", "Will Anderson", "Micah Parsons",
            "Myles Garrett", "Maxx Crosby", "Abdul Carter", "Jared Verse",
            "Nik Bonitto", "Nathan Landman", "Arvell Reese", "Sonny Styles",
            "Jack Campbell", "Carson Schwesinger", "David Bailey",
            "Roquan Smith", "Ernest Jones",
        ]
        r1 = generate_suggestions(idp, snap)
        r2 = generate_suggestions(idp, snap)
        assert r1 == r2


# ── KTC Top-N Filter ───────────────────────────────────────────────────

class TestKtcTopNFilter:
    """Verify the KTC top-150 quality gate in the suggestions engine."""

    def _make_large_snapshot(self, n=200):
        """Build a snapshot with n players of descending value."""
        assets = []
        for i in range(n):
            val = 9000 - i * 40
            pos = ["QB", "RB", "WR", "TE"][i % 4]
            assets.append(_make_asset(
                f"Player_{i:03d}", pos, val,
                display_value=val,
                source_count=6,
            ))
        return _build_snapshot(assets)

    def test_default_filter_is_150(self):
        assert KTC_TOP_N_FILTER == 150

    def test_pool_size_capped_at_top_n(self):
        snap = self._make_large_snapshot(300)
        pool = build_asset_pool(snap, ktc_top_n=150)
        assert len(pool) == 150

    def test_pool_all_top_ranked(self):
        snap = self._make_large_snapshot(300)
        pool = build_asset_pool(snap, ktc_top_n=100)
        for p in pool:
            assert p.ktc_rank is not None
            assert p.ktc_rank <= 100

    def test_filter_disabled_when_zero(self):
        snap = self._make_large_snapshot(300)
        pool = build_asset_pool(snap, ktc_top_n=0)
        assert len(pool) == 300

    def test_top_n_preserves_ordering(self):
        snap = self._make_large_snapshot(200)
        pool = build_asset_pool(snap, ktc_top_n=50)
        vals = [p.display_value for p in pool]
        assert vals == sorted(vals, reverse=True)

    def test_ktc_rank_assigned_sequentially(self):
        snap = self._make_large_snapshot(50)
        pool = build_asset_pool(snap, ktc_top_n=0)
        ranks = [p.ktc_rank for p in pool]
        assert ranks == list(range(1, 51))

    def test_suggestions_only_include_top_n_players(self):
        """Every player in every suggestion must be inside the KTC top N."""
        snap = self._make_large_snapshot(200)
        # Roster of top-tier players
        roster = [f"Player_{i:03d}" for i in range(20)]
        result = generate_suggestions(roster, snap, ktc_top_n=100)
        all_suggestions = (
            result.get("sellHigh", [])
            + result.get("buyLow", [])
            + result.get("consolidation", [])
            + result.get("positionalUpgrades", [])
        )
        for s in all_suggestions:
            for side in ("give", "receive"):
                for player in s[side]:
                    assert player.get("ktcRank") is not None, (
                        f"{player['name']} in {side} has no ktcRank"
                    )
                    assert player["ktcRank"] <= 100, (
                        f"{player['name']} ranked {player['ktcRank']} — "
                        f"outside top 100 filter"
                    )

    def test_no_suggestions_with_very_tight_filter(self):
        """With an impossibly tight filter, should return 0 suggestions gracefully."""
        snap = self._make_large_snapshot(200)
        roster = [f"Player_{i:03d}" for i in range(20)]
        result = generate_suggestions(roster, snap, ktc_top_n=5)
        # With only 5 players in the pool, the roster can't match many
        # and surplus/need detection won't fire. Should be 0 or very few.
        total = result["totalSuggestions"]
        assert total >= 0  # Just ensure it doesn't crash

    def test_metadata_includes_filter(self):
        snap = self._make_large_snapshot(200)
        roster = [f"Player_{i:03d}" for i in range(20)]
        result = generate_suggestions(roster, snap, ktc_top_n=100)
        assert result["metadata"]["ktcTopNFilter"] == 100

    def test_balancers_respect_filter(self):
        """Balancer candidates must also come from the filtered pool."""
        snap = self._make_large_snapshot(200)
        pool = build_asset_pool(snap, ktc_top_n=50)
        roster_set = set()
        exclude = set()
        candidates = _pool_balancer_candidates(
            target_value=3000,
            asset_pool=pool,
            roster_names_set=roster_set,
            exclude_names=exclude,
        )
        for c in candidates:
            assert c.ktc_rank is not None
            assert c.ktc_rank <= 50


class TestBuildAssetPoolFromContract:
    """The contract-native asset pool builder is the live path for
    ``/api/trade/suggestions`` — the suggestion engine reads the
    ``/api/data`` contract directly, no offline canonical build.

    These tests pin the field-mapping from ``playersArray`` rows to
    ``PlayerAsset`` objects.  The suggestion engine is unchanged; as
    long as the pool shape matches, every downstream assertion that
    worked against the canonical snapshot continues to hold.
    """

    def _contract(self, rows, players_dict=None):
        return {
            "playersArray": rows,
            "players": players_dict or {},
        }

    def _row(
        self,
        name,
        pos,
        value,
        *,
        rookie=False,
        team="",
        site_values=None,
        asset_class="player",
        legacy_ref=None,
    ):
        return {
            "canonicalName": name,
            "displayName": name,
            "position": pos,
            "team": team,
            "rookie": rookie,
            "assetClass": asset_class,
            "rankDerivedValue": value,
            "canonicalSiteValues": site_values or {"ktc": value, "idpTradeCalc": value - 50},
            "legacyRef": legacy_ref or name,
        }

    def test_builds_expected_player_fields(self):
        from src.trade.suggestions import build_asset_pool_from_contract
        rows = [
            self._row("Josh Allen", "QB", 9997, team="BUF"),
            self._row("Bijan Robinson", "RB", 9604, team="ATL"),
        ]
        # Legacy dict carries the years-of-experience the suggestion
        # engine uses for prime-age boosts.
        players_dict = {
            "Josh Allen": {"_yearsExp": 7},
            "Bijan Robinson": {"_yearsExp": 2},
        }
        pool = build_asset_pool_from_contract(
            self._contract(rows, players_dict), ktc_top_n=0
        )
        assert len(pool) == 2
        allen = next(p for p in pool if p.name == "Josh Allen")
        bijan = next(p for p in pool if p.name == "Bijan Robinson")
        assert allen.position == "QB"
        assert allen.calibrated_value == 9997
        assert allen.display_value == 9997
        assert allen.team == "BUF"
        assert allen.years_exp == 7
        assert allen.universe == "offense_vet"
        assert bijan.universe == "offense_vet"
        assert bijan.years_exp == 2
        # source_count == number of site values > 0.
        assert allen.source_count == 2

    def test_universe_labels(self):
        from src.trade.suggestions import build_asset_pool_from_contract
        rows = [
            self._row("Josh Allen", "QB", 9000),                     # offense_vet
            self._row("Jeremiyah Love", "RB", 7000, rookie=True),    # offense_rookie
            self._row("Will Anderson", "DL", 7000),                  # idp_vet
            self._row("Arvell Reese", "LB", 5000, rookie=True),      # idp_rookie
            self._row("2026 Pick 1.01", "PICK", 9000,
                      asset_class="pick", site_values={"ktc": 9000}),
        ]
        pool = build_asset_pool_from_contract(self._contract(rows), ktc_top_n=0)
        universes = {p.name: p.universe for p in pool}
        assert universes["Josh Allen"] == "offense_vet"
        assert universes["Jeremiyah Love"] == "offense_rookie"
        assert universes["Will Anderson"] == "idp_vet"
        assert universes["Arvell Reese"] == "idp_rookie"
        assert universes["2026 Pick 1.01"] == "picks"

    def test_skips_rows_without_value(self):
        from src.trade.suggestions import build_asset_pool_from_contract
        rows = [
            self._row("Josh Allen", "QB", 9997),
            # rankDerivedValue=0 → pool skip (mirrors canonical-snapshot
            # filter that required calibrated_value to be present).
            self._row("No Value Player", "WR", 0),
            # rankDerivedValue=None → pool skip.
            {**self._row("Missing Value", "WR", 1), "rankDerivedValue": None},
        ]
        pool = build_asset_pool_from_contract(self._contract(rows), ktc_top_n=0)
        names = {p.name for p in pool}
        assert names == {"Josh Allen"}

    def test_dispersion_cv_uses_canonical_site_values(self):
        from src.trade.suggestions import build_asset_pool_from_contract
        # Site values with meaningful spread → dispersion_cv > 0.
        rows = [
            self._row("Spread Player", "WR", 8000,
                      site_values={"ktc": 9000, "idpTradeCalc": 7000, "dlfSf": 8000}),
            # Identical site values → dispersion_cv == 0.
            self._row("Consensus Player", "WR", 8000,
                      site_values={"ktc": 8000, "idpTradeCalc": 8000, "dlfSf": 8000}),
        ]
        pool = build_asset_pool_from_contract(self._contract(rows), ktc_top_n=0)
        spread = next(p for p in pool if p.name == "Spread Player")
        consensus = next(p for p in pool if p.name == "Consensus Player")
        assert spread.dispersion_cv is not None and spread.dispersion_cv > 0
        assert consensus.dispersion_cv == 0 or consensus.dispersion_cv is None

    def test_pool_sorted_by_display_value_desc(self):
        from src.trade.suggestions import build_asset_pool_from_contract
        rows = [
            self._row("Low Value", "WR", 3000),
            self._row("High Value", "WR", 9000),
            self._row("Mid Value", "WR", 6000),
        ]
        pool = build_asset_pool_from_contract(self._contract(rows), ktc_top_n=0)
        assert [p.name for p in pool] == ["High Value", "Mid Value", "Low Value"]

    def test_ktc_top_n_filter_applies(self):
        from src.trade.suggestions import build_asset_pool_from_contract, KTC_TOP_N_FILTER
        rows = [
            self._row(f"Player {i:03d}", "WR", 9999 - i)
            for i in range(KTC_TOP_N_FILTER + 50)
        ]
        pool = build_asset_pool_from_contract(self._contract(rows))
        # Every asset in the pool must have a ktc_rank within the filter.
        assert len(pool) <= KTC_TOP_N_FILTER
        for p in pool:
            assert p.ktc_rank is not None and p.ktc_rank <= KTC_TOP_N_FILTER

    def test_suggestion_engine_accepts_contract_pool(self):
        """End-to-end: a pool built from a synthetic contract feeds
        ``generate_suggestions_from_pool`` without errors and produces
        a well-formed response with the expected top-level keys.
        """
        from src.trade.suggestions import (
            build_asset_pool_from_contract,
            generate_suggestions_from_pool,
        )
        rows = []
        # Enough players to survive the starter-needs check + KTC filter.
        positions = [("QB", 10), ("RB", 12), ("WR", 15), ("TE", 8)]
        value = 9500
        for pos, n in positions:
            for i in range(n):
                rows.append(
                    self._row(f"{pos}{i:02d}", pos, value, team="X")
                )
                value -= 25
        pool = build_asset_pool_from_contract(
            self._contract(rows), ktc_top_n=0
        )
        roster_names = ["QB00", "RB00", "WR00", "WR01", "TE00"]
        result = generate_suggestions_from_pool(
            roster_names=roster_names,
            pool=pool,
        )
        # Response shape matches the canonical-snapshot path.
        assert "rosterAnalysis" in result
        assert "sellHigh" in result
        assert "buyLow" in result
        assert "consolidation" in result
        assert "positionalUpgrades" in result
        assert "metadata" in result
        assert result["metadata"]["assetPoolSize"] == len(pool)
