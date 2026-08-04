"""The snapshot timer must be installed, not merely written.

The audit's standing rule: "a timer template that is never installed
does not count as active automation." Consensus Edge had no scheduled
job of any kind, so these tests check the whole chain — template exists,
installer references it, installer enables it — rather than just the
file being present.

A later audit found the chain-check was weaker than it looked, in a way
worth stating so it is not re-weakened:

* ``assert "enable --now" in body`` matched any of eleven OTHER timers
  in the same installer. It would have passed with the Consensus Edge
  enable line deleted. Assertions here now scope to ``${ce_...}``
  variables so they can only be satisfied by this unit.
* Nothing checked ``User=``. This template was the ONLY one in the repo
  without it, so the unit ran as root and created a root-owned
  ``consensus_edge.sqlite``; ``snapshot.connect()`` opens read-write, so
  the API process could then never open the database it is meant to
  read. Every snapshot written, none readable.
* ``ce_needs_install`` was absent from the installer's daemon-reload
  guard — every other timer's flag was there — so a forced rewrite
  started the stale cached unit.
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


def _directives(path):
    """Uncommented directive lines only.

    Every assertion below has to read these rather than the raw file:
    this template documents the User= defect in a comment, so a
    substring search over the whole body would pass on the prose that
    describes the bug.
    """
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_service_does_not_run_as_root():
    # The defect, stated as an invariant rather than as a value: a
    # oneshot that writes into data/ must run as the same user the API
    # runs as, or the API cannot open what it writes.
    directives = _directives(_SERVICE)
    assert "User=__APP_USER__" in directives, "the unit would run as root"
    assert "Group=__APP_USER__" in directives


def test_the_service_matches_the_conventions_every_other_timer_follows():
    # Compared against a sibling rather than against a hardcoded list,
    # so this keeps working if the repo convention moves.
    reference = _REPO / "deploy" / "systemd" / "dynasty-bdvm-refresh.service.template"
    if not reference.is_file():  # pragma: no cover - reference removed
        return
    expected = {
        line
        for line in _directives(reference)
        if line.startswith(
            ("User=", "Group=", "EnvironmentFile=", "StandardOutput=", "StandardError=")
        )
    }
    missing = expected - set(_directives(_SERVICE))
    assert not missing, f"consensus-edge unit is missing conventional directives: {sorted(missing)}"


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
    # Scoped to THIS unit's variable. The old form — `"enable --now" in
    # body` — matched any of eleven other timers and would have passed
    # with the consensus-edge enable line deleted outright.
    assert (
        'enable --now "${ce_service_name}.timer"' in body
    ), "installer never enables the consensus-edge timer specifically"


def test_the_installer_reloads_systemd_after_writing_this_unit():
    # A forced rewrite that skips daemon-reload writes the new file and
    # starts the stale cached one: deployed, reported as deployed, not
    # running. Every other timer's flag was in this guard; this one's
    # was not.
    body = _INSTALLER.read_text(encoding="utf-8")
    guard = [
        line
        for line in body.splitlines()
        if "daemon-reload" not in line
        and "_needs_install}" in line
        and line.strip().startswith("if [[")
    ]
    assert guard, "could not find the daemon-reload guard"
    assert any(
        "${ce_needs_install}" in line for line in guard
    ), "ce_needs_install is not in the daemon-reload guard"


def test_the_service_passes_the_app_user_through_the_installer():
    # The template is only as good as its substitution: __APP_USER__ has
    # to be one of the tokens the installer replaces for this unit.
    body = _INSTALLER.read_text(encoding="utf-8")
    block = body.split("${ce_service_template}", 1)
    assert len(block) > 1, "installer does not render the consensus-edge template"
    preamble = block[0].rsplit("tmp_ce_service", 1)[-1] + block[1][:400]
    assert "__APP_USER__" in preamble, "the installer never substitutes __APP_USER__ for this unit"


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
