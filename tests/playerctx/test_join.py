"""Join correctness for ``normalize.build_player_context`` against a
fake Sleeper pool — exact-ID joins, unified-mapper name joins, manual
override aliases, and the drop rules.  No network."""

from __future__ import annotations

import json

import pytest

from src.identity import unified_mapper
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


class TestManualOverrides:
    """Regression: manual overrides (``id_overrides.json``) must be
    reachable for source rows.  ``resolve_player``'s own override rung
    only fires when given a ``sleeper_id`` — which external datasets
    never carry — so ``build_player_context`` reverse-indexes the
    override file by normalized name / gsis_id / espn_id and consults
    it before dropping a row (Codex round 1, finding 1 on PR #539)."""

    @pytest.fixture(autouse=True)
    def _clean_override_cache(self):
        unified_mapper.reload_overrides()
        yield
        unified_mapper.reload_overrides()

    @pytest.fixture
    def overrides_path(self, tmp_path):
        p = tmp_path / "id_overrides.json"
        p.write_text(
            json.dumps(
                {
                    # Source-name alias for a player whose pool name is
                    # nothing like the source's ("Zzyzx Quixote" fails
                    # every exact rung AND the fuzzy ladder).
                    "4034": {
                        "gsis_id": "00-0033280",
                        "espn_id": "3117251",
                        "full_name": "Zzyzx Quixote",
                    },
                    # ID alias for the no-gsis pool player: maps an
                    # external gsis/espn the pool doesn't know.
                    "7777": {
                        "gsis_id": "00-0777777",
                        "espn_id": "7654321",
                        "full_name": "Ghost Nogsis",
                    },
                }
            ),
            encoding="utf-8",
        )
        return p

    def test_name_alias_rescues_unmatchable_source_row(self, players_dir, overrides_path):
        records, stats = norm.build_player_context(
            contracts=[_contract("Zzyzx Quixote", "SF", "RB")],
            snaps=[_snap("Zzyzx Quixote", "SF", "RB")],
            depth=[],
            players_dir=players_dir,
            overrides_path=overrides_path,
        )
        assert set(records) == {"00-0033280"}
        rec = records["00-0033280"]
        assert rec["sleeperId"] == "4034"
        assert rec["name"] == "Christian McCaffrey"  # pool stays canonical
        assert rec["contract"]["apy"] == 12_000_000
        assert rec["snaps"]["pct"] == 80.0
        assert stats["contracts"]["matched"] == 1
        assert stats["snapCounts"]["matched"] == 1

    def test_same_row_is_dropped_without_the_override(self, players_dir, tmp_path):
        empty = tmp_path / "no_overrides.json"
        empty.write_text("{}", encoding="utf-8")
        records, _ = norm.build_player_context(
            contracts=[_contract("Zzyzx Quixote", "SF", "RB")],
            snaps=[],
            depth=[],
            players_dir=players_dir,
            overrides_path=empty,
        )
        assert records == {}

    def test_gsis_alias_rescues_depth_row(self, players_dir, overrides_path):
        # Depth row: unknown display name, gsis only known via the
        # override entry → must land on sleeper 7777.
        records, stats = norm.build_player_context(
            contracts=[],
            snaps=[],
            depth=[_depth("Totally Different Name", gsis="00-0777777", team="CHI", pos="WR")],
            players_dir=players_dir,
            overrides_path=overrides_path,
        )
        assert set(records) == {"00-0777777"}  # source gsis backfills the key
        assert records["00-0777777"]["sleeperId"] == "7777"
        assert stats["depthCharts"]["matched"] == 1

    def test_espn_alias_rescues_depth_row(self, players_dir, overrides_path):
        records, _ = norm.build_player_context(
            contracts=[],
            snaps=[],
            depth=[_depth("Totally Different Name", gsis="", espn="7654321", team="CHI", pos="WR")],
            players_dir=players_dir,
            overrides_path=overrides_path,
        )
        assert len(records) == 1
        assert next(iter(records.values()))["sleeperId"] == "7777"


class TestAmbiguousNames:
    """Regression (Codex round 3 on PR #539): two ACTIVE pool records
    sharing a normalized name + position family must never be matched
    arbitrarily.  The old ``setdefault`` index silently kept whichever
    record was indexed first, so a teamless (or signing-team-stale)
    contract row attached to the wrong player.  Deterministic rungs
    now accept only a UNIQUE candidate; ambiguity is settled by a
    manual override or the row is dropped — never by the fuzzy layer's
    first-match walk."""

    @pytest.fixture(autouse=True)
    def _clean_override_cache(self):
        unified_mapper.reload_overrides()
        yield
        unified_mapper.reload_overrides()

    @pytest.fixture
    def dup_pool(self, players_dir):
        pool = dict(players_dir)
        pool["9001"] = {
            "player_id": "9001",
            "full_name": "Lamar Woods",
            "position": "WR",
            "team": "KC",
            "gsis_id": "00-0900001",
            "espn_id": "911",
        }
        pool["9002"] = {
            "player_id": "9002",
            "full_name": "Lamar Woods",
            "position": "WR",
            "team": "NYJ",
            "gsis_id": "00-0900002",
            "espn_id": "912",
        }
        return pool

    @pytest.fixture
    def no_overrides(self, tmp_path):
        p = tmp_path / "no_overrides.json"
        p.write_text("{}", encoding="utf-8")
        return p

    def test_teamless_ambiguous_row_is_dropped(self, dup_pool, no_overrides):
        records, stats = norm.build_player_context(
            contracts=[_contract("Lamar Woods", "", "WR")],
            snaps=[],
            depth=[],
            players_dir=dup_pool,
            overrides_path=no_overrides,
        )
        assert records == {}
        assert stats["contracts"]["matched"] == 0

    def test_stale_signing_team_ambiguous_row_is_dropped(self, dup_pool, no_overrides):
        # A contract still carrying the signing team post-trade: the
        # team matches NEITHER candidate, and name+family covers two
        # players — must drop, not keep whichever was indexed first.
        records, _ = norm.build_player_context(
            contracts=[_contract("Lamar Woods", "MIA", "WR")],
            snaps=[],
            depth=[],
            players_dir=dup_pool,
            overrides_path=no_overrides,
        )
        assert records == {}

    def test_override_settles_ambiguity(self, dup_pool, tmp_path):
        ov = tmp_path / "id_overrides.json"
        ov.write_text(
            json.dumps(
                {"9002": {"gsis_id": "00-0900002", "espn_id": "912", "full_name": "Lamar Woods"}}
            ),
            encoding="utf-8",
        )
        records, stats = norm.build_player_context(
            contracts=[_contract("Lamar Woods", "", "WR")],
            snaps=[],
            depth=[],
            players_dir=dup_pool,
            overrides_path=ov,
        )
        assert set(records) == {"00-0900002"}
        assert records["00-0900002"]["sleeperId"] == "9002"
        assert stats["contracts"]["matched"] == 1

    def test_matching_team_disambiguates_to_exactly_one(self, dup_pool, no_overrides):
        records, _ = norm.build_player_context(
            contracts=[_contract("Lamar Woods", "KC", "WR")],
            snaps=[],
            depth=[],
            players_dir=dup_pool,
            overrides_path=no_overrides,
        )
        assert set(records) == {"00-0900001"}
        assert records["00-0900001"]["sleeperId"] == "9001"

    def test_unique_name_pos_candidate_still_matches_teamless(self, dup_pool, no_overrides):
        # Uniqueness, not team presence, is the acceptance criterion.
        records, _ = norm.build_player_context(
            contracts=[_contract("Justin Jefferson", "", "WR")],
            snaps=[],
            depth=[],
            players_dir=dup_pool,
            overrides_path=no_overrides,
        )
        assert set(records) == {"00-0036322"}
