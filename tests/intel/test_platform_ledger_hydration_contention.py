"""V1-59: the FFPC bootstrap crashloop — CPU spin, lock, unrecordable failure.

MEASURED PRODUCTION CHAIN (Bootstrap Sharp Records run 32813417583; every
non-skipped run failing back through Aug 22):

1. ``chaseupside-ffpc-sharp.service`` hits its 30-minute ``TimeoutStartSec``
   while consuming ~29m25-45s of **CPU** — spin, not I/O wait;
2. ingestion then dies at ``register_asset_alias`` with
   ``sqlite3.OperationalError: database is locked``;
3. ``record_ingestion_run`` hits the same lock, so the run is never marked
   failed and ``platform_coverage`` keeps reporting the previous SUCCESS.

ONE CAUSE, THREE SYMPTOMS.  ``register_asset_alias`` repairs previously
unmapped rows with ``UPDATE asset_movements WHERE platform=? AND
source_asset_id=?``.  With only ``idx_am_platform_ts`` available that plans
as a scan of the whole platform partition, and
``hydrate_sleeper_asset_catalog`` issues one per player in Sleeper's
directory — so the catalog pass costs O(players x movements) and grows with
every ingest.  Measured on a synthetic ledger: 1,500 players over 60,000
movements took 22.70 s unindexed and 0.15 s indexed (151x), the cost
doubling exactly with movement count (20k/40k/80k/160k ->
1.48/3.01/5.99/12.08 s).  Because the pass is ONE transaction, a half-hour
hydration holds the write lock for half an hour, and every other writer
waits out its ``busy_timeout`` and raises.

WHY THE ASSERTIONS ARE SHAPED THIS WAY.  Wall-clock thresholds are the
obvious test here and the wrong one — a loaded CI box would flake, and a
generous threshold would stop failing long before the scan came back.  The
deterministic statement is the QUERY PLAN, so that is what is pinned; the
timing evidence lives in the docstrings above and in the PR.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from src.intel import ledger, platform_ledger


def _seed_movements(conn: sqlite3.Connection, n: int, platform: str = "sleeper") -> None:
    conn.executemany(
        "INSERT INTO asset_movements (tx_id, league_id, tx_type, asset_id, asset_type,"
        " action, user_id, ts, ingested_ms, platform, source_asset_id, movement_key)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                f"tx-{platform}-{i}",
                "lg",
                "waiver",
                str(i),
                "player",
                "add",
                "u",
                1,
                1,
                platform,
                str(i),
                f"mv-{platform}-{i}",
            )
            for i in range(n)
        ],
    )


def _alias_update_plan(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "EXPLAIN QUERY PLAN UPDATE asset_movements SET canonical_asset_id=?, asset_id=? "
        "WHERE platform=? AND source_asset_id=?",
        ("c", "c", "sleeper", "1"),
    ).fetchall()
    return " | ".join(str(r[3]) for r in rows)


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        str(r[0])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }


class TestTheScanIsGone:
    def test_the_alias_repair_is_an_indexed_lookup_not_a_partition_scan(self, tmp_path):
        conn = platform_ledger.ensure_platform_schema(tmp_path / "l.sqlite")
        try:
            plan = _alias_update_plan(conn)
            assert "idx_am_platform_source" in plan, plan
            assert "source_asset_id=?" in plan, plan
        finally:
            conn.close()

    def test_without_the_index_the_planner_falls_back_to_the_partition_scan(self, tmp_path):
        """The control that makes the test above non-vacuous.

        Dropping the index reproduces the deployed ledger exactly, and the
        planner's own answer names the defect: it can only use the
        ``platform=?`` prefix of ``idx_am_platform_ts`` and must then walk
        every row of that platform, once per player.
        """
        path = tmp_path / "l.sqlite"
        conn = platform_ledger.ensure_platform_schema(path)
        try:
            conn.execute("DROP INDEX idx_am_platform_source")
            conn.commit()
            plan = _alias_update_plan(conn)
            assert "idx_am_platform_source" not in plan
            assert "source_asset_id=?" not in plan, (
                "the planner should be unable to narrow by source_asset_id: " + plan
            )
        finally:
            conn.close()


class TestTheIndexReachesAnAlreadyMigratedLedger:
    """The V1-59 state: fully migrated at the current schema version, and
    still missing the index.  ``_platform_schema_ready`` checks columns, a
    table and triggers — never indexes — so adding it to the schema script
    alone would reach new ledgers and no deployed one.
    """

    def test_a_ready_ledger_missing_the_index_gets_it_on_next_connect(self, tmp_path):
        path = tmp_path / "l.sqlite"
        first = platform_ledger.ensure_platform_schema(path)
        first.execute("DROP INDEX idx_am_platform_source")
        first.commit()
        # Precondition: the ledger still reports as fully migrated.
        assert platform_ledger._platform_schema_ready(first) is True
        assert "idx_am_platform_source" not in _index_names(first)
        first.close()

        second = platform_ledger.ensure_platform_schema(path)
        try:
            assert "idx_am_platform_source" in _index_names(second)
            assert "idx_am_platform_source" in _alias_update_plan(second)
        finally:
            second.close()

    def test_the_pass_is_idempotent_and_takes_no_write_lock_when_satisfied(self, tmp_path):
        """Safe to run on every connect.  If ensuring the index needed the
        write lock in steady state it would be a NEW contention source —
        the opposite of the repair.
        """
        path = tmp_path / "l.sqlite"
        platform_ledger.ensure_platform_schema(path).close()

        holder = ledger.connect(path)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO meta(key, value) VALUES ('v159', 'held')")
        try:
            other = ledger.connect(path)
            other.execute("PRAGMA busy_timeout=500")
            started = time.perf_counter()
            platform_ledger.ensure_platform_indexes(other)
            assert time.perf_counter() - started < 0.5
            other.close()
        finally:
            holder.rollback()
            holder.close()

    def test_existing_indexes_are_untouched(self, tmp_path):
        conn = platform_ledger.ensure_platform_schema(tmp_path / "l.sqlite")
        try:
            names = _index_names(conn)
            for pre_existing in (
                "idx_am_platform_ts",
                "idx_am_canonical_ts",
                "idx_am_manager_key_ts",
                "idx_am_league_key_ts",
                "idx_am_movement_key",
                "idx_alias_canonical",
            ):
                assert pre_existing in names
        finally:
            conn.close()


class TestHydrationSemanticsAreUnchanged:
    def test_hydration_still_registers_aliases_and_repairs_movements(self, tmp_path):
        path = tmp_path / "l.sqlite"
        conn = platform_ledger.ensure_platform_schema(path)
        _seed_movements(conn, 25)
        conn.commit()
        conn.close()

        count = platform_ledger.hydrate_sleeper_asset_catalog(
            {
                "7": {"full_name": "Some Player", "team": "kc", "position": "wr"},
                "9": {"full_name": "Other Player", "team": "sf", "position": "rb"},
                "bad": "not-a-dict",
                "blank": {"full_name": "   "},
            },
            path=path,
        )
        assert count == 2

        conn = ledger.connect(path)
        try:
            alias = conn.execute(
                "SELECT canonical_asset_id, source_name, nfl_team, position, "
                "match_method, manually_verified FROM asset_aliases "
                "WHERE platform='sleeper' AND source_asset_id='7'"
            ).fetchone()
            assert alias["canonical_asset_id"] == "7"
            assert alias["source_name"] == "Some Player"
            assert alias["nfl_team"] == "KC"
            assert alias["position"] == "WR"
            assert alias["match_method"] == "authoritative_source_id"
            assert alias["manually_verified"] == 1

            # the movement repair the UPDATE exists for
            moved = conn.execute(
                "SELECT canonical_asset_id FROM asset_movements "
                "WHERE platform='sleeper' AND source_asset_id='7'"
            ).fetchone()
            assert moved["canonical_asset_id"] == "7"

            untouched = conn.execute(
                "SELECT canonical_asset_id FROM asset_movements "
                "WHERE platform='sleeper' AND source_asset_id='3'"
            ).fetchone()
            assert untouched["canonical_asset_id"] is None
        finally:
            conn.close()

    def test_other_platforms_are_not_repaired_by_a_sleeper_hydration(self, tmp_path):
        path = tmp_path / "l.sqlite"
        conn = platform_ledger.ensure_platform_schema(path)
        _seed_movements(conn, 5, platform="ffpc")
        conn.commit()
        conn.close()

        platform_ledger.hydrate_sleeper_asset_catalog(
            {"1": {"full_name": "Sleeper Guy", "team": "KC", "position": "WR"}}, path=path
        )
        conn = ledger.connect(path)
        try:
            row = conn.execute(
                "SELECT canonical_asset_id FROM asset_movements "
                "WHERE platform='ffpc' AND source_asset_id='1'"
            ).fetchone()
            assert row["canonical_asset_id"] is None
        finally:
            conn.close()


class TestFailureRecordingSurvivesContention:
    """Symptom 3, and the one that made the crashloop invisible."""

    def test_the_recorder_waits_the_full_default_when_the_lock_is_held(self, tmp_path):
        """Control: this is the pre-repair behaviour, and it is why the
        failure report never landed.  Measured at 30.09 s in production
        shape; asserted here against a lowered connection default so the
        test is fast, proving the recorder inherits whatever the
        connection's budget is.
        """
        path = tmp_path / "l.sqlite"
        platform_ledger.ensure_platform_schema(path).close()

        holder = ledger.connect(path)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO meta(key, value) VALUES ('v159', 'held')")
        try:
            started = time.perf_counter()
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                platform_ledger.record_ingestion_run(
                    run_id="r-slow",
                    platform="ffpc",
                    source_ref=None,
                    started_ms=1,
                    finished_ms=2,
                    status="failed",
                    path=path,
                    busy_timeout_ms=1500,
                )
            waited = time.perf_counter() - started
            assert waited >= 1.4, waited
        finally:
            holder.rollback()
            holder.close()

    def test_a_bounded_budget_lets_the_recorder_give_up_promptly(self, tmp_path):
        path = tmp_path / "l.sqlite"
        platform_ledger.ensure_platform_schema(path).close()

        holder = ledger.connect(path)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO meta(key, value) VALUES ('v159', 'held')")
        try:
            started = time.perf_counter()
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                platform_ledger.record_ingestion_run(
                    run_id="r-fast",
                    platform="ffpc",
                    source_ref=None,
                    started_ms=1,
                    finished_ms=2,
                    status="failed",
                    path=path,
                    busy_timeout_ms=200,
                )
            waited = time.perf_counter() - started
            # Far below the 30 s connection default: survivable on a unit
            # about to be SIGKILLed at its start timeout.
            assert waited < 5.0, waited
        finally:
            holder.rollback()
            holder.close()

    def test_contention_is_raised_never_swallowed(self, tmp_path):
        """A recorder that returned quietly on a lost lock would turn a
        failed ingestion into a silent one."""
        path = tmp_path / "l.sqlite"
        platform_ledger.ensure_platform_schema(path).close()
        holder = ledger.connect(path)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO meta(key, value) VALUES ('v159', 'held')")
        try:
            with pytest.raises(sqlite3.OperationalError):
                platform_ledger.record_ingestion_run(
                    run_id="r-quiet",
                    platform="ffpc",
                    source_ref=None,
                    started_ms=1,
                    finished_ms=2,
                    status="failed",
                    path=path,
                    busy_timeout_ms=100,
                )
        finally:
            holder.rollback()
            holder.close()
        conn = ledger.connect(path)
        try:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM ingestion_runs WHERE run_id='r-quiet'"
                ).fetchone()[0]
                == 0
            )
        finally:
            conn.close()

    def test_the_default_budget_is_unchanged_when_not_asked_for(self, tmp_path):
        path = tmp_path / "l.sqlite"
        platform_ledger.record_ingestion_run(
            run_id="r-ok",
            platform="ffpc",
            source_ref=None,
            started_ms=1,
            finished_ms=2,
            status="success",
            counters={"pagesFetched": 3},
            path=path,
        )
        conn = ledger.connect(path)
        try:
            row = conn.execute(
                "SELECT status, pages_fetched FROM ingestion_runs WHERE run_id='r-ok'"
            ).fetchone()
            assert row["status"] == "success"
            assert row["pages_fetched"] == 3
        finally:
            conn.close()


class TestAnUnfinishedRunIsNeverReportedAsSuccess:
    """The truthfulness half.  ``platform_coverage`` reports the newest run
    per platform, so with no row for a crashed attempt it kept surfacing
    the previous SUCCESS — a crashlooping collector reading as a healthy
    one.
    """

    def test_a_running_row_supersedes_the_previous_success(self, tmp_path):
        path = tmp_path / "l.sqlite"
        platform_ledger.record_ingestion_run(
            run_id="old-good",
            platform="ffpc",
            source_ref=None,
            started_ms=1_000,
            finished_ms=2_000,
            status="success",
            path=path,
        )
        platform_ledger.record_ingestion_run(
            run_id="new-attempt",
            platform="ffpc",
            source_ref=None,
            started_ms=3_000,
            finished_ms=None,
            status="running",
            path=path,
        )
        latest = platform_ledger.platform_coverage(path=path)["ffpc"]["latestIngestion"]
        assert latest["status"] == "running"
        assert latest["finished_ms"] is None

    def test_a_finished_run_upserts_over_its_own_claim(self, tmp_path):
        path = tmp_path / "l.sqlite"
        for status, finished in (("running", None), ("success", 9_000)):
            platform_ledger.record_ingestion_run(
                run_id="same-run",
                platform="ffpc",
                source_ref=None,
                started_ms=5_000,
                finished_ms=finished,
                status=status,
                path=path,
            )
        conn = ledger.connect(path)
        try:
            rows = conn.execute(
                "SELECT status, finished_ms FROM ingestion_runs WHERE platform='ffpc'"
            ).fetchall()
            assert len(rows) == 1, "the claim must be upserted, never duplicated"
            assert rows[0]["status"] == "success"
            assert rows[0]["finished_ms"] == 9_000
        finally:
            conn.close()


class TestTheCrawlerClaimsItsRunBeforeTheHeavyWork:
    """Structural: a claim written after hydration would never be reached
    on the timeout path this repairs."""

    def test_the_claim_precedes_hydration_and_the_recorder_is_bounded(self):
        import inspect

        from scripts import crawl_ffpc_sharp

        src = inspect.getsource(crawl_ffpc_sharp.main)
        assert 'status="running"' in src
        assert src.index('status="running"') < src.index("hydrate_sleeper_asset_catalog")
        assert "busy_timeout_ms=_FAILURE_RECORD_BUSY_TIMEOUT_MS" in src
        assert crawl_ffpc_sharp._FAILURE_RECORD_BUSY_TIMEOUT_MS < 30_000

    def test_the_service_timeout_was_not_widened_to_hide_the_spin(self):
        from pathlib import Path

        repo = Path(__file__).resolve().parents[2]
        for template in sorted((repo / "deploy").rglob("*ffpc-sharp.service*")):
            text = template.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.strip().startswith("TimeoutStartSec"):
                    assert "30min" in line or "1800" in line, line
