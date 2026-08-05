"""The suggestion engine's quality gate cuts per asset class.

Audit findings W09-F004, W27-F002, W09-F001 (root cause R7).

``BOARD_TOP_N_FILTER`` used to be a single global cut over one ranked
list spanning offense, IDP and picks.  Those populations do not share a
ceiling — on the live board offense peaks at 9,999, IDP at ~6,400 and DB
at 3,159 — so the cut removed an entire position family: 0 of 96 DBs
survived, while ``rosterAnalysis.needPositions`` told all 12 managers to
target DB.

The gate is a QUALITY filter ("do not propose roster clog").  Quality is
defined inside a population, exactly as ``src/trade/finder.py`` already
ranks each retail market's own population from 1.  These tests pin that.
"""

from __future__ import annotations


from src.trade.suggestions import (
    build_asset_pool_from_contract,
    generate_suggestions_from_pool,
)


def _contract(rows: list[tuple[str, str, int]]) -> dict:
    """Minimal live-contract shape: (name, position, rankDerivedValue)."""
    return {
        "playersArray": [
            {"canonicalName": n, "position": p, "rankDerivedValue": v} for n, p, v in rows
        ],
        "players": {},
    }


def _board() -> dict:
    """A board shaped like the live one: offense owns the top, DB the floor.

    200 offense rows run 9,999 → 4,030.  The 150th row overall is an
    offense row, so under a single global top-150 no defender and no
    pick can ever qualify.
    """
    rows: list[tuple[str, str, int]] = []
    off_positions = ["WR", "RB", "QB", "TE"]
    for i in range(200):
        rows.append((f"Off_{i:03d}", off_positions[i % 4], 9999 - i * 30))
    for i in range(60):
        rows.append((f"Dl_{i:03d}", "DL", 3900 - i * 40))
    for i in range(50):
        rows.append((f"Lb_{i:03d}", "LB", 3700 - i * 40))
    for i in range(90):
        rows.append((f"Db_{i:03d}", "DB", 3159 - i * 25))
    for i in range(40):
        rows.append((f"20{26 + i % 3} Pick 1.{i:02d}", "PICK", 3500 - i * 60))
    return _contract(rows)


# A roster deep enough at offense to have something to trade and thin
# enough at IDP to have somewhere to trade it, so the generators fire.
_DEEP_ROSTER = [f"Off_{i:03d}" for i in range(0, 80, 2)] + [f"Db_{i:03d}" for i in range(4)]


class TestPerClassGate:
    def test_no_family_is_structurally_excluded(self):
        """Every family on the board reaches the pool (W09-F004)."""
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        positions = {a.position for a in pool}
        assert "DB" in positions, "the whole DB family was gated out of the pool"
        assert {"DL", "LB", "PICK"} <= positions

    def test_low_ceiling_family_is_ranked_inside_its_own_population(self):
        """The best DB qualifies even though its GLOBAL rank is past the cut."""
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        dbs = [a for a in pool if a.position == "DB"]
        assert dbs, "no DB survived the gate"
        best = max(dbs, key=lambda a: a.display_value)
        # This is the whole point: it is outside the top 150 overall and
        # inside the top 150 of its own class.
        assert best.board_rank > 150
        assert best.class_rank is not None and best.class_rank <= 150

    def test_board_rank_stays_the_global_board_rank(self):
        """``boardRank`` is published; the gate must not redefine it."""
        pool = build_asset_pool_from_contract(_board(), board_top_n=0)
        ranked = sorted(pool, key=lambda a: a.board_rank or 0)
        assert [a.board_rank for a in ranked] == list(range(1, len(pool) + 1))

    def test_a_class_smaller_than_the_cut_is_admitted_whole(self):
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        assert len([a for a in pool if a.position == "PICK"]) == 40

    def test_gate_of_zero_still_disables_the_filter(self):
        pool = build_asset_pool_from_contract(_board(), board_top_n=0)
        assert len(pool) == 440


class TestCoverageIsVisible:
    def test_metadata_stamps_per_class_coverage(self):
        """Follow finder.py's ``marketCoverage`` precedent (W09-F004)."""
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        result = generate_suggestions_from_pool(
            roster_names=[f"Off_{i:03d}" for i in range(20)],
            pool=pool,
            board_top_n=150,
        )
        meta = result["metadata"]
        cov = meta["assetClassCoverage"]
        assert cov["offense"] == 150
        assert cov["idp"] > 0
        assert cov["pick"] == 40
        # The pre-gate population makes the cut itself visible: 150 of
        # 150 and 150 of 900 are different states.
        pop = meta["assetClassPopulation"]
        assert pop["offense"] == 200
        assert pop["pick"] == 40
        assert meta["positionCoverage"]["DB"] > 0

    def test_position_coverage_names_a_family_the_pool_cannot_reach(self):
        """A family with no board rows is reported, not silently absent."""
        rows = [(f"Off_{i:03d}", "WR", 9000 - i * 20) for i in range(60)]
        pool = build_asset_pool_from_contract(_contract(rows), board_top_n=150)
        result = generate_suggestions_from_pool(
            roster_names=[f"Off_{i:03d}" for i in range(20)],
            pool=pool,
            starter_needs={"WR": 3, "DB": 3},
            board_top_n=150,
        )
        assert result["metadata"]["uncoveredStarterPositions"] == ["DB"]

    def test_an_unsatisfiable_need_is_not_advertised_as_advice(self):
        """No candidate exists, so 'target DB' is not a recommendation (W27-F002)."""
        rows = [(f"Off_{i:03d}", "WR", 9000 - i * 20) for i in range(60)]
        pool = build_asset_pool_from_contract(_contract(rows), board_top_n=150)
        result = generate_suggestions_from_pool(
            roster_names=[f"Off_{i:03d}" for i in range(20)],
            pool=pool,
            starter_needs={"WR": 3, "DB": 3},
            board_top_n=150,
        )
        assert "DB" not in result["rosterAnalysis"]["needPositions"]
        assert any("DB" in w for w in result["warnings"])

    def test_an_empty_feed_says_how_much_of_the_roster_it_read(self):
        """W09-F001: zero suggestions must read as 'not measured', not 'none exist'."""
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        result = generate_suggestions_from_pool(
            roster_names=[f"Ghost_{i}" for i in range(50)],
            pool=pool,
            board_top_n=150,
        )
        assert result["totalSuggestions"] == 0
        joined = " ".join(result["warnings"])
        assert "0" in joined and "50" in joined, joined

    def test_a_fully_matched_roster_carries_no_spurious_warning(self):
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        result = generate_suggestions_from_pool(
            roster_names=_DEEP_ROSTER,
            pool=pool,
            board_top_n=150,
        )
        assert result["totalSuggestions"] > 0
        assert isinstance(result["warnings"], list)
        assert result["warnings"] == []


class TestClassRankIsSerialized:
    def test_every_served_asset_carries_its_class_rank(self):
        pool = build_asset_pool_from_contract(_board(), board_top_n=150)
        result = generate_suggestions_from_pool(
            roster_names=_DEEP_ROSTER,
            pool=pool,
            board_top_n=150,
        )
        legs = [
            p
            for bucket in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades")
            for s in result[bucket]
            for p in s["give"] + s["receive"]
        ]
        assert legs, "fixture produced no suggestions to inspect"
        for leg in legs:
            assert leg["classRank"] is not None
            assert leg["classRank"] <= 150
            assert leg["assetClass"] in {"offense", "idp", "pick"}
