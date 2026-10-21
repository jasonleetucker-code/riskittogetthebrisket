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


# ── systemd-initiated stops (no "Stopping" line) ──────────────────────────
# Stage 1's success criterion ("zero watchdog restarts, no OOM kill") reads
# this script, so a kill under the raised MemoryMax must be counted, not lost.

P = "2026-10-22T10:00:0{}.{:06d}+00:00 host "
STARTED = (
    P.format(9, 0) + "systemd[1]: Started dynasty.service - Dynasty Trade Calculator (dynasty)."
)

OOM_JOURNAL = "\n".join(
    [
        P.format(0, 1) + "kernel: python invoked oom-killer: gfp_mask=0xcc0(GFP_KERNEL), order=0",
        P.format(0, 2) + "kernel: Memory cgroup out of memory: Killed process 4242 (python)",
        P.format(0, 3)
        + "systemd[1]: dynasty.service: A process of this unit has been killed by the OOM killer.",
        P.format(0, 4)
        + "systemd[1]: dynasty.service: Main process exited, code=killed, status=9/KILL",
        P.format(0, 5) + "systemd[1]: dynasty.service: Failed with result 'oom-kill'.",
        P.format(0, 6)
        + "systemd[1]: dynasty.service: Consumed 30min 1.000s CPU time, 3.4G memory peak, 0B memory swap peak.",
        P.format(5, 0)
        + "systemd[1]: dynasty.service: Scheduled restart job, restart counter is at 1.",
        P.format(5, 1)
        + "systemd[1]: Stopped dynasty.service - Dynasty Trade Calculator (dynasty).",
        STARTED,
    ]
)


def test_an_oom_kill_without_a_stopping_line_is_counted_and_classified():
    parsed = rep.parse_log(OOM_JOURNAL)
    summary = rep.summarize(parsed)
    (stop,) = parsed["stops"]
    assert stop.kind == "oom_kill"
    assert not stop.requested and stop.oom_killed and stop.auto_restart
    assert stop.result == "oom-kill" and stop.exit_status == "9/KILL"
    assert stop.peak_bytes == pytest.approx(3.4 * 1024**3)
    assert summary["stops_total"] == 1
    assert summary["oom_kills"] == 1 and summary["systemd_initiated"] == 1
    assert summary["clean_stops"] == 0 and summary["watchdog_restarts"] == 0


def test_the_oom_result_alone_or_a_kernel_oom_line_alone_is_enough():
    result_only = "\n".join(
        [
            P.format(0, 4)
            + "systemd[1]: dynasty.service: Main process exited, code=killed, status=9/KILL",
            P.format(0, 5) + "systemd[1]: dynasty.service: Failed with result 'oom-kill'.",
            STARTED,
        ]
    )
    kernel_only = "\n".join(
        [
            P.format(0, 2) + "kernel: Memory cgroup out of memory: Killed process 4242 (python)",
            P.format(0, 4)
            + "systemd[1]: dynasty.service: Main process exited, code=killed, status=9/KILL",
            P.format(0, 5) + "systemd[1]: dynasty.service: Failed with result 'signal'.",
            STARTED,
        ]
    )
    for text in (result_only, kernel_only):
        assert [s.kind for s in rep.parse_log(text)["stops"]] == ["oom_kill"]


def test_a_crash_and_a_bare_auto_restart_are_distinct_kinds():
    crash = "\n".join(
        [
            P.format(0, 4)
            + "systemd[1]: dynasty.service: Main process exited, code=exited, status=1/FAILURE",
            P.format(0, 5) + "systemd[1]: dynasty.service: Failed with result 'exit-code'.",
            P.format(5, 0)
            + "systemd[1]: dynasty.service: Scheduled restart job, restart counter is at 1.",
            STARTED,
        ]
    )
    (stop,) = rep.parse_log(crash)["stops"]
    assert stop.kind == "crash" and stop.auto_restart
    bare = (
        P.format(5, 0)
        + "systemd[1]: dynasty.service: Scheduled restart job, restart counter is at 2.\n"
        + STARTED
    )
    summary = rep.summarize(rep.parse_log(bare))
    assert summary["auto_restarts_without_cause"] == 1 and summary["stops_total"] == 1


def test_other_units_failing_are_not_backend_stops():
    text = "\n".join(
        [
            P.format(0, 5)
            + "systemd[1]: dynasty-dlf-fetch.service: Failed with result 'exit-code'.",
            P.format(0, 6)
            + "systemd[1]: dynasty-frontend.service: Main process exited, code=killed, status=9/KILL",
            STARTED,
        ]
    )
    assert rep.parse_log(text)["stops"] == []


def test_the_backend_unit_can_be_named_when_no_started_line_is_in_the_window():
    text = P.format(0, 5) + "systemd[1]: dynasty.service: Failed with result 'oom-kill'."
    assert rep.parse_log(text)["stops"] == []  # unknown unit: nothing is guessed
    assert [s.kind for s in rep.parse_log(text, units=("dynasty.service",))["stops"]] == [
        "oom_kill"
    ]


def test_the_watchdog_and_clean_fixtures_are_unchanged_by_systemd_line_parsing():
    oct19 = rep.parse_log(
        (FIXTURES / "backend_restart_2026-10-19_08-42_excerpt.txt").read_text(encoding="utf-8")
    )
    (stop,) = oct19["stops"]
    assert stop.requested and stop.kind == "watchdog_restart" and stop.result == "timeout"
    clean = rep.parse_log(
        (FIXTURES / "backend_restart_2026-10-19_to_20_clean_stops_excerpt.txt").read_text(
            encoding="utf-8"
        )
    )
    assert {s.kind for s in clean["stops"]} == {"clean_stop"}


# ── --high-bytes and a removed MemoryHigh ─────────────────────────────────

WATCHDOG_NA_HIGH = "\n".join(
    [
        P.format(0, 0)
        + "dynasty-healthcheck.sh[1]: [healthcheck] snapshot mem reason=liveness-fail-1 "
        "cur=2700000000 peak=2700000000 high=na max=3221225472 ev_high=100 ev_max=0 ev_oom=0 ev_oom_kill=0",
        P.format(1, 0)
        + "dynasty-healthcheck.sh[1]: [healthcheck] threshold reached — restarting dynasty.service",
        P.format(1, 1) + "dynasty-healthcheck.sh[1]: [healthcheck] snapshot mem reason=pre-restart "
        "cur=2700000000 peak=2700000000 high=na max=3221225472 ev_high=900 ev_max=0 ev_oom=0 ev_oom_kill=0",
        P.format(2, 0)
        + "systemd[1]: Stopping dynasty.service - Dynasty Trade Calculator (dynasty)...",
    ]
)


def test_high_bytes_fills_in_an_unreadable_high_through_parse_log_and_the_cli(capsys, tmp_path):
    without = rep.parse_log(WATCHDOG_NA_HIGH)["stops"][0].verdict["verdict"]
    with_high = rep.parse_log(WATCHDOG_NA_HIGH, high_bytes=HIGH)["stops"][0].verdict["verdict"]
    assert without == "inconclusive"
    assert with_high == "memory_high_throttle_confirmed"
    log = tmp_path / "na.txt"
    log.write_text(WATCHDOG_NA_HIGH, encoding="utf-8")
    assert rep.main([str(log), "--format", "json", "--high-bytes", str(HIGH)]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["stops"][0]["verdict"]["verdict"] == "memory_high_throttle_confirmed"


def test_a_max_reading_means_no_memory_high_and_is_never_back_filled():
    snap = rep.Snapshot(ts="t", reason="liveness-fail-1")
    rep._fill(
        snap, "mem", " cur=2700000000 high=max max=3758096384 ev_high=0 ev_max=0 ev_oom_kill=0"
    )
    assert snap.high_unlimited and snap.high is None
    out = rep.classify_snapshots([snap], high_bytes=HIGH)  # stale config must not win
    assert out["verdict"] == "memory_high_not_configured"
    assert out["evidence"]["high_bytes"] is None and out["evidence"]["memory_high_unlimited"]
    assert out["evidence"]["cur_over_max"] == pytest.approx(2700000000 / 3758096384, abs=1e-4)
    near = rep.Snapshot(ts="t", reason="r")
    rep._fill(
        near, "mem", " cur=3700000000 high=max max=3758096384 ev_high=0 ev_max=0 ev_oom_kill=0"
    )
    assert rep.classify_snapshots([near])["verdict"] == "near_memory_max_no_high"
    unlimited = rep.Snapshot(ts="t", reason="r")
    rep._fill(unlimited, "mem", " cur=1 high=max max=max")
    assert (
        unlimited.max_unlimited
        and rep.classify_snapshots([unlimited])["verdict"] == "memory_high_not_configured"
    )


# ── masked input fails closed (GitHub masks "***" inside timestamps) ──────

RAW_DAY = FIXTURES / "backend_restart_2026-10-19_to_20_RAW_MASKED.txt"
RAW_1021 = FIXTURES / "backend_restart_2026-10-21_RAW_MASKED.txt"


def test_raw_masked_day_keeps_all_eleven_restarts_the_old_parser_merged():
    # In the published log the 03:52Z stop's "Consumed" line is masked in its
    # fractional seconds; the old parser skipped it and merged 03:52 with 06:20.
    parsed = rep.parse_log(RAW_DAY.read_text(encoding="utf-8"))
    summary = rep.summarize(parsed)
    assert summary["stops_total"] == 11 and summary["clean_stops"] == 11
    assert summary["input"] == "complete" and summary["reduced_precision_lines"] > 0
    by_hour = {s.ts[:16]: s for s in parsed["stops"]}
    assert by_hour["2026-10-20T03:52"].peak_text == "2.1G"
    assert by_hour["2026-10-20T06:20"].peak_text == "2.0G"
    # the masked unit name is found from its description
    assert {s.unit for s in parsed["stops"]} == {"***.service"}


def test_raw_masked_21st_still_confirms_the_throttle():
    summary = rep.summarize(rep.parse_log(RAW_1021.read_text(encoding="utf-8")))
    assert summary["watchdog_restarts"] == 1 and summary["input"] == "complete"
    stop = [s for s in rep.parse_log(RAW_1021.read_text(encoding="utf-8"))["stops"] if s.verdict][0]
    assert stop.verdict["verdict"] == "memory_high_throttle_confirmed"


def _mask_ts(line: str) -> str:
    """Mask the HOUR of a journal timestamp, as GitHub does for any 22:xx line."""
    return line[:11] + "***" + line[13:]


def test_a_fully_masked_consumed_line_cannot_merge_two_restarts_and_is_incomplete(capsys, tmp_path):
    lines = (
        (FIXTURES / "backend_restart_2026-10-19_to_20_clean_stops_excerpt.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    lines = [
        _mask_ts(ln) if ln.startswith("2026-10-20T03:52:20.685") and "Consumed" in ln else ln
        for ln in lines
    ]
    text = "\n".join(lines)
    parsed = rep.parse_log(text)
    summary = rep.summarize(parsed)
    assert summary["stops_total"] == 11  # Stopped/Started close the record
    by_hour = {s.ts[:16]: s for s in parsed["stops"]}
    assert by_hour["2026-10-20T03:52"].peak_text is None  # its peak is honestly missing
    assert by_hour["2026-10-20T06:20"].peak_text == "2.0G"
    assert summary["input"] == "incomplete"
    assert parsed["unparseable_relevant_kinds"] == {"consumed": 1}
    log = tmp_path / "masked.txt"
    log.write_text(text, encoding="utf-8")
    assert rep.main([str(log)]) == 3  # never a pass
    assert "INPUT INCOMPLETE" in capsys.readouterr().out


def test_a_masked_watchdog_restart_is_never_reported_as_a_clean_pass(tmp_path):
    lines = (
        (FIXTURES / "backend_restart_2026-10-19_08-42_excerpt.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    masked = [
        _mask_ts(ln) if ("threshold reached" in ln or "stop-sigterm" in ln) else ln for ln in lines
    ]
    parsed = rep.parse_log("\n".join(masked))
    summary = rep.summarize(parsed)
    # with both tell-tale lines masked, the stop LOOKS clean ...
    assert [s.kind for s in parsed["stops"]] == ["clean_stop"]
    # ... and the report refuses to call that a result
    assert summary["input"] == "incomplete"
    assert parsed["unparseable_relevant_kinds"] == {"sigterm_timeout": 1, "watchdog_threshold": 1}
    log = tmp_path / "w.txt"
    log.write_text("\n".join(masked), encoding="utf-8")
    assert rep.main([str(log), "--format", "json"]) == 3


def test_masked_lines_about_other_units_do_not_block():
    text = (
        "2026-10-21T07:***:36.657278+00:00 host systemd[1]: ***-game-day-live.service: "
        "Deactivated successfully.\n" + OOM_JOURNAL
    )
    parsed = rep.parse_log(text)
    assert parsed["unparseable_other_lines"] == 1 and parsed["unparseable_relevant_lines"] == 0
    assert rep.summarize(parsed)["input"] == "complete"


def test_a_new_stopping_always_starts_a_new_record():
    text = "\n".join(
        [
            "2026-10-20T03:52:20.000000+00:00 host systemd[1]: Stopping dynasty.service - Dynasty Trade Calculator (dynasty)...",
            # every closing line of the first stop is missing
            "2026-10-20T06:20:47.000000+00:00 host systemd[1]: Stopping dynasty.service - Dynasty Trade Calculator (dynasty)...",
        ]
    )
    assert len(rep.parse_log(text)["stops"]) == 2


# ── canary observability (M1) ─────────────────────────────────────────────


def test_host_full_stall_is_read_and_every_breaching_snapshot_is_listed():
    snap = rep.Snapshot(ts="t", reason="liveness-fail-1")
    rep._fill(snap, "host", " mem_available_kb=1000000 h_some_avg10=30.0 h_full_avg10=25.5")
    rep._fill(
        snap, "mem", " cur=3700000000 high=max max=3758096384 ev_high=0 ev_max=0 ev_oom_kill=1"
    )
    assert snap.host_mem_stall_full_avg10 == 25.5
    (hit,) = rep.trigger_breaches([snap])
    assert set(hit["breaches"]) == {
        "host_mem_available_below_1.5GiB",
        "host_mem_stall_full_above_10pct(scrape_window_unknown)",
        "backend_cgroup_at_or_above_3.4GiB",
        "backend_cgroup_oom_kill",
    }


def test_a_masked_trigger_input_is_unknown_not_healthy():
    snap = rep.Snapshot(ts="t", reason="liveness-fail-2")
    rep._fill(snap, "host", " mem_available_kb=4652916 h_full_avg10=***.64")
    rep._fill(snap, "mem", " cur=2739773440 ev_oom_kill=0")
    (row,) = rep.trigger_breaches([snap])
    assert row["breaches"] == [] and row["unknown"] == ["host_mem_stall_full_avg10"]
    summary_rows = rep.summarize({"stops": [], "snapshots": [snap], "snapshots_total": 1})
    assert summary_rows["trigger_unknown_snapshots"][0]["unknown"] == ["host_mem_stall_full_avg10"]


def test_recovered_failures_kernel_ooms_and_other_units_ooms_are_summarized():
    text = "\n".join(
        [
            "2026-10-19T08:28:13.000000+00:00 host h[1]: [healthcheck] LIVENESS FAIL 1/3: no HTTP response",
            # the watchdog always logs "mem" first; it opens the snapshot
            "2026-10-19T08:28:13.050000+00:00 host h[1]: [healthcheck] snapshot mem reason=liveness-fail-1 "
            "cur=2000000000 high=2684354560 max=3221225472 ev_high=0 ev_max=0 ev_oom=0 ev_oom_kill=0",
            "2026-10-19T08:28:13.100000+00:00 host h[1]: [healthcheck] snapshot host reason=liveness-fail-1 "
            "mem_available_kb=900000 h_full_avg10=12.0",
            "2026-10-19T08:29:48.000000+00:00 host h[1]: [healthcheck] recovered: responding again",
            "2026-10-19T09:00:00.000000+00:00 host kernel: Memory cgroup out of memory: Killed process 77 (node)",
            "2026-10-19T09:00:00.100000+00:00 host systemd[1]: dynasty-frontend.service: "
            "A process of this unit has been killed by the OOM killer.",
            "2026-10-19T09:00:00.200000+00:00 host systemd[1]: dynasty-frontend.service: Failed with result 'oom-kill'.",
            STARTED,
        ]
    )
    summary = rep.summarize(rep.parse_log(text))
    assert summary["liveness_fail_lines"] == 1 and summary["recoveries_without_restart"] == 1
    assert summary["kernel_oom_lines"] == 1
    assert summary["other_unit_oom_kills"] == {"dynasty-frontend.service": 2}
    assert summary["stops_total"] == 0  # the frontend's kill is not a backend stop
    # the recovered failure's snapshot is not attached to any stop, and is still checked
    assert summary["trigger_breaches"][0]["reason"] == "liveness-fail-1"


def test_high_bytes_against_a_removed_memory_high_is_called_out():
    snap = rep.Snapshot(ts="t", reason="r")
    rep._fill(snap, "mem", " cur=1 high=max max=3758096384")
    summary = rep.summarize(
        {"stops": [], "snapshots": [snap], "snapshots_total": 1}, high_bytes=HIGH
    )
    assert any("--high-bytes ignored" in n for n in summary["notes"])
