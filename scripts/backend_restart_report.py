#!/usr/bin/env python3
"""Classify every backend stop in a ``prod_restart_diagnostics`` run.

OFFLINE and READ-ONLY.  It reads text that already exists -- the stdout of
``deploy/diagnostics/prod_restart_diagnostics.sh`` (or the log of the
``Production Restart Diagnostics (read-only)`` workflow, which wraps it) --
and prints which restarts were clean stops, which were watchdog restarts, and,
for the watchdog ones, whether the cgroup counters the watchdog snapshotted
before the restart say MEMORY.HIGH THROTTLING, an OOM kill, or neither.

It touches no host, no journal and no network.  Nothing here changes a
limit, a unit or a service.

WHY IT EXISTS
-------------
The 2026-10-19 restart left "memory throttling" at LIKELY because the dead
process's ``memory.events`` vanished with its cgroup.  The watchdog now logs
those counters on every liveness failure (``snapshot mem ...`` lines), and the
2026-10-21 restart is the first one with them.  This module turns "read the
counters and decide" into a rule that is written down and tested, so the next
restart is classified the same way by anyone.

THE RULE (``classify_snapshots``)
---------------------------------
* ``oom_kill``                  -- ``oom_kill`` or ``oom`` counter above zero.
* ``memory_max_reached_no_oom_kill`` -- ``memory.events max`` above zero with
  no kill recorded.
* ``memory_high_throttle_confirmed`` -- two or more snapshots, the cgroup is
  at ``memory.high`` (>= 95%), ``memory.events high`` is RISING between the
  first and last snapshot, and ``memory.events max`` is zero.  Allocations were
  being throttled for the whole stall and the hard limit was never reached.
* ``memory_high_throttle_likely``    -- one snapshot with the same shape; the
  counter cannot be shown rising.
* ``at_memory_high_throttle_unproven`` -- at ``memory.high`` but the throttle
  counter is zero or unreadable.
* ``below_memory_high``         -- counters were readable and the cgroup was
  NOT near ``memory.high``; look elsewhere.
* ``no_cgroup_counters``        -- no snapshot at all (any restart before the
  watchdog logged them); the report then only says whether the systemd peak
  sits at or above the configured high.

WHAT THE RULE DOES NOT PROVE
----------------------------
A rising ``high`` counter proves the cgroup was being throttled while the
service stopped answering.  It does not prove throttling was the only reason
the event loop was silent: no stack dump exists (``py-spy`` is not installed
on the host).  Every verdict therefore carries that caveat.

Values the log masked (GitHub replaces secret substrings with ``***``) and the
watchdog's own ``na`` / ``max`` parse to ``None`` -- never to zero.

Usage:
    python scripts/backend_restart_report.py LOGFILE|-  [--format json|text]
                                                     [--high-bytes N]
                                                     [--service-description REGEX]
Exit codes: 0 report printed; 2 no input / unreadable.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import sys

# A journal line as ``journalctl -o short-iso(-precise)`` prints it: the
# timestamp carries a numeric offset, which the GitHub log's own ``...Z``
# prefix does not, so the first match is always the journal's.
_LINE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:?\d{2}) (?P<host>\S+) (?P<msg>.*)$"
)
_STOPPING = re.compile(r"Stopping (?P<unit>\S+\.service) - (?P<desc>.*?)\.\.\.$")
_SIGTERM_TIMEOUT = re.compile(r"(?P<unit>\S+\.service): State 'stop-sigterm' timed out")
_CONSUMED = re.compile(
    r"(?P<unit>\S+\.service): Consumed (?P<cpu>.+?) CPU time,\s*(?P<peak>[\d.]+[KMGT]?) memory peak"
)
_WATCHDOG_THRESHOLD = re.compile(r"\[healthcheck\] threshold reached")
_SNAPSHOT = re.compile(
    r"\[healthcheck\] snapshot (?P<kind>[a-z_]+) reason=(?P<reason>\S+)(?P<rest>.*)$"
)
_KV = re.compile(r"(?P<k>[a-z0-9_]+)=(?P<v>\S+)")

_UNIT_FACTOR = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

#: systemd prints peaks with one decimal ("2.5G"), so a printed value can sit
#: up to 0.05 of its unit below or above the true figure.
_SYSTEMD_ROUNDING = 0.05

#: A cgroup is "at" memory.high from this fraction of it.
AT_HIGH_FRACTION = 0.95

CAVEAT = (
    "A rising memory.events high counter proves allocations were being throttled while the "
    "service was silent; it does not prove throttling was the only cause (no stack dump is "
    "available)."
)


def _num(token: str | None) -> float | None:
    """A plain non-negative number, else None (``na``, ``max``, masked ``3***1``)."""
    if token is not None and re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token)
    return None


def parse_systemd_size(text: str) -> tuple[float, float] | None:
    """``"2.5G"`` -> (bytes, rounding slack in bytes); None when unparseable."""
    match = re.fullmatch(r"(?P<n>\d+(?:\.\d+)?)(?P<u>[KMGT]?)", text.strip())
    if not match:
        return None
    factor = _UNIT_FACTOR[match["u"]]
    return float(match["n"]) * factor, _SYSTEMD_ROUNDING * factor


@dataclass
class Snapshot:
    ts: str
    reason: str
    cur: float | None = None
    peak: float | None = None
    high: float | None = None
    max: float | None = None
    ev_high: float | None = None
    ev_max: float | None = None
    ev_oom: float | None = None
    ev_oom_kill: float | None = None
    anon: float | None = None
    file: float | None = None
    mem_stall_some_avg10: float | None = None
    mem_stall_full_avg10: float | None = None
    host_mem_available_kb: float | None = None
    host_mem_stall_some_avg10: float | None = None


@dataclass
class StopRecord:
    ts: str
    unit: str
    description: str
    sigterm_timed_out: bool = False
    cpu: str | None = None
    peak_text: str | None = None
    peak_bytes: float | None = None
    peak_rounding_bytes: float | None = None
    kind: str = "clean_stop"
    watchdog_fails: int = 0
    snapshots: list[Snapshot] = field(default_factory=list)
    verdict: dict | None = None


def _fill(snap: Snapshot, kind: str, rest: str) -> None:
    kv = {m["k"]: _num(m["v"]) for m in _KV.finditer(rest)}
    if kind == "mem":
        snap.cur, snap.peak = kv.get("cur"), kv.get("peak")
        snap.high, snap.max = kv.get("high"), kv.get("max")
        snap.ev_high, snap.ev_max = kv.get("ev_high"), kv.get("ev_max")
        snap.ev_oom, snap.ev_oom_kill = kv.get("ev_oom"), kv.get("ev_oom_kill")
    elif kind == "stat":
        snap.anon, snap.file = kv.get("anon"), kv.get("file")
    elif kind == "psi_memory":
        snap.mem_stall_some_avg10 = kv.get("some_avg10")
        snap.mem_stall_full_avg10 = kv.get("full_avg10")
    elif kind == "host":
        snap.host_mem_available_kb = kv.get("mem_available_kb")
        snap.host_mem_stall_some_avg10 = kv.get("h_some_avg10")


def classify_snapshots(snaps: list[Snapshot], high_bytes: float | None = None) -> dict:
    """Apply the rule in the module docstring to the snapshots of ONE stall."""
    base = {"snapshots": len(snaps), "caveat": CAVEAT}
    if not snaps:
        return {**base, "verdict": "no_cgroup_counters"}
    first, last = snaps[0], snaps[-1]
    high = last.high if last.high is not None else high_bytes
    killed = any((s.ev_oom_kill or 0) > 0 or (s.ev_oom or 0) > 0 for s in snaps)
    max_reached = any((s.ev_max or 0) > 0 for s in snaps)
    delta = None
    if len(snaps) >= 2 and first.ev_high is not None and last.ev_high is not None:
        delta = last.ev_high - first.ev_high
    at_high = bool(high and last.cur is not None and last.cur >= AT_HIGH_FRACTION * high)
    stall_full = [s.mem_stall_full_avg10 for s in snaps if s.mem_stall_full_avg10 is not None]
    evidence = {
        "cur_bytes": last.cur,
        "high_bytes": high,
        "cur_over_high": round(last.cur / high, 4) if high and last.cur is not None else None,
        "anon_share_of_cur": (
            round(last.anon / last.cur, 4) if last.anon is not None and last.cur else None
        ),
        "file_bytes": last.file,
        "ev_high_first": first.ev_high,
        "ev_high_last": last.ev_high,
        "ev_high_delta": delta,
        "ev_max": last.ev_max,
        "ev_oom_kill": last.ev_oom_kill,
        "memory_stall_full_avg10_max": max(stall_full) if stall_full else None,
        "host_mem_available_kb_last": last.host_mem_available_kb,
    }
    if killed:
        verdict = "oom_kill"
    elif max_reached:
        # memory.max was hit but nothing was killed: a different failure from
        # high-throttling, so it must not fall through to either label below.
        verdict = "memory_max_reached_no_oom_kill"
    elif at_high and delta is not None and delta > 0:
        verdict = "memory_high_throttle_confirmed"
    elif at_high and (last.ev_high or 0) > 0:
        verdict = "memory_high_throttle_likely"
    elif at_high:
        # At the line, but the throttle counter is zero or unreadable: the
        # cgroup is where throttling would happen, nothing shows that it did.
        verdict = "at_memory_high_throttle_unproven"
    elif high is not None and last.cur is not None:
        verdict = "below_memory_high"
    else:
        verdict = "inconclusive"
    return {**base, "verdict": verdict, "evidence": evidence}


def parse_log(text: str, service_description: str = r"Dynasty Trade Calculator \(") -> dict:
    """Parse diagnostics output into stop records and a summary."""
    desc_re = re.compile(service_description)
    stops: list[StopRecord] = []
    open_stop: dict[str, StopRecord] = {}
    all_snaps: list[Snapshot] = []
    threshold_ts: list[str] = []
    for raw in text.splitlines():
        m = _LINE.search(raw)
        if not m:
            continue
        ts, msg = m["ts"], m["msg"]
        s = _STOPPING.search(msg)
        if s and desc_re.search(s["desc"]):
            rec = StopRecord(ts=ts, unit=s["unit"], description=s["desc"])
            stops.append(rec)
            open_stop[s["unit"]] = rec
            continue
        s = _SIGTERM_TIMEOUT.search(msg)
        if s and s["unit"] in open_stop:
            open_stop[s["unit"]].sigterm_timed_out = True
            continue
        s = _CONSUMED.search(msg)
        if s and s["unit"] in open_stop:
            rec = open_stop.pop(s["unit"])
            rec.cpu, rec.peak_text = s["cpu"], s["peak"]
            parsed = parse_systemd_size(s["peak"])
            if parsed:
                rec.peak_bytes, rec.peak_rounding_bytes = parsed
            continue
        if _WATCHDOG_THRESHOLD.search(msg):
            threshold_ts.append(ts)
            continue
        s = _SNAPSHOT.search(msg)
        if s:
            kind, reason, rest = s["kind"], s["reason"], s["rest"]
            if kind == "mem":
                all_snaps.append(Snapshot(ts=ts, reason=reason))
            if all_snaps and all_snaps[-1].reason == reason:
                _fill(all_snaps[-1], kind, rest)
    for rec in stops:
        # The watchdog logs "threshold reached" and its pre-restart snapshot
        # in the seconds before systemd prints "Stopping"; a snapshot that
        # belongs to the NEW process is logged after the stop and is excluded.
        near = [t for t in threshold_ts if 0 <= _seconds(rec.ts) - _seconds(t) <= 120]
        if rec.sigterm_timed_out or near:
            rec.kind = "watchdog_restart" if near else "killed_after_sigterm_timeout"
        if near:
            window_start = _seconds(near[0]) - 600
            rec.snapshots = [
                s
                for s in all_snaps
                if window_start <= _seconds(s.ts) <= _seconds(rec.ts) + 5
                and (s.reason.startswith("liveness-fail") or s.reason == "pre-restart")
            ]
            rec.watchdog_fails = sum(
                1 for s in rec.snapshots if s.reason.startswith("liveness-fail")
            )
            rec.verdict = classify_snapshots(rec.snapshots)
    return {"stops": stops, "snapshots_total": len(all_snaps)}


def _seconds(ts: str) -> float:
    """Seconds since epoch for a journal timestamp (offset-aware)."""
    from datetime import datetime

    fixed = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts)
    return datetime.fromisoformat(fixed).timestamp()


def summarize(parsed: dict, high_bytes: float | None = None) -> dict:
    stops: list[StopRecord] = parsed["stops"]
    for rec in stops:
        if (
            rec.kind == "watchdog_restart"
            and rec.verdict
            and rec.verdict["verdict"] == "no_cgroup_counters"
        ):
            if high_bytes and rec.peak_bytes is not None:
                rec.verdict["systemd_peak_at_or_above_high"] = (
                    rec.peak_bytes + (rec.peak_rounding_bytes or 0) >= high_bytes
                )
                rec.verdict["note"] = (
                    "no watchdog snapshots; only the systemd peak is comparable, and it is "
                    "rounded to one decimal"
                )
    peaks = [r.peak_bytes for r in stops if r.peak_bytes is not None and r.kind == "clean_stop"]
    span_h = None
    if len(stops) >= 2:
        span_h = round((_seconds(stops[-1].ts) - _seconds(stops[0].ts)) / 3600, 2)
    return {
        "stops_total": len(stops),
        "clean_stops": sum(1 for r in stops if r.kind == "clean_stop"),
        "watchdog_restarts": sum(1 for r in stops if r.kind == "watchdog_restart"),
        "killed_other": sum(1 for r in stops if r.kind == "killed_after_sigterm_timeout"),
        "span_hours_first_to_last_stop": span_h,
        "clean_stop_peak_bytes_max": max(peaks) if peaks else None,
        "clean_stop_peak_bytes_median": sorted(peaks)[len(peaks) // 2] if peaks else None,
        "snapshots_total": parsed["snapshots_total"],
    }


def render_text(parsed: dict, summary: dict) -> str:
    out = ["backend stop report (offline; read-only)", ""]
    for k, v in summary.items():
        out.append(f"  {k}: {v}")
    out.append("")
    for rec in parsed["stops"]:
        peak = f"{rec.peak_text}" if rec.peak_text else "n/a"
        out.append(
            f"{rec.ts}  {rec.kind:<28} peak={peak:<6} sigterm_timeout={rec.sigterm_timed_out}"
        )
        if rec.verdict:
            ev = rec.verdict.get("evidence") or {}
            out.append(
                f"    verdict: {rec.verdict['verdict']}  (snapshots={rec.verdict['snapshots']})"
            )
            for key in (
                "cur_over_high",
                "anon_share_of_cur",
                "file_bytes",
                "ev_high_first",
                "ev_high_last",
                "ev_high_delta",
                "ev_max",
                "ev_oom_kill",
                "memory_stall_full_avg10_max",
                "host_mem_available_kb_last",
            ):
                if key in ev:
                    out.append(f"      {key}: {ev[key]}")
            out.append(f"    caveat: {rec.verdict['caveat']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log", help="diagnostics output / workflow log file, or - for stdin")
    ap.add_argument("--format", choices=("json", "text"), default="text")
    ap.add_argument("--high-bytes", type=float, default=None, help="configured MemoryHigh in bytes")
    ap.add_argument("--service-description", default=r"Dynasty Trade Calculator \(")
    args = ap.parse_args(argv)
    try:
        text = (
            sys.stdin.read()
            if args.log == "-"
            else Path(args.log).read_text(encoding="utf-8", errors="replace")
        )
    except OSError as exc:
        print(f"cannot read {args.log}: {exc}", file=sys.stderr)
        return 2
    parsed = parse_log(text, args.service_description)
    summary = summarize(parsed, args.high_bytes)
    if args.format == "json":
        print(
            json.dumps(
                {"summary": summary, "stops": [asdict(r) for r in parsed["stops"]]}, indent=2
            )
        )
    else:
        print(render_text(parsed, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
