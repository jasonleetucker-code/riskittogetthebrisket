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
    st_pct: float = 0.0,
    season: int = 2025,
    game_type: str = "REG",
    team: str = "SF",
    pos: str = "RB",
    pfr: str = "McCaCh01",
) -> str:
    off_snaps = int(off_pct * 70)
    def_snaps = int(def_pct * 70)
    st_snaps = int(st_pct * 30)
    return (
        f"2025_{week:02d}_{team}_XX,x{week},{season},{game_type},{week},{name},{pfr},"
        f"{pos},{team},XX,{off_snaps},{off_pct},{def_snaps},{def_pct},{st_snaps},{st_pct}"
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


class TestSnapCountsAsOf:
    """Reading the file as it stood at a past week.

    The `snapTrend` axis in `consensus_edge.opportunity` was described in
    four places as "production-only and unmeasurable", attributed to the
    playerctx snapshot being overwritten weekly with no history. That
    attribution was incomplete: nflverse publishes `snap_counts_{season}.csv`
    as one row per player PER GAME with a `week` column, so the history
    was always in the file — `parse_snap_counts` was the thing discarding
    it, with a newest-season filter and no week cutoff.

    These pin the two properties that make an as-of read trustworthy: the
    cutoff actually moves the derived signal, and supplying nothing at all
    leaves the live path exactly as it was.
    """

    def _four_weeks(self, tmp_path):
        return write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Rising Back", 1, 0.20),
                _snap_row("Rising Back", 2, 0.40),
                _snap_row("Rising Back", 3, 0.60),
                _snap_row("Rising Back", 4, 0.80),
            ],
        )

    def test_a_week_cutoff_drops_later_games(self, tmp_path):
        p = self._four_weeks(tmp_path)
        assert [r["week"] for r in norm.parse_snap_counts(p, through_week=2)] == [1, 2]

    def test_the_cutoff_is_inclusive(self, tmp_path):
        p = self._four_weeks(tmp_path)
        assert max(r["week"] for r in norm.parse_snap_counts(p, through_week=3)) == 3

    def test_the_derived_trend_actually_moves_with_the_cutoff(self, tmp_path):
        """The test that would have caught the frozen-constant problem.

        A cutoff that filters rows but leaves `trend` unchanged would be
        useless for a backtest — every fold would resample one
        observation, which is exactly what the offseason panel does to
        this axis. Usage climbing 20/40/60/80 must read differently at
        week 3 than at week 4.
        """
        p = self._four_weeks(tmp_path)
        trends = {}
        for cutoff in (3, 4):
            rows = norm.parse_snap_counts(p, through_week=cutoff)
            agg = norm.aggregate_snaps(rows, recent_games=2)
            trends[cutoff] = agg[0]["trend"]
        assert trends[3] != trends[4], f"trend frozen across cutoffs: {trends}"
        # Climbing usage: the later view is further above its own mean.
        assert trends[4] > trends[3]

    def test_an_explicit_season_overrides_newest(self, tmp_path):
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Old Season", 1, 0.9, season=2024),
                _snap_row("New Season", 1, 0.8, season=2025),
            ],
        )
        assert [r["name"] for r in norm.parse_snap_counts(p, season=2024)] == ["Old Season"]

    def test_defaults_are_byte_identical_to_the_unparameterised_read(self, tmp_path):
        # The parameters must be inert until used, or adding them would
        # have silently repriced the live board.
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Old Season", 1, 0.9, season=2024),
                _snap_row("A", 1, 0.5),
                _snap_row("A", 2, 0.6),
                _snap_row("B", 3, 0.7, def_pct=0.4),
            ],
        )
        assert norm.parse_snap_counts(p) == norm.parse_snap_counts(
            p, season=None, through_week=None
        )
        # And the season filter still bites by default.
        assert "Old Season" not in {r["name"] for r in norm.parse_snap_counts(p)}

    def test_a_cutoff_before_any_game_yields_nothing_rather_than_everything(self, tmp_path):
        # An empty result is a legible "no data yet at that week"; falling
        # back to the full season would be a silent look-ahead.
        p = self._four_weeks(tmp_path)
        assert norm.parse_snap_counts(p, through_week=0) == []

    def test_missing_st_column_is_schema_regression(self, tmp_path):
        broken = SNAPS_HEADER.replace("st_pct", "st_pct_renamed")
        p = write_csv(tmp_path / "snaps.csv", broken, [_snap_row("X", 1, 0.5)])
        with pytest.raises(SchemaRegressionError, match="st_pct"):
            norm.parse_snap_counts(p)

    def test_kicker_publishes_st_share(self, tmp_path):
        # Regression (Codex round 2 on PR #539): kickers live entirely
        # in st_snaps/st_pct; discarding the ST unit classified every
        # K as "offense" with a misleading 0% share.
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Kicky McLeg", 1, 0.0, st_pct=0.28, pos="K", pfr="McLeKi00"),
                _snap_row("Kicky McLeg", 2, 0.0, st_pct=0.32, pos="K", pfr="McLeKi00"),
            ],
        )
        agg = norm.aggregate_snaps(norm.parse_snap_counts(p))
        assert len(agg) == 1
        kicker = agg[0]
        assert kicker["side"] == "st"
        assert kicker["pct"] == pytest.approx(30.0)  # mean of 28/32
        assert kicker["games"] == 2

    def test_offense_still_wins_over_incidental_st_snaps(self, tmp_path):
        # A skill player with a few ST snaps must stay "offense".
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [_snap_row("RB Guy", 1, 0.6, st_pct=0.2)],
        )
        agg = norm.aggregate_snaps(norm.parse_snap_counts(p))
        assert agg[0]["side"] == "offense"
        assert agg[0]["pct"] == pytest.approx(60.0)

    def test_kicker_with_trick_play_snap_still_classifies_st(self, tmp_path):
        # Regression (Codex round 4 on PR #539): one offensive snap
        # (fake FG / trick play) made ``off_total > 0`` true and the
        # kicker classified "offense" at ~0% — all THREE unit totals
        # must compete and the max wins.
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                # off_pct 0.02 → 1 offensive snap; st_pct 0.9 → 27 ST snaps.
                _snap_row("Kicky McLeg", 1, 0.02, st_pct=0.9, pos="K", pfr="McLeKi00"),
                _snap_row("Kicky McLeg", 2, 0.0, st_pct=0.9, pos="K", pfr="McLeKi00"),
            ],
        )
        agg = norm.aggregate_snaps(norm.parse_snap_counts(p))
        assert len(agg) == 1
        assert agg[0]["side"] == "st"
        assert agg[0]["pct"] == pytest.approx(90.0)

    def test_idless_traded_player_aggregates_across_teams(self, tmp_path):
        # Regression (Codex round 2 on PR #539): the ID-less fallback
        # key included the team, so a traded player's season split into
        # per-stint aggregates that later overwrote each other on the
        # same Sleeper record.
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Traded Guy", 1, 0.40, team="CAR", pfr=""),
                _snap_row("Traded Guy", 2, 0.50, team="CAR", pfr=""),
                _snap_row("Traded Guy", 3, 0.80, team="SF", pfr=""),
            ],
        )
        agg = norm.aggregate_snaps(norm.parse_snap_counts(p))
        assert len(agg) == 1  # one season line, not one per stint
        rec = agg[0]
        assert rec["games"] == 3
        assert rec["team"] == "SF"  # latest stint
        assert rec["pct"] == pytest.approx(56.7, abs=0.05)  # mean of 40/50/80

    def test_idless_same_week_collision_is_dropped(self, tmp_path):
        # Two DISTINCT ID-less players sharing name+position betray
        # themselves by playing the same week twice — the group must be
        # dropped, not merged into a chimera.
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Common Name", 1, 0.5, team="CAR", pfr=""),
                _snap_row("Common Name", 1, 0.7, team="SF", pfr=""),
            ],
        )
        assert norm.aggregate_snaps(norm.parse_snap_counts(p)) == []

    def test_pfr_id_groups_are_exempt_from_collision_drop(self, tmp_path):
        # An ID-bearing group is a single human by definition; the
        # duplicate-week guard only applies to the ID-less fallback.
        p = write_csv(
            tmp_path / "snaps.csv",
            SNAPS_HEADER,
            [
                _snap_row("Id Guy", 1, 0.5, team="CAR", pfr="GuyId00"),
                _snap_row("Id Guy", 2, 0.5, team="SF", pfr="GuyId00"),
            ],
        )
        agg = norm.aggregate_snaps(norm.parse_snap_counts(p))
        assert len(agg) == 1
        assert agg[0]["games"] == 2


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


class TestDepthChartsAsOf:
    """The same as-of read for the other playerctx parser.

    The seasonal file appends a full dated snapshot per upstream scrape,
    so the history is in the file here too; `parse_depth_charts` was
    discarding it by keeping only the newest `dt` per team.
    """

    def _three_snapshots(self, tmp_path):
        return write_csv(
            tmp_path / "depth.csv",
            DEPTH_HEADER,
            [
                _depth_row("September Starter", dt="2025-09-03T08:00:00Z"),
                _depth_row("November Starter", dt="2025-11-09T12:30:00Z"),
                _depth_row("January Starter", dt="2026-01-04T09:00:00Z"),
            ],
        )

    def test_the_bound_selects_the_snapshot_live_at_that_date(self, tmp_path):
        p = self._three_snapshots(tmp_path)
        rows = norm.parse_depth_charts(p, as_of="2025-11-20T00:00:00Z")
        assert {r["name"] for r in rows} == {"November Starter"}

    def test_a_date_only_bound_includes_that_whole_day(self, tmp_path):
        """`dt` carries a time, so a naive `dt > as_of` drops its own day.

        With `as_of="2025-11-09"` and `dt="2025-11-09T12:30:00Z"`, a
        whole-string compare says the snapshot is in the future and falls
        back to September — an off-by-one-day that reads as working code
        because it still returns a plausible depth chart.
        """
        p = self._three_snapshots(tmp_path)
        rows = norm.parse_depth_charts(p, as_of="2025-11-09")
        assert {r["name"] for r in rows} == {"November Starter"}

    def test_the_bound_is_per_team_like_the_unbounded_read(self, tmp_path):
        p = write_csv(
            tmp_path / "depth.csv",
            DEPTH_HEADER,
            [
                _depth_row("Niner Old", team="SF", dt="2025-09-03T08:00:00Z"),
                _depth_row("Niner New", team="SF", dt="2025-11-09T08:00:00Z"),
                _depth_row("Cowboy Old", team="DAL", dt="2025-09-03T08:00:00Z"),
            ],
        )
        rows = norm.parse_depth_charts(p, as_of="2025-11-09")
        # DAL's newest AT THAT DATE is September; it must not be dropped
        # for being older than SF's.
        assert {r["name"] for r in rows} == {"Niner New", "Cowboy Old"}

    def test_a_bound_before_everything_yields_nothing(self, tmp_path):
        p = self._three_snapshots(tmp_path)
        assert norm.parse_depth_charts(p, as_of="2025-01-01") == []

    def test_default_is_byte_identical_to_the_unparameterised_read(self, tmp_path):
        p = self._three_snapshots(tmp_path)
        assert norm.parse_depth_charts(p) == norm.parse_depth_charts(p, as_of=None)
        assert {r["name"] for r in norm.parse_depth_charts(p)} == {"January Starter"}


class TestDepthRanks:
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
