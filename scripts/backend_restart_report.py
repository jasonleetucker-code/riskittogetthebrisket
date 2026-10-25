#!/usr/bin/env python3
"""Classify every backend stop in a ``prod_restart_diagnostics`` run.

OFFLINE and READ-ONLY.  It reads text that already exists -- the stdout of
``deploy/diagnostics/prod_restart_diagnostics.sh`` (or the log of the
``Production Restart Diagnostics (read-only)`` workflow, which wraps it) --
and prints which restarts were clean stops, which were watchdog restarts,
which systemd initiated itself (OOM kill, crash, auto-restart), and, where the
watchdog snapshotted cgroup counters, whether they say MEMORY.HIGH
THROTTLING, an OOM kill, or neither.

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
* ``memory_high_not_configured`` / ``near_memory_max_no_high`` -- the cgroup
  reads ``memory.high = max`` (MemoryHigh removed): no throttle verdict is
  possible; the second form means ``memory.current`` was >= 95% of
  ``memory.max``.
* ``memory_high_throttle_confirmed`` -- two or more snapshots, the cgroup is
  at ``memory.high`` (>= 95%), ``memory.events high`` is RISING between the
  first and last snapshot, and ``memory.events max`` is zero.
* ``memory_high_throttle_likely``    -- one snapshot with the same shape.
* ``at_memory_high_throttle_unproven`` -- at ``memory.high`` but the throttle
  counter is zero or unreadable.
* ``below_memory_high``         -- counters readable, cgroup NOT near
  ``memory.high``; look elsewhere.
* ``no_cgroup_counters``        -- no snapshot at all; the report then only
  says whether the systemd peak sits at or above ``--high-bytes``.

``--high-bytes`` (the configured MemoryHigh) only fills in an UNREADABLE
``memory.high``; a reading of ``max`` is never back-filled.  Once MemoryHigh is
removed (``infinity``), omit ``--high-bytes``: there is no limit left to
compare against, and the report says so if it is passed anyway.

WHAT THE RULE DOES NOT PROVE
----------------------------
A rising ``high`` counter proves the cgroup was being throttled while the
service stopped answering.  It does not prove throttling was the only reason
the event loop was silent: no stack dump exists (``py-spy`` is not installed
on the host).  Every verdict therefore carries that caveat.

MASKED INPUT FAILS CLOSED
-------------------------
GitHub replaces every occurrence of a secret value in a workflow log with
``***``, including inside journal TIMESTAMPS (any hour, minute, second, day
or fraction that happens to contain the value).  The parser therefore:

* reads a line whose timestamp is masked ONLY in the fractional seconds at
  one-second precision (counted as ``reduced_precision_lines``);
* counts every other masked-timestamp line it would have acted on (backend
  lifecycle, watchdog verdicts and snapshots, OOM lines) as
  ``unparseable_relevant_lines``.  Any such line makes the input
  ``incomplete``: the report says so and the exit code is 3.  It is never a
  pass.  Masked lines about OTHER units are counted separately and do not
  block (``unparseable_other_lines``).

Masked numeric VALUES (``max=3***1***5472``) and the watchdog's ``na`` /
``max`` parse to ``None`` -- never to zero.  A masked unit name appears as
``***.service``; the backend unit is found from its unmasked description, so
pass ``--unit`` only with the name exactly as it appears in the input.  The
clean way to avoid masking is to classify the script's stdout on the runner
before it is logged (proposed: ``docs/ops/patches/
prod-restart-diagnostics-classify.PROPOSED.patch``).

A record is closed by ``Consumed``, ``Stopped``, ``Deactivated successfully``
or the next ``Started``, and a new ``Stopping`` always starts a new record, so
one missing line cannot merge two restarts.

CANARY TRIGGERS (``trigger_breaches``)
--------------------------------------
Every watchdog snapshot -- including those of liveness failures that
recovered without a restart -- is checked against the Stage 1 rollback
triggers in ``docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md`` and every breach is
listed.  The watchdog snapshots ONLY on a liveness failure, so a healthy
period produces no samples: absence of breaches is not evidence of health.

Usage:
    python scripts/backend_restart_report.py LOGFILE|-  [--format json|text]
            [--high-bytes N] [--service-description REGEX] [--unit NAME]
Exit codes: 0 complete report; 2 no input / unreadable; 3 report printed but
the input is INCOMPLETE (masked or unparseable relevant lines).
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
import sys

# A journal line as ``journalctl -o short-iso(-precise)`` prints it.  The
# timestamp carries a numeric offset, which the GitHub log's own ``...Z``
# prefix does not, so the first match is always the journal's.  Digits may be
# masked (``***``); ``_parse_ts`` decides what is still usable.
_LINE = re.compile(
    r"(?P<ts>\d{4}-[0-9*]+-[0-9*]+T[0-9*]+:[0-9*]+:[0-9*]+(?:\.[0-9*]+)?[+-]\d{2}:?\d{2})"
    r" (?P<host>\S+) (?P<msg>.*)$"
)
_TS = re.compile(
    r"(?P<main>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(?P<frac>[0-9*]+))?(?P<tz>[+-]\d{2}:?\d{2})"
)

_STOPPING = re.compile(r"Stopping (?P<unit>\S+\.service) - (?P<desc>.*?)\.\.\.$")
_STARTED = re.compile(r"Started (?P<unit>\S+\.service) - (?P<desc>.*?)\.?$")
_STOPPED = re.compile(r"Stopped (?P<unit>\S+\.service) - ")
_DEACTIVATED = re.compile(r"(?P<unit>\S+\.service): Deactivated successfully")
_SIGTERM_TIMEOUT = re.compile(r"(?P<unit>\S+\.service): State 'stop-sigterm' timed out")
# systemd-initiated stops: nothing asked for these, so there is no "Stopping".
_MAIN_EXITED = re.compile(
    r"(?P<unit>\S+\.service): Main process exited, code=(?P<code>\w+), status=(?P<status>\S+)"
)
_FAILED_RESULT = re.compile(r"(?P<unit>\S+\.service): Failed with result '(?P<result>[a-z-]+)'")
_OOM_UNIT = re.compile(
    r"(?P<unit>\S+\.service): A process of this unit has been killed by the OOM killer"
)
_SCHEDULED_RESTART = re.compile(r"(?P<unit>\S+\.service): Scheduled restart job")
_KERNEL_OOM = re.compile(
    r"kernel: .*(?:Memory cgroup out of memory|oom-kill:|Out of memory:)|systemd-oomd\[\d+\]: Killed"
)
_CONSUMED = re.compile(
    r"(?P<unit>\S+\.service): Consumed (?P<cpu>.+?) CPU time,\s*(?P<peak>[\d.]+[KMGT]?) memory peak"
)
_WATCHDOG_THRESHOLD = re.compile(r"\[healthcheck\] threshold reached")
_LIVENESS_FAIL = re.compile(r"\[healthcheck\] LIVENESS FAIL \d+/\d+")
_RECOVERED = re.compile(r"\[healthcheck\] recovered:")
_SNAPSHOT = re.compile(
    r"\[healthcheck\] snapshot (?P<kind>[a-z_]+) reason=(?P<reason>\S+)(?P<rest>.*)$"
)
_KV = re.compile(r"(?P<k>[a-z0-9_]+)=(?P<v>\S+)")

#: unit-scoped lines: relevant when the unit is the backend (and, for the
#: two OOM forms, for any unit -- other units' OOM kills are summarized).
_UNIT_LINES = {
    "stopping": _STOPPING,
    "started": _STARTED,
    "stopped": _STOPPED,
    "deactivated": _DEACTIVATED,
    "sigterm_timeout": _SIGTERM_TIMEOUT,
    "main_exited": _MAIN_EXITED,
    "failed_result": _FAILED_RESULT,
    "oom_unit": _OOM_UNIT,
    "scheduled_restart": _SCHEDULED_RESTART,
    "consumed": _CONSUMED,
}
_GLOBAL_LINES = {
    "kernel_oom": _KERNEL_OOM,
    "watchdog_threshold": _WATCHDOG_THRESHOLD,
    "liveness_fail": _LIVENESS_FAIL,
    "recovered": _RECOVERED,
    "watchdog_snapshot": _SNAPSHOT,
}

#: Results systemd reports for a process that died on its own.
_CRASH_RESULTS = frozenset({"signal", "exit-code", "core-dump", "watchdog"})

_UNIT_FACTOR = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

#: systemd prints peaks with one decimal ("2.5G"), so a printed value can sit
#: up to 0.05 of its unit below or above the true figure.
_SYSTEMD_ROUNDING = 0.05

#: A cgroup is "at" memory.high from this fraction of it.
AT_HIGH_FRACTION = 0.95

#: Stage 1 rollback triggers (docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md §5.2)
#: that a watchdog snapshot can show.
CANARY_TRIGGERS = {
    "host_mem_available_kb_below": 1.5 * 1024 * 1024,  # 1.5 GiB in kB
    "host_mem_stall_full_avg10_above": 10.0,
    "cgroup_current_bytes_at_or_above": 3.4 * 1024**3,
}

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


def _parse_ts(ts: str) -> tuple[str | None, bool]:
    """(usable timestamp or None, reduced_precision).

    Masking confined to the fractional seconds costs sub-second precision
    only, so the fraction is dropped.  Masking anywhere else makes the
    timestamp unusable: guessing the masked digits would mean encoding the
    secret, and skipping silently is how two restarts used to merge.
    """
    m = _TS.fullmatch(ts)
    if not m:
        return None, False
    if m["frac"] and "*" in m["frac"]:
        return m["main"] + m["tz"], True
    return ts, False


def _seconds(ts: str) -> float:
    """Seconds since epoch for a journal timestamp (offset-aware)."""
    fixed = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", ts)
    return datetime.fromisoformat(fixed).timestamp()


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
    host_mem_stall_full_avg10: float | None = None
    #: the watchdog logs the literal "max" for an unlimited knob -- after
    #: MemoryHigh is removed, memory.high reads "max".  Distinct from "na".
    high_unlimited: bool = False
    max_unlimited: bool = False


@dataclass
class StopRecord:
    ts: str
    unit: str
    description: str
    #: True when something asked for the stop ("Stopping ..." from a deploy, an
    #: operator or the watchdog); False when systemd observed the process die.
    requested: bool = True
    result: str | None = None
    exit_code: str | None = None
    exit_status: str | None = None
    oom_killed: bool = False
    auto_restart: bool = False
    sigterm_timed_out: bool = False
    closed_ts: str | None = None
    cpu: str | None = None
    peak_text: str | None = None
    peak_bytes: float | None = None
    peak_rounding_bytes: float | None = None
    kind: str = "clean_stop"
    watchdog_fails: int = 0
    snapshots: list[Snapshot] = field(default_factory=list)
    verdict: dict | None = None


def _fill(snap: Snapshot, kind: str, rest: str) -> None:
    raw = {m["k"]: m["v"] for m in _KV.finditer(rest)}
    kv = {k: _num(v) for k, v in raw.items()}
    if kind == "mem":
        snap.cur, snap.peak = kv.get("cur"), kv.get("peak")
        snap.high, snap.max = kv.get("high"), kv.get("max")
        snap.high_unlimited = raw.get("high") == "max"
        snap.max_unlimited = raw.get("max") == "max"
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
        snap.host_mem_stall_full_avg10 = kv.get("h_full_avg10")


def classify_snapshots(snaps: list[Snapshot], high_bytes: float | None = None) -> dict:
    """Apply the rule in the module docstring to the snapshots of ONE stall."""
    base = {"snapshots": len(snaps), "caveat": CAVEAT}
    if not snaps:
        return {**base, "verdict": "no_cgroup_counters"}
    first, last = snaps[0], snaps[-1]
    # The cgroup's own reading wins.  ``high_bytes`` (the configured value,
    # from --high-bytes) only fills in an UNREADABLE reading; a reading of
    # "max" means no MemoryHigh is in force and must never be back-filled.
    high = None if last.high_unlimited else (last.high if last.high is not None else high_bytes)
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
        "memory_high_unlimited": last.high_unlimited,
        "max_bytes": last.max,
        "cur_over_max": (
            round(last.cur / last.max, 4) if last.max and last.cur is not None else None
        ),
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
        "host_mem_stall_full_avg10_last": last.host_mem_stall_full_avg10,
    }
    if killed:
        verdict = "oom_kill"
    elif max_reached:
        # memory.max was hit but nothing was killed: a different failure from
        # high-throttling, so it must not fall through to either label below.
        verdict = "memory_max_reached_no_oom_kill"
    elif last.high_unlimited:
        # MemoryHigh removed (the recommended policy): no throttle exists, so
        # no throttle verdict is possible; say how close to the hard line it was.
        near_max = bool(
            last.max and last.cur is not None and last.cur >= AT_HIGH_FRACTION * last.max
        )
        verdict = "near_memory_max_no_high" if near_max else "memory_high_not_configured"
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


def trigger_breaches(snaps: list[Snapshot], triggers: dict | None = None) -> list[dict]:
    """Every snapshot that breaches a Stage 1 rollback trigger, with which ones.

    A trigger whose input is unreadable (masked, ``na``) is listed under
    ``unknown`` rather than treated as not breached.
    """
    t = {**CANARY_TRIGGERS, **(triggers or {})}
    out = []
    for s in snaps:
        hit = []
        unknown = [
            name
            for name, value in (
                ("host_mem_available_kb", s.host_mem_available_kb),
                ("host_mem_stall_full_avg10", s.host_mem_stall_full_avg10),
                ("cgroup_current_bytes", s.cur),
                ("ev_oom_kill", s.ev_oom_kill),
            )
            if value is None
        ]
        if (
            s.host_mem_available_kb is not None
            and s.host_mem_available_kb < t["host_mem_available_kb_below"]
        ):
            hit.append("host_mem_available_below_1.5GiB")
        if (
            s.host_mem_stall_full_avg10 is not None
            and s.host_mem_stall_full_avg10 > t["host_mem_stall_full_avg10_above"]
        ):
            # the snapshot cannot say whether a scrape was running
            hit.append("host_mem_stall_full_above_10pct(scrape_window_unknown)")
        if s.cur is not None and s.cur >= t["cgroup_current_bytes_at_or_above"]:
            hit.append("backend_cgroup_at_or_above_3.4GiB")
        if (s.ev_oom_kill or 0) > 0:
            hit.append("backend_cgroup_oom_kill")
        if hit or unknown:
            out.append({"ts": s.ts, "reason": s.reason, "breaches": hit, "unknown": unknown})
    return out


def _journal(text: str):
    """(usable ts or None, msg, reduced_precision) for every journal-shaped line."""
    for raw in text.splitlines():
        m = _LINE.search(raw)
        if m:
            ts, reduced = _parse_ts(m["ts"])
            yield ts, m["msg"], reduced


def backend_units(
    text: str, service_description: str = r"Dynasty Trade Calculator \(", extra=()
) -> set[str]:
    """Units whose Stopping/Started line carries the backend's description.

    Needed BEFORE the stop lines are read: a systemd-initiated stop is logged
    as ``<unit>: Main process exited`` / ``Failed with result`` with no
    description, and only the later ``Started <unit> - <description>`` line
    says which unit is the backend.  Timestamps are not needed for this, so a
    masked-timestamp line still identifies the unit.
    """
    desc_re = re.compile(service_description)
    units = set(extra)
    for _ts, msg, _reduced in _journal(text):
        s = _STOPPING.search(msg) or _STARTED.search(msg)
        if s and desc_re.search(s["desc"]):
            units.add(s["unit"])
    return units


def _line_kind(msg: str, backend: set[str]) -> tuple[str | None, bool]:
    """(kind, relevant) for a journal message the parser would act on."""
    for name, rx in _UNIT_LINES.items():
        s = rx.search(msg)
        if s:
            relevant = (
                s["unit"] in backend
                or name == "oom_unit"
                or (name == "failed_result" and s["result"] == "oom-kill")
            )
            return name, relevant
    for name, rx in _GLOBAL_LINES.items():
        if rx.search(msg):
            return name, True
    return None, False


def _classify_unrequested(rec: StopRecord, kernel_oom_near: bool) -> str:
    if rec.oom_killed or rec.result == "oom-kill" or kernel_oom_near:
        return "oom_kill"
    if rec.result in _CRASH_RESULTS or rec.exit_code is not None:
        return "crash"
    return "auto_restart"


def parse_log(
    text: str,
    service_description: str = r"Dynasty Trade Calculator \(",
    high_bytes: float | None = None,
    units: tuple[str, ...] = (),
) -> dict:
    """Parse diagnostics output into stop records and input-quality counters.

    A stop is either REQUESTED (``Stopping <unit>``: a deploy, an operator or
    the watchdog) or SYSTEMD-INITIATED (the process died; systemd logs
    ``Main process exited`` / ``A process of this unit has been killed by the
    OOM killer`` / ``Failed with result '...'`` and, with ``Restart=always``,
    ``Scheduled restart job``).  Both kinds become records; the second is
    classified ``oom_kill``, ``crash`` or ``auto_restart``.
    """
    backend = backend_units(text, service_description, units)
    stops: list[StopRecord] = []
    open_stop: dict[str, StopRecord] = {}
    last_rec: dict[str, StopRecord] = {}
    all_snaps: list[Snapshot] = []
    threshold_ts: list[str] = []
    kernel_oom_ts: list[str] = []
    quality: Counter[str] = Counter()
    unparseable_kinds: Counter[str] = Counter()
    liveness = Counter()
    other_unit_ooms: Counter[str] = Counter()

    def _close(unit: str, ts: str) -> None:
        rec = open_stop.pop(unit, None)
        if rec is not None:
            rec.closed_ts = ts

    def _start(unit: str, ts: str, requested: bool, desc: str = "") -> StopRecord:
        _close(unit, ts)
        rec = StopRecord(ts=ts, unit=unit, description=desc, requested=requested)
        stops.append(rec)
        open_stop[unit] = rec
        last_rec[unit] = rec
        return rec

    def _unrequested(unit: str, ts: str) -> StopRecord:
        # systemd's lines for one death arrive within seconds; an open record
        # older than that belongs to something else.
        rec = open_stop.get(unit)
        if rec is not None and _seconds(ts) - _seconds(rec.ts) <= 120:
            return rec
        return _start(unit, ts, False)

    for ts, msg, reduced in _journal(text):
        if ts is None:
            kind, relevant = _line_kind(msg, backend)
            if relevant:
                quality["unparseable_relevant_lines"] += 1
                unparseable_kinds[kind] += 1
            else:
                quality["unparseable_other_lines"] += 1
            continue
        if reduced:
            quality["reduced_precision_lines"] += 1

        s = _OOM_UNIT.search(msg)
        if s and s["unit"] not in backend:
            other_unit_ooms[s["unit"]] += 1
            continue
        s = _FAILED_RESULT.search(msg)
        if s and s["unit"] not in backend and s["result"] == "oom-kill":
            other_unit_ooms[s["unit"]] += 1
            continue

        s = _STOPPING.search(msg)
        if s and s["unit"] in backend:
            _start(s["unit"], ts, True, s["desc"])
            continue
        s = _STOPPED.search(msg) or _DEACTIVATED.search(msg) or _STARTED.search(msg)
        if s and s["unit"] in backend:
            _close(s["unit"], ts)
            continue
        s = _SIGTERM_TIMEOUT.search(msg)
        if s and s["unit"] in open_stop:
            open_stop[s["unit"]].sigterm_timed_out = True
            continue
        s = _OOM_UNIT.search(msg)
        if s and s["unit"] in backend:
            _unrequested(s["unit"], ts).oom_killed = True
            continue
        s = _MAIN_EXITED.search(msg)
        if s and s["unit"] in backend:
            rec = open_stop.get(s["unit"]) or _unrequested(s["unit"], ts)
            rec.exit_code, rec.exit_status = s["code"], s["status"]
            continue
        s = _FAILED_RESULT.search(msg)
        if s and s["unit"] in backend:
            rec = open_stop.get(s["unit"]) or _unrequested(s["unit"], ts)
            rec.result = s["result"]
            continue
        s = _SCHEDULED_RESTART.search(msg)
        if s and s["unit"] in backend:
            prev = last_rec.get(s["unit"])
            # "Scheduled restart job" follows the failed stop's Consumed line
            # by RestartSec (5 s); it belongs to that stop, not a new one.
            if prev is not None and not prev.requested and _seconds(ts) - _seconds(prev.ts) <= 120:
                prev.auto_restart = True
            else:
                _start(s["unit"], ts, False).auto_restart = True
                _close(s["unit"], ts)
            continue
        s = _CONSUMED.search(msg)
        if s and s["unit"] in backend:
            # Consumed follows "Stopped" by microseconds, so it attaches to the
            # unit's last record when that one was closed within a minute.
            rec = open_stop.pop(s["unit"], None)
            if rec is None:
                cand = last_rec.get(s["unit"])
                if (
                    cand is not None
                    and cand.peak_text is None
                    and _seconds(ts) - _seconds(cand.closed_ts or cand.ts) <= 60
                ):
                    rec = cand
            if rec is not None:
                rec.closed_ts = rec.closed_ts or ts
                rec.cpu, rec.peak_text = s["cpu"], s["peak"]
                parsed = parse_systemd_size(s["peak"])
                if parsed:
                    rec.peak_bytes, rec.peak_rounding_bytes = parsed
            continue
        if _KERNEL_OOM.search(msg):
            kernel_oom_ts.append(ts)
            continue
        if _WATCHDOG_THRESHOLD.search(msg):
            threshold_ts.append(ts)
            continue
        if _LIVENESS_FAIL.search(msg):
            liveness["liveness_fail_lines"] += 1
            continue
        if _RECOVERED.search(msg):
            liveness["recoveries"] += 1
            continue
        s = _SNAPSHOT.search(msg)
        if s:
            kind, reason, rest = s["kind"], s["reason"], s["rest"]
            if kind == "mem":
                all_snaps.append(Snapshot(ts=ts, reason=reason))
            if all_snaps and all_snaps[-1].reason == reason:
                _fill(all_snaps[-1], kind, rest)

    for rec in stops:
        t = _seconds(rec.ts)
        # The watchdog logs "threshold reached" and its pre-restart snapshot
        # in the seconds before systemd prints "Stopping"; a snapshot that
        # belongs to the NEW process is logged after the stop and is excluded.
        near = [x for x in threshold_ts if 0 <= t - _seconds(x) <= 120]
        if rec.requested:
            if rec.sigterm_timed_out or near:
                rec.kind = "watchdog_restart" if near else "killed_after_sigterm_timeout"
        else:
            oom_near = any(0 <= t - _seconds(x) <= 30 for x in kernel_oom_ts)
            rec.kind = _classify_unrequested(rec, oom_near)
        if rec.kind == "clean_stop":
            continue
        window_start = (_seconds(near[0]) if near else t) - 600
        rec.snapshots = [
            s
            for s in all_snaps
            if window_start <= _seconds(s.ts) <= t + 5
            and (s.reason.startswith("liveness-fail") or s.reason == "pre-restart")
        ]
        rec.watchdog_fails = sum(1 for s in rec.snapshots if s.reason.startswith("liveness-fail"))
        if near or rec.snapshots:
            rec.verdict = classify_snapshots(rec.snapshots, high_bytes)
    return {
        "stops": stops,
        "snapshots": all_snaps,
        "snapshots_total": len(all_snaps),
        "unparseable_relevant_lines": quality["unparseable_relevant_lines"],
        "unparseable_relevant_kinds": dict(sorted(unparseable_kinds.items())),
        "unparseable_other_lines": quality["unparseable_other_lines"],
        "reduced_precision_lines": quality["reduced_precision_lines"],
        "liveness_fail_lines": liveness["liveness_fail_lines"],
        "recoveries": liveness["recoveries"],
        "kernel_oom_lines": len(kernel_oom_ts),
        "other_unit_oom_kills": dict(sorted(other_unit_ooms.items())),
    }


def summarize(parsed: dict, high_bytes: float | None = None) -> dict:
    stops: list[StopRecord] = parsed["stops"]
    notes = []
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
    snaps = parsed.get("snapshots", [])
    if high_bytes and any(s.high_unlimited for s in snaps):
        notes.append(
            "--high-bytes ignored where memory.high reads max: MemoryHigh is not in force, so "
            "there is no limit to compare against"
        )
    peaks = [r.peak_bytes for r in stops if r.peak_bytes is not None and r.kind == "clean_stop"]
    all_peaks = [r.peak_bytes for r in stops if r.peak_bytes is not None]
    span_h = None
    if len(stops) >= 2:
        span_h = round((_seconds(stops[-1].ts) - _seconds(stops[0].ts)) / 3600, 2)
    complete = parsed.get("unparseable_relevant_lines", 0) == 0
    if not complete:
        notes.append(
            "INPUT INCOMPLETE: relevant journal lines have masked/unparseable timestamps "
            f"{parsed.get('unparseable_relevant_kinds')}; this report is not a pass. Classify the "
            "unmasked script stdout instead (docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md §2)."
        )
    breaches = trigger_breaches(snaps)
    return {
        "input": "complete" if complete else "incomplete",
        "unparseable_relevant_lines": parsed.get("unparseable_relevant_lines", 0),
        "unparseable_other_lines": parsed.get("unparseable_other_lines", 0),
        "reduced_precision_lines": parsed.get("reduced_precision_lines", 0),
        "stops_total": len(stops),
        "clean_stops": sum(1 for r in stops if r.kind == "clean_stop"),
        "watchdog_restarts": sum(1 for r in stops if r.kind == "watchdog_restart"),
        "killed_other": sum(1 for r in stops if r.kind == "killed_after_sigterm_timeout"),
        "oom_kills": sum(1 for r in stops if r.kind == "oom_kill"),
        "crashes": sum(1 for r in stops if r.kind == "crash"),
        "auto_restarts_without_cause": sum(1 for r in stops if r.kind == "auto_restart"),
        "systemd_initiated": sum(1 for r in stops if not r.requested),
        "liveness_fail_lines": parsed.get("liveness_fail_lines", 0),
        "recoveries_without_restart": parsed.get("recoveries", 0),
        "kernel_oom_lines": parsed.get("kernel_oom_lines", 0),
        "other_unit_oom_kills": parsed.get("other_unit_oom_kills", {}),
        "trigger_breaches": [b for b in breaches if b["breaches"]],
        "trigger_unknown_snapshots": [b for b in breaches if b["unknown"] and not b["breaches"]],
        "span_hours_first_to_last_stop": span_h,
        "clean_stop_peak_bytes_max": max(peaks) if peaks else None,
        "clean_stop_peak_bytes_median": sorted(peaks)[len(peaks) // 2] if peaks else None,
        "any_stop_peak_bytes_max": max(all_peaks) if all_peaks else None,
        "snapshots_total": parsed["snapshots_total"],
        "notes": notes,
    }


def render_text(parsed: dict, summary: dict) -> str:
    out = ["backend stop report (offline; read-only)", ""]
    for k, v in summary.items():
        if k == "notes":
            continue
        out.append(f"  {k}: {v}")
    for note in summary["notes"]:
        out.append(f"  NOTE: {note}")
    out.append("")
    for rec in parsed["stops"]:
        peak = f"{rec.peak_text}" if rec.peak_text else "n/a"
        extra = (
            "" if rec.requested else f" result={rec.result} exit={rec.exit_code}/{rec.exit_status}"
        )
        out.append(
            f"{rec.ts}  {rec.kind:<28} peak={peak:<6} sigterm_timeout={rec.sigterm_timed_out}{extra}"
        )
        if rec.verdict:
            ev = rec.verdict.get("evidence") or {}
            out.append(
                f"    verdict: {rec.verdict['verdict']}  (snapshots={rec.verdict['snapshots']})"
            )
            for key in (
                "memory_high_unlimited",
                "cur_over_max",
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
                "host_mem_stall_full_avg10_last",
            ):
                if key in ev:
                    out.append(f"      {key}: {ev[key]}")
            out.append(f"    caveat: {rec.verdict['caveat']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("log", help="diagnostics output / workflow log file, or - for stdin")
    ap.add_argument(
        "--format",
        choices=("json", "text", "summary"),
        default="text",
        help="summary = the summary object only, as JSON (for the diagnostics workflow)",
    )
    ap.add_argument(
        "--high-bytes",
        type=float,
        default=None,
        help="configured MemoryHigh in bytes; omit once MemoryHigh is infinity",
    )
    ap.add_argument("--service-description", default=r"Dynasty Trade Calculator \(")
    ap.add_argument(
        "--unit",
        action="append",
        default=[],
        help="backend unit name EXACTLY as it appears in the input (a GitHub-masked log shows "
        "'***.service'); added to those found by description",
    )
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
    parsed = parse_log(text, args.service_description, args.high_bytes, tuple(args.unit))
    summary = summarize(parsed, args.high_bytes)
    if args.format == "summary":
        print(json.dumps(summary, indent=2))
    elif args.format == "json":
        print(
            json.dumps(
                {
                    "summary": summary,
                    "stops": [asdict(r) for r in parsed["stops"]],
                },
                indent=2,
            )
        )
    else:
        print(render_text(parsed, summary))
    return 0 if summary["input"] == "complete" else 3


if __name__ == "__main__":
    raise SystemExit(main())
