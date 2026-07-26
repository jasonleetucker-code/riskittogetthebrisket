"""Fixture-based tests for ``src.playerctx.normalize`` parsing +
aggregation.  Pins the live nflverse schemas and the exit-2 schema-
drift path.  No network."""

from __future__ import annotations

import pytest

from src.playerctx import normalize as norm
from src.playerctx.normalize import SchemaRegressionError
from tests.playerctx.conftest import (
    CONTRACTS_HEADER,
    DEPTH_HEADER,
    SNAPS_HEADER,
    write_csv,
)

# ── Contracts ────────────────────────────────────────────────────────


def _contract_row(
    name: str,
    pos: str = "QB",
    team: str = "Packers",
    active: str = "TRUE",
    year_signed: int = 2024,
    years: int = 4,
    value: int = 40_000_000,
    apy: int = 10_000_000,
    guaranteed: int = 20_000_000,
) -> str:
    return (
        f"{name},{pos},{team},{active},{year_signed},{years},{value},"
        f"{apy},{guaranteed},0.05,https://example.invalid,1,2020"
    )


class TestParseContracts:
    def test_active_filter_and_fields(self, tmp_path):
        p = write_csv(
            tmp_path / "contracts.csv",
            CONTRACTS_HEADER,
            [
                _contract_row("Aaron Example", active="TRUE"),
                _contract_row("Retired Guy", active="FALSE"),
            ],
        )
        rows = norm.parse_contracts(p)
        assert len(rows) == 1
        rec = rows[0]
        assert rec["name"] == "Aaron Example"
        assert rec["team"] == "GB"  # nickname → abbreviation
        assert rec["apy"] == 10_000_000
        assert rec["total"] == 40_000_000
        assert rec["guaranteed"] == 20_000_000
        assert rec["years"] == 4
        assert rec["yearSigned"] == 2024
        assert rec["endYear"] == 2027

    def test_latest_signing_wins_for_duplicates(self, tmp_path):
        p = write_csv(
            tmp_path / "contracts.csv",
            CONTRACTS_HEADER,
            [
                _contract_row("Dup Player", year_signed=2021, apy=5_000_000),
                _contract_row("Dup Player", year_signed=2025, apy=9_000_000),
            ],
        )
        rows = norm.parse_contracts(p)
        assert len(rows) == 1
        assert rows[0]["apy"] == 9_000_000
        assert rows[0]["yearSigned"] == 2025

    def test_gzip_variant(self, tmp_path):
        p = write_csv(tmp_path / "contracts.csv.gz", CONTRACTS_HEADER, [_contract_row("Zip Man")])
        assert norm.parse_contracts(p)[0]["name"] == "Zip Man"

    def test_missing_column_is_schema_regression(self, tmp_path):
        broken_header = CONTRACTS_HEADER.replace("apy,", "apy_renamed,")
        p = write_csv(tmp_path / "contracts.csv", broken_header, [_contract_row("X")])
        with pytest.raises(SchemaRegressionError, match="apy"):
            norm.parse_contracts(p)


# ── Snap counts ──────────────────────────────────────────────────────


def _snap_row(
    name: str,
    week: int,
    off_pct: float,
    def_pct: float = 0.0,
    season: int = 2025,
    game_type: str = "REG",
    team: str = "SF",
    pos: str = "RB",
    pfr: str = "McCaCh01",
) -> str:
    off_snaps = int(off_pct * 70)
    def_snaps = int(def_pct * 70)
    return (
        f"2025_{week:02d}_{team}_XX,x{week},{season},{game_type},{week},{name},{pfr},"
        f"{pos},{team},XX,{off_snaps},{off_pct},{def_snaps},{def_pct},0,0"
    )


class TestSnapCounts:
    def test_parse_keeps_only_newest_season(self, tmp_path):
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Old Season", 1, 0.9, season=2024),
                _snap_row("New Season", 1, 0.8, season=2025),
            ],
        )
        rows = norm.parse_snap_counts(p)
        assert [r["name"] for r in rows] == ["New Season"]
        assert rows[0]["offPct"] == pytest.approx(0.8)

    def test_aggregate_pct_trend_and_side(self, tmp_path):
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Christian McCaffrey", 1, 0.40),
                _snap_row("Christian McCaffrey", 2, 0.50),
                _snap_row("Christian McCaffrey", 3, 0.60),
                _snap_row("Christian McCaffrey", 4, 0.70),
                _snap_row(
                    "Micah Parsons", 1, 0.0, def_pct=0.9, team="DAL", pos="DE", pfr="ParsMi00"
                ),
            ],
        )
        agg = {a["name"]: a for a in norm.aggregate_snaps(norm.parse_snap_counts(p))}
        cmc = agg["Christian McCaffrey"]
        assert cmc["games"] == 4
        assert cmc["side"] == "offense"
        assert cmc["pct"] == pytest.approx(55.0)  # mean of 40/50/60/70
        assert cmc["recentPct"] == pytest.approx(60.0)  # last 3: 50/60/70
        assert cmc["trend"] == pytest.approx(5.0)
        parsons = agg["Micah Parsons"]
        assert parsons["side"] == "defense"
        assert parsons["pct"] == pytest.approx(90.0)

    def test_postseason_orders_after_regular_season(self, tmp_path):
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("P Layer", 1, 0.9, game_type="SB"),
                _snap_row("P Layer", 17, 0.3, game_type="REG"),
            ],
        )
        agg = norm.aggregate_snaps(norm.parse_snap_counts(p), recent_games=1)
        # recent (last ordered game) must be the Super Bowl, not week 17
        assert agg[0]["recentPct"] == pytest.approx(90.0)

    def test_missing_column_is_schema_regression(self, tmp_path):
        broken = SNAPS_HEADER.replace("offense_pct", "off_pct_renamed")
        p = write_csv(tmp_path / "snaps.csv", broken, [_snap_row("X", 1, 0.5)])
        with pytest.raises(SchemaRegressionError, match="offense_pct"):
            norm.parse_snap_counts(p)


# ── Depth charts ─────────────────────────────────────────────────────


def _depth_row(
    name: str,
    *,
    dt: str = "2026-07-25T08:57:25Z",
    team: str = "SF",
    gsis: str = "00-0000001",
    espn: str = "111",
    grp: str = "3WR 1TE",
    abb: str = "WR",
    slot: int = 1,
    rank: int = 1,
) -> str:
    return f"{dt},{team},{name},{espn},{gsis},20,{grp},1,{abb},{abb},{slot},{rank}"


class TestDepthCharts:
    def test_newest_snapshot_wins_and_slots_filtered(self, tmp_path):
        p = write_csv(
            tmp_path / "depth.csv",
            DEPTH_HEADER,
            [
                _depth_row("Stale Starter", dt="2026-01-01T00:00:00Z"),
                _depth_row("Fresh Starter", dt="2026-07-25T08:57:25Z"),
                _depth_row("Left Tackle", abb="LT"),  # OL — dropped
                _depth_row("Punter Person", grp="Special Teams", abb="P"),  # dropped
                _depth_row("Kicker Person", grp="Special Teams", abb="PK"),  # kept as K
            ],
        )
        rows = norm.parse_depth_charts(p)
        names = {r["name"] for r in rows}
        assert names == {"Fresh Starter", "Kicker Person"}
        kicker = next(r for r in rows if r["name"] == "Kicker Person")
        assert kicker["position"] == "K"

    def test_newest_snapshot_is_per_team(self, tmp_path):
        p = write_csv(
            tmp_path / "depth.csv",
            DEPTH_HEADER,
            [
                _depth_row("Niner Guy", team="SF", dt="2026-07-25T00:00:00Z"),
                _depth_row("Cowboy Guy", team="DAL", dt="2026-07-20T00:00:00Z"),
            ],
        )
        assert {r["name"] for r in norm.parse_depth_charts(p)} == {"Niner Guy", "Cowboy Guy"}

    def test_compute_depth_ranks_orders_slots_then_backups(self):
        rows = [
            {
                "team": "SF",
                "name": "WR One",
                "gsisId": "g1",
                "espnId": "",
                "position": "WR",
                "depthPosition": "WR",
                "slot": 1,
                "slotRank": 1,
            },
            {
                "team": "SF",
                "name": "WR Backup",
                "gsisId": "g3",
                "espnId": "",
                "position": "WR",
                "depthPosition": "WR",
                "slot": 1,
                "slotRank": 2,
            },
            {
                "team": "SF",
                "name": "WR Two",
                "gsisId": "g2",
                "espnId": "",
                "position": "WR",
                "depthPosition": "WR",
                "slot": 2,
                "slotRank": 1,
            },
        ]
        ranked = {r["name"]: r["rank"] for r in norm.compute_depth_ranks(rows)}
        assert ranked == {"WR One": 1, "WR Two": 2, "WR Backup": 3}

    def test_compute_depth_ranks_dedupes_multi_slot_player(self):
        rows = [
            {
                "team": "DAL",
                "name": "Corner Man",
                "gsisId": "g9",
                "espnId": "",
                "position": "DB",
                "depthPosition": "LCB",
                "slot": 1,
                "slotRank": 1,
            },
            {
                "team": "DAL",
                "name": "Corner Man",
                "gsisId": "g9",
                "espnId": "",
                "position": "DB",
                "depthPosition": "NB",
                "slot": 5,
                "slotRank": 2,
            },
            {
                "team": "DAL",
                "name": "Safety Man",
                "gsisId": "g8",
                "espnId": "",
                "position": "DB",
                "depthPosition": "FS",
                "slot": 3,
                "slotRank": 1,
            },
        ]
        ranked = norm.compute_depth_ranks(rows)
        corner = [r for r in ranked if r["name"] == "Corner Man"]
        assert len(corner) == 1
        assert corner[0]["depthPosition"] == "LCB"  # best slot kept
        assert len(ranked) == 2

    def test_missing_column_is_schema_regression(self, tmp_path):
        broken = DEPTH_HEADER.replace("gsis_id", "gsis_renamed")
        p = write_csv(tmp_path / "depth.csv", broken, [_depth_row("X")])
        with pytest.raises(SchemaRegressionError, match="gsis_id"):
            norm.parse_depth_charts(p)


# ── Team + pool helpers ──────────────────────────────────────────────


class TestHelpers:
    def test_team_code_aliases(self):
        assert norm.normalize_team_code("LA") == "LAR"
        assert norm.normalize_team_code("OAK") == "LV"
        assert norm.normalize_team_code("sf") == "SF"
        assert norm.normalize_team_code(None) == ""

    def test_nickname_map_covers_all_32(self):
        abbrs = {v for k, v in norm._TEAM_NICKNAME_TO_ABBR.items()}
        assert len(abbrs) == 32

    def test_build_sleeper_pool_filters_and_canonicalizes(self):
        dump = {
            "1": {
                "active": True,
                "position": "DE",
                "full_name": "Edge Guy",
                "team": "DAL",
                "gsis_id": " 00-0001 ",
                "espn_id": 42,
            },
            "2": {"active": False, "position": "QB", "full_name": "Retired QB", "team": "SF"},
            "3": {"active": True, "position": "OT", "full_name": "Tackle Guy", "team": "SF"},
            "4": {
                "active": True,
                "position": "WR",
                "first_name": "No",
                "last_name": "Fullname",
                "team": "MIN",
            },
        }
        pool = norm.build_sleeper_pool(dump)
        assert set(pool) == {"1", "4"}
        assert pool["1"]["position"] == "DL"  # DE → DL family
        assert pool["1"]["gsis_id"] == "00-0001"  # stripped
        assert pool["4"]["full_name"] == "No Fullname"
