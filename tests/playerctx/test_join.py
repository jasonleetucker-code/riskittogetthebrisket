"""Join correctness for ``normalize.build_player_context`` against a
fake Sleeper pool — exact-ID joins, unified-mapper name joins, and
the drop rules.  No network."""

from __future__ import annotations

from src.playerctx import normalize as norm


def _depth(name: str, gsis: str, espn: str = "", team: str = "SF", pos: str = "RB") -> dict:
    return {
        "team": team,
        "name": name,
        "gsisId": gsis,
        "espnId": espn,
        "position": pos,
        "depthPosition": pos,
        "slot": 1,
        "slotRank": 1,
    }


def _snap(name: str, team: str, pos: str) -> dict:
    return {
        "name": name,
        "team": team,
        "position": pos,
        "season": 2025,
        "games": 16,
        "side": "offense",
        "pct": 80.0,
        "recentPct": 85.0,
        "trend": 5.0,
    }


def _contract(name: str, team: str, pos: str) -> dict:
    return {
        "name": name,
        "position": pos,
        "team": team,
        "apy": 12_000_000,
        "total": 48_000_000,
        "guaranteed": 30_000_000,
        "years": 4,
        "yearSigned": 2024,
        "endYear": 2027,
    }


class TestBuildPlayerContext:
    def test_depth_joins_by_exact_gsis(self, players_dir):
        records, stats = norm.build_player_context(
            contracts=[],
            snaps=[],
            depth=[_depth("C. McCaffrey Jr.", gsis="00-0033280")],  # name mangled on purpose
            players_dir=players_dir,
        )
        assert set(records) == {"00-0033280"}
        rec = records["00-0033280"]
        assert rec["sleeperId"] == "4034"
        assert rec["name"] == "Christian McCaffrey"  # Sleeper pool is canonical
        assert rec["depth"] == {
            "position": "RB",
            "rank": 1,
            "depthPosition": "RB",
            "team": "SF",
        }
        assert stats["depthCharts"]["matched"] == 1

    def test_depth_falls_back_to_espn_then_name(self, players_dir):
        records, _ = norm.build_player_context(
            contracts=[],
            snaps=[],
            depth=[
                _depth("J. Jefferson", gsis="", espn="4262921", team="MIN", pos="WR"),
                _depth("Micah Parsons", gsis="", espn="", team="DAL", pos="DL"),
            ],
            players_dir=players_dir,
        )
        assert set(records) == {"00-0036322", "00-0036933"}

    def test_snaps_join_by_name_team_position_family(self, players_dir):
        # PFR position "DE" must land on the Sleeper "DL" family row.
        records, stats = norm.build_player_context(
            contracts=[],
            snaps=[_snap("Micah Parsons", "DAL", "DE")],
            depth=[],
            players_dir=players_dir,
        )
        assert set(records) == {"00-0036933"}
        assert records["00-0036933"]["snaps"]["pct"] == 80.0
        assert stats["snapCounts"]["matched"] == 1

    def test_contract_join_and_merged_record(self, players_dir):
        records, stats = norm.build_player_context(
            contracts=[_contract("Christian McCaffrey", "SF", "RB")],
            snaps=[_snap("Christian McCaffrey", "SF", "RB")],
            depth=[_depth("Christian McCaffrey", gsis="00-0033280")],
            players_dir=players_dir,
        )
        rec = records["00-0033280"]
        assert rec["contract"]["apy"] == 12_000_000
        assert rec["contract"]["endYear"] == 2027
        assert rec["snaps"]["season"] == 2025
        assert rec["depth"]["rank"] == 1
        assert stats["players"] == 1
        assert stats["contracts"]["matched"] == 1

    def test_unmapped_rows_are_dropped(self, players_dir):
        records, stats = norm.build_player_context(
            contracts=[_contract("Total Stranger", "GB", "QB")],
            snaps=[_snap("Unknown Athlete", "NYJ", "WR")],
            depth=[_depth("Mystery Man", gsis="00-9999999")],
            players_dir=players_dir,
        )
        assert records == {}
        assert stats["contracts"]["matched"] == 0
        assert stats["snapCounts"]["matched"] == 0
        assert stats["depthCharts"]["matched"] == 0

    def test_pool_record_without_gsis_gets_fallback_key(self, players_dir):
        # Sleeper's gsis coverage is sparse; a successful join must
        # not be thrown away just because Sleeper doesn't know the
        # player's gsis_id.
        records, stats = norm.build_player_context(
            contracts=[],
            snaps=[_snap("Ghost Nogsis", "CHI", "WR")],
            depth=[],
            players_dir=players_dir,
        )
        assert set(records) == {"sleeper:7777"}
        assert records["sleeper:7777"]["gsisId"] == ""
        assert records["sleeper:7777"]["snaps"]["pct"] == 80.0
        assert stats["noGsisFallback"] == 1

    def test_source_gsis_backfills_missing_sleeper_gsis(self, players_dir):
        # Depth charts carry an authoritative gsis_id; when Sleeper
        # lacks one (espn-id join), the source's gsis becomes the key —
        # and a later pass without a gsis must land on the SAME record.
        records, stats = norm.build_player_context(
            contracts=[_contract("Ghost Nogsis", "CHI", "WR")],
            snaps=[],
            depth=[_depth("Ghost Nogsis", gsis="00-0777777", espn="1234567", team="CHI", pos="WR")],
            players_dir=players_dir,
        )
        assert set(records) == {"00-0777777"}
        rec = records["00-0777777"]
        assert rec["sleeperId"] == "7777"
        assert rec["depth"]["rank"] == 1
        assert rec["contract"]["apy"] == 12_000_000  # merged, not split
        assert stats["noGsisFallback"] == 0

    def test_stats_parsed_counts(self, players_dir):
        _, stats = norm.build_player_context(
            contracts=[_contract("Christian McCaffrey", "SF", "RB")],
            snaps=[],
            depth=[_depth("Christian McCaffrey", gsis="00-0033280")],
            players_dir=players_dir,
        )
        assert stats["contracts"]["parsed"] == 1
        assert stats["snapCounts"]["parsed"] == 0
        assert stats["depthCharts"]["parsed"] == 1
