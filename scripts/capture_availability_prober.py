#!/usr/bin/env python3
"""Detached, capture-correlated external availability prober.

This is deliberately a separate process.  It probes the public HTTPS path
users use, never localhost or an in-process handler, and writes every first
result without retrying.  A failure here is diagnostic only: it must never
change, delay, or fail the KTC scrape that launched it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.diagnostics import proc_probe  # noqa: E402
from src.diagnostics import scrape_telemetry as telemetry  # noqa: E402

DEFAULT_INTERVAL_SECONDS = 0.1
DEFAULT_MAX_SECONDS = 3.0
DEFAULT_TIMEOUT_SECONDS = 2.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _failure_kind(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return "timeout"
        return "connection_error"
    return "probe_error"


def probe_once(url: str, timeout: float) -> dict[str, object]:
    """Perform exactly one public-path request; do not retry failures."""
    started_mono = time.monotonic()
    started_at = telemetry.utc_now_iso()
    request = urllib.request.Request(url, headers={"User-Agent": "riskit-capture-prober/1"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(response.getcode())
            return {
                "probe_started_at": started_at,
                "probe_finished_at": telemetry.utc_now_iso(),
                "http_status": status,
                "latency_ms": round((time.monotonic() - started_mono) * 1000, 2),
                "failure_kind": "http_error" if status >= 400 else None,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "probe_started_at": started_at,
            "probe_finished_at": telemetry.utc_now_iso(),
            "http_status": int(exc.code),
            "latency_ms": round((time.monotonic() - started_mono) * 1000, 2),
            "failure_kind": "http_5xx" if int(exc.code) >= 500 else "http_error",
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - the result is evidence, not a crash
        return {
            "probe_started_at": started_at,
            "probe_finished_at": telemetry.utc_now_iso(),
            "http_status": None,
            "latency_ms": round((time.monotonic() - started_mono) * 1000, 2),
            "failure_kind": _failure_kind(exc),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _resource_snapshot(target_pid: int) -> dict[str, object]:
    """Best-effort resource fields tied to the same probe timestamp."""
    try:
        tree = proc_probe.sample_process_tree(target_pid)
        cgroup = proc_probe.resolve_cgroup_dir(\n            target_pid if tree.get("pid_alive") else os.getpid()\n        )
        out: dict[str, object] = {
            "target_pid": target_pid,
            "target_alive": tree.get("pid_alive"),
            "app_rss_kb": tree.get("app_rss_kb"),
            "chromium_rss_kb": tree.get("chromium_rss_kb"),
            "process_count": int(tree.get("app_proc_count") or 0)
            + int(tree.get("chromium_proc_count") or 0),
            "psi_memory": proc_probe.read_pressure("memory"),
        }
        cgroup_metrics = proc_probe.read_cgroup_metrics(cgroup)
        out["cgroup_memory_current"] = cgroup_metrics.get("memory.current")
        out["cgroup_memory_max"] = cgroup_metrics.get("memory.max")
        out["cgroup_memory_events"] = cgroup_metrics.get("memory.events")
        maximum = out["cgroup_memory_max"]
        current = out["cgroup_memory_current"]
        if isinstance(maximum, int) and maximum > 0 and isinstance(current, int):
            out["memory_headroom_bytes"] = maximum - current
            out["memory_headroom_pct"] = round(100 * (maximum - current) / maximum, 2)
        return out
    except Exception as exc:  # noqa: BLE001 - probe evidence must still be written
        return {\n            "target_pid": target_pid,\n            "resource_error": f"{type(exc).__name__}: {exc}",\n        }


def run(
    *,
    capture_id: str,
    target_pid: int,
    probe_url: str,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """Probe until capture completion updates the phase, or the hard bound."""
    started = time.monotonic()
    probe_number = 0
    telemetry.record(
        "capture_probe_started",
        capture_id=capture_id,
        target_pid=target_pid,
        probe_url=probe_url,
        interval_s=interval,
        max_seconds=max_seconds,
        out_of_process=True,
    )
    while time.monotonic() - started < max_seconds:
        phase = telemetry.read_phase()
        if phase.get("phase") != "value_source_capture" or phase.get("capture_id") != capture_id:
            telemetry.record(
                "capture_probe_stopped",
                capture_id=capture_id,
                reason="capture_phase_ended",
                probes=probe_number,
            )
            return 0

        probe_number += 1
        result = probe_once(probe_url, timeout)
        telemetry.record(
            "capture_probe_result",
            capture_id=capture_id,
            probe_number=probe_number,
            probe_url=probe_url,
            out_of_process=True,
            **result,
            **_resource_snapshot(target_pid),
        )
        elapsed = time.monotonic() - started
        if elapsed < max_seconds:
            time.sleep(max(0.0, interval - (time.monotonic() - started - elapsed)))

    telemetry.record(
        "capture_probe_stopped", capture_id=capture_id, reason="max_duration", probes=probe_number
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--target-pid", type=int, required=True)
    parser.add_argument("--probe-url", required=True)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)
    try:
        return run(
            capture_id=args.capture_id,
            target_pid=args.target_pid,
            probe_url=args.probe_url,
            interval=args.interval,
            max_seconds=args.max_seconds,
            timeout=args.timeout,
        )
    except Exception as exc:  # noqa: BLE001 - detached diagnostics must never escape
        telemetry.record(
            "capture_probe_fatal",
            capture_id=args.capture_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
