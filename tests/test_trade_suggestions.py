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
    build_asset_pool,
    analyze_roster,
    generate_suggestions,
    _fairness_label,
    _norm_pos,
    DEFAULT_STARTER_NEEDS,
    MIN_RELEVANT_VALUE,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _make_asset(name, pos, cal_value, display_value=None, source_count=6,
                team="", rookie=False, years_exp=None):
    """Create a minimal canonical asset dict."""
    if display_value is None:
        display_value = max(1, round(cal_value * 9999 / 7800))
    return {
        "display_name": name,
        "calibrated_value": cal_value,
        "display_value": display_value,
        "source_values": {f"src{i}": 1 for i in range(source_count)},
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
