"""The snapshot timer must be installed, not merely written.

The audit's standing rule: "a timer template that is never installed
does not count as active automation." Consensus Edge had no scheduled
job of any kind, so these tests check the whole chain — template exists,
installer references it, installer enables it — rather than just the
file being present.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO / "deploy" / "install-systemd-service.sh"
_SERVICE = _REPO / "deploy" / "systemd" / "dynasty-consensus-edge-snapshot.service.template"
_TIMER = _REPO / "deploy" / "systemd" / "dynasty-consensus-edge-snapshot.timer.template"
_SCRIPT = _REPO / "scripts" / "snapshot_consensus_edge.py"


def test_every_artifact_exists():
    for path in (_INSTALLER, _SERVICE, _TIMER, _SCRIPT):
        assert path.is_file(), path


def test_service_runs_the_snapshot_script():
    body = _SERVICE.read_text(encoding="utf-8")
    assert "scripts/snapshot_consensus_edge.py" in body
    assert "Type=oneshot" in body
    # Never let a background snapshot starve the API it reads from.
    assert "Nice=10" in body


def test_timer_is_catch_up_safe_and_names_only_its_own_service():
    body = _TIMER.read_text(encoding="utf-8")
    directives = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))
    assert "Persistent=true" in directives, "a missed run must be backfilled"
    assert "Unit=__SERVICE_NAME__-consensus-edge-snapshot.service" in directives
    # A Requires= in [Unit] would start the service every boot and let a
    # service failure kill the schedule.
    assert "Requires=" not in directives.split("[Timer]", 1)[0]


def test_timer_declares_utc_explicitly():
    # Pinned repo-wide by tests/deploy/test_timers_are_utc.py; asserted
    # here too so a local edit fails against the nearest test.
    body = _TIMER.read_text(encoding="utf-8")
    calendars = [ln for ln in body.splitlines() if ln.strip().startswith("OnCalendar=")]
    assert calendars, "timer declares no schedule"
    for line in calendars:
        assert line.rstrip().endswith("UTC"), line


def test_installer_installs_and_enables_it():
    body = _INSTALLER.read_text(encoding="utf-8")
    assert "dynasty-consensus-edge-snapshot.service.template" in body
    assert "dynasty-consensus-edge-snapshot.timer.template" in body
    assert "${ce_service_name}.timer" in body, "installer never enables the timer"
    assert "enable --now" in body


def test_the_script_exposes_an_argv_injectable_main():
    # Repo convention (tests/scripts/test_fetcher_main_argv_contract.py):
    # main(argv) must be callable without touching sys.argv.
    body = _SCRIPT.read_text(encoding="utf-8")
    assert "def main(argv: list[str] | None = None) -> int:" in body
    assert "sys.exit(main())" in body


def test_the_script_documents_its_exit_codes():
    body = _SCRIPT.read_text(encoding="utf-8")
    assert "Exit codes" in body
    for code in ("0", "1", "2"):
        assert f"    {code}  -" in body
