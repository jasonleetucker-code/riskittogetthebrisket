"""Failed timer services reach the operator through the existing ops-alert path (MD-103).

38 ``dynasty-*`` timers have no ``OnFailure=`` (adding it is a production
infrastructure change; see ``docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md`` section 7).
Until an operator does that, the daily ops sweep reads the failed-unit list that
``systemctl`` already gives an unprivileged user.  Pinned: parsing, the shipped-
units-only filter, ``None`` = not checked (never "no failures"), one alert per
unit, and that an unreadable pass does not recover a firing alert.
"""

from __future__ import annotations

import subprocess

from src.api import ops_alerts
from src.api import systemd_failures as sf

SAMPLE = """\
  dynasty-ktc-trades.service      loaded failed failed KTC trade archive fetch
* dynasty-sharp-rosters.service   loaded failed failed Sharp rosters
  riskit-backup.service           loaded failed failed Legacy backup
  nginx.service                   loaded failed failed A web server
  user@1000.service               loaded failed failed Not ours
  dynasty-ktc-trades.service      loaded failed failed duplicate row
"""


def _proc(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_only_shipped_services_are_kept_sorted_and_deduplicated():
    assert sf.parse_failed_units(SAMPLE) == [
        "dynasty-ktc-trades.service",
        "dynasty-sharp-rosters.service",
        "riskit-backup.service",
    ]


def test_an_empty_failed_list_is_an_empty_list_not_unknown():
    assert sf.failed_units(lambda argv: _proc("")) == []


def test_the_list_is_bounded():
    many = "\n".join(f"dynasty-x{i:03d}.service loaded failed failed x" for i in range(200))
    assert len(sf.parse_failed_units(many)) == sf.MAX_UNITS


def test_a_host_that_cannot_answer_is_unknown_never_clean():
    def missing(argv):
        raise FileNotFoundError("systemctl")

    def timeout(argv):
        raise subprocess.TimeoutExpired(argv, 10)

    assert sf.failed_units(missing) is None
    assert sf.failed_units(timeout) is None
    assert sf.failed_units(lambda argv: _proc("", returncode=1)) is None


def test_the_command_is_a_fixed_unprivileged_read():
    seen: list[list[str]] = []

    def capture(argv):
        seen.append(argv)
        return _proc("")

    sf.failed_units(capture)
    assert seen[0][:2] == ["systemctl", "list-units"] and "--failed" in seen[0]
    assert "sudo" not in seen[0]


def test_one_alert_per_failed_unit_with_per_unit_categories():
    alerts = ops_alerts._check_failed_units(["dynasty-a.service", "riskit-b.service"])
    assert {a.category for a in alerts} == {
        "systemd_unit:dynasty-a.service",
        "systemd_unit:riskit-b.service",
    }
    assert all(a.severity == "warning" for a in alerts)
    assert "journalctl -u dynasty-a.service" in alerts[0].detail
    assert ops_alerts._check_failed_units([]) == []
    assert ops_alerts._check_failed_units(None) == []


def _sweep(kv, failed, sent):
    def delivery(to, subject, body):
        sent.append((subject, body))
        return True

    return ops_alerts.check_and_alert(
        failed_units=failed, delivery=delivery, to_email="ops@example.test", kv_path=kv
    )


def test_a_failure_alerts_once_and_recovers_when_the_unit_clears(tmp_path):
    kv = tmp_path / "kv.sqlite"
    sent: list[tuple] = []
    first = _sweep(kv, ["dynasty-a.service"], sent)
    assert first["fired"] == 1 and first["delivered"]
    assert "dynasty-a.service" in sent[0][1]
    # Still failing inside the cooldown: no second email.
    again = _sweep(kv, ["dynasty-a.service"], sent)
    assert again["fired"] == 0 and len(sent) == 1
    cleared = _sweep(kv, [], sent)
    assert cleared["recovered"] == 1 and len(sent) == 2


def test_an_unreadable_pass_does_not_recover_a_firing_unit(tmp_path):
    kv = tmp_path / "kv.sqlite"
    sent: list[tuple] = []
    _sweep(kv, ["dynasty-a.service"], sent)
    blind = _sweep(kv, None, sent)  # systemctl could not be asked
    assert blind["recovered"] == 0 and len(sent) == 1
