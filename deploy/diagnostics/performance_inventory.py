"""Bounded read-only Linux inventory; runner emits only validated fixed-schema JSON.

No application imports, providers, journals, command lines or environment reads.
Checkout identity is deliberately not a claim about Python's loaded code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import threading
import time

CAP = 131072
RESULTS = {
    "success",
    "resources",
    "timeout",
    "exit-code",
    "signal",
    "core-dump",
    "watchdog",
    "start-limit-hit",
    "oom-kill",
    "exec-condition",
    "protocol",
}
DIAGNOSTIC_NUMBERS = (
    "ExecMainCode",
    "ExecMainStartTimestampMonotonic",
    "ExecMainExitTimestampMonotonic",
    "LastTriggerUSecMonotonic",
    "NextElapseUSecMonotonic",
)
DLF_KEYS = ("dlfSf", "dlfIdp", "dlfRookieSf", "dlfRookieIdp", "dlfValuesSfTep")
ROLES = {
    "web": ".service",
    "frontend": "-frontend.service",
    "dlf": "-dlf-fetch.service",
    "dlf_timer": "-dlf-fetch.timer",
    "game_day_live": "-game-day-live.service",
    "game_day_live_timer": "-game-day-live.timer",
    "game_day_capture": "-game-day-capture.service",
    "game_day_capture_timer": "-game-day-capture.timer",
    "nginx": None,
}
STATES = {
    "loaded",
    "not-found",
    "masked",
    "error",
    "bad-setting",
    "merged",
    "stub",
    "active",
    "inactive",
    "activating",
    "deactivating",
    "failed",
    "reloading",
    "maintenance",
    "refreshing",
}
UNIT_NUMBERS = (
    "MainPID",
    "MemoryCurrent",
    "MemoryPeak",
    "MemoryMax",
    "TasksCurrent",
    "LimitNOFILE",
    "ExecMainStatus",
    "NRestarts",
)
PROCESS_NUMBERS = ("pid", "startTicks", "cpuTicks", "rssBytes", "threads", "fdCount", "uid", "gid")
HOST_NUMBERS = (
    "memoryTotalBytes",
    "memoryAvailableBytes",
    "cpuCount",
    "cpuTotalTicks",
    "cpuIdleTicks",
    "diskTotalBytes",
    "diskFreeBytes",
    "clockTicks",
)


class ProbeError(Exception):
    """Messages never cross the report boundary."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ProbeError()


def bounded(argv, *, data=None, timeout=8, cap=16384):
    child = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    chunks, failed = [], threading.Event()

    def read():
        total = 0
        try:
            while chunk := child.stdout.read(4096):
                total += len(chunk)
                if total > cap:
                    failed.set()
                    return
                chunks.append(chunk)
        except OSError:
            failed.set()

    def write():
        try:
            child.stdin.write(data)
            child.stdin.close()
        except (OSError, BrokenPipeError):
            failed.set()

    reader = threading.Thread(target=read, daemon=True)
    writer = threading.Thread(target=write, daemon=True) if data is not None else None
    reader.start()
    if writer:
        writer.start()
    deadline = time.monotonic() + timeout
    try:
        while child.poll() is None:
            if failed.is_set() or time.monotonic() >= deadline:
                raise ProbeError()
            time.sleep(0.02)
        reader.join(max(0, deadline - time.monotonic()))
        if writer:
            writer.join(max(0, deadline - time.monotonic()))
        if (
            child.returncode
            or failed.is_set()
            or reader.is_alive()
            or (writer and writer.is_alive())
        ):
            raise ProbeError()
        return b"".join(chunks)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
        child.stdout.close()
        if child.stdin and not child.stdin.closed:
            child.stdin.close()
        reader.join(3)
        if writer:
            writer.join(3)


def number(value):
    return int(value) if re.fullmatch(r"[0-9]{1,22}", str(value)) else None


def read_text(path, cap=16384):
    with Path(path).open("rb") as stream:
        raw = stream.read(cap + 1)
    if len(raw) > cap:
        raise ProbeError()
    return raw.decode("utf-8", errors="strict")


def revision(app):
    try:
        raw = bounded(["git", "-C", app, "rev-parse", "HEAD"]).decode().strip()
        return raw if re.fullmatch(r"[a-f0-9]{40}", raw) else None
    except (OSError, ProbeError, UnicodeError):
        return None


def process(pid, app):
    result = {k: None for k in PROCESS_NUMBERS}
    result.update(state="unavailable", cwdMatchesCheckout=None)
    if pid is None:
        return result
    if pid == 0:
        result["state"] = "not-running"
        return result
    try:
        root = Path("/proc") / str(pid)
        first = read_text(root / "stat").rsplit(")", 1)[1].split()
        status = dict(
            line.split(":", 1) for line in read_text(root / "status").splitlines() if ":" in line
        )
        count = None
        try:
            count = 0
            for _ in (root / "fd").iterdir():
                count += 1
                if count > 100000:
                    count = None
                    break
        except OSError:
            count = None
        try:
            matches = os.path.realpath(root / "cwd") == os.path.realpath(app)
        except OSError:
            matches = None
        last = read_text(root / "stat").rsplit(")", 1)[1].split()
        if first[19] != last[19]:
            result["state"] = "identity-changed"
            return result
        result.update(
            pid=pid,
            startTicks=int(first[19]),
            cpuTicks=int(last[11]) + int(last[12]),
            rssBytes=number(status.get("VmRSS", "").split()[0]) if status.get("VmRSS") else None,
            threads=number(status.get("Threads", "").strip()),
            fdCount=count,
            uid=number(status["Uid"].split()[0]),
            gid=number(status["Gid"].split()[0]),
            state="observed",
            cwdMatchesCheckout=matches,
        )
        if result["rssBytes"] is not None:
            result["rssBytes"] *= 1024
    except (OSError, ValueError, IndexError, KeyError, ProbeError):
        pass
    return result


def unit(name, app):
    result = {k: None for k in UNIT_NUMBERS}
    result.update(
        state="unavailable",
        load=None,
        active=None,
        memoryUnlimited=False,
        process=process(None, app),
        diagnostics={
            **dict.fromkeys(DIAGNOSTIC_NUMBERS),
            "result": None,
            "successExitStatuses": None,
        },
    )
    try:
        props = [
            "LoadState",
            "ActiveState",
            *UNIT_NUMBERS,
            "Result",
            "SuccessExitStatus",
            *DIAGNOSTIC_NUMBERS,
        ]
        raw = bounded(
            ["systemctl", "show", name, "--no-pager", *[f"--property={p}" for p in props]]
        )
        fields = dict(line.split("=", 1) for line in raw.decode().splitlines() if "=" in line)
        load, active = fields.get("LoadState"), fields.get("ActiveState")
        if load not in STATES or active not in STATES:
            return result
        result.update(
            state="observed",
            load=load,
            active=active,
            memoryUnlimited=fields.get("MemoryMax") == "infinity",
        )
        result.update({k: number(fields.get(k, "")) for k in UNIT_NUMBERS})
        success = fields.get("SuccessExitStatus")
        statuses = success.split() if success is not None else None
        result["diagnostics"] = {
            **{k: number(fields.get(k, "")) for k in DIAGNOSTIC_NUMBERS},
            "result": fields.get("Result") if fields.get("Result") in RESULTS else None,
            "successExitStatuses": sorted(set(map(int, statuses)))
            if statuses is not None
            and len(statuses) <= 256
            and all(re.fullmatch(r"[0-9]{1,3}", item) and int(item) <= 255 for item in statuses)
            else None,
        }
        result["process"] = process(result["MainPID"], app)
    except (OSError, ProbeError, UnicodeError):
        pass
    return result


def dlf_manifest(path=Path("/var/lib/dlf-fetch/dlf_written.json")):
    """Default-path observation only; never proof of effective service configuration."""
    result = {
        "state": "unavailable",
        "assumedDefaultPath": True,
        "mtimeEpochSeconds": None,
        "written": dict.fromkeys(DLF_KEYS),
    }
    try:
        path = Path(path)
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            return result
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        )
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > 4096:
                return result
            raw = stream.read(4097)
            after = os.fstat(stream.fileno())
        if len(raw) > 4096 or (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            return result
        keys = json.loads(raw)
        if (
            not isinstance(keys, list)
            or len(keys) > len(DLF_KEYS)
            or any(type(k) is not str or k not in DLF_KEYS for k in keys)
            or len(set(keys)) != len(keys)
        ):
            return result
        result.update(
            state="observed",
            mtimeEpochSeconds=before.st_mtime,
            written={key: key in keys for key in DLF_KEYS},
        )
    except (OSError, ValueError, TypeError):
        pass
    return result


def host(app):
    result = {k: None for k in HOST_NUMBERS}
    result["cpuCount"] = os.cpu_count()
    result["clockTicks"] = os.sysconf("SC_CLK_TCK")
    try:
        mem = dict(line.split(":", 1) for line in read_text("/proc/meminfo").splitlines())
        result.update(
            memoryTotalBytes=int(mem["MemTotal"].split()[0]) * 1024,
            memoryAvailableBytes=int(mem["MemAvailable"].split()[0]) * 1024,
        )
        cpu = [int(x) for x in read_text("/proc/stat", 131072).splitlines()[0].split()[1:9]]
        result.update(cpuTotalTicks=sum(cpu), cpuIdleTicks=cpu[3] + cpu[4])
        disk = os.statvfs(app)
        result.update(
            diskTotalBytes=disk.f_blocks * disk.f_frsize,
            diskFreeBytes=disk.f_bavail * disk.f_frsize,
        )
    except (OSError, ValueError, KeyError, IndexError, ProbeError):
        pass
    return result


def complete_observations(value):
    rows = value["rows"]
    identities = {
        (row["units"]["web"]["process"]["pid"], row["units"]["web"]["process"]["startTicks"])
        for row in rows
    }
    return (
        value["checkoutStable"]
        and len(identities) == 1
        and all(
            row["units"]["web"]["state"] == "observed"
            and row["units"]["web"]["active"] == "active"
            and row["units"]["web"]["process"]["state"] == "observed"
            and row["units"]["web"]["MainPID"] == row["units"]["web"]["process"]["pid"]
            and all(row["units"]["web"]["process"][key] is not None for key in PROCESS_NUMBERS)
            and all(row["host"][key] is not None for key in HOST_NUMBERS)
            for row in rows
        )
    )


def collect(args):
    start, before = time.monotonic(), revision(args.app_dir)
    rows = []
    for index in range(args.samples):
        if index:
            time.sleep(args.interval)
        rows.append(
            {
                "sequence": index,
                "observedAtEpochSeconds": time.time(),
                "elapsedSeconds": time.monotonic() - start,
                "host": host(args.app_dir),
                "units": {
                    role: unit(
                        args.service + suffix if suffix is not None else "nginx.service",
                        args.app_dir,
                    )
                    for role, suffix in ROLES.items()
                },
            }
        )
    after = revision(args.app_dir)
    result = {
        "schema": 1,
        "state": "partial",
        "checkoutBefore": before,
        "checkoutAfter": after,
        "checkoutStable": before is not None and before == after,
        "loadedProcessRevision": None,
        "rows": rows,
        "dlfManifest": dlf_manifest(),
    }
    if complete_observations(result):
        result["state"] = "complete"
    return result


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProbeError()
        result[key] = value
    return result


def validate(raw, count):
    if len(raw) > CAP:
        raise ProbeError()
    value = json.loads(raw, object_pairs_hook=strict_object)
    if set(value) - {"dlfManifest"} != {
        "schema",
        "state",
        "checkoutBefore",
        "checkoutAfter",
        "checkoutStable",
        "loadedProcessRevision",
        "rows",
    }:
        raise ProbeError()
    if (
        value["schema"] != 1
        or value["state"] not in ("complete", "partial")
        or value["loadedProcessRevision"] is not None
    ):
        raise ProbeError()
    if "dlfManifest" in value:
        manifest = value["dlfManifest"]
        if (
            set(manifest) != {"state", "assumedDefaultPath", "mtimeEpochSeconds", "written"}
            or manifest["state"] not in {"observed", "unavailable"}
            or manifest["assumedDefaultPath"] is not True
            or set(manifest["written"]) != set(DLF_KEYS)
        ):
            raise ProbeError()
        stamp = manifest["mtimeEpochSeconds"]
        if manifest["state"] == "observed":
            if (
                type(stamp) not in (int, float)
                or not math.isfinite(stamp)
                or not 0 <= stamp <= 10**22
                or any(type(x) is not bool for x in manifest["written"].values())
            ):
                raise ProbeError()
        elif stamp is not None or any(x is not None for x in manifest["written"].values()):
            raise ProbeError()
    for key in ("checkoutBefore", "checkoutAfter"):
        if value[key] is not None and not re.fullmatch(r"[a-f0-9]{40}", str(value[key])):
            raise ProbeError()
    if value["checkoutStable"] is not (
        value["checkoutBefore"] is not None and value["checkoutBefore"] == value["checkoutAfter"]
    ):
        raise ProbeError()

    def nums(obj, keys):
        for key in keys:
            x = obj[key]
            if x is not None and (
                type(x) not in (int, float) or not math.isfinite(x) or x < 0 or x > 10**22
            ):
                raise ProbeError()

    if type(value["rows"]) is not list or len(value["rows"]) != count:
        raise ProbeError()
    previous = -1
    for index, row in enumerate(value["rows"]):
        if (
            set(row) != {"sequence", "observedAtEpochSeconds", "elapsedSeconds", "host", "units"}
            or type(row["sequence"]) is not int
            or row["sequence"] != index
        ):
            raise ProbeError()
        nums(row, ("elapsedSeconds", "observedAtEpochSeconds"))
        if row["observedAtEpochSeconds"] is None:
            raise ProbeError()
        if row["elapsedSeconds"] is None or row["elapsedSeconds"] < previous:
            raise ProbeError()
        previous = row["elapsedSeconds"]
        if set(row["host"]) != set(HOST_NUMBERS) or set(row["units"]) != set(ROLES):
            raise ProbeError()
        nums(row["host"], HOST_NUMBERS)
        for u in row["units"].values():
            if set(u) - {"diagnostics"} != set(UNIT_NUMBERS) | {
                "state",
                "load",
                "active",
                "memoryUnlimited",
                "process",
            }:
                raise ProbeError()
            if "diagnostics" in u:
                diagnostic = u["diagnostics"]
                if set(diagnostic) != set(DIAGNOSTIC_NUMBERS) | {
                    "result",
                    "successExitStatuses",
                } or diagnostic["result"] not in RESULTS | {None}:
                    raise ProbeError()
                nums(diagnostic, DIAGNOSTIC_NUMBERS)
                if any(
                    diagnostic[key] is not None and type(diagnostic[key]) is not int
                    for key in DIAGNOSTIC_NUMBERS
                ):
                    raise ProbeError()
                statuses = diagnostic["successExitStatuses"]
                if statuses is not None and (
                    type(statuses) is not list
                    or len(statuses) > 256
                    or any(type(x) is not int or not 0 <= x <= 255 for x in statuses)
                    or statuses != sorted(set(statuses))
                ):
                    raise ProbeError()
            nums(u, UNIT_NUMBERS)
            if (
                u["state"] not in ("observed", "unavailable")
                or u["load"] not in STATES | {None}
                or u["active"] not in STATES | {None}
                or type(u["memoryUnlimited"]) is not bool
            ):
                raise ProbeError()
            p = u["process"]
            if set(p) != set(PROCESS_NUMBERS) | {"state", "cwdMatchesCheckout"}:
                raise ProbeError()
            nums(p, PROCESS_NUMBERS)
            if p["state"] not in ("observed", "unavailable", "not-running", "identity-changed") or (
                p["cwdMatchesCheckout"] is not None and type(p["cwdMatchesCheckout"]) is not bool
            ):
                raise ProbeError()
    if (value["state"] == "complete") != bool(complete_observations(value)):
        raise ProbeError()
    return value


def main():
    parser = Parser()
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--app-dir", default="/home/dynasty/trade-calculator")
    parser.add_argument("--service", default="dynasty")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (
        not 1 <= args.samples <= 20
        or not 1 <= args.interval <= 60
        or args.samples * args.interval > 300
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.service)
    ):
        raise ProbeError()
    if args.collect:
        # Covers the whole remote process even if a proc/filesystem read stalls.
        import signal

        def deadline_expired(*_):
            raise ProbeError()

        signal.signal(signal.SIGALRM, deadline_expired)
        signal.alarm(480)
        print(json.dumps(collect(args), allow_nan=False))
        return 0
    if args.output is None:
        raise ProbeError()
    result, code = {"schema": 1, "state": "probe-failed"}, 1
    try:
        port = os.environ.get("PORT", "22")
        if not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ProbeError()
        remote = " ".join(
            shlex.quote(x)
            for x in [
                "python3",
                "-",
                "--collect",
                "--app-dir",
                args.app_dir,
                "--service",
                args.service,
                "--samples",
                str(args.samples),
                "--interval",
                str(args.interval),
            ]
        )
        ssh = [
            "ssh",
            "-i",
            str(Path.home() / ".ssh/id_ed25519"),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={Path.home() / '.ssh/known_hosts'}",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
            "-p",
            port,
            "--",
            os.environ["DEPLOY_USER"] + "@" + os.environ["DEPLOY_HOST"],
            remote,
        ]
        source = Path(__file__).read_bytes()
        result = validate(bounded(ssh, data=source, timeout=510, cap=CAP), args.samples)
        code = 0 if result["state"] == "complete" else 1
    except (OSError, ValueError, KeyError, TypeError, ProbeError):
        pass
    result["provenance"] = {
        "sourceSha": os.environ.get("GITHUB_SHA")
        if re.fullmatch(r"[a-f0-9]{40}", os.environ.get("GITHUB_SHA", ""))
        else None,
        "helperSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runId": number(os.environ.get("GITHUB_RUN_ID", "")),
        "attempt": number(os.environ.get("GITHUB_RUN_ATTEMPT", "")),
    }
    args.output.write_text(json.dumps(result, allow_nan=False) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        # No command, error message, filesystem path or external text escapes.
        raise SystemExit(1) from None
