"""ROS collector run status: kept-previous and the CONTENT clock.

``status`` / ``completed_at`` in a ROS run are the FETCH clock -- "did we
retrieve something".  They cannot say (a) that a zero-row fetch left the
previous CSV standing in, or (b) that a source's content has not moved in
weeks.  The run status now reports both, additively:

* ``kept_previous`` (``"zero_rows"``) + ``kept_previous_rows``;
* ``content_hash`` / ``content_state`` / ``content_first_observed_at`` /
  ``last_content_change`` -- a content clock persisted in
  ``data/ros/content_clock.json``.

REPORTING ONLY.  Nothing below may change a status the weight model reads, a
``scraped_at``, a row, or a multiplier -- the last section pins that.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest import mock

import pytest

from src.ros import api as ros_api
from src.ros import scrape
from src.ros.aggregate import SourceSnapshot

KEY = "demoSource"


def _row(name: str, rank: int, total: int = 3) -> dict:
    return {
        "sourceName": name,
        "canonicalName": name.lower(),
        "position": "QB",
        "team": "BUF",
        "rank": rank,
        "total_ranked": total,
        "projection": "",
    }


BOARD_A = [_row("Alpha", 1), _row("Beta", 2), _row("Gamma", 3)]
BOARD_B = [_row("Beta", 1), _row("Alpha", 2), _row("Gamma", 3)]  # same players, new order


class _Harness:
    """Drive ``scrape.run_all`` against a temp ROS root with a scripted adapter."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path
        self.snapshots: list[SourceSnapshot] = []
        self.src = {"key": KEY, "base_weight": 1.0, "scraper": "unused", "is_ros": True}

    def run(
        self,
        rows: list[dict],
        *,
        completed_at: str,
        adapter_status: str = "ok",
        error: str | None = None,
        sources: list[dict] | None = None,
        real_aggregate: bool = False,
    ) -> dict:
        def fake_adapter(src_meta):
            return scrape.ScrapeResult(
                source_key=str(src_meta["key"]),
                status=adapter_status,
                rows=[dict(r) for r in rows],
                error=error,
                started_at=completed_at,
                completed_at=completed_at,
                player_count=len(rows),
            )

        def fake_aggregate(snaps, **_kw):
            self.snapshots[:] = list(snaps)
            return []

        with (
            mock.patch.object(scrape, "ROS_DATA_DIR", self.root),
            mock.patch.object(scrape, "enabled_ros_sources", return_value=sources or [self.src]),
            mock.patch.object(scrape, "_invoke_adapter", side_effect=fake_adapter),
            mock.patch.object(
                scrape,
                "aggregate",
                side_effect=scrape.aggregate if real_aggregate else fake_aggregate,
            ),
            mock.patch.object(scrape, "_refresh_team_strength_snapshot", return_value={}),
            mock.patch.object(scrape, "_refresh_power_snapshots", return_value={}),
            mock.patch.object(scrape, "_refresh_sim_caches", return_value={}),
        ):
            return scrape.run_all(canonical_universe={"alpha", "beta", "gamma"})

    def index_entry(self, key: str = KEY) -> dict:
        index = json.loads((self.root / "runs" / "index.json").read_text(encoding="utf-8"))
        return index["sources"][key]

    def run_json(self, key: str = KEY) -> dict:
        rel = self.index_entry(key)["run_path"]
        return json.loads((self.root / rel).read_text(encoding="utf-8"))

    def ledger(self) -> dict:
        return json.loads((self.root / scrape.CONTENT_CLOCK_FILENAME).read_text(encoding="utf-8"))

    @property
    def csv(self) -> Path:
        return self.root / "sources" / f"{KEY}.csv"


@pytest.fixture()
def h(tmp_path: Path) -> _Harness:
    return _Harness(tmp_path)


# ── 1. a zero-row fetch is explicit, never "ok" ───────────────────────────


def test_zero_rows_keeps_previous_and_says_so(h: _Harness, caplog):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    before = h.csv.read_bytes()
    assert h.index_entry()["kept_previous"] is None

    with caplog.at_level(logging.WARNING, logger="ros.scrape"):
        h.run([], completed_at="2026-10-26T03:00:00+00:00")

    entry = h.index_entry()
    assert entry["kept_previous"] == scrape.KEPT_PREVIOUS_ZERO_ROWS == "zero_rows"
    assert entry["kept_previous_rows"] == 3
    assert entry["rows_written"] == 0
    assert entry["player_count"] == 0
    assert h.csv.read_bytes() == before, "the previous CSV must be left byte-identical"
    # The same fields land in the per-run JSON.
    run = h.run_json()
    assert run["kept_previous"] == "zero_rows"
    assert run["kept_previous_rows"] == 3
    # ... and the operator is told in the log.
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(KEY in r.getMessage() and "kept previous CSV" in r.getMessage() for r in warned)


def test_zero_row_fetch_never_reads_ok(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    # An adapter that CLAIMS success with nothing in it.
    h.run([], completed_at="2026-10-26T03:00:00+00:00", adapter_status="ok")
    entry = h.index_entry()
    assert entry["status"] != "ok"
    assert entry["kept_previous"] == "zero_rows"
    assert h.run_json()["status"] != "ok"


def test_zero_rows_after_a_crash_is_kept_previous_and_failed(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    h.run([], completed_at="2026-10-26T03:00:00+00:00", adapter_status="failed", error="http: 503")
    entry = h.index_entry()
    assert entry["status"] == "failed"
    assert entry["error"] == "http: 503"
    assert entry["kept_previous"] == "zero_rows"


def test_rows_unresolved_after_quarantine_is_also_zero_rows(h: _Harness):
    """An adapter that returns rows none of which resolve is a zero-row fetch."""
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    unresolved = [{**_row("Nobody", 1), "canonicalName": ""}]
    with mock.patch.object(
        scrape,
        "resolve_player",
        return_value=mock.Mock(canonical_name="", confidence=0.0),
    ):
        h.run(unresolved, completed_at="2026-10-26T03:00:00+00:00")
    entry = h.index_entry()
    assert entry["status"] != "ok"
    assert entry["kept_previous"] == "zero_rows"


def test_first_ever_zero_row_fetch_has_nothing_to_keep(h: _Harness):
    h.run([], completed_at="2026-10-26T01:00:00+00:00", adapter_status="failed", error="x")
    entry = h.index_entry()
    assert entry["kept_previous"] is None
    assert entry["kept_previous_rows"] is None
    assert entry["status"] != "ok"


def test_write_csv_outcome_distinguishes_kept_from_empty_write(tmp_path: Path):
    with mock.patch.object(scrape, "ROS_DATA_DIR", tmp_path):
        first = scrape._write_csv_outcome(KEY, BOARD_A)
        assert (first.rows_written, first.kept_previous) == (3, None)
        kept = scrape._write_csv_outcome(KEY, [])
        assert (kept.rows_written, kept.kept_previous, kept.kept_previous_rows) == (
            0,
            "zero_rows",
            3,
        )
        # Back-compat: the int-returning writer still reports 0 for a kept file.
        assert scrape._write_csv(KEY, []) == 0


def test_kept_header_only_file_reports_zero_kept_rows(tmp_path: Path):
    """A kept file with nothing in it must not read as reassurance."""
    with mock.patch.object(scrape, "ROS_DATA_DIR", tmp_path):
        empty_first = scrape._write_csv_outcome(KEY, [])  # no file yet -> header-only write
        assert empty_first.kept_previous is None
        again = scrape._write_csv_outcome(KEY, [])
        assert again.kept_previous == "zero_rows"
        assert again.kept_previous_rows == 0


# ── 2. the content clock ──────────────────────────────────────────────────


def test_first_observation_is_a_baseline_not_a_change(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    entry = h.index_entry()
    assert entry["content_state"] == "baseline"
    assert len(entry["content_hash"]) == 64
    assert entry["content_first_observed_at"] == "2026-10-26T01:00:00+00:00"
    # Unknown, not "now" and not zero: observing a file is not observing a change.
    assert entry["last_content_change"] is None
    assert h.ledger()["sources"][KEY]["content_hash"] == entry["content_hash"]


def test_unchanged_hash_keeps_last_content_change(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    h.run(BOARD_B, completed_at="2026-10-26T03:00:00+00:00")  # a genuine change
    changed = h.index_entry()
    assert changed["last_content_change"] == "2026-10-26T03:00:00+00:00"

    # Two more successful fetches that return exactly the same board.
    h.run(BOARD_B, completed_at="2026-10-26T05:00:00+00:00")
    h.run(BOARD_B, completed_at="2026-10-26T07:00:00+00:00")
    entry = h.index_entry()
    assert entry["status"] == "ok", "fetch status is still ok -- that is the whole point"
    assert entry["completed_at"] == "2026-10-26T07:00:00+00:00"
    assert entry["content_state"] == "unchanged"
    assert entry["content_hash"] == changed["content_hash"]
    assert entry["last_content_change"] == "2026-10-26T03:00:00+00:00"
    assert entry["content_first_observed_at"] == "2026-10-26T01:00:00+00:00"


def test_changed_hash_advances_last_content_change(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    first = h.index_entry()
    h.run(BOARD_B, completed_at="2026-10-26T03:00:00+00:00")
    second = h.index_entry()
    assert second["content_state"] == "changed"
    assert second["content_hash"] != first["content_hash"]
    assert second["last_content_change"] == "2026-10-26T03:00:00+00:00"
    # And it advances again on the next real change.
    h.run(BOARD_A, completed_at="2026-10-26T09:00:00+00:00")
    third = h.index_entry()
    assert third["content_state"] == "changed"
    assert third["last_content_change"] == "2026-10-26T09:00:00+00:00"
    assert third["content_first_observed_at"] == "2026-10-26T01:00:00+00:00"


def test_kept_previous_does_not_move_the_content_clock(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    h.run(BOARD_B, completed_at="2026-10-26T03:00:00+00:00")
    h.run([], completed_at="2026-10-26T05:00:00+00:00", adapter_status="failed", error="x")
    entry = h.index_entry()
    assert entry["kept_previous"] == "zero_rows"
    assert entry["content_state"] == "unchanged"
    assert entry["last_content_change"] == "2026-10-26T03:00:00+00:00"


def test_ledger_is_not_rewritten_when_nothing_changed(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    ledger_path = h.root / scrape.CONTENT_CLOCK_FILENAME
    before = ledger_path.read_bytes()
    with mock.patch.object(scrape, "save_state") as save:
        h.run(BOARD_A, completed_at="2026-10-26T03:00:00+00:00")
    save.assert_not_called()
    assert ledger_path.read_bytes() == before


def test_a_source_not_run_this_time_keeps_its_clock(h: _Harness):
    other = {"key": "otherSource", "base_weight": 1.0, "scraper": "unused", "is_ros": True}
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00", sources=[h.src, other])
    h.run(BOARD_B, completed_at="2026-10-26T03:00:00+00:00", sources=[h.src, other])
    h.run(BOARD_B, completed_at="2026-10-26T05:00:00+00:00", sources=[other])  # KEY disabled
    ledger = h.ledger()["sources"]
    assert ledger[KEY]["last_content_change"] == "2026-10-26T03:00:00+00:00"
    h.run(BOARD_B, completed_at="2026-10-26T07:00:00+00:00", sources=[h.src, other])
    entry = h.index_entry()
    assert entry["content_state"] == "unchanged"
    assert entry["last_content_change"] == "2026-10-26T03:00:00+00:00"


def test_line_endings_alone_do_not_look_like_a_content_change(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    original = h.csv.read_bytes()
    first_hash = h.index_entry()["content_hash"]
    # Re-checkout with different line endings; the rows are identical.
    h.csv.write_bytes(original.replace(b"\r\n", b"\n"))
    h.run([], completed_at="2026-10-26T03:00:00+00:00", adapter_status="failed", error="x")
    entry = h.index_entry()
    assert entry["kept_previous"] == "zero_rows"
    assert entry["content_hash"] == first_hash
    assert entry["content_state"] == "unchanged"


def test_missing_csv_is_a_failed_observation_not_a_change(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    prior = h.ledger()["sources"][KEY]
    entry, outcome = scrape.advance_content_clock(prior, None, "t")
    assert outcome == "no_file"
    assert entry == prior  # untouched


def test_unreadable_ledger_rebaselines_and_never_fails_the_scrape(h: _Harness, caplog):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    (h.root / scrape.CONTENT_CLOCK_FILENAME).write_text("{ not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="ros.scrape"):
        h.run(BOARD_A, completed_at="2026-10-26T03:00:00+00:00")
    assert h.index_entry()["content_state"] == "baseline"
    assert any("unreadable" in r.getMessage() for r in caplog.records)


def test_ledger_write_failure_does_not_fail_the_scrape(h: _Harness, caplog):
    with (
        caplog.at_level(logging.WARNING, logger="ros.scrape"),
        mock.patch.object(scrape, "save_state", side_effect=OSError("disk full")),
    ):
        summary = h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    assert summary["results"][KEY]["status"] == "ok"
    assert h.index_entry()["content_state"] == "baseline"
    assert any("failed to persist content clock" in r.getMessage() for r in caplog.records)


# ── pure clock ────────────────────────────────────────────────────────────


def test_advance_content_clock_is_pure_and_total():
    base, state = scrape.advance_content_clock(None, "h1", "t1")
    assert state == "baseline"
    assert base == {"content_hash": "h1", "first_observed_at": "t1", "last_content_change": None}

    frozen = dict(base)
    same, state = scrape.advance_content_clock(base, "h1", "t2")
    assert (same, state) == (frozen, "unchanged")
    assert base == frozen, "input must not be mutated"

    moved, state = scrape.advance_content_clock(base, "h2", "t3")
    assert state == "changed"
    assert moved == {
        "content_hash": "h2",
        "first_observed_at": "t1",
        "last_content_change": "t3",
    }
    assert base == frozen

    kept, state = scrape.advance_content_clock(moved, None, "t4")
    assert (kept, state) == (moved, "no_file")

    # A prior entry with no usable hash is re-baselined, not trusted.
    rebased, state = scrape.advance_content_clock({"content_hash": ""}, "h9", "t5")
    assert state == "baseline"
    assert rebased["last_content_change"] is None


# ── 3. additive on the status API ─────────────────────────────────────────


def test_status_endpoint_keeps_old_fields_and_adds_new_ones(h: _Harness):
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    h.run([], completed_at="2026-10-26T03:00:00+00:00")
    with mock.patch.object(ros_api, "ROS_DATA_DIR", h.root):
        body = json.loads(asyncio.run(ros_api.get_status()).body)
    source = body["sources"][KEY]
    # Every field a reader had before is still there ...
    for old in (
        "status",
        "player_count",
        "rows_written",
        "started_at",
        "completed_at",
        "error",
        "run_path",
    ):
        assert old in source
    # ... and the new ones ride along.
    assert source["kept_previous"] == "zero_rows"
    assert source["content_state"] == "unchanged"
    assert source["last_content_change"] is None
    assert len(source["content_hash"]) == 64


# ── 4. REPORTING ONLY: no value or weight input moved ─────────────────────


def test_snapshot_fed_to_the_aggregate_is_unchanged_by_the_new_fields(h: _Harness):
    """The weight model reads ``status``, ``scraped_at``, ``player_count``,
    ``has_valid_cache`` and the rows.  The content clock and ``kept_previous``
    feed none of them."""
    h.run(BOARD_A, completed_at="2026-10-26T01:00:00+00:00")
    h.run(BOARD_A, completed_at="2026-10-26T03:00:00+00:00")  # identical content, re-fetched
    (snap,) = h.snapshots
    assert snap.status == "ok"
    # scraped_at is still the FETCH time, not the (older) content-change time.
    assert snap.scraped_at == "2026-10-26T03:00:00+00:00"
    assert snap.player_count == 3
    assert snap.has_valid_cache is True
    assert [(r.canonical_name, r.rank) for r in snap.rows] == [
        ("alpha", 1),
        ("beta", 2),
        ("gamma", 3),
    ]
    assert set(vars(snap)) == {
        "source_key",
        "base_weight",
        "is_ros",
        "is_dynasty",
        "is_te_premium",
        "is_superflex",
        "is_2qb",
        "is_idp",
        "status",
        "scraped_at",
        "player_count",
        "has_valid_cache",
        "rows",
    }


def test_aggregate_output_is_identical_with_and_without_the_content_clock(tmp_path: Path):
    """Run the REAL aggregate twice over the same fetches -- once normally, once
    with the content clock and ``kept_previous`` bookkeeping switched off -- and
    require byte-identical player values.  Values come from rank, weight,
    freshness (fetch clock), completeness and availability; none of them may
    read the new fields."""
    from datetime import datetime, timezone

    def fetches(h: _Harness) -> dict:
        now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731
        h.run(BOARD_A, completed_at=now(), real_aggregate=True)
        h.run(BOARD_B, completed_at=now(), real_aggregate=True)
        h.run(BOARD_B, completed_at=now(), real_aggregate=True)  # same content, re-fetched
        h.run([], completed_at=now(), real_aggregate=True)  # zero rows, previous kept
        payload = json.loads((h.root / "aggregate" / "latest.json").read_text(encoding="utf-8"))
        for player in payload["players"]:
            player.pop("aggregatedAt", None)
        return payload["players"]

    with_clock = fetches(_Harness(tmp_path / "with"))

    plain = _Harness(tmp_path / "without")
    with (
        mock.patch.object(scrape, "_csv_content_hash", return_value=None),
        mock.patch.object(scrape, "_save_content_clock"),
    ):
        without_clock = fetches(plain)

    assert with_clock == without_clock
    assert not (plain.root / scrape.CONTENT_CLOCK_FILENAME).exists()
