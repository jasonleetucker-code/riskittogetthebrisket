"""A diagnostic that answers nothing must not report success.

The first production privilege probe died on ``BASH_SOURCE[0]: unbound
variable`` after its earlier sections had already printed.  ``ssh``
returned that failure, but the script's own trailing ``exit 0`` had
overridden it, so the job went green while answering none of the
question it was dispatched for.

``fd_inventory.sh`` now declares each section as required or optional:
required evidence must both run AND yield, and any required failure is
accumulated into a non-zero exit.  Optional evidence — a tool that is
not installed, a journal that does not reach back far enough — degrades
with an explicit line and does not affect the verdict.

The real script is executed here.  ``sudo`` is stubbed on ``PATH``
(these tests run as root, and the script only ever sudoes systemctl and
journalctl) so a required probe can be broken on purpose; ``/proc`` reads
are real, against a real child process.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INVENTORY = REPO / "deploy" / "diagnostics" / "fd_inventory.sh"

# `sudo -n <bin> ...` stand-in.  IDENTITY_MODE controls only the
# multi-property `show` — the one that feeds the required
# "service identity and limits" section.  `--value` (PID resolution)
# always answers, so the script gets past its hard guard and reaches the
# accumulator, which is what is under test.
FAKE_SUDO = r"""#!/usr/bin/env bash
[[ "${1:-}" == "-n" ]] && shift
bin="$(basename "${1:-}")"; shift || true
case "${bin}" in
  systemctl)
    case "${1:-}" in
      show)
        if [[ "$*" == *--value* ]]; then
          printf '%s\n' "${FAKE_PID}"
          exit 0
        fi
        case "${IDENTITY_MODE:-ok}" in
          ok)    printf 'MainPID=%s\nLimitNOFILE=524288\nLimitNOFILESoft=1024\n' "${FAKE_PID}"; exit 0 ;;
          empty) exit 0 ;;                       # ran, yielded nothing
          fail)  echo "boom" >&2; exit 1 ;;      # did not run
        esac
        ;;
      list-timers) printf 'NEXT LEFT LAST PASSED UNIT ACTIVATES\n'; exit 0 ;;
    esac
    exit 0
    ;;
  journalctl)
    if [[ "${JOURNAL_MODE:-ok}" == "fail" ]]; then
      echo "journal unavailable" >&2
      exit 1
    fi
    exit 0
    ;;
esac
exit 0
"""


@pytest.fixture
def probe(tmp_path):
    """A real child process to inventory, plus a stubbed sudo."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo = bin_dir / "sudo"
    sudo.write_text(FAKE_SUDO)
    sudo.chmod(0o755)

    child = subprocess.Popen(["sleep", "120"])
    # Give the kernel a moment to publish /proc/<pid>/fd.
    for _ in range(50):
        if Path(f"/proc/{child.pid}/fd").exists():
            break
        time.sleep(0.02)

    def run(**mode) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_PID": str(child.pid),
            **mode,
        }
        return subprocess.run(
            ["bash", str(INVENTORY), "brisket", "2", "0"],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

    try:
        yield run
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait()


class TestRequiredEvidenceCannotDegrade:
    def test_a_healthy_run_exits_zero(self, probe):
        r = probe()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "fd_inventory complete" in r.stdout
        assert "REQUIRED EVIDENCE MISSING" not in r.stderr

    def test_a_broken_required_command_fails_the_run(self, probe):
        """`systemctl show` errors — the section did not run."""
        r = probe(IDENTITY_MODE="fail")

        assert r.returncode == 5, r.stdout + r.stderr
        assert "REQUIRED EVIDENCE MISSING" in r.stderr
        assert "service identity and limits" in r.stderr
        assert "fd_inventory INCOMPLETE" in r.stderr
        assert (
            "fd_inventory complete" not in r.stdout
        ), "the script claimed completion after a required section failed"

    def test_a_required_command_that_yields_nothing_also_fails(self, probe):
        """Exit status 0 is not evidence.  A probe that ran and printed
        nothing has answered nothing, and that must read the same as a
        crash — the failure mode the original probe had."""
        r = probe(IDENTITY_MODE="empty")

        assert r.returncode == 5, r.stdout + r.stderr
        assert "service identity and limits" in r.stderr

    def test_later_sections_still_run_after_a_required_failure(self, probe):
        """One broken probe must not hide the rest of the evidence; the
        exit status carries the verdict instead of an early abort."""
        r = probe(IDENTITY_MODE="fail")

        assert "FD type breakdown" in r.stdout
        assert "FD count samples" in r.stdout
        assert "total_fds=" in r.stdout

    def test_the_script_has_no_unconditional_final_exit_zero(self):
        """Read as code, not behaviour: an `exit 0` that is not guarded
        by the accumulator can override any failure above it."""
        lines = [ln.strip() for ln in INVENTORY.read_text().splitlines()]
        assert lines[-1] == "exit 0"
        tail = lines[-12:]
        assert any(
            "REQUIRED_FAILED[@]}" in ln and "((" in ln for ln in tail
        ), "the trailing exit 0 is not guarded by the required-evidence check"
        assert "exit 5" in tail


class TestOptionalEvidenceDegradesExplicitly:
    def test_a_failing_optional_probe_does_not_fail_the_run(self, probe):
        r = probe(JOURNAL_MODE="fail")

        assert r.returncode == 0, r.stdout + r.stderr
        assert "fd_inventory complete" in r.stdout

    def test_it_says_so_rather_than_passing_silently(self, probe):
        """'Degrades' means the reader is told, not that the gap is
        invisible."""
        r = probe(JOURNAL_MODE="fail")
        assert "[optional]" in r.stderr
        assert "earliest Errno 24" in r.stderr


class TestItStaysReadOnly:
    def test_no_state_changing_systemctl_verb_appears(self):
        """The contract in the header, enforced."""
        text = INVENTORY.read_text()
        for verb in (
            "restart",
            "reload",
            "daemon-reload",
            "start ",
            "stop ",
            "enable ",
            "disable ",
            "kill ",
        ):
            assert f"systemctl {verb}" not in text
            assert f'SYSTEMCTL}}" {verb}' not in text

    def test_it_does_not_print_the_environment_or_command_lines(self):
        text = INVENTORY.read_text()
        assert "/proc/${PID}/environ" not in text
        assert "/proc/${PID}/cmdline" not in text
        assert "printenv" not in text
