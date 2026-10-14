"""Trade Suggestions — owner inventory 2.3 / 2.4 (audit W09-F001, W27-F002).

Two measured defects and the repairs that close them:

* **Whole teams got zero suggestions with no reason.**  The roster was joined
  against the top-N quality pool, so every rostered player outside it vanished
  from the analysis; and an empty answer carried no ``noResultReason``.
* **Defensive backs were never recommended.**  The global top-N held no DBs, so
  a DB-needy team had no DB targets at all.  The positional floor admits each
  demanded position's starter-caliber population (``starters x teamCount``).

Also pinned: the positional-upgrade fallback sweetener respects protection, the
all-protected path answers the normal camelCase shape, needs come from the
canonical Team Weakness owner when supplied, and LOCK is honoured.
"""

from __future__ import annotations

from src.trade import suggestions as sg
from src.trade.constraints import resolve_constraints
from src.trade.suggestions import PlayerAsset, generate_suggestions_from_pool

NEEDS = {"QB": 2, "RB": 3, "WR": 4, "TE": 2, "DL": 3, "LB": 3, "DB": 3}


def _p(name, pos, value):
    return PlayerAsset(
        name=name, position=pos, display_value=value, calibrated_value=value, source_count=6
    )


def _board(players):
    """Rank a board the way ``build_asset_pool_from_contract`` does."""
    ordered = sorted(players, key=lambda p: -p.display_value)
    return sg._assign_board_ranks(ordered)


def _offense_heavy_board():
    """An offense board whose top-N holds no DB, plus a DB tier below it."""
    mine = [
        _p("QB One", "QB", 9000),
        _p("QB Two", "QB", 8800),
        _p("WR A", "WR", 8600),
        _p("WR B", "WR", 8400),
        _p("WR C", "WR", 8200),
        _p("WR D", "WR", 8000),
        _p("WR Spare1", "WR", 5100),
        _p("WR Spare2", "WR", 5000),
        _p("DB Weak1", "DB", 1000),
        _p("DB Weak2", "DB", 950),
        _p("DB Weak3", "DB", 900),
    ]
    others = [_p(f"Other QB{i}", "QB", 7800 - i * 10) for i in range(4)] + [
        _p(f"Other WR{i}", "WR", 7600 - i * 10) for i in range(6)
    ]
    db_targets = [_p("DB Star", "DB", 4950), _p("DB Good", "DB", 4900)]
    board = _board(mine + others + db_targets)
    roster = [p.name for p in mine]
    return board, roster


def test_db_targets_reach_a_db_needy_team_through_the_positional_floor():
    board, roster = _offense_heavy_board()
    top_n = sum(1 for p in board if p.display_value >= 5000)
    pool = sg._apply_board_top_n_filter(list(board), top_n)
    assert not any(p.position == "DB" for p in pool), "fixture: the top-N holds no DB"

    result = generate_suggestions_from_pool(
        roster,
        list(pool),
        starter_needs=NEEDS,
        roster_pool=board,
        team_count=2,
        weakness_needs=["DB"],
    )
    received = {
        p["position"]
        for cat in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades")
        for s in result[cat]
        for p in s["receive"]
    }
    assert "DB" in received, result
    floor = result["metadata"]["positionalFloor"]
    assert floor["applied"] and floor["addedByPosition"].get("DB", 0) >= 2
    assert result["metadata"]["needSource"]["source"] == "team_weakness_owner"


def test_without_roster_pool_the_legacy_behaviour_is_unchanged():
    board, roster = _offense_heavy_board()
    top_n = sum(1 for p in board if p.display_value >= 5000)
    pool = sg._apply_board_top_n_filter(list(board), top_n)
    legacy = generate_suggestions_from_pool(roster, list(pool), starter_needs=NEEDS)
    assert "positionalFloor" not in legacy["metadata"]
    assert "rosterAnalysisPool" not in legacy["metadata"]
    assert legacy["metadata"]["needSource"] == {"source": "startable_count"}


def test_the_roster_is_analysed_whole_not_through_the_quality_gate():
    """A rostered player outside the top-N still occupies his room."""
    board, roster = _offense_heavy_board()
    top_n = sum(1 for p in board if p.display_value >= 5000)
    pool = sg._apply_board_top_n_filter(list(board), top_n)
    legacy = generate_suggestions_from_pool(roster, list(pool), starter_needs=NEEDS)
    whole = generate_suggestions_from_pool(
        roster, list(pool), starter_needs=NEEDS, roster_pool=board, team_count=2
    )
    assert legacy["rosterAnalysis"]["rosterSize"] < whole["rosterAnalysis"]["rosterSize"]


def test_a_roster_player_the_board_cannot_price_is_named_not_dropped():
    """T-9: what the analysis could not see is published, by name."""
    board, roster = _offense_heavy_board()
    out = generate_suggestions_from_pool(
        [*roster, "Unpriced Rookie"],
        list(board),
        starter_needs=NEEDS,
        roster_pool=board,
        team_count=2,
    )
    meta = out["metadata"]
    assert meta["rosterUnpriced"] == ["Unpriced Rookie"]
    assert meta["rosterProvided"] == meta["rosterMatched"] + 1


def test_an_empty_answer_always_says_why():
    board, roster = _offense_heavy_board()
    # A quality pool with nothing this roster can offer.
    pool = sg._apply_board_top_n_filter(list(board), 2)
    result = generate_suggestions_from_pool(
        roster, list(pool), starter_needs=NEEDS, roster_pool=board, team_count=2
    )
    assert result["totalSuggestions"] == 0
    md = result["metadata"]
    assert md["noResultReason"] in {
        "no_surplus_or_need",
        "no_offerable_surplus_in_quality_pool",
        "no_need_positions",
        "no_targets_in_pool",
        "quality_filters_removed_all",
    }
    assert md["noResultLabel"].startswith("No qualifying trade found")
    assert "generated" in md["generatorDiagnostics"]


def test_all_protected_answers_the_normal_camelcase_shape():
    board, roster = _offense_heavy_board()
    c = resolve_constraints(persistent={"untouchables": roster})
    result = generate_suggestions_from_pool(roster, list(board), starter_needs=NEEDS, constraints=c)
    for key in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades"):
        assert result[key] == []
    assert result["totalSuggestions"] == 0
    assert "rosterAnalysis" in result
    assert result["metadata"]["noResultReason"] == "all_outgoing_assets_constrained"
    assert "sell_high" not in result


def test_the_upgrade_fallback_sweetener_respects_protection():
    """The widened surplus sweetener never checked ``can_send``."""
    players = [
        _p("WR1", "WR", 6000),
        _p("WR2", "WR", 5800),
        _p("WR3", "WR", 5600),
        _p("WR4", "WR", 3000),  # weakest starter
        _p("WR5", "WR", 2500),  # depth too far from the 1000 gap to sweeten
        _p("RB1", "RB", 7000),
        _p("RB2", "RB", 6900),
        _p("RB3", "RB", 6800),
        _p("RB Spare1", "RB", 2100),  # the only surplus body near the gap
        _p("RB Spare2", "RB", 3400),  # surplus, but too far from the gap
    ]
    target = _p("WR Target", "WR", 4000)
    board = _board(players + [target])
    roster = [p.name for p in players]
    needs = {"WR": 4, "RB": 3}

    open_ = sg.analyze_roster(roster, board, needs)
    free = sg._generate_positional_upgrades(open_, board, {sg._identity_key(n) for n in roster})
    assert any("RB Spare1" in {p.name for p in s.give} for s in free), "fixture sanity"

    c = resolve_constraints(persistent={"untouchables": ["RB Spare1"]})
    guarded = sg.analyze_roster(roster, board, needs, constraints=c)
    out = sg._generate_positional_upgrades(guarded, board, {sg._identity_key(n) for n in roster})
    for s in out:
        assert "RB Spare1" not in {p.name for p in s.give}


def test_lock_every_suggestion_sends_the_locked_player_or_it_explains():
    board, roster = _offense_heavy_board()
    c = resolve_constraints(refinement={"lock": ["WR Spare1"]})
    result = generate_suggestions_from_pool(
        roster,
        list(board),
        starter_needs=NEEDS,
        roster_pool=board,
        team_count=2,
        weakness_needs=["DB"],
        constraints=c,
    )
    sent = [
        {p["name"] for p in s["give"]}
        for cat in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades")
        for s in result[cat]
    ]
    assert sent, result
    assert all("WR Spare1" in give for give in sent)


def test_an_unsatisfiable_lock_is_a_no_result_under_constraints():
    board, roster = _offense_heavy_board()
    c = resolve_constraints(
        persistent={"untouchables": ["WR Spare1"]}, refinement={"lock": ["WR Spare1"]}
    )
    result = generate_suggestions_from_pool(roster, list(board), starter_needs=NEEDS, constraints=c)
    assert result["totalSuggestions"] == 0
    assert result["metadata"]["noResultReason"] == "lock_conflicts_with_protection"


def _deep_wr_board():
    """Independent review repro: nine spare WRs, DB targets at every value."""
    starters = [_p(f"WR Start{i}", "WR", 9000 - i) for i in range(4)]
    spares = [_p(f"WR S{i}", "WR", 6000 - 150 * i) for i in range(9)]
    dbs = [_p(f"DB Weak{i}", "DB", 900 - i) for i in range(3)]
    targets = [_p(f"DB T{i}", "DB", 6000 - 150 * i) for i in range(9)]
    board = _board(starters + spares + dbs + targets)
    return board, [p.name for p in starters + spares + dbs]


def test_a_lock_past_the_generators_caps_is_still_reached():
    """LOCK is a generation rule: a locked depth player beyond the top-3/top-2
    caps still produces his legal even trade instead of an empty answer."""
    board, roster = _deep_wr_board()
    for locked in ("WR S3", "WR S8"):
        c = resolve_constraints(refinement={"lock": [locked]})
        result = generate_suggestions_from_pool(
            roster, list(board), starter_needs=NEEDS, weakness_needs=["DB"], constraints=c
        )
        gives = [
            {p["name"] for p in s["give"]}
            for cat in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades")
            for s in result[cat]
        ]
        assert gives, (locked, result["metadata"])
        assert all(locked in g for g in gives)


def test_a_locked_player_below_the_quality_pool_says_so():
    board, roster = _deep_wr_board()
    pool = sg._apply_board_top_n_filter(list(board), 6)
    c = resolve_constraints(refinement={"lock": ["WR S8"]})
    result = generate_suggestions_from_pool(
        roster, list(pool), starter_needs=NEEDS, roster_pool=board, team_count=2, constraints=c
    )
    assert result["totalSuggestions"] == 0
    assert result["metadata"]["noResultReason"] == "locked_player_outside_quality_pool"
