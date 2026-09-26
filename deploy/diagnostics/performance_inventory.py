"""Bounded read-only Linux inventory; runner emits only validated fixed-schema JSON.

No application imports, providers, raw journal output, command lines or environment reads.
Checkout identity is deliberately not a claim about Python's loaded code.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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


class ProbeTimeout(ProbeError):
    pass


class ProbeLimit(ProbeError):
    pass


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
    limited = threading.Event()

    def read():
        total = 0
        try:
            while chunk := child.stdout.read(4096):
                total += len(chunk)
                if total > cap:
                    limited.set()
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
            if limited.is_set():
                raise ProbeLimit()
            if failed.is_set():
                raise ProbeError()
            if time.monotonic() >= deadline:
                raise ProbeTimeout()
            time.sleep(0.02)
        reader.join(max(0, deadline - time.monotonic()))
        if writer:
            writer.join(max(0, deadline - time.monotonic()))
        if limited.is_set():
            raise ProbeLimit()
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


JOURNAL_STATES = {
    "complete",
    "empty",
    "truncated",
    "unavailable",
    "timeout",
    "malformed",
    "invocation_changed",
}
STAGE_PATTERNS = {
    "dlf": {
        "sync_started": r"\[dlf-fetch\] syncing to origin/main",
        "fetch_started": r"\[dlf-fetch\] running scripts/fetch_dlf\.py",
        "credentials_missing": r"\[dlf-fetch\]\[ERR\] DLF_USERNAME / DLF_PASSWORD not set in environment - check the systemd unit's EnvironmentFile=\.",
        "preview_detected": r"\[DLF\] (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep): got non-member preview — re-authenticating …",
        "reauth_failed": r"\[DLF\] (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep): re-auth failed: .+",
        "preview_persisted": r"\[DLF\] (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep): still preview after re-auth — membership may have lapsed\.",
        "no_rows": r"\[DLF\] WARN: no rows extracted for (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep)",
        "board_parsed": r"\[DLF\] (?:dlfSf \(Dynasty Superflex\)|dlfIdp \(Dynasty IDP\)|dlfRookieSf \(Rookie Superflex\)|dlfRookieIdp \(Rookie IDP\)|dlfValuesSfTep \(Trade Analyzer Values \(SF, TE premium\)\)): parsed [0-9]{1,6} (?:rows|assets)",
        "push_succeeded": r"\[dlf-fetch\] push succeeded on attempt [1-3]/3",
        "push_rejected": r"\[dlf-fetch\] push rejected on attempt [1-3]/3 - rebasing and retrying",
        "rebase_failed": r"\[dlf-fetch\]\[ERR\] rebase failed - manual intervention required\.",
        "push_exhausted": r"\[dlf-fetch\]\[ERR\] push still rejected after 3 attempts - giving up; will retry on next timer fire\.",
        "login_failed": r"\[DLF\] login failed: .+",
        "board_fetch_failed": r"\[DLF\] (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep) fetch failed: .+",
        "board_refused": r"\[DLF\] (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep): .+\.  Preserving last-good CSV, NOT overwriting .+\.",
        "no_board_written": r"\[dlf-fetch\]\[ERR\] fetch_dlf\.py exited [0-9]{1,3} and wrote no board - keeping previous CSVs / stamps; will retry on next timer fire\.",
        "partial_commit": r"\[dlf-fetch\]\[ERR\] fetch_dlf\.py exited [0-9]{1,3}; committing only the boards it wrote: (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep)(?: (?:dlfSf|dlfIdp|dlfRookieSf|dlfRookieIdp|dlfValuesSfTep))*",
    },
    "game_day_capture": {
        "no_leagues": r"Nothing to do: no leagues resolved\.",
        "no_week": r"Nothing to do: no season/week resolved\.",
        "kickoff_passed": r"REFUSED: first kickoff has passed\.",
        "window_closed": r"REFUSED: the pregame window has closed for this week\.",
        "capture_started": r"Capturing (?:pregame|live) for season [0-9]{4}, week [0-9]{1,2} across [0-9]{1,3} league\(s\)\.",
        "league_id_missing": r"    ERROR: no Sleeper league id",
        "league_payload_missing": r"    ERROR: Sleeper returned no league payload or no rosters",
        "capture_refused": r"    REFUSED: .+",
        "capture_error": r"    ERROR: .+",
        "refusal_summary": r"REFUSED [0-9]{1,3} league\(s\): pregame window closed\.",
        "failure_summary": r"FAILED for [0-9]{1,3} league\(s\)\.",
        "completed": r"Done\.",
    },
}


def stage_result(state):
    return {
        "state": state,
        "invocationStable": None,
        "rows": 0,
        "unknown": 0,
        "stages": {},
        "lastRecognizedStage": None,
        "codeBinding": "unproven",
    }


def parse_journal(raw, invocation, role):
    result = stage_result("complete")
    lines = raw.splitlines()
    if len(raw) > CAP or len(lines) > 200:
        return stage_result("truncated")
    for line in lines:
        try:
            row = json.loads(line, object_pairs_hook=strict_object)
            message = row["MESSAGE"]
            if row.get("_SYSTEMD_INVOCATION_ID") != invocation:
                return stage_result("invocation_changed")
            if not isinstance(message, str) or len(message.encode("utf-8")) > 8192:
                return stage_result("malformed")
        except (ValueError, KeyError, TypeError, ProbeError):
            return stage_result("malformed")
        result["rows"] += 1
        stage = next(
            (
                key
                for key, pattern in STAGE_PATTERNS[role].items()
                if re.fullmatch(pattern, message)
            ),
            None,
        )
        if stage:
            result["stages"][stage] = result["stages"].get(stage, 0) + 1
            result["lastRecognizedStage"] = stage
        else:
            result["unknown"] += 1
    if not lines:
        result["state"] = "empty"
    return result


def journal_stages(service, role):
    unit_name = service + ROLES[role]
    command = ["systemctl", "show", unit_name, "--property=InvocationID", "--value"]
    try:
        before = bounded(command, timeout=8, cap=128).decode("ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{32}", before):
            return stage_result("unavailable")
        raw = bounded(
            [
                "journalctl",
                "--quiet",
                "--no-pager",
                "--output=json",
                "--output-fields=MESSAGE,_SYSTEMD_INVOCATION_ID",
                "--lines=201",
                "--unit=" + unit_name,
                "_SYSTEMD_INVOCATION_ID=" + before,
            ],
            timeout=8,
            cap=CAP,
        )
        after = bounded(command, timeout=8, cap=128).decode("ascii").strip()
        if before != after:
            result = stage_result("invocation_changed")
            result["invocationStable"] = False
            return result
        result = parse_journal(raw, before, role)
        result["invocationStable"] = result["state"] != "invocation_changed"
        return result
    except ProbeLimit:
        return stage_result("truncated")
    except ProbeTimeout:
        return stage_result("timeout")
    except (OSError, ValueError, ProbeError):
        return stage_result("unavailable")


def validate_stages(value):
    if not isinstance(value, dict) or set(value) != set(STAGE_PATTERNS):
        raise ProbeError()
    for role, row in value.items():
        if not isinstance(row, dict) or set(row) != set(stage_result("empty")):
            raise ProbeError()
        if row["state"] not in JOURNAL_STATES or row["codeBinding"] != "unproven":
            raise ProbeError()
        if row["invocationStable"] is not None and type(row["invocationStable"]) is not bool:
            raise ProbeError()
        if any(type(row[k]) is not int or not 0 <= row[k] <= 200 for k in ("rows", "unknown")):
            raise ProbeError()
        stages = row["stages"]
        if not isinstance(stages, dict) or set(stages) - set(STAGE_PATTERNS[role]):
            raise ProbeError()
        if any(type(n) is not int or not 1 <= n <= 200 for n in stages.values()):
            raise ProbeError()
        if row["rows"] != row["unknown"] + sum(stages.values()):
            raise ProbeError()
        if row["lastRecognizedStage"] not in ({None} | set(stages)) or (
            bool(stages) != (row["lastRecognizedStage"] is not None)
        ):
            raise ProbeError()
        if row["state"] in {"complete", "empty"}:
            if row["invocationStable"] is not True or (row["state"] == "empty") != (
                row["rows"] == 0
            ):
                raise ProbeError()
        elif row["rows"] or stages or row["lastRecognizedStage"] is not None:
            raise ProbeError()


def fixed_file(path, cap):
    """Bounded no-follow regular file; callers supply fixed owner-relative paths."""
    path = Path(path)
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ProbeError()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > cap:
            raise ProbeError()
        value = stream.read(cap + 1)
        after = os.fstat(stream.fileno())
    if len(value) > cap or (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise ProbeError()
    return value


def deployment_files(app, state_dir=Path("/home/dynasty/.deploy-state")):
    # Fixed configured paths, independently read from GitHub variables on 2026-09-26;
    # this historical configuration observation is not loaded-code proof.
    result = {
        "pathBinding": "configured_paths_observed_2026-09-26",
        "receiptState": "unavailable",
        "targetRevision": None,
        "successAtUtc": None,
        "successAtEpochSeconds": None,
        "frontendBuildIdSha256": None,
        "frontendManifestSha256": None,
        "loadedProcessRevision": None,
    }
    try:
        paths = [
            state_dir / name
            for name in (
                "last_successful_rev",
                "last_successful_at_utc",
                "trade-calculator.last_successful_deploy_commit",
            )
        ]
        first = [fixed_file(path, 128) for path in paths]
        revision_value, stamp, duplicate = [raw.decode("ascii").strip() for raw in first]
        if not re.fullmatch(r"[a-f0-9]{40}", revision_value) or duplicate != revision_value:
            raise ProbeError()
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", stamp):
            raise ProbeError()
        epoch = (
            datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        )
        if first != [fixed_file(path, 128) for path in paths]:
            result["receiptState"] = "ambiguous"
        else:
            result.update(
                receiptState="observed",
                targetRevision=revision_value,
                successAtUtc=stamp,
                successAtEpochSeconds=epoch,
            )
    except (OSError, ValueError, ProbeError):
        pass
    for name, output, cap in (
        ("BUILD_ID", "frontendBuildIdSha256", 256),
        ("build-manifest.json", "frontendManifestSha256", CAP),
    ):
        try:
            raw = fixed_file(Path(app) / "frontend" / ".next" / name, cap)
            if name == "BUILD_ID" and not re.fullmatch(rb"[A-Za-z0-9_-]{1,200}\n?", raw):
                raise ProbeError()
            if name != "BUILD_ID" and not isinstance(json.loads(raw), dict):
                raise ProbeError()
            result[output] = hashlib.sha256(raw).hexdigest()
        except (OSError, ValueError, ProbeError):
            pass
    return result


def validate_deployment(value):
    keys = {
        "pathBinding",
        "receiptState",
        "targetRevision",
        "successAtUtc",
        "successAtEpochSeconds",
        "frontendBuildIdSha256",
        "frontendManifestSha256",
        "loadedProcessRevision",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or value["pathBinding"] != "configured_paths_observed_2026-09-26"
        or value["receiptState"] not in {"observed", "unavailable", "ambiguous"}
        or value["loadedProcessRevision"] is not None
    ):
        raise ProbeError()
    for key in ("frontendBuildIdSha256", "frontendManifestSha256"):
        if value[key] is not None and (
            type(value[key]) is not str or not re.fullmatch(r"[a-f0-9]{64}", value[key])
        ):
            raise ProbeError()
    if value["receiptState"] == "observed":
        try:
            stamp = value["successAtUtc"]
            if type(stamp) is not str or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", stamp
            ):
                raise ProbeError()
            epoch = (
                datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=timezone.utc)
                .timestamp()
            )
            if (
                type(value["targetRevision"]) is not str
                or not re.fullmatch(r"[a-f0-9]{40}", value["targetRevision"])
                or type(value["successAtEpochSeconds"]) not in (int, float)
                or epoch < 0
                or value["successAtEpochSeconds"] != epoch
            ):
                raise ProbeError()
        except (ValueError, TypeError):
            raise ProbeError() from None
    elif any(
        value[k] is not None for k in ("targetRevision", "successAtUtc", "successAtEpochSeconds")
    ):
        raise ProbeError()


def deployment_chronology(args, previous, receipt):
    output = {}
    boot = None
    try:
        match = re.search(r"(?m)^btime ([0-9]+)$", read_text("/proc/stat"))
        boot = int(match.group(1)) if match else None
        ticks = os.sysconf("SC_CLK_TCK")
        if ticks <= 0:
            boot = None
    except (OSError, ValueError, AttributeError, ProbeError):
        pass
    for role in ("web", "frontend"):
        old = previous[role]["process"]
        new = unit(args.service + ROLES[role], args.app_dir)["process"]
        stable = (
            old["state"] == new["state"] == "observed"
            and old["pid"] == new["pid"]
            and old["startTicks"] == new["startTicks"]
        )
        epoch = boot + new["startTicks"] / ticks if stable and boot is not None else None
        succeeded = receipt["successAtEpochSeconds"]
        output[role] = {
            "processIdentityStable": stable,
            "pid": new["pid"],
            "startTicks": new["startTicks"],
            "startEpochApprox": epoch,
            "startedBeforeReceipt": epoch <= succeeded
            if epoch is not None and succeeded is not None
            else None,
        }
    return output


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
        "deploymentFiles": deployment_files(args.app_dir),
        "dlfManifest": dlf_manifest(),
        "sourceStages": {role: journal_stages(args.service, role) for role in STAGE_PATTERNS},
    }
    result["deploymentChronology"] = deployment_chronology(
        args, rows[-1]["units"], result["deploymentFiles"]
    )
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
    if set(value) - {"dlfManifest", "sourceStages", "deploymentFiles", "deploymentChronology"} != {
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
    if "deploymentChronology" in value:
        chronology = value["deploymentChronology"]
        if not isinstance(chronology, dict) or set(chronology) != {"web", "frontend"}:
            raise ProbeError()
        for row in chronology.values():
            if (
                set(row)
                != {
                    "processIdentityStable",
                    "pid",
                    "startTicks",
                    "startEpochApprox",
                    "startedBeforeReceipt",
                }
                or type(row["processIdentityStable"]) is not bool
            ):
                raise ProbeError()
            for key in ("pid", "startTicks", "startEpochApprox"):
                if row[key] is not None and (
                    type(row[key]) not in (int, float)
                    or not math.isfinite(row[key])
                    or row[key] < 0
                ):
                    raise ProbeError()
            if (
                row["startedBeforeReceipt"] is not None
                and type(row["startedBeforeReceipt"]) is not bool
            ):
                raise ProbeError()
            if not row["processIdentityStable"] and (
                row["startEpochApprox"] is not None or row["startedBeforeReceipt"] is not None
            ):
                raise ProbeError()
            if row["processIdentityStable"] and any(
                type(row[key]) is not int or row[key] <= 0 for key in ("pid", "startTicks")
            ):
                raise ProbeError()
            receipt_epoch = value.get("deploymentFiles", {}).get("successAtEpochSeconds")
            expected = (
                row["startEpochApprox"] <= receipt_epoch
                if row["startEpochApprox"] is not None and type(receipt_epoch) in (int, float)
                else None
            )
            if row["startedBeforeReceipt"] is not expected:
                raise ProbeError()
    if "deploymentFiles" in value:
        validate_deployment(value["deploymentFiles"])
    if "sourceStages" in value:
        validate_stages(value["sourceStages"])
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
