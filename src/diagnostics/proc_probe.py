"""Single owner for reading process/system/cgroup state from ``/proc``.

WHY THIS MODULE EXISTS
----------------------
``server.py`` already hand-rolled a ``/proc`` walk to find and reap
orphaned Playwright Chromium processes (there is no ``psutil`` in
``requirements.txt``, deliberately — see ``docs/ops``). The resource
sampler needs the *same* discovery logic to attribute RSS/CPU to
Chromium versus the app, but it **cannot import ``server.py``**: it runs
as a detached process whose whole purpose is to outlive a killed server,
and importing the server would drag in FastAPI, the scraper bridge and
import-time side effects.

Rather than keep a second copy of the walk, the primitives live here and
``server.py`` imports them back as an adapter — the same arrangement
``src/identity/name_primitives.py`` already has with ``Dynasty Scraper.py``.

EVERY function here is best-effort and returns ``None``/empty on failure.
None of them raise. They are read by monitoring code on a box that may
already be under memory pressure, and a diagnostic probe that can break
its caller is worse than no probe at all.
"""

from __future__ import annotations

import os
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")


def _read_text(path: str | Path) -> str | None:
    try:
        with open(path, "rb") as fh:
            return fh.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None


def clock_ticks_per_second() -> int:
    """``SC_CLK_TCK`` — the unit of /proc CPU-time fields."""
    try:
        return int(os.sysconf("SC_CLK_TCK")) or 100
    except (ValueError, OSError, AttributeError):
        return 100


def looks_like_playwright_chromium(cmdline: str) -> bool:
    """True for a Playwright-spawned headless Chromium command line.

    Deliberately conservative: requires BOTH a chromium binary token
    AND an automation/headless marker, so it can't match an unrelated
    process even before the descendant-scoping guard.
    """
    c = cmdline.lower()
    if "chrome" not in c and "chromium" not in c:
        return False
    return (
        "--headless" in c
        or "--remote-debugging-" in c
        or "--remote-debugging-pipe" in c
        or "/ms-playwright/" in c
        or "playwright" in c
    )


def collect_descendant_pids(root_pid: int) -> set[int]:
    """All transitive child PIDs of ``root_pid`` via /proc (Linux only).

    Uses the ppid field of /proc/<pid>/stat (field after the comm
    parenthesis) — no kernel CONFIG_PROC_CHILDREN dependency.
    """
    # PID 0 is the kernel scheduler, not a process: every kernel thread
    # AND init report ppid 0, so walking "descendants of 0" returns the
    # entire process table.  That matters beyond wrong numbers — this
    # walker also scopes _reap_orphan_browsers' SIGKILL sweep, and a
    # whole-system scope there would let it reach processes it has no
    # business touching.  Negative pids are likewise never a tree root.
    if root_pid <= 0:
        return set()
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return set()
    for entry in entries:
        if not entry.isdigit():
            continue
        data = _read_text(f"/proc/{entry}/stat")
        if data is None:
            continue
        rparen = data.rfind(")")
        if rparen == -1:
            continue
        fields = data[rparen + 2 :].split()
        try:
            ppid = int(fields[1])  # fields[0]=state, fields[1]=ppid
        except (IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    out: set[int] = set()
    stack = [root_pid]
    while stack:
        p = stack.pop()
        for child in children.get(p, ()):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def read_cmdline(pid: int) -> str:
    raw = _read_text(f"/proc/{pid}/cmdline")
    if not raw:
        return ""
    return raw.replace("\x00", " ").strip()


def pid_alive(pid: int) -> bool:
    return os.path.isdir(f"/proc/{pid}")


def process_rss_kb(pid: int) -> int | None:
    """Resident set size in kB from /proc/<pid>/status (already kB)."""
    text = _read_text(f"/proc/{pid}/status")
    if not text:
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    return None
    return None


def process_cpu_ticks(pid: int) -> int | None:
    """utime+stime in clock ticks from /proc/<pid>/stat."""
    data = _read_text(f"/proc/{pid}/stat")
    if not data:
        return None
    rparen = data.rfind(")")
    if rparen == -1:
        return None
    fields = data[rparen + 2 :].split()
    # After comm: [0]=state [1]=ppid ... [11]=utime [12]=stime
    try:
        return int(fields[11]) + int(fields[12])
    except (IndexError, ValueError):
        return None


def read_meminfo() -> dict[str, int]:
    """Selected /proc/meminfo keys, in kB."""
    text = _read_text("/proc/meminfo")
    if not text:
        return {}
    wanted = {
        "MemTotal",
        "MemFree",
        "MemAvailable",
        "SwapTotal",
        "SwapFree",
        "Cached",
        "Buffers",
        "Dirty",
    }
    out: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key not in wanted:
            continue
        parts = rest.split()
        if parts:
            try:
                out[key] = int(parts[0])
            except ValueError:
                continue
    return out


def read_loadavg() -> dict[str, float | int | str]:
    text = _read_text("/proc/loadavg")
    if not text:
        return {}
    parts = text.split()
    if len(parts) < 4:
        return {}
    try:
        return {
            "load1": float(parts[0]),
            "load5": float(parts[1]),
            "load15": float(parts[2]),
            "runnable": parts[3],
        }
    except ValueError:
        return {}


def read_total_cpu_ticks() -> dict[str, int] | None:
    """Aggregate CPU jiffies from the ``cpu`` line of /proc/stat.

    Returns ``total`` and ``idle`` so a caller can compute utilization
    across two samples (a single sample cannot express a rate).
    """
    text = _read_text("/proc/stat")
    if not text:
        return None
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()[1:]
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return None
        if len(nums) < 5:
            return None
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0)  # idle + iowait
        return {"total": sum(nums), "idle": idle}
    return None


def read_pressure(kind: str) -> dict[str, float] | None:
    """PSI for ``memory`` / ``cpu`` / ``io`` from /proc/pressure/<kind>.

    Absent on kernels built without CONFIG_PSI, hence the ``None``.
    """
    text = _read_text(f"/proc/pressure/{kind}")
    if not text:
        return None
    out: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        scope = parts[0]  # "some" / "full"
        for token in parts[1:]:
            key, _, value = token.partition("=")
            try:
                out[f"{scope}_{key}"] = float(value)
            except ValueError:
                continue
    return out or None


def resolve_cgroup_dir(pid: int) -> Path | None:
    """The cgroup-v2 directory for ``pid`` under /sys/fs/cgroup."""
    text = _read_text(f"/proc/{pid}/cgroup")
    if not text:
        return None
    for line in text.splitlines():
        # cgroup v2 unified: "0::/system.slice/dynasty.service"
        if line.startswith("0::"):
            rel = line[3:].strip().lstrip("/")
            candidate = CGROUP_ROOT / rel if rel else CGROUP_ROOT
            return candidate if candidate.is_dir() else None
    return None


def _parse_keyed_file(path: Path) -> dict[str, int]:
    text = _read_text(path)
    if not text:
        return {}
    out: dict[str, int] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                out[parts[0]] = int(parts[1])
            except ValueError:
                continue
    return out


def read_cgroup_metrics(cgroup_dir: Path | None) -> dict[str, object]:
    """memory.current/max/peak/events + pressure + cpu.stat for a cgroup.

    ``memory.events``' ``oom`` and ``oom_kill`` counters are the decisive
    fields: they state outright whether this cgroup hit its limit and
    whether the kernel killed something in it. Everything else in a
    resource investigation is inference; these two are testimony.
    """
    if cgroup_dir is None:
        return {}
    out: dict[str, object] = {"cgroup": str(cgroup_dir)}

    for name in ("memory.current", "memory.peak", "memory.swap.current"):
        raw = _read_text(cgroup_dir / name)
        if raw is not None:
            try:
                out[name] = int(raw.strip())
            except ValueError:
                pass

    raw_max = _read_text(cgroup_dir / "memory.max")
    if raw_max is not None:
        value = raw_max.strip()
        # "max" means no limit — keep it distinguishable from a number.
        out["memory.max"] = value if value == "max" else _safe_int(value)

    events = _parse_keyed_file(cgroup_dir / "memory.events")
    if events:
        out["memory.events"] = events

    cpu_stat = _parse_keyed_file(cgroup_dir / "cpu.stat")
    if cpu_stat:
        # Only the throttling-relevant subset; cpu.stat is long.
        out["cpu.stat"] = {
            k: v
            for k, v in cpu_stat.items()
            if k in {"usage_usec", "nr_throttled", "throttled_usec", "nr_periods"}
        }

    mem_pressure = _read_text(cgroup_dir / "memory.pressure")
    if mem_pressure:
        out["memory.pressure"] = mem_pressure.strip().replace("\n", " | ")

    return out


def _safe_int(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


def sample_process_tree(root_pid: int) -> dict[str, object]:
    """RSS/CPU for ``root_pid``'s tree, split into Chromium vs the rest.

    The scraper runs IN-PROCESS in the server (importlib), so Chromium is
    genuinely a descendant of the server PID and this split is meaningful:
    it answers "is the browser eating the memory, or is the app?" — which
    no aggregate number can.
    """
    alive = pid_alive(root_pid)
    out: dict[str, object] = {
        "pid": root_pid,
        "pid_alive": alive,
        "app_rss_kb": 0,
        "app_cpu_ticks": 0,
        "app_proc_count": 0,
        "chromium_rss_kb": 0,
        "chromium_proc_count": 0,
        "chromium_cpu_ticks": 0,
    }
    # A dead target owns nothing.  Returning zeros keeps "the process is
    # gone" readable as exactly that, instead of silently reporting some
    # other tree's usage under a dead PID's name.
    if not alive:
        return out
    pids = {root_pid} | collect_descendant_pids(root_pid)
    for pid in pids:
        rss = process_rss_kb(pid)
        ticks = process_cpu_ticks(pid)
        if rss is None and ticks is None:
            continue  # process vanished between listing and reading
        is_chromium = looks_like_playwright_chromium(read_cmdline(pid))
        prefix = "chromium" if is_chromium else "app"
        out[f"{prefix}_rss_kb"] = int(out[f"{prefix}_rss_kb"]) + (rss or 0)
        out[f"{prefix}_cpu_ticks"] = int(out[f"{prefix}_cpu_ticks"]) + (ticks or 0)
        out[f"{prefix}_proc_count"] = int(out[f"{prefix}_proc_count"]) + 1
    return out
