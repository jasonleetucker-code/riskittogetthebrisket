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
import shutil
import tempfile
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
#: Module constants (not literals at call sites) so tests can point the whole
#: probe at a fake tree and never touch a real process.
PROC_ROOT = "/proc"


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
        entries = os.listdir(PROC_ROOT)
    except OSError:
        return set()
    for entry in entries:
        if not entry.isdigit():
            continue
        data = _read_text(f"{PROC_ROOT}/{entry}/stat")
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
    raw = _read_text(f"{PROC_ROOT}/{pid}/cmdline")
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
    text = _read_text(f"{PROC_ROOT}/{pid}/cgroup")
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


# -- Service-cgroup membership (reparented-orphan detection) ---------------
#
# ``collect_descendant_pids`` follows ppid links, so it loses any process whose
# parent died: the kernel reparents it to init (or a subreaper) and it is no
# longer a descendant of the server -- yet it stays in the service's cgroup,
# still counted against MemoryMax / TasksMax.  Cgroup membership is the
# property reparenting cannot change.


def service_cgroup_dir(pid: int) -> Path | None:
    """The cgroup-v2 dir for ``pid`` ONLY if it is a dedicated systemd service.

    A cgroup that is not a ``*.service`` (the root, a login session scope, a
    container slice) may contain unrelated processes -- e.g. a developer's own
    Playwright run -- so membership there proves nothing about ownership and
    callers get ``None``.
    """
    cg = resolve_cgroup_dir(pid)
    if cg is None or cg == CGROUP_ROOT or not cg.name.endswith(".service"):
        return None
    return cg


def read_cgroup_procs(cgroup_dir: Path | None) -> set[int]:
    """PIDs listed in ``cgroup.procs`` (empty on any failure)."""
    if cgroup_dir is None:
        return set()
    text = _read_text(cgroup_dir / "cgroup.procs")
    if not text:
        return set()
    return {int(tok) for tok in text.split() if tok.isdigit() and int(tok) > 0}


def collect_service_pids(root_pid: int) -> tuple[set[int], set[int]]:
    """``(descendants, cgroup_only)`` of ``root_pid``, ``root_pid`` excluded.

    ``cgroup_only`` are service-cgroup members that are NOT descendants,
    i.e. reparented orphans.  Empty when the cgroup is not a dedicated service.
    """
    descendants = collect_descendant_pids(root_pid)
    members = read_cgroup_procs(service_cgroup_dir(root_pid))
    members.discard(root_pid)
    return descendants, members - descendants


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None  # includes the literal "max" (no limit)


def _free_bytes(path: str) -> int | None:
    try:
        return int(shutil.disk_usage(path).free)
    except (OSError, ValueError):
        return None


def service_diagnostics(
    root_pid: int, *, tmp_dir: str | None = None, shm_dir: str = "/dev/shm"
) -> dict[str, int | None]:
    """Numbers-only box snapshot for the PUBLIC status.  Never raises.

    No paths, hostnames or command lines: every value is an integer or
    ``None`` (unreadable / no limit).  ``cgroup_*_max`` is ``None`` when the
    limit is the literal ``max`` (unlimited) as well as when unreadable.
    """
    out: dict[str, int | None] = {
        "chromium_processes": None,
        "chromium_reparented": None,
        "cgroup_memory_current_bytes": None,
        "cgroup_memory_max_bytes": None,
        "cgroup_pids_current": None,
        "cgroup_pids_max": None,
        "shm_free_bytes": None,
        "tmp_free_bytes": None,
    }
    try:
        descendants, cgroup_only = collect_service_pids(root_pid)
        chromium = [
            p for p in descendants | cgroup_only if looks_like_playwright_chromium(read_cmdline(p))
        ]
        out["chromium_processes"] = len(chromium)
        out["chromium_reparented"] = sum(1 for p in chromium if p in cgroup_only)
        cg = service_cgroup_dir(root_pid)
        if cg is not None:
            out["cgroup_memory_current_bytes"] = _int_or_none(_read_text(cg / "memory.current"))
            out["cgroup_memory_max_bytes"] = _int_or_none(_read_text(cg / "memory.max"))
            out["cgroup_pids_current"] = _int_or_none(_read_text(cg / "pids.current"))
            out["cgroup_pids_max"] = _int_or_none(_read_text(cg / "pids.max"))
        out["shm_free_bytes"] = _free_bytes(shm_dir)
        out["tmp_free_bytes"] = _free_bytes(tmp_dir or tempfile.gettempdir())
    except Exception:  # noqa: BLE001 -- a diagnostic must never break its caller
        pass
    return out
