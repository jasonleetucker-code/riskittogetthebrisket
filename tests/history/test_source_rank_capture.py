"""#804 per-source rank CAPTURE — the lane, and the guarantees it inherits.

Capture only.  These tests pin what is recorded and, just as importantly,
that recording it changes nothing: no consumer, no weighting, no canonical
value or ranking movement.  Correlation methodology is POST-V1 and
unauthorized; nothing here computes one.
"""

from __future__ import annotations

import ast
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.history import asof, record, source_rank, store
from src.utils.config_loader import repo_root


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "temporal.sqlite"


def contract(
    *,
    date="2026-08-18",
    scraped="2026-08-18T23:02:11.345069+00:00",
    ranks=None,
    raw=None,
    meta=None,
):
    row = {
        "displayName": "Test Player",
        "position": "WR",
        "playerId": "5859",
        "sourceRanks": ranks if ranks is not None else {"ktcSfTep": 12, "dlfSf": 15},
        "sourceOriginalRanks": raw if raw is not None else {"dlfSf": 15.4},
        "sourceRankMeta": meta
        if meta is not None
        else {
            "ktcSfTep": {
                "scope": "overall_offense",
                "method": "direct",
                "rankCoordinatePool": "offense",
                "sharedMarketTranslated": False,
            },
            "dlfSf": {
                "scope": "overall_offense",
                "method": "ladder",
                "rankCoordinatePool": "offense",
                "sharedMarketTranslated": True,
            },
        },
    }
    return {
        "date": date,
        "scrapeTimestamp": scraped,
        "playersArray": [row],
        "meta": {"scoringFingerprint": "sf-abc"},
    }


def _imported_modules(path: Path) -> set[str]:
    """Fully-qualified module names imported by ``path``.

    ``from src.history import source_rank`` and
    ``import src.history.source_rank`` both normalise to the same string, so
    a caller can test one thing instead of two shapes.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            found.add(mod)
            found.update(f"{mod}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def rows_in(ledger, lane=store.LANE_SOURCE_RANK):
    conn = store.connect(ledger)
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM observations WHERE lane=? ORDER BY source_key", (lane,)
            )
        ]
    finally:
        conn.close()


# ── The lane exists, and is not source_value ─────────────────────────


class TestTheLaneIsItsOwnQuantity:
    def test_the_lane_is_registered_and_distinct(self):
        assert store.LANE_SOURCE_RANK == "source_rank"
        assert store.LANE_SOURCE_RANK in store.VALID_LANES
        assert store.LANE_SOURCE_RANK != store.LANE_SOURCE

    def test_a_rank_observation_may_not_carry_a_value(self, ledger):
        """A rank is an ordering position; a value is a price.  Storing one
        under the other makes the series unreadable later."""
        obs = {
            "asset_key": "player:1",
            "asset_class": "player",
            "lane": store.LANE_SOURCE_RANK,
            "source_key": "dlfSf",
            "observed_date": "2026-08-18",
            "origin": "test",
            "rank": 5,
            "value": 4200.0,
        }
        result = store.write_observations([obs], path=ledger)
        assert result["written"] == 0
        assert "never a value" in result["rejected"][0]["reason"]

    def test_capture_writes_only_into_its_own_lane(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        conn = store.connect(ledger)
        try:
            lanes = {r[0] for r in conn.execute("SELECT DISTINCT lane FROM observations")}
        finally:
            conn.close()
        assert lanes == {store.LANE_SOURCE_RANK}


# ── Missing is absence, never zero ───────────────────────────────────


class TestMissingRankIsNeverZero:
    @pytest.mark.parametrize("bad", [0, -1, -99])
    def test_a_nonpositive_rank_is_refused(self, ledger, bad):
        obs = {
            "asset_key": "player:1",
            "asset_class": "player",
            "lane": store.LANE_SOURCE_RANK,
            "source_key": "dlfSf",
            "observed_date": "2026-08-18",
            "origin": "test",
            "rank": bad,
        }
        result = store.write_observations([obs], path=ledger)
        assert result["written"] == 0
        assert "never position zero" in result["rejected"][0]["reason"]

    def test_a_source_that_did_not_rank_contributes_no_row(self, ledger):
        """Absence is the encoding.  Rank 0 would sort first on every board."""
        source_rank.record_source_ranks(
            contract(ranks={"ktcSfTep": 12, "dlfSf": None, "fantasyCalc": 0}),
            path=ledger,
            origin="test",
        )
        assert {r["source_key"] for r in rows_in(ledger)} == {"ktcSfTep"}

    def test_a_missing_raw_rank_stays_null_not_zero(self, ledger):
        source_rank.record_source_ranks(contract(raw={}), path=ledger, origin="test")
        assert all(r["raw_rank"] is None for r in rows_in(ledger))

    def test_a_bool_is_not_a_rank(self, ledger):
        """``True`` is an ``int`` in Python and would store as rank 1."""
        source_rank.record_source_ranks(
            contract(ranks={"ktcSfTep": True, "dlfSf": 15}), path=ledger, origin="test"
        )
        assert {r["source_key"] for r in rows_in(ledger)} == {"dlfSf"}


# ── Provenance for a later independence analysis ─────────────────────


class TestProvenance:
    def test_source_identity_and_lineage_are_captured(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        by_source = {r["source_key"]: r for r in rows_in(ledger)}
        assert set(by_source) == {"ktcSfTep", "dlfSf"}
        dlf = by_source["dlfSf"]
        assert dlf["rank"] == 15
        assert dlf["raw_rank"] == pytest.approx(15.4)
        assert dlf["rank_method"] == "ladder"
        assert dlf["rank_pool"] == "offense"
        assert dlf["scope"] == "overall_offense"

    def test_shared_market_translation_is_recorded(self, ledger):
        """The single most important lineage fact: a source projected onto
        another market's backbone is correlated with it BY CONSTRUCTION, and
        an analysis that missed it would 'discover' a correlation the
        pipeline itself created."""
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        by_source = {r["source_key"]: r for r in rows_in(ledger)}
        assert by_source["dlfSf"]["shared_market_translated"] == 1
        assert by_source["ktcSfTep"]["shared_market_translated"] == 0

    def test_unknown_translation_stays_unknown(self, ledger):
        source_rank.record_source_ranks(contract(meta={}), path=ledger, origin="test")
        assert all(r["shared_market_translated"] is None for r in rows_in(ledger))

    def test_the_raw_and_effective_ranks_are_both_kept(self, ledger):
        """A rookie board's #36 becomes #247 on the overall ladder.  Those
        are two different facts and correlation needs to know which it has."""
        source_rank.record_source_ranks(
            contract(
                ranks={"dlfRookieSf": 247},
                raw={"dlfRookieSf": 36.0},
                meta={"dlfRookieSf": {"method": "ladder"}},
            ),
            path=ledger,
            origin="test",
        )
        row = rows_in(ledger)[0]
        assert (row["rank"], row["raw_rank"]) == (247, 36.0)

    def test_the_board_identity_travels_with_every_row(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        for row in rows_in(ledger):
            assert row["observed_date"] == "2026-08-18"
            assert row["observed_at"] == "2026-08-18T23:02:11.345069+00:00"
            assert row["origin"] == "test"
            assert row["asset_key"] == "player:5859"


# ── Timezone awareness ───────────────────────────────────────────────


class TestObservedAtIsTimezoneAware:
    def test_a_tz_aware_scrape_stamp_records_utc(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        row = rows_in(ledger)[0]
        assert row["observed_at_zone"] == "utc"
        assert datetime.fromisoformat(row["observed_at"]).tzinfo is not None

    def test_a_naive_stamp_is_recorded_as_naive_not_assumed_utc(self, ledger):
        source_rank.record_source_ranks(
            contract(scraped="2026-08-18T23:02:11"), path=ledger, origin="test"
        )
        assert rows_in(ledger)[0]["observed_at_zone"] == "naive"

    def test_a_date_only_stamp_is_no_instant_at_all(self, ledger):
        """A date-only string parses as midnight and would lexicographically
        precede every instant of its own day — promoting an UNKNOWN scrape
        time to 'provably at-or-before any moment today'."""
        source_rank.record_source_ranks(contract(scraped="2026-08-18"), path=ledger, origin="test")
        row = rows_in(ledger)[0]
        assert row["observed_at"] is None and row["observed_at_zone"] is None

    def test_the_instant_rule_has_one_owner(self, ledger):
        """Both lanes read the producer's instant through the same helper,
        so they cannot drift into two definitions of 'when'."""
        assert source_rank.record.contract_observed_instant is record.contract_observed_instant


# ── Inherited store guarantees ───────────────────────────────────────


class TestAppendOnlyAndIdempotent:
    def test_recording_the_same_build_twice_writes_nothing_new(self, ledger):
        first = source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        second = source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        assert first["written"] == 2
        assert second["written"] == 0
        assert second["duplicates"] == 2
        assert second["contentConflicts"] == []

    def test_two_scrapes_on_one_date_are_two_observations(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        source_rank.record_source_ranks(
            contract(scraped="2026-08-18T23:59:00+00:00", ranks={"ktcSfTep": 13}),
            path=ledger,
            origin="test",
        )
        assert len(rows_in(ledger)) == 3

    def test_a_changed_rank_at_the_same_identity_is_surfaced_not_applied(self, ledger):
        """Append-only: a conflicting re-record never overwrites."""
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        result = source_rank.record_source_ranks(
            contract(ranks={"ktcSfTep": 99, "dlfSf": 15}), path=ledger, origin="test"
        )
        assert result["written"] == 0
        assert len(result["contentConflicts"]) == 1
        stored = {r["source_key"]: r["rank"] for r in rows_in(ledger)}
        assert stored["ktcSfTep"] == 12, "the stored observation must be untouched"

    def test_no_update_or_delete_reaches_the_store(self):
        """Structural: the write path issues only INSERT."""
        src = (repo_root() / "src" / "history" / "source_rank.py").read_text(encoding="utf-8")
        lowered = src.lower()
        for forbidden in ("update ", "delete ", "drop ", "alter "):
            assert forbidden not in lowered, f"{forbidden!r} in the capture module"


class TestHistoryFloorAndNeverFuture:
    def test_an_observation_before_the_floor_is_refused(self, ledger):
        result = source_rank.record_source_ranks(
            contract(date="2026-07-13"), path=ledger, origin="test"
        )
        assert result["written"] == 0
        assert "history floor" in result["rejected"][0]["reason"]

    def test_a_future_observation_is_never_selected(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        answer = asof.value_as_of(
            "player:5859",
            "2026-08-17",
            lane=store.LANE_SOURCE_RANK,
            source_key="dlfSf",
            path=ledger,
        )
        assert answer["fidelity"] == "unavailable"
        assert answer.get("rank") is None

    def test_an_at_or_before_observation_is_selected(self, ledger):
        source_rank.record_source_ranks(contract(), path=ledger, origin="test")
        answer = asof.value_as_of(
            "player:5859",
            "2026-08-19",
            lane=store.LANE_SOURCE_RANK,
            source_key="dlfSf",
            path=ledger,
        )
        assert answer["fidelity"] != "unavailable"
        assert answer["rank"] == 15


# ── The capture must not touch anything ──────────────────────────────


class TestNonInfluence:
    def test_no_valuation_or_weighting_module_imports_the_rank_lane(self):
        """No consumer edge may exist from rank history into anything that
        decides a number.  Asserted structurally, because an accidental
        import is exactly how a capture lane becomes an input.

        An IMPORT EDGE, not a substring: ``source_ranks`` is a long-standing
        local variable name in ``data_contract``, and matching text would
        fail on code that has nothing to do with this lane.
        """
        roots = (
            "src/api",
            "src/canonical",
            "src/trade",
            "src/bdvm",
            "src/league_intel",
            "src/scoring",
            "src/consensus_edge",
        )
        offenders = []
        for root in roots:
            for path in (repo_root() / root).rglob("*.py"):
                for mod in _imported_modules(path):
                    if mod.endswith("history.source_rank"):
                        offenders.append(str(path.relative_to(repo_root())))
        assert not offenders, f"rank-capture reached a decision module: {offenders}"

    def test_the_only_importer_is_the_capture_call_site(self):
        """Exactly one production importer — the fresh-scrape write in
        server.py.  A second one is a consumer appearing."""
        importers = []
        for path in list((repo_root() / "src").rglob("*.py")) + [repo_root() / "server.py"]:
            if path.name == "source_rank.py":
                continue
            if any(m.endswith("history.source_rank") for m in _imported_modules(path)):
                importers.append(path.name)
        assert importers == ["server.py"], f"unexpected importers: {importers}"

    def test_the_capture_module_imports_nothing_that_prices_anything(self):
        """The dependency arrow points one way: capture reads a finished
        contract and writes.  It must not reach back into valuation."""
        tree = ast.parse(
            (repo_root() / "src" / "history" / "source_rank.py").read_text(encoding="utf-8")
        )
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        banned = {
            "src.api.data_contract",
            "src.canonical.player_valuation",
            "src.trade.faab_engine",
            "src.bdvm.market",
        }
        assert not (imported & banned), f"capture imports a pricing module: {imported & banned}"

    def test_building_observations_does_not_mutate_the_contract(self):
        import copy

        payload = contract()
        before = copy.deepcopy(payload)
        source_rank.observations_from_contract(payload)
        assert payload == before

    def test_the_flag_is_off_by_default(self):
        """~38.8 MB/day is a production disk commitment an owner makes
        deliberately, not one a merge makes for them."""
        from src.api import feature_flags

        assert feature_flags._DEFAULTS["source_rank_capture"] is False


class TestLegacyContentHashesAreUnchanged:
    def test_adding_the_lane_did_not_change_any_existing_hash(self):
        """The new columns are folded into ``content_hash`` only when
        present.  Without that, every already-stored row would re-ingest as
        a CONFLICT instead of a duplicate and the store's idempotency —
        which backfill and the migrations are built on — would break."""
        legacy = {
            "value": 4200.0,
            "rank": 12,
            "tier": 2,
            "confidence": "high",
            "display_name": "X",
            "position": "WR",
            "player_id": "1",
            "scope": None,
            "pipeline_version": "pv1",
        }
        with_new_keys_absent = store.content_hash(dict(legacy))
        with_new_keys_none = store.content_hash(
            {
                **legacy,
                "raw_rank": None,
                "rank_method": None,
                "rank_pool": None,
                "shared_market_translated": None,
            }
        )
        assert with_new_keys_absent == with_new_keys_none

    def test_a_rank_row_hashes_over_its_own_extra_content(self):
        base = {
            "value": None,
            "rank": 12,
            "tier": None,
            "confidence": None,
            "display_name": None,
            "position": None,
            "player_id": None,
            "scope": None,
            "pipeline_version": None,
        }
        assert store.content_hash({**base, "raw_rank": 15.4}) != store.content_hash(
            {**base, "raw_rank": 99.9}
        )


class TestSchemaUpgrade:
    def test_a_v1_ledger_gains_the_columns_without_losing_rows(self, tmp_path):
        """An already-deployed ledger predates these columns, and
        ``CREATE TABLE IF NOT EXISTS`` cannot add one."""
        db = tmp_path / "old.sqlite"
        # A v1 table: the shipped schema minus the extension columns, built
        # directly rather than by DROP COLUMN — SQLite refuses that while the
        # identity index still references the table.
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE observations ("
            "id INTEGER PRIMARY KEY, asset_key TEXT NOT NULL, "
            "asset_class TEXT NOT NULL, lane TEXT NOT NULL, "
            "source_key TEXT NOT NULL DEFAULT '', observed_date TEXT NOT NULL, "
            "observed_at TEXT, observed_at_zone TEXT, value REAL, rank INTEGER, "
            "tier INTEGER, confidence TEXT, display_name TEXT, position TEXT, "
            "player_id TEXT, scope TEXT, pipeline_version TEXT, "
            "origin TEXT NOT NULL, recorded_at TEXT NOT NULL, "
            "content_hash TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO observations (asset_key, asset_class, lane, source_key, "
            "observed_date, origin, rank, recorded_at, content_hash) "
            "VALUES ('player:1','player','canonical_board','','2026-08-18','test',5,'t','h')"
        )
        conn.commit()
        conn.close()
        store._reset_setup_cache_for_tests()

        conn = store.connect(db)
        try:
            present = {r[1] for r in conn.execute("PRAGMA table_info(observations)")}
            assert {c for c, _ in store._EXTENSION_COLUMNS} <= present
            assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
        finally:
            conn.close()
