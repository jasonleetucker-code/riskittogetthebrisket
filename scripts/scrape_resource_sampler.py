#!/usr/bin/env python3
"""Out-of-process resource sampler for the production scrape.

WHY THIS RUNS OUTSIDE THE SERVER — THE WHOLE POINT
---------------------------------------------------
Production suffers repeating multi-minute total outages during the
scrape's KTC phase. The observed signature is the key clue: the site goes
**completely silent first** (curl exit 28, zero bytes, ~3 minutes) and
only returns 502s at the very *end* of the window. A clean cgroup
OOM-kill of the dynasty process alone cannot produce that ordering —
nginx is alive with a 5s ``proxy_connect_timeout``, so a dead upstream
would 502 immediately, not after three minutes of silence. Silence first,
502s last, is what you would expect if **nginx itself were starved too**,
with the 502s appearing only once dynasty died and released resource.

Testing that requires system-wide measurements taken by a process that is
**not** dynasty — because dynasty may be the victim here rather than the
cause, and a dead process reports nothing. Hence a separate, detached
sampler that keeps writing after the server is killed and records the
exact sample in which the server's PID disappeared.

SURVIVABILITY — HONESTLY STATED
-------------------------------
The sampler is spawned by the scrape, so it lives in the same systemd
cgroup. The unit (``deploy/systemd/dynasty.service.template``) sets
``MemoryMax=3G`` but **no ``OOMPolicy=``**, so ``memory.oom.group`` keeps
its default of 0: the kernel kills the single highest-badness task (the
large RSS consumer — Chromium or uvicorn), not the whole group. A ~10 MB
stdlib sampler is never that victim, so it should survive the kill that
matters. It is NOT guaranteed: if the unit ever gains ``OOMPolicy=kill``,
the group dies together. Even then the flushed samples up to that instant
survive, which is strictly more than exists today.

Bounded by construction: a hard max duration plus an exit once the target
PID has been gone for a few samples, so it can never leak. systemd's
default ``KillMode=control-group`` reaps it on unit restart as a second
backstop.

Kept to pure stdlib on purpose — no psutil (absent from requirements
anyway), nothing that would add meaningful RSS to a box we suspect of
running out of memory.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.diagnostics import proc_probe  # noqa: E402
from src.diagnostics import scrape_telemetry as telemetry  # noqa: E402

# Phases during which we sample harder. The KTC/browser window is where
# every observed outage has happened, and a 5s cadence can miss the whole
# collapse-and-restart cycle.
HOT_PHASES = {"browser", "source_start"}
HOT_SOURCES = {"KTC"}


def _interval_for(phase: dict, base: float, hot: float) -> float:
    if str(phase.get("phase") or "") in HOT_PHASES:
        return hot
    if str(phase.get("source") or "") in HOT_SOURCES:
        return hot
    return base


def build_sample(
    target_pid: int,
    run_id: str,
    prev_cpu: dict | None,
    prev_tree: dict | None,
    elapsed: float,
) -> dict:
    """One fully-populated telemetry row.

    Every field the owner asked for, plus the deltas that turn two
    cumulative counters into a rate (a single /proc reading cannot
    express CPU utilization).
    """
    phase = telemetry.read_phase()
    tree = proc_probe.sample_process_tree(target_pid)
    meminfo = proc_probe.read_meminfo()
    cgroup_dir = proc_probe.resolve_cgroup_dir(target_pid if tree.get("pid_alive") else os.getpid())

    sample: dict[str, object] = {
        "ts": telemetry.utc_now_iso(),
        "kind": "sample",
        "run_id": run_id,
        "sampler_pid": os.getpid(),
        "elapsed_s": round(elapsed, 2),
        "phase": phase.get("phase"),
        "phase_source": phase.get("source"),
        "phase_detail": phase.get("detail"),
        "phase_ts": phase.get("ts"),
        "target_pid": target_pid,
        "target_alive": tree.get("pid_alive"),
        "app_rss_kb": tree.get("app_rss_kb"),
        "app_proc_count": tree.get("app_proc_count"),
        "chromium_rss_kb": tree.get("chromium_rss_kb"),
        "chromium_proc_count": tree.get("chromium_proc_count"),
        "meminfo_kb": meminfo,
        "loadavg": proc_probe.read_loadavg(),
    }

    total_rss = int(tree.get("app_rss_kb") or 0) + int(tree.get("chromium_rss_kb") or 0)
    sample["tree_rss_kb"] = total_rss

    if meminfo.get("MemTotal") and meminfo.get("MemAvailable") is not None:
        sample["mem_available_pct"] = round(
            100.0 * meminfo["MemAvailable"] / meminfo["MemTotal"], 2
        )
    if meminfo.get("SwapTotal"):
        used = meminfo["SwapTotal"] - meminfo.get("SwapFree", 0)
        sample["swap_used_kb"] = used
        sample["swap_used_pct"] = round(100.0 * used / meminfo["SwapTotal"], 2)

    # PSI: the clearest single signal for "was anything actually stalled".
    for kind in ("memory", "cpu", "io"):
        psi = proc_probe.read_pressure(kind)
        if psi:
            sample[f"psi_{kind}"] = psi

    sample.update(proc_probe.read_cgroup_metrics(cgroup_dir))

    # CPU rates need two readings; emit absolutes too so a single
    # surviving sample is still interpretable.
    cpu_now = proc_probe.read_total_cpu_ticks()
    if cpu_now:
        sample["cpu_total_ticks"] = cpu_now["total"]
        sample["cpu_idle_ticks"] = cpu_now["idle"]
        if prev_cpu:
            d_total = cpu_now["total"] - prev_cpu["total"]
            d_idle = cpu_now["idle"] - prev_cpu["idle"]
            if d_total > 0:
                sample["cpu_util_pct"] = round(100.0 * (d_total - d_idle) / d_total, 2)

    if prev_tree is not None and elapsed > 0:
        ticks = proc_probe.clock_ticks_per_second()
        for prefix in ("app", "chromium"):
            key = f"{prefix}_cpu_ticks"
            delta = int(tree.get(key) or 0) - int(prev_tree.get(key) or 0)
            dt = elapsed - float(prev_tree.get("_elapsed") or 0.0)
            if dt > 0 and delta >= 0:
                sample[f"{prefix}_cpu_pct"] = round(100.0 * (delta / ticks) / dt, 2)

    tree["_elapsed"] = elapsed
    return sample


def run(
    target_pid: int,
    run_id: str,
    interval: float,
    hot_interval: float,
    max_seconds: float,
    gone_samples_before_exit: int,
) -> int:
    started = time.monotonic()
    prev_cpu = proc_probe.read_total_cpu_ticks()
    prev_tree: dict | None = None
    gone_streak = 0

    telemetry.record(
        "sampler_started",
        run_id=run_id,
        target_pid=target_pid,
        sampler_pid=os.getpid(),
        interval_s=interval,
        hot_interval_s=hot_interval,
        max_seconds=max_seconds,
    )

    while True:
        elapsed = time.monotonic() - started
        if elapsed >= max_seconds:
            telemetry.record(
                "sampler_stopped", run_id=run_id, reason="max_duration", elapsed_s=round(elapsed, 1)
            )
            return 0

        try:
            sample = build_sample(target_pid, run_id, prev_cpu, prev_tree, elapsed)
            telemetry.record_sample(sample)

            cpu_now = proc_probe.read_total_cpu_ticks()
            if cpu_now:
                prev_cpu = cpu_now
            prev_tree = proc_probe.sample_process_tree(target_pid)
            prev_tree["_elapsed"] = elapsed

            if sample.get("target_alive"):
                gone_streak = 0
            else:
                gone_streak += 1
                if gone_streak == 1:
                    # The moment the server died. Loudest possible marker.
                    telemetry.record(
                        "target_pid_vanished",
                        run_id=run_id,
                        target_pid=target_pid,
                        elapsed_s=round(elapsed, 1),
                        note="dynasty process is gone; sampler continuing to observe recovery",
                    )
                if gone_streak >= gone_samples_before_exit:
                    telemetry.record(
                        "sampler_stopped",
                        run_id=run_id,
                        reason="target_gone",
                        elapsed_s=round(elapsed, 1),
                    )
                    return 0
        except Exception as exc:  # noqa: BLE001 — sampler must never die on a bad read
            telemetry.record("sampler_error", run_id=run_id, error=f"{type(exc).__name__}: {exc}")

        phase = telemetry.read_phase()
        time.sleep(_interval_for(phase, interval, hot_interval))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target-pid", type=int, required=True)
    ap.add_argument("--run-id", default="")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument(
        "--hot-interval",
        type=float,
        default=2.0,
        help="Sampling interval during the browser/KTC phases.",
    )
    ap.add_argument(
        "--max-seconds",
        type=float,
        default=3600.0,
        help="Hard lifetime cap so the sampler can never leak.",
    )
    ap.add_argument("--gone-samples-before-exit", type=int, default=6)
    args = ap.parse_args(argv)

    try:
        return run(
            target_pid=args.target_pid,
            run_id=args.run_id,
            interval=args.interval,
            hot_interval=args.hot_interval,
            max_seconds=args.max_seconds,
            gone_samples_before_exit=args.gone_samples_before_exit,
        )
    except KeyboardInterrupt:
        telemetry.record("sampler_stopped", run_id=args.run_id, reason="interrupted")
        return 0


if __name__ == "__main__":
    sys.exit(main())
