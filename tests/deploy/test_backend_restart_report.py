"""The restart report classifies stops from counters, and refuses to guess without them.

``scripts/backend_restart_report.py`` is offline.  These tests feed it sanitized
excerpts of the public ``Production Restart Diagnostics (read-only)`` logs for
the two production stalls (2026-10-19 08:42 UTC and 2026-10-21 07:53 UTC) plus
24 hours of clean stops, and synthetic snapshots for the verdict boundaries.

What is pinned:

* the 2026-10-21 stall is ``memory_high_throttle_confirmed`` -- the cgroup sat
  at ``memory.high``, ``memory.events high`` rose by 63,440 across the stall,
  ``max`` and ``oom_kill`` stayed at zero;
* the 2026-10-19 stall has NO counters and is reported as such, never as a
  throttle verdict;
* snapshots logged by the NEW process after the restart are not attributed to
  the stall that caused it;
* a masked or ``na`` value is ``None``, never zero, and cannot promote a
  verdict;
* every verdict carries the "throttling is not proven to be the only cause"
  caveat.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import backend_restart_report as rep

FIXTURES = Path(__file__).parent / "fixtures"
HIGH = 2560 * 1024**2  # MemoryHigh=2560M, as MEASURED in the diagnostics (2684354560)


def _load(name: str) -> dict:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return rep.parse_log(text)


def _snap(**kw) -> rep.Snapshot:
    return rep.Snapshot(ts="2026-10-21T07:51:17+00:00", reason="liveness-fail-1", **kw)


def test_high_constant_matches_the_measured_unit_property():
    assert HIGH == 2684354560


def test_2026_10_21_stall_is_a_confirmed_memory_high_throttle():
    parsed = _load("backend_restart_2026-10-21_excerpt.txt")
    watchdog = [s for s in parsed["stops"] if s.kind == "watchdog_restart"]
    assert len(watchdog) == 1
    verdict = watchdog[0].verdict
    assert verdict["verdict"] == "memory_high_throttle_confirmed"
    ev = verdict["evidence"]
    assert ev["ev_high_first"] == 63734
    assert ev["ev_high_last"] == 127174
    assert ev["ev_high_delta"] == 63440
    assert ev["ev_max"] == 0
    assert ev["ev_oom_kill"] == 0
    assert ev["cur_over_high"] > 1.0
    assert ev["anon_share_of_cur"] > 0.99  # swapless host: nothing reclaimable
    assert ev["file_bytes"] < 1024**2  # the cgroup's own file cache was gone
    assert ev["memory_stall_full_avg10_max"] > 30


def test_snapshots_from_the_new_process_are_not_attributed_to_the_stall():
    watchdog = [
        s
        for s in _load("backend_restart_2026-10-21_excerpt.txt")["stops"]
        if s.kind == "watchdog_restart"
    ][0]
    # liveness-fail-1/2/3 + pre-restart; the fixture also holds a fifth
    # snapshot logged 34 s later by the freshly started process (cur=81 MB).
    assert [s.reason for s in watchdog.snapshots] == [
        "liveness-fail-1",
        "liveness-fail-2",
        "liveness-fail-3",
        "pre-restart",
    ]
    assert all(s.cur > 2_000_000_000 for s in watchdog.snapshots)


def test_2026_10_19_stall_has_no_counters_and_is_not_labelled_a_throttle():
    parsed = _load("backend_restart_2026-10-19_08-42_excerpt.txt")
    summary = rep.summarize(parsed, high_bytes=HIGH)
    (stop,) = parsed["stops"]
    assert stop.kind == "watchdog_restart" and stop.sigterm_timed_out
    assert stop.verdict["verdict"] == "no_cgroup_counters"
    assert stop.verdict["snapshots"] == 0
    # circumstantial only: the systemd peak (rounded to one decimal) is at/above high
    assert stop.verdict["systemd_peak_at_or_above_high"] is True
    assert "rounded" in stop.verdict["note"]
    assert summary["watchdog_restarts"] == 1


def test_a_day_of_clean_stops_is_eleven_deploy_restarts_and_no_watchdog():
    parsed = _load("backend_restart_2026-10-19_to_20_clean_stops_excerpt.txt")
    summary = rep.summarize(parsed, high_bytes=HIGH)
    assert summary["stops_total"] == 11
    assert summary["clean_stops"] == 11
    assert summary["watchdog_restarts"] == 0 and summary["killed_other"] == 0
    assert 22 < summary["span_hours_first_to_last_stop"] < 24
    # peaks are systemd's one-decimal GiB; the highest clean one sits AT the
    # 2560 MiB throttle line, which is why it may be censored by it.
    assert summary["clean_stop_peak_bytes_max"] == pytest.approx(2.5 * 1024**3)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2.5G", 2.5 * 1024**3), ("93.9M", 93.9 * 1024**2), ("512K", 512 * 1024), ("7", 7.0)],
)
def test_systemd_size_parses_with_its_rounding_slack(text, expected):
    got = rep.parse_systemd_size(text)
    assert got is not None and got[0] == pytest.approx(expected)
    assert got[1] > 0


@pytest.mark.parametrize("text", ["", "na", "max", "3***1***5472", "2.5GB"])
def test_unparseable_sizes_are_none(text):
    assert rep.parse_systemd_size(text) is None


def test_masked_and_na_values_are_none_never_zero():
    snap = rep.Snapshot(ts="t", reason="r")
    rep._fill(
        snap,
        "mem",
        " cur=2744926208 peak=na high=2684354560 max=3***1***5472 ev_high=127174 ev_max=na",
    )
    assert snap.cur == 2744926208
    assert snap.peak is None and snap.max is None and snap.ev_max is None
    assert snap.high == 2684354560


def test_unknown_counters_cannot_promote_a_verdict():
    # at high, but ev_high unreadable: no throttle claim, and not "below" either.
    out = rep.classify_snapshots([_snap(cur=HIGH, high=HIGH, ev_high=None)])
    assert out["verdict"] == "at_memory_high_throttle_unproven"
    # a zero counter at the line is the same: nothing shows it throttled.
    zero = rep.classify_snapshots([_snap(cur=HIGH, high=HIGH, ev_high=0, ev_max=0)])
    assert zero["verdict"] == "at_memory_high_throttle_unproven"
    assert rep.classify_snapshots([_snap()])["verdict"] == "inconclusive"


def test_single_snapshot_is_likely_not_confirmed():
    out = rep.classify_snapshots([_snap(cur=HIGH + 1, high=HIGH, ev_high=900, ev_max=0)])
    assert out["verdict"] == "memory_high_throttle_likely"
    assert out["evidence"]["ev_high_delta"] is None


def test_a_flat_counter_across_snapshots_is_likely_not_confirmed():
    a = _snap(cur=HIGH, high=HIGH, ev_high=900, ev_max=0)
    b = _snap(cur=HIGH, high=HIGH, ev_high=900, ev_max=0)
    assert rep.classify_snapshots([a, b])["verdict"] == "memory_high_throttle_likely"


def test_rising_counter_at_high_is_confirmed():
    a = _snap(cur=HIGH, high=HIGH, ev_high=900, ev_max=0)
    b = _snap(cur=HIGH + 5, high=HIGH, ev_high=1500, ev_max=0)
    assert rep.classify_snapshots([a, b])["verdict"] == "memory_high_throttle_confirmed"


def test_an_oom_kill_outranks_everything():
    a = _snap(cur=HIGH, high=HIGH, ev_high=900, ev_max=1, ev_oom_kill=1)
    b = _snap(cur=HIGH, high=HIGH, ev_high=1500, ev_max=1, ev_oom_kill=1)
    assert rep.classify_snapshots([a, b])["verdict"] == "oom_kill"


def test_reaching_memory_max_without_a_kill_is_its_own_verdict():
    a = _snap(cur=HIGH, high=HIGH, ev_high=900, ev_max=0)
    b = _snap(cur=HIGH, high=HIGH, ev_high=1500, ev_max=3, ev_oom_kill=0)
    assert rep.classify_snapshots([a, b])["verdict"] == "memory_max_reached_no_oom_kill"


def test_a_cgroup_well_below_high_points_elsewhere():
    out = rep.classify_snapshots([_snap(cur=HIGH // 2, high=HIGH, ev_high=0, ev_max=0)])
    assert out["verdict"] == "below_memory_high"


def test_no_snapshots_is_no_counters():
    assert rep.classify_snapshots([])["verdict"] == "no_cgroup_counters"


def test_every_verdict_carries_the_not_the_only_cause_caveat():
    for snaps in ([], [_snap(cur=HIGH, high=HIGH, ev_high=5)], [_snap()]):
        assert "does not prove" in rep.classify_snapshots(snaps)["caveat"]


def test_cli_json_and_missing_input(tmp_path, capsys):
    fx = FIXTURES / "backend_restart_2026-10-21_excerpt.txt"
    assert rep.main([str(fx), "--format", "json", "--high-bytes", str(HIGH)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["summary"]["watchdog_restarts"] == 1
    assert rep.main([str(tmp_path / "does-not-exist.log")]) == 2
    assert "cannot read" in capsys.readouterr().err
    assert rep.main([str(fx)]) == 0
    assert "memory_high_throttle_confirmed" in capsys.readouterr().out
