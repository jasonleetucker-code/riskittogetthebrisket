"""C1-U4 GREEN: the canonical temporal ledger's load-bearing semantics.

Covers the acceptance evidence for all three manifest rows:

* C1-HIST-01 — replay determinism (same inputs → same ledger → same
  answers, before and after later builds), the five-label fidelity
  vocabulary, never-future selection, the permanent pre-2026-07-14
  boundary, provenance round-trip, immutability (idempotent re-ingest,
  surfaced-not-applied conflicts, explicit corrections).
* C1-HIST-02 — pick-value history rows exist and are recoverable,
  keyed by C1-U3 market-pick identity (the RED counterpart is
  ``test_temporal_red.py::TestRed3``).
* C1-HIST-03 — back-to-back build determinism for ``rankChange``,
  collision-safe keying, and None-never-zero for a missing comparator
  (supersedes RED-1/RED-2, whose mechanism was deleted).

Fixture data is the same unedited production subset the RED tests use
(``tests/fixtures/temporal_live_subset.json``).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.api import data_contract
from src.history import asof, backfill, keys, migrate, record, store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "temporal_live_subset.json"


def _fx() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rows(fx: dict) -> list[dict]:
    return json.loads(json.dumps(fx["currentRows"]))


def _contract_for(rows: list[dict], date: str) -> dict:
    return {"playersArray": rows, "date": date, "scrapeTimestamp": f"{date}T11:01:40.000000"}


def _record_fixture_board(path: Path, date: str, rows: list[dict] | None = None) -> dict:
    fx = _fx()
    board = rows if rows is not None else _rows(fx)
    return record.record_contract(_contract_for(board, date), path=path)


def _prior_rows(fx: dict) -> list[dict]:
    """The REAL 2026-08-15 board restated as contract rows."""
    rows = []
    for r in _rows(fx):
        name = r["canonicalName"]
        prev_rank = fx["priorRanks"].get(name)
        prev_val = fx["priorSlotPickValues"].get(name)
        row = dict(r)
        row["canonicalConsensusRank"] = prev_rank
        if prev_val is not None:
            row["rankDerivedValue"] = prev_val
        rows.append(row)
    return rows


class _LedgerCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.ledger = Path(self._td.name) / "ledger.sqlite"
        store._reset_setup_cache_for_tests()


class TestAsOfFidelity(_LedgerCase):
    def test_exact_observation(self):
        _record_fixture_board(self.ledger, "2026-08-16")
        r = asof.value_as_of("player:5859", "2026-08-16", path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_EXACT)
        self.assertEqual(r["value"], 4947.0)
        self.assertEqual(r["rank"], 72)
        self.assertEqual(r["observedDate"], "2026-08-16")

    def test_nearest_prior_with_distance(self):
        _record_fixture_board(self.ledger, "2026-08-10")
        r = asof.value_as_of("player:5859", "2026-08-14", path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_NEAREST_PRIOR)
        self.assertEqual(r["observedDate"], "2026-08-10")
        self.assertEqual(r["distanceDays"], 4)

    def test_never_future_exhaustive(self):
        """Property, exhaustively over a date lattice: the selected
        observation NEVER postdates the requested date."""
        obs_dates = ["2026-07-20", "2026-07-28", "2026-08-05", "2026-08-13"]
        for d in obs_dates:
            _record_fixture_board(self.ledger, d)
        start = datetime(2026, 7, 14, tzinfo=timezone.utc).date()
        for offset in range(0, 40):
            q = (start + timedelta(days=offset)).isoformat()
            r = asof.value_as_of("player:5859", q, path=self.ledger)
            if r["fidelity"] == asof.FIDELITY_UNAVAILABLE:
                # Only legal before the first observation.
                self.assertLess(q, obs_dates[0])
                self.assertEqual(r["missingReason"], asof.REASON_NO_PRIOR)
            else:
                self.assertLessEqual(r["observedDate"], q)

    def test_future_only_asset_is_unavailable(self):
        _record_fixture_board(self.ledger, "2026-08-16")
        r = asof.value_as_of("player:5859", "2026-08-01", path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_NO_PRIOR)
        self.assertIsNone(r["value"])

    def test_before_boundary_is_permanent_missing(self):
        _record_fixture_board(self.ledger, "2026-08-16")
        r = asof.value_as_of("player:5859", "2026-07-01", path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_BEFORE_BOUNDARY)
        self.assertEqual(r["historyFloor"], "2026-07-14")

    def test_pre_boundary_write_is_refused(self):
        result = store.write_observations(
            [
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": "2026-07-01",
                    "value": 5000.0,
                    "origin": "test",
                }
            ],
            path=self.ledger,
        )
        self.assertEqual(result["written"], 0)
        self.assertEqual(len(result["rejected"]), 1)
        self.assertIn("permanent history floor", result["rejected"][0]["reason"])

    def test_max_age_budget(self):
        _record_fixture_board(self.ledger, "2026-07-20")
        r = asof.value_as_of("player:5859", "2026-08-16", max_age_days=7, path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertEqual(r["missingReason"], asof.REASON_OUTSIDE_MAX_AGE)
        self.assertEqual(r["nearestPriorDate"], "2026-07-20")

    def test_series_preserves_gaps(self):
        for d in ("2026-07-20", "2026-08-13"):
            _record_fixture_board(self.ledger, d)
        s = asof.series("player:5859", path=self.ledger)
        self.assertEqual([p["observedDate"] for p in s["points"]], ["2026-07-20", "2026-08-13"])

    def test_batch_partial_fidelity(self):
        _record_fixture_board(self.ledger, "2026-08-16")
        b = asof.batch_as_of(
            ["player:5859", "mpick:2026:r1:s1", "player:no-such"], "2026-08-16", path=self.ledger
        )
        self.assertEqual(b["summary"]["fidelity"], asof.FIDELITY_PARTIAL)
        self.assertEqual(b["summary"]["exact"], 2)
        self.assertEqual(b["summary"]["unavailable"], 1)

    def test_instant_strict_excludes_unproven_same_day(self):
        _record_fixture_board(self.ledger, "2026-08-16")  # naive scrape stamp
        early = datetime(2026, 8, 16, 6, 0, tzinfo=timezone.utc)
        r = asof.value_known_before("player:5859", early, path=self.ledger)
        # The same-day observation's instant is naive/unproven — it must
        # NOT be served as known-before a same-day instant.
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        # A prior-day observation qualifies for any instant on a later day.
        _record_fixture_board(self.ledger, "2026-08-15", rows=_prior_rows(_fx()))
        r2 = asof.value_known_before("player:5859", early, path=self.ledger)
        self.assertEqual(r2["observedDate"], "2026-08-15")

    def test_date_only_observed_at_is_an_unknown_instant(self):
        """Final-review blocker 1: a date-only stamp parses as midnight
        and lexicographically precedes every instant of its own day, so
        treating it as proven would serve same-day evidence whose
        scrape time is UNKNOWN as 'known before' any moment of that
        day.  Two defenses, both pinned here: the write path normalizes
        a time-less observed_at to NULL, and the instant-strict reader
        refuses unproven stamps even if one is already in the store."""
        # Write-path normalization: board_store's scraped_at fallback
        # can be the bare contract date — it must land as no-instant.
        store.write_observations(
            [
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": "2026-08-16",
                    "observed_at": "2026-08-16",  # date-only: unknown instant
                    "value": 4947.0,
                    "origin": "migration:board_history",
                }
            ],
            path=self.ledger,
        )
        conn = store.connect(self.ledger)
        stored = conn.execute("SELECT observed_at FROM observations").fetchone()[0]
        conn.close()
        self.assertIsNone(stored)

        early = datetime(2026, 8, 16, 0, 30, tzinfo=timezone.utc)
        r = asof.value_known_before("player:5859", early, path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)

        # Reader defense-in-depth: even a PRE-EXISTING date-only stamp
        # (legacy row written before normalization) never qualifies.
        conn = store.connect(self.ledger)
        conn.execute(
            "UPDATE observations SET observed_at='2026-08-16' WHERE asset_key='player:5859'"
        )
        conn.commit()
        conn.close()
        r2 = asof.value_known_before("player:5859", early, path=self.ledger)
        self.assertEqual(r2["fidelity"], asof.FIDELITY_UNAVAILABLE)
        # …while the day-granular mode still answers (day resolution is
        # its documented contract).
        r3 = asof.value_as_of("player:5859", "2026-08-16", path=self.ledger)
        self.assertEqual(r3["fidelity"], asof.FIDELITY_EXACT)

    def test_negative_utc_offset_instant_compares_correctly(self):
        """Instant comparison is on parsed datetimes, not text: a
        zone-qualified stamp with a negative offset would defeat a
        lexicographic compare."""
        store.write_observations(
            [
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": "2026-08-16",
                    # 18:00-07:00 == 2026-08-17T01:00Z — AFTER the query
                    # instant below despite sorting before it as text.
                    "observed_at": "2026-08-16T18:00:00-07:00",
                    "value": 4947.0,
                    "origin": "test",
                }
            ],
            path=self.ledger,
        )
        q = datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc)
        r = asof.value_known_before("player:5859", q, path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        q2 = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)
        r2 = asof.value_known_before("player:5859", q2, path=self.ledger)
        self.assertEqual(r2["observedDate"], "2026-08-16")

    def test_non_canonical_observed_date_rejected(self):
        """strptime accepts '2026-7-15'; stored, it would corrupt every
        lexicographic date bound.  The canonical ISO spelling is
        required exactly."""
        result = store.write_observations(
            [
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": "2026-7-15",
                    "value": 1.0,
                    "origin": "test",
                }
            ],
            path=self.ledger,
        )
        self.assertEqual(result["written"], 0)
        self.assertIn("not canonical ISO", result["rejected"][0]["reason"])

    def test_source_key_none_normalized(self):
        result = store.write_observations(
            [
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_SOURCE,
                    "source_key": None,
                    "observed_date": "2026-08-16",
                    "value": 5000.0,
                    "origin": "test",
                }
            ],
            path=self.ledger,
        )
        self.assertEqual(result["written"], 1)
        r = asof.value_as_of(
            "player:5859",
            "2026-08-16",
            lane=store.LANE_SOURCE,
            source_key="",
            path=self.ledger,
        )
        self.assertEqual(r["value"], 5000.0)

    def test_naive_instant_refused(self):
        with self.assertRaises(store.ObservationError):
            asof.value_known_before("player:5859", datetime(2026, 8, 16, 6, 0), path=self.ledger)

    def test_utc_conversion_on_aware_datetime(self):
        # 2026-08-17T01:30+05:30 is 2026-08-16T20:00 UTC — the UTC date governs.
        from datetime import timedelta as _td, timezone as _tz

        _record_fixture_board(self.ledger, "2026-08-16")
        aware = datetime(2026, 8, 17, 1, 30, tzinfo=_tz(_td(hours=5, minutes=30)))
        r = asof.value_as_of("player:5859", aware, path=self.ledger)
        self.assertEqual(r["requestedDate"], "2026-08-16")
        self.assertEqual(r["fidelity"], asof.FIDELITY_EXACT)

    def test_read_does_not_create_ledger(self):
        missing = Path(self._td.name) / "never_written.sqlite"
        r = asof.value_as_of("player:5859", "2026-08-16", path=missing)
        self.assertEqual(r["fidelity"], asof.FIDELITY_UNAVAILABLE)
        self.assertFalse(missing.exists())


class TestReplayDeterminism(_LedgerCase):
    """THE C1-HIST-01 acceptance: replay determinism."""

    def test_same_inputs_same_ledger(self):
        other = Path(self._td.name) / "ledger2.sqlite"
        for target in (self.ledger, other):
            _record_fixture_board(target, "2026-08-15", rows=_prior_rows(_fx()))
            _record_fixture_board(target, "2026-08-16")

        def dump(path: Path):
            conn = sqlite3.connect(str(path))
            try:
                return conn.execute(
                    "SELECT asset_key, asset_class, lane, source_key, observed_date, "
                    "observed_at, value, rank, tier, confidence, origin, content_hash "
                    "FROM observations ORDER BY asset_key, lane, source_key, observed_date"
                ).fetchall()
            finally:
                conn.close()

        rows_a, rows_b = dump(self.ledger), dump(other)
        self.assertEqual(rows_a, rows_b)
        self.assertGreater(len(rows_a), 0)

    def test_answer_stable_after_later_builds(self):
        _record_fixture_board(self.ledger, "2026-08-15", rows=_prior_rows(_fx()))
        before = asof.value_as_of("player:5859", "2026-08-15", path=self.ledger)
        _record_fixture_board(self.ledger, "2026-08-16")
        after = asof.value_as_of("player:5859", "2026-08-15", path=self.ledger)
        self.assertEqual(before, after)

    def test_reingest_is_idempotent(self):
        first = _record_fixture_board(self.ledger, "2026-08-16")
        second = _record_fixture_board(self.ledger, "2026-08-16")
        self.assertGreater(first["written"], 0)
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["duplicates"], first["written"])
        self.assertEqual(second["contentConflicts"], [])

    def test_conflicting_reingest_surfaced_never_applied(self):
        _record_fixture_board(self.ledger, "2026-08-16")
        drifted = _rows(_fx())
        for r in drifted:
            if r["canonicalName"] == "A.J. Brown":
                r["rankDerivedValue"] = 4800
        result = record.record_contract(_contract_for(drifted, "2026-08-16"), path=self.ledger)
        self.assertGreaterEqual(len(result["contentConflicts"]), 1)
        # The stored evidence is untouched — RED-5's silent rewrite is
        # unrepresentable here.
        r = asof.value_as_of("player:5859", "2026-08-16", path=self.ledger)
        self.assertEqual(r["value"], 4947.0)

    def test_duplicate_same_date_two_instants_deterministic(self):
        obs = {
            "asset_key": "player:5859",
            "asset_class": "offense",
            "lane": store.LANE_CANONICAL,
            "source_key": "",
            "observed_date": "2026-08-16",
            "origin": "test",
        }
        store.write_observations(
            [
                {**obs, "observed_at": "2026-08-16T04:00:00", "value": 4900.0},
                {**obs, "observed_at": "2026-08-16T22:00:00", "value": 4950.0},
            ],
            path=self.ledger,
        )
        for _ in range(3):
            r = asof.value_as_of("player:5859", "2026-08-16", path=self.ledger)
            self.assertEqual(r["value"], 4950.0)  # latest instant wins, every time

    def test_corrections_are_explicit_and_preferred(self):
        store.write_observations(
            [
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": "2026-08-16",
                    "observed_at": "2026-08-16T04:00:00",
                    "value": 9999999.0,  # a corrupt write worth correcting
                    "origin": "test",
                },
                {
                    "asset_key": "player:5859",
                    "asset_class": "offense",
                    "lane": store.LANE_CANONICAL,
                    "source_key": "",
                    "observed_date": "2026-08-16",
                    "observed_at": "2026-08-16T04:00:01",
                    "value": 4947.0,
                    "origin": "test:correction",
                },
            ],
            path=self.ledger,
        )
        conn = store.connect(self.ledger)
        ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM observations ORDER BY observed_at").fetchall()
        ]
        conn.close()
        with self.assertRaises(store.ObservationError):
            store.record_correction(ids[0], ids[1], "   ", path=self.ledger)
        with self.assertRaises(store.ObservationError):
            store.record_correction(ids[0], ids[0], "self", path=self.ledger)
        store.record_correction(ids[0], ids[1], "corrupt write", path=self.ledger)
        # A superseded row cannot itself supersede — a two-row cycle
        # would remove BOTH rows from every query surface.
        with self.assertRaises(store.ObservationError):
            store.record_correction(ids[1], ids[0], "cycle", path=self.ledger)
        r = asof.value_as_of("player:5859", "2026-08-16", path=self.ledger)
        self.assertEqual(r["value"], 4947.0)
        # The superseded row is retained, readable, marked — not erased.
        conn = store.connect(self.ledger)
        kept = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        marks = conn.execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
        conn.close()
        self.assertEqual((kept, marks), (2, 1))


class TestPickHistoryFirstClass(_LedgerCase):
    """C1-HIST-02 GREEN — the RED counterpart is TestRed3."""

    def test_slot_pick_values_recorded_and_recoverable(self):
        fx = _fx()
        _record_fixture_board(self.ledger, "2026-08-15", rows=_prior_rows(fx))
        _record_fixture_board(self.ledger, "2026-08-16")

        # The exact question RED-3 proves unanswerable through
        # rank_history: what was 2026 Pick 1.01 worth on 2026-08-15?
        r = asof.value_as_of("mpick:2026:r1:s1", "2026-08-15", path=self.ledger)
        self.assertEqual(r["fidelity"], asof.FIDELITY_EXACT)
        self.assertEqual(r["value"], float(fx["priorSlotPickValues"]["2026 Pick 1.01"]))
        r2 = asof.value_as_of("mpick:2026:r1:s1", "2026-08-16", path=self.ledger)
        self.assertEqual(r2["value"], 7779.0)
        # Rank-less rows are first-class: the slot pick has a value and
        # no rank, and the ledger records exactly that.
        self.assertIsNone(r2["rank"])

    def test_pick_identity_stable_across_label_form_and_ownership(self):
        # Identity comes from the C1-U3 owner: every label form of the
        # same market ref keys identically, and ownership is state that
        # never appears in the key.
        self.assertEqual(keys.pick_asset_key("2026 Pick 1.04"), "mpick:2026:r1:s4")
        # Tier and slot grades are DISTINCT market refs (a state
        # transition in league-pick space, never a silent merge here).
        self.assertEqual(keys.pick_asset_key("2027 Early 1st"), "mpick:2027:r1:tearly")
        self.assertNotEqual(
            keys.pick_asset_key("2027 Early 1st"), keys.pick_asset_key("2026 Pick 1.01")
        )

    def test_player_identity_stable_across_team_and_name_change(self):
        a = keys.asset_key_for_contract_row(
            {
                "canonicalName": "A.J. Brown",
                "assetClass": "offense",
                "position": "WR",
                "playerId": "5859",
                "team": "PHI",
            }
        )
        b = keys.asset_key_for_contract_row(
            {
                "canonicalName": "AJ Brown",
                "assetClass": "offense",
                "position": "WR",
                "playerId": "5859",
                "team": "DAL",
            }
        )
        self.assertEqual(a, b)

    def test_namespaces_cannot_collide(self):
        self.assertTrue(keys.is_valid_asset_key("player:5859"))
        self.assertTrue(keys.is_valid_asset_key("mpick:2026:r1:s1"))
        self.assertTrue(keys.is_valid_asset_key("name:james williams::IDP"))
        prefixes = {"player:", "name:", "mpick:"}
        for a in prefixes:
            for b in prefixes - {a}:
                self.assertFalse(a.startswith(b))


class TestRankChangeDeterministic(_LedgerCase):
    """C1-HIST-03 GREEN — supersedes RED-1/RED-2 (mechanism deleted)."""

    def _stamp(self, rows, board_date):
        data_contract._stamp_rank_changes(rows, board_date=board_date, ledger_path=self.ledger)
        return {
            r["canonicalName"]: r.get("rankChange")
            for r in rows
            if isinstance(r.get("canonicalConsensusRank"), int)
        }

    def test_back_to_back_builds_identical(self):
        fx = _fx()
        _record_fixture_board(self.ledger, "2026-08-15", rows=_prior_rows(fx))
        first = self._stamp(_rows(fx), "2026-08-16")
        second = self._stamp(_rows(fx), "2026-08-16")
        third = self._stamp(_rows(fx), "2026-08-16")
        self.assertEqual(first, second)
        self.assertEqual(second, third)
        # And the stamps reflect the REAL day-over-day movement.
        self.assertEqual(first["2027 Early 2nd"], 1)  # 110 → 109

    def test_recording_today_does_not_change_todays_comparator(self):
        fx = _fx()
        _record_fixture_board(self.ledger, "2026-08-15", rows=_prior_rows(fx))
        before = self._stamp(_rows(fx), "2026-08-16")
        _record_fixture_board(self.ledger, "2026-08-16")  # today's board lands
        after = self._stamp(_rows(fx), "2026-08-16")
        self.assertEqual(before, after)  # strictly-before excludes today

    def test_no_comparator_is_none_never_zero(self):
        stamps = self._stamp(_rows(_fx()), "2026-08-16")  # empty ledger
        self.assertTrue(all(v is None for v in stamps.values()))

    def test_collision_keyed(self):
        pair = [
            {
                "canonicalName": "James Williams",
                "displayName": "James Williams",
                "assetClass": "offense",
                "position": "RB",
                "canonicalConsensusRank": 400,
                "rankDerivedValue": 1700,
            },
            {
                "canonicalName": "James Williams",
                "displayName": "James Williams",
                "assetClass": "idp",
                "position": "S",
                "canonicalConsensusRank": 700,
                "rankDerivedValue": 1100,
            },
        ]
        record.record_contract(
            _contract_for(json.loads(json.dumps(pair)), "2026-08-15"), path=self.ledger
        )
        rows = json.loads(json.dumps(pair))
        rows[0]["canonicalConsensusRank"] = 410  # offense moved down 10
        data_contract._stamp_rank_changes(rows, board_date="2026-08-16", ledger_path=self.ledger)
        offense = next(r for r in rows if r["assetClass"] == "offense")
        idp = next(r for r in rows if r["assetClass"] == "idp")
        # Each player diffs against HIS OWN prior rank — the RED-2
        # cross-contamination (+300 fabricated move) is unrepresentable.
        self.assertEqual(offense["rankChange"], -10)
        self.assertEqual(idp["rankChange"], 0)

    def test_flag_off_stamps_none_not_the_retired_cache(self):
        import os

        fx = _fx()
        _record_fixture_board(self.ledger, "2026-08-15", rows=_prior_rows(fx))
        os.environ["RISKIT_FEATURE_LEDGER_RANK_CHANGE"] = "0"
        try:
            stamps = self._stamp(_rows(fx), "2026-08-16")
        finally:
            del os.environ["RISKIT_FEATURE_LEDGER_RANK_CHANGE"]
        self.assertTrue(all(v is None for v in stamps.values()))


class TestBackfillAndMigration(_LedgerCase):
    def _mini_archive(self, tmp: Path) -> Path:
        """A real-shape archive dir with two dated bundles."""
        import zipfile

        arch = tmp / "archive"
        arch.mkdir()
        for stamp, date, ktc in (
            ("20260720_230000", "2026-07-20", 6600),
            ("20260721_230000", "2026-07-21", 6650),
        ):
            payload = {
                "date": date,
                "scrapeTimestamp": f"{date}T23:00:00.000000",
                "players": {
                    "A.J. Brown": {
                        "_sleeperId": "5859",
                        "ktc": ktc,
                        "_composite": 7000,
                        "_finalAdjusted": 7000,
                    },
                    "2026 Pick 1.01": {
                        "ktc": 6700,
                        "idpTradeCalc": 8000,
                        "_composite": 7500,
                        "_finalAdjusted": 7500,
                    },
                },
                "sleeper": {"positions": {"A.J. Brown": "WR"}},
            }
            zp = arch / f"dynasty_export_{stamp}.zip"
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("manifest.json", json.dumps({"date": date}))
                z.writestr(f"dynasty_data_{date}.json", json.dumps(payload))
        return arch

    def test_backfill_deterministic_and_idempotent(self):
        arch = self._mini_archive(Path(self._td.name))
        r1 = backfill.backfill_archive(arch, path=self.ledger)
        self.assertEqual(r1["totals"]["dates"], 2)
        self.assertGreater(r1["totals"]["written"], 0)
        self.assertEqual(r1["totals"]["contentConflicts"], 0)
        r2 = backfill.backfill_archive(arch, path=self.ledger)
        self.assertEqual(r2["totals"]["written"], 0)
        self.assertEqual(r2["totals"]["duplicates"], r1["totals"]["written"])
        # The archived vendor pick price is recoverable per date, keyed
        # by canonical pick identity.
        r = asof.value_as_of(
            "mpick:2026:r1:s1",
            "2026-07-21",
            lane=store.LANE_SOURCE,
            source_key="ktc",
            path=self.ledger,
        )
        self.assertEqual((r["fidelity"], r["value"]), (asof.FIDELITY_EXACT, 6700.0))
        # …and the scraper blend is a DIFFERENT named lane, never the
        # canonical one: canonical stays honestly unavailable.
        rc = asof.value_as_of("mpick:2026:r1:s1", "2026-07-21", path=self.ledger)
        self.assertEqual(rc["fidelity"], asof.FIDELITY_UNAVAILABLE)

    def test_rank_history_migration_resolves_identity_and_refuses_reconstruction(self):
        # Identity evidence first (as the CLI orders it): an id-bearing row.
        _record_fixture_board(self.ledger, "2026-08-16")
        log = Path(self._td.name) / "rank_history.jsonl"
        log.write_text(
            json.dumps(
                {
                    "date": "2026-07-20",
                    "ranks": {"A.J. Brown::offense": 70, "2027 Early 1st::pick": 30},
                }
            )
            + "\n"
            + json.dumps(
                {
                    "date": "2026-07-21",
                    "ranks": {"A.J. Brown::offense": 71},
                    "values": {"A.J. Brown::offense": 4990},
                }
            )
            + "\n"
        )
        result = migrate.migrate_rank_history(log, path=self.ledger)
        self.assertFalse(result.get("skipped"))
        self.assertEqual(result["nameKeyed"], 0)  # resolved via ledger evidence

        # Rank-only day: rank recoverable, value honestly ABSENT — the
        # ledger refuses to launder load_history's Hill reconstruction
        # (RED-4's defect) into an observation.
        r_rank_only = asof.value_as_of("player:5859", "2026-07-20", path=self.ledger)
        self.assertEqual(r_rank_only["rank"], 70)
        self.assertIsNone(r_rank_only["value"])
        # Recorded-value day migrates the value.
        r_val = asof.value_as_of("player:5859", "2026-07-21", path=self.ledger)
        self.assertEqual(r_val["value"], 4990.0)
        # The generic pick key routes through the C1-U3 owner.
        r_pick = asof.value_as_of("mpick:2027:r1:tearly", "2026-07-20", path=self.ledger)
        self.assertEqual(r_pick["rank"], 30)
        # Idempotent rerun.
        again = migrate.migrate_rank_history(log, path=self.ledger)
        self.assertEqual(again["written"], 0)

    def test_migrate_rerun_is_noop_after_identity_evidence_arrives(self):
        """Final-review blocker 2: the name→id map grows as live
        recording lands, so re-resolving on every run would migrate the
        same legacy fact again under a new key.  First migration wins;
        a re-run against the byte-identical log writes NOTHING even
        after better identity evidence arrives."""
        log = Path(self._td.name) / "rank_history.jsonl"
        log.write_text(
            json.dumps({"date": "2026-07-20", "ranks": {"Jalen Carter::idp": 40}}) + "\n"
        )
        # Run 1: no identity evidence — migrates name-keyed.
        r1 = migrate.migrate_rank_history(log, path=self.ledger)
        self.assertEqual((r1["written"], r1["nameKeyed"]), (1, 1))

        # Live recording later supplies the platform id for that name.
        record.record_contract(
            _contract_for(
                [
                    {
                        "canonicalName": "Jalen Carter",
                        "displayName": "Jalen Carter",
                        "assetClass": "idp",
                        "position": "DL",
                        "playerId": "9999",
                        "canonicalConsensusRank": 38,
                        "rankDerivedValue": 6000,
                    }
                ],
                "2026-08-16",
            ),
            path=self.ledger,
        )

        # Run 2, byte-identical log: a genuine no-op — the fact is NOT
        # re-minted under player:9999.
        r2 = migrate.migrate_rank_history(log, path=self.ledger)
        self.assertEqual(r2["written"], 0)
        self.assertEqual(r2["alreadyMigrated"], 1)
        conn = store.connect(self.ledger)
        n = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE observed_date='2026-07-20'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n, 1)

    def test_migrate_ignores_same_date_log_rewrite(self):
        """The legacy log overwrites a date's entry in place (RED-5).
        The ledger keeps the first-migrated evidence rather than
        following the rewrite — and reports it, instead of spamming a
        content conflict on every deploy."""
        log = Path(self._td.name) / "rank_history.jsonl"
        log.write_text(
            json.dumps({"date": "2026-07-20", "ranks": {"Jalen Carter::idp": 40}}) + "\n"
        )
        migrate.migrate_rank_history(log, path=self.ledger)
        # The log's 2026-07-20 entry is later rewritten in place.
        log.write_text(
            json.dumps({"date": "2026-07-20", "ranks": {"Jalen Carter::idp": 44}}) + "\n"
        )
        r = migrate.migrate_rank_history(log, path=self.ledger)
        self.assertEqual((r["written"], len(r["contentConflicts"])), (0, 0))
        self.assertEqual(r["alreadyMigrated"], 1)
        got = asof.value_as_of("name:jalen carter::IDP", "2026-07-20", path=self.ledger)
        self.assertEqual(got["rank"], 40)  # first evidence stands

    def test_provenance_round_trip(self):
        _record_fixture_board(self.ledger, "2026-08-16")
        r = asof.value_as_of("player:5859", "2026-08-16", path=self.ledger)
        prov = r["provenance"]
        self.assertEqual(prov["origin"], "live:server")
        self.assertTrue(prov["pipelineVersion"])
        self.assertTrue(prov["recordedAt"])
        self.assertTrue(prov["contentHash"])
        self.assertEqual(prov["playerId"], "5859")


class TestValuationInertness(unittest.TestCase):
    """The ledger records and derives; it never moves a canonical value
    or rank.  Two full builds of the same real archived payload — one
    against a genuinely POPULATED ledger (seeded with a prior-day
    board, so rankChange actually derives comparators), one with the
    derivation off — must produce byte-identical values, ranks and
    tiers.  The populated build doubles as the end-to-end proof that
    ``build_api_data_contract`` threads the board's own date into the
    derivation: the prior-day comparator is found, so ranked rows stamp
    a real (zero) delta instead of None."""

    def test_ledger_presence_never_moves_values_or_ranks(self):
        import os
        import tempfile
        import zipfile
        from datetime import date as _date, timedelta
        from unittest import mock

        archive_dir = Path(__file__).resolve().parents[2] / "exports" / "archive"
        zips = sorted(archive_dir.glob("dynasty_export_*.zip"))
        if not zips:
            self.skipTest("no archive bundles in this checkout")
        with zipfile.ZipFile(zips[-1]) as z:
            data_name = next(
                n for n in z.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            raw = json.load(z.open(data_name))

        def snapshot(contract):
            return [
                (
                    r.get("canonicalName"),
                    r.get("assetClass"),
                    r.get("rankDerivedValue"),
                    r.get("canonicalConsensusRank"),
                    r.get("canonicalTierId"),
                )
                for r in contract["playersArray"]
            ]

        # Build 1 — derivation off.
        os.environ["RISKIT_FEATURE_LEDGER_RANK_CHANGE"] = "0"
        try:
            baseline = data_contract.build_api_data_contract(json.loads(json.dumps(raw)))
        finally:
            os.environ.pop("RISKIT_FEATURE_LEDGER_RANK_CHANGE", None)

        # Seed a ledger with the SAME board recorded under the prior
        # date, then build again with the derivation on and the default
        # ledger path patched to the seed.
        board_date = str(raw.get("date"))
        prior = (_date.fromisoformat(board_date) - timedelta(days=1)).isoformat()
        with tempfile.TemporaryDirectory() as td:
            seeded = Path(td) / "ledger.sqlite"
            store._reset_setup_cache_for_tests()
            record.record_contract(baseline, path=seeded, observed_date=prior)
            with mock.patch.object(store, "DB_PATH", seeded):
                populated = data_contract.build_api_data_contract(json.loads(json.dumps(raw)))

        self.assertEqual(snapshot(baseline), snapshot(populated))

        # Threading proof: the prior-day comparator was actually found
        # — identical boards a day apart stamp 0 (a found comparator),
        # not None (no comparator), on hundreds of ranked rows.
        stamped = [
            r.get("rankChange")
            for r in populated["playersArray"]
            if isinstance(r.get("canonicalConsensusRank"), int)
        ]
        zeros = sum(1 for v in stamped if v == 0)
        self.assertGreater(zeros, 500)
        self.assertTrue(all(v in (0, None) for v in stamped))
        # And the off-build stamped only None, as the rollback contract
        # requires.
        self.assertTrue(all(r.get("rankChange") is None for r in baseline["playersArray"]))


if __name__ == "__main__":
    unittest.main()
