"""Exercise the proposed Class-B container boundary with real denied actions.

This is a probe, not a worker or an authorization decision. Run only with the
fixed Docker invocation in ``class-b-isolation.yml``. Its JSON result is safe
to retain as CI evidence because it contains no repository or secret content.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket


def _denied_write(path: Path) -> bool:
    try:
        path.write_text("probe\n", encoding="utf-8")
    except OSError:
        return True
    path.unlink()
    return False


def _status_field(name: str) -> str | None:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}:"):
            return line.split(":", 1)[1].strip()
    return None


def _no_external_route() -> bool:
    rows = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()[1:]
    return not any(
        len(parts := row.split()) > 1 and parts[0] != "lo" and parts[1] == "00000000"
        for row in rows
    )


def _network_denied() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1):
            return False
    except OSError:
        return True


def _cgroup_limit(path: str, maximum: int) -> bool:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
        return value != "max" and int(value) <= maximum
    except (OSError, ValueError):
        return False


def _cpu_limit() -> bool:
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").split()
        return quota != "max" and 0 < int(quota) <= int(period)
    except (OSError, ValueError):
        return False


def main() -> int:
    worktree = Path("/worktree")
    output = Path("/output")
    output_file = output / "allowed.txt"
    output_file.write_text("allowed\n", encoding="utf-8")
    output_ok = output_file.read_text(encoding="utf-8") == "allowed\n"
    output_file.unlink()

    checks = {
        "non_root": os.geteuid() == 65534 and os.getegid() == 65534,
        "fixture_read": (worktree / "fixture.txt").read_text(encoding="utf-8")
        == "class-b-fixture\n",
        "source_write_denied": _denied_write(worktree / "forbidden.txt"),
        "rootfs_write_denied": _denied_write(Path("/var/tmp/forbidden.txt")),
        "output_write_allowed": output_ok,
        "network_route_denied": _no_external_route(),
        "network_connection_denied": _network_denied(),
        "host_credential_absent": not any(
            os.environ.get(name)
            for name in (
                "CLASS_B_HOST_CANARY",
                "GITHUB_TOKEN",
                "GH_TOKEN",
                "AWS_ACCESS_KEY_ID",
                "SSH_AUTH_SOCK",
                "DOCKER_HOST",
            )
        ),
        "host_path_absent": not (worktree / "host-escape").exists(),
        "docker_socket_absent": not Path("/var/run/docker.sock").exists(),
        "no_new_privileges": _status_field("NoNewPrivs") == "1",
        "no_capabilities": _status_field("CapBnd") == "0000000000000000",
        "pid_limit": _cgroup_limit("/sys/fs/cgroup/pids.max", 32),
        "memory_limit": _cgroup_limit("/sys/fs/cgroup/memory.max", 256 * 1024 * 1024),
        "cpu_limit": _cpu_limit(),
    }
    print(json.dumps({"schema": "class-b-isolation-probe/v1", "checks": checks}, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
