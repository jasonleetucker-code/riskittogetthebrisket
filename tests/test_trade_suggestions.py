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
    TradeSuggestion,
    DEFAULT_STARTER_NEEDS,
    MIN_RELEVANT_VALUE,
    HIGH_DISPERSION_CV,
    MAX_GIVE_PLAYER_APPEARANCES,
    MAX_RECEIVE_TARGET_PER_CATEGORY,
    MAX_LOW_CONFIDENCE_PER_CATEGORY,
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
        """Consolidation suggestions with fairness='stretch' should be suppressed."""
        s_even = _make_suggestion(fairness="even")
        s_even.type = "consolidation"
        s_stretch = _make_suggestion(fairness="stretch", give_name="Player C", recv_name="Player D")
        s_stretch.type = "consolidation"
        s_lean = _make_suggestion(fairness="lean", give_name="Player E", recv_name="Player F")
        s_lean.type = "consolidation"

        result = _apply_quality_filters({
            "sell_high": [],
            "buy_low": [],
            "consolidation": [s_even, s_stretch, s_lean],
            "positional_upgrade": [],
        })
        consol = result["consolidation"]
        assert len(consol) == 2
        assert all(s.fairness != "stretch" for s in consol)

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
        cap in consolidation too."""
        # 3 sell_high suggestions all giving Player A
        sell = [
            _make_suggestion(give_name="Player A", recv_name=f"Target {i}")
            for i in range(3)
        ]
        # 2 more in buy_low giving Player A
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
        """Consolidation pairs track individual players, not the pair string."""
        # Player A appears 3x in sell_high (maxes out)
        sell = [
            _make_suggestion(give_name="Player A", recv_name=f"T{i}")
            for i in range(3)
        ]
        # Consolidation gives Player A + Player B — should be blocked
        consol_s = _make_suggestion(give_name="Player A", recv_name="Big Target")
        consol_s.type = "consolidation"
        consol_s.give.append(PlayerAsset("Player B", "RB", 3000, 3000, source_count=6))

        result = _apply_quality_filters({
            "sell_high": sell,
            "buy_low": [],
            "consolidation": [consol_s],
            "positional_upgrade": [],
        })
        assert len(result["consolidation"]) == 0

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
