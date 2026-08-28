"""Unit tests for ``scripts/diff_bdvm_snapshots.py``.

Pins the properties the V1-49 activation workflow's "BDVM rerun against
challenger output" measurement depends on:

1. Records are matched by (playerKey, season, source); an added/removed
   player is reported, not silently dropped or fabricated as a zero
   delta.
2. Numeric field deltas are computed only from already-published
   numbers — this tool never recomputes a fantasy-points value.
3. Provenance flips (e.g. a proxy record superseded by a real one) are
   reported even when the point totals happen to match.
4. Unchanged records are counted, not listed, and excluded from
   "changed".
5. `changed` is sorted by the largest absolute numeric delta first.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "diff_bdvm_snapshots.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("diff_bdvm_snapshots", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()


def _record(player_key, source="idpShow", season=2026, **overrides):
    base = {
        "source": source,
        "playerKey": player_key,
        "position": "LB",
        "season": season,
        "asOf": "2026-08-28",
        "games": 17,
        "statLine": None,
        "statBasis": "season",
        "fpg": 10.0,
        "fpts": 170.0,
        "scoringNative": True,
        "isProxy": False,
        "projHigh": None,
        "projLow": None,
    }
    base.update(overrides)
    return base


def _write_snapshot(path: Path, records: list[dict], season=2026, as_of="2026-08-28"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"asOf": as_of, "season": season, "recordCount": len(records), "records": records}
        )
    )


def test_added_and_removed_players_are_reported(tmp_path):
    before = [_record("player-a")]
    after = [_record("player-a"), _record("player-b")]
    report = _mod.diff_records(before, after)
    assert report["addedCount"] == 1
    assert report["added"][0]["playerKey"] == "player-b"
    assert report["removedCount"] == 0


def test_removed_player_is_reported_not_dropped(tmp_path):
    before = [_record("player-a"), _record("player-b")]
    after = [_record("player-a")]
    report = _mod.diff_records(before, after)
    assert report["removedCount"] == 1
    assert report["removed"][0]["playerKey"] == "player-b"


def test_numeric_field_delta_is_computed_correctly(tmp_path):
    before = [_record("player-a", fpg=10.0, fpts=170.0)]
    after = [_record("player-a", fpg=12.5, fpts=212.5)]
    report = _mod.diff_records(before, after)
    assert report["changedCount"] == 1
    changed = report["changed"][0]
    assert changed["fieldDeltas"]["fpg"]["delta"] == 2.5
    assert changed["fieldDeltas"]["fpts"]["delta"] == 42.5


def test_unchanged_records_are_counted_not_listed(tmp_path):
    rec = _record("player-a")
    report = _mod.diff_records([rec], [dict(rec)])
    assert report["unchangedCount"] == 1
    assert report["changedCount"] == 0
    assert report["changed"] == []


def test_provenance_flip_is_reported_even_with_identical_points(tmp_path):
    before = [_record("player-a", isProxy=True, fpg=10.0, fpts=170.0)]
    after = [_record("player-a", isProxy=False, fpg=10.0, fpts=170.0)]
    report = _mod.diff_records(before, after)
    assert report["changedCount"] == 1
    changed = report["changed"][0]
    assert changed["fieldDeltas"] == {}
    assert changed["provenanceDeltas"]["isProxy"] == {"before": True, "after": False}


def test_changed_is_sorted_by_largest_absolute_delta_first(tmp_path):
    before = [
        _record("small-move", fpg=10.0, fpts=170.0),
        _record("big-move", fpg=10.0, fpts=170.0),
    ]
    after = [
        _record("small-move", fpg=10.5, fpts=178.5),
        _record("big-move", fpg=20.0, fpts=340.0),
    ]
    report = _mod.diff_records(before, after)
    assert [c["playerKey"] for c in report["changed"]] == ["big-move", "small-move"]


def test_different_sources_for_the_same_player_are_distinct_records(tmp_path):
    before = [_record("player-a", source="idpShow"), _record("player-a", source="mikeClay")]
    after = [_record("player-a", source="idpShow", fpg=15.0, fpts=255.0)]
    report = _mod.diff_records(before, after)
    assert report["changedCount"] == 1
    assert report["removedCount"] == 1
    assert report["removed"][0]["source"] == "mikeClay"


def test_diff_snapshots_reads_files_and_stamps_metadata(tmp_path):
    before_path = tmp_path / "projections_2026-08-27_v149_pre.json"
    after_path = tmp_path / "projections_2026-08-28_v149_post.json"
    _write_snapshot(before_path, [_record("player-a", fpg=10.0, fpts=170.0)], as_of="2026-08-27")
    _write_snapshot(after_path, [_record("player-a", fpg=12.0, fpts=204.0)], as_of="2026-08-28")

    report = _mod.diff_snapshots(before_path, after_path)
    assert report["beforeAsOf"] == "2026-08-27"
    assert report["afterAsOf"] == "2026-08-28"
    assert report["changedCount"] == 1


def test_top_n_truncates_lists_but_not_counts(tmp_path):
    before = [_record(f"player-{i}", fpg=10.0, fpts=170.0) for i in range(5)]
    after = [_record(f"player-{i}", fpg=10.0 + i + 1, fpts=170.0 + i + 1) for i in range(5)]
    report = _mod.diff_records(before, after)
    assert report["changedCount"] == 5

    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    _write_snapshot(before_path, before)
    _write_snapshot(after_path, after)
    truncated = _mod.diff_snapshots(before_path, after_path, top_n=2)
    assert truncated["changedCount"] == 5
    assert len(truncated["changed"]) == 2


def test_missing_snapshot_file_raises(tmp_path):
    try:
        _mod.load_snapshot_payload(tmp_path / "nope.json")
        raise AssertionError("expected SnapshotDiffError")
    except _mod.SnapshotDiffError:
        pass


def test_malformed_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    try:
        _mod.load_snapshot_payload(bad)
        raise AssertionError("expected SnapshotDiffError")
    except _mod.SnapshotDiffError:
        pass


def test_cli_diff(tmp_path, capsys):
    before_path = tmp_path / "before.json"
    after_path = tmp_path / "after.json"
    _write_snapshot(before_path, [_record("player-a", fpg=10.0, fpts=170.0)])
    _write_snapshot(after_path, [_record("player-a", fpg=12.0, fpts=204.0)])

    rc = _mod.main(["--before", str(before_path), "--after", str(after_path)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["changedCount"] == 1
