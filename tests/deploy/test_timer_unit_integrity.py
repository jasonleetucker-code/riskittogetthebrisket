"""Generic, data-driven integrity invariants for EVERY shipped systemd timer.

CW-50 / CW-46 (QA directive 2026-11-06, docs/engineering/
CONTINUOUS_VERIFICATION_STANDARD_2026-11-06.md sections 3-4): the feature
census found production timers that no test referenced.  A timer nobody
tests can silently stop being installed, point at a renamed script, or run
with a broken schedule.

Existing guards already cover wiring (``test_all_timers_are_wired``), the
UTC suffix (``test_timers_are_utc``) and ExecStart-under-__APP_DIR__
existence.  This file generalises over every timer under ``deploy/`` found
by glob (so a new timer is covered automatically) and adds:

* a matching service exists and ``Unit=`` resolves to its own service;
* every trigger directive is syntactically valid (a small validator for the
  subset this repo uses; ``systemd-analyze calendar`` is an optional extra
  check, never required);
* the service ExecStart script / module exists in the repo, and uses only
  placeholders the installer fills;
* every timer is reached by an installer route (a deploy/*.sh script names
  it) or is in the explicit manual allowlist with a reason;
* conventions that already hold: ``Persistent=`` is declared explicitly and
  every oneshot service bounds its runtime with ``TimeoutStartSec``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DEPLOY = _REPO / "deploy"

# Intentionally not installed by any deploy/*.sh route: unit -> reason.
_MANUAL_UNITS: dict[str, str] = {}

# Oneshot services with a pre-existing, documented absence of TimeoutStartSec.
_NO_TIMEOUT_OK = {
    "dynasty-custom-alerts.service.template",
    "dynasty-signal-alerts.service.template",
}

# Legacy backup oneshots that predate the convention (bounded in practice by
# the scripts themselves); listed rather than silently ignored.
_NO_TIMEOUT_OK |= {"riskit-backup.service", "riskit-backup-restore-test.service"}

_KNOWN_PLACEHOLDERS = {
    "__APP_DIR__",
    "__VENV_DIR__",
    "__SERVICE_NAME__",
    "__APP_USER__",
    "__NODE_BIN_DIR__",
    "__NPM_BIN__",
}


def _timers() -> list[Path]:
    found: set[Path] = set()
    for pattern in ("*/*.timer", "*/*.timer.template"):
        found.update(_DEPLOY.glob(pattern))
    return sorted(found)


def _service_for(timer: Path) -> Path:
    return timer.with_name(timer.name.replace(".timer", ".service", 1))


def _directives(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out.setdefault(key.strip(), []).append(value.strip())
    return out


# ── Validators for the subset this repo uses ─────────────────────────

_TIMESPAN = re.compile(r"^\d+(\.\d+)?\s?(us|ms|s|sec|m|min|h|hr|d|w)?$")
_DOW = r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_DOW_LIST = re.compile(rf"^{_DOW}(\.\.{_DOW})?(,{_DOW}(\.\.{_DOW})?)*$")
_DATE = re.compile(r"^(\*|\d{4})-(\*|\d{1,2})-(\*|\d{1,2})$")
_FIELD = re.compile(r"^(\*|\d+(\.\.\d+)?)(/\d+)?(,(\*|\d+(\.\.\d+)?)(/\d+)?)*$")


def _calendar_error(value: str) -> str | None:
    """Return a reason the OnCalendar value is invalid, else None."""
    parts = value.split()
    if parts and parts[-1] == "UTC":
        parts = parts[:-1]
    if not parts:
        return "empty"
    time_part = parts.pop()
    if parts and _DATE.match(parts[-1]):
        parts.pop()
    if parts and _DOW_LIST.match(parts[-1]):
        parts.pop()
    if parts:
        return f"unrecognised tokens {parts}"
    fields = time_part.split(":")
    if len(fields) not in (2, 3):
        return f"time {time_part!r} is not H:M[:S]"
    for field, limit in zip(fields, (23, 59, 59)):
        if not _FIELD.match(field):
            return f"bad time field {field!r}"
        for number in re.findall(r"\d+", field):
            if int(number) > limit:
                return f"time field {field!r} exceeds {limit}"
    return None


def test_calendar_validator_is_not_vacuous() -> None:
    for good in (
        "*-*-* 04:20:00 UTC",
        "Tue,Thu,Sat,Sun *-*-* 14:10:00 UTC",
        "*-*-* 00/6:47:00 UTC",
        "*-*-* *:07,37:00 UTC",
        "Wed *-*-* 12:20:00 UTC",
    ):
        assert _calendar_error(good) is None, good
    for bad in ("*-*-* 25:00:00 UTC", "Funday *-*-* 01:00:00 UTC", "*-*-* 04:20:00:00 UTC", ""):
        assert _calendar_error(bad), bad


def test_there_are_timers_to_check() -> None:
    assert len(_timers()) >= 36


_IDS = [str(p.relative_to(_DEPLOY)) for p in _timers()]


@pytest.mark.parametrize("timer", _timers(), ids=_IDS)
def test_timer_triggers_are_valid(timer: Path) -> None:
    d = _directives(timer)
    triggers = [
        k
        for k in ("OnCalendar", "OnBootSec", "OnActiveSec", "OnUnitActiveSec", "OnUnitInactiveSec")
        if k in d
    ]
    assert triggers, f"{timer.name} has no trigger directive; it would never fire"
    for value in d.get("OnCalendar", []):
        error = _calendar_error(value)
        assert error is None, f"{timer.name}: OnCalendar={value}: {error}"
        if shutil.which("systemd-analyze"):
            res = subprocess.run(
                ["systemd-analyze", "calendar", value], capture_output=True, text=True
            )
            assert res.returncode == 0, f"{timer.name}: systemd-analyze: {res.stderr.strip()}"
    for key in ("OnBootSec", "OnActiveSec", "OnUnitActiveSec", "OnUnitInactiveSec"):
        for value in d.get(key, []):
            assert _TIMESPAN.match(value), f"{timer.name}: {key}={value}"
    for value in d.get("RandomizedDelaySec", []) + d.get("AccuracySec", []):
        assert _TIMESPAN.match(value), f"{timer.name}: bad timespan {value}"


@pytest.mark.parametrize("timer", _timers(), ids=_IDS)
def test_timer_declares_persistent_explicitly(timer: Path) -> None:
    """Holds for every OnCalendar timer: the catch-up policy is a decision.
    (Persistent= is meaningless for purely monotonic timers.)"""
    if "OnCalendar" not in _directives(timer):
        return
    vals = _directives(timer).get("Persistent", [])
    assert vals and vals[-1] in {"true", "false"}, f"{timer.name}: Persistent= missing/invalid"


@pytest.mark.parametrize("timer", _timers(), ids=_IDS)
def test_timer_has_a_service_and_unit_resolves(timer: Path) -> None:
    service = _service_for(timer)
    assert service.is_file(), f"{timer.name}: no matching {service.name}"
    unit = _directives(timer).get("Unit", [])
    if unit:
        plain = service.name.removesuffix(".template")
        names = {plain, plain.replace("dynasty-", "__SERVICE_NAME__-", 1)}
        # ffpc / curated-sharps templates ship as chase-upside-<x> and are
        # rendered by their dedicated installers to <SERVICE_NAME>-<x>.
        names.add(re.sub(r"^(dynasty|chase-upside)-", "__SERVICE_NAME__-", plain, count=1))
        assert unit[-1] in names, f"{timer.name}: Unit={unit[-1]} is not its own service {names}"


@pytest.mark.parametrize("timer", _timers(), ids=_IDS)
def test_service_execstart_targets_exist(timer: Path) -> None:
    service = _service_for(timer)
    assert service.is_file(), f"{service.name} missing"
    execs = _directives(service).get("ExecStart", [])
    assert execs, f"{service.name}: no ExecStart"
    for line in execs:
        line = line.lstrip("-@+!:")
        # Only executable targets; ``--output-dir __APP_DIR__/data/...`` style
        # arguments name runtime-created directories, not shipped files.
        for rel in re.findall(r"__APP_DIR__/(\S+\.(?:py|sh|js|mjs))\b", line):
            assert (_REPO / rel).exists(), f"{service.name}: ExecStart target {rel} missing"
        for mod in re.findall(r"-m\s+([\w.]+)", line):
            base = _REPO / mod.replace(".", "/")
            assert (
                base.with_suffix(".py").exists() or (base / "__init__.py").exists()
            ), f"{service.name}: module {mod} missing"
        unknown = set(re.findall(r"__[A-Z_]+__", line)) - _KNOWN_PLACEHOLDERS
        assert not unknown, f"{service.name}: placeholder {unknown} the installer never fills"


@pytest.mark.parametrize("timer", _timers(), ids=_IDS)
def test_oneshot_services_bound_their_runtime(timer: Path) -> None:
    service = _service_for(timer)
    if service.name in _NO_TIMEOUT_OK:
        return
    d = _directives(service)
    if d.get("Type", [""])[-1] != "oneshot":
        return
    # oneshot defaults to NO timeout: a hung job would block every later
    # firing of the timer without any failure signal.
    assert "TimeoutStartSec" in d, f"{service.name}: oneshot without TimeoutStartSec"
    assert d["TimeoutStartSec"][-1] not in {"0", "infinity"}, service.name


# ── Installer routes ─────────────────────────────────────────────────


def _installer_corpus() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in sorted(_DEPLOY.rglob("*.sh"))
    )


@pytest.mark.parametrize("timer", _timers(), ids=_IDS)
def test_timer_is_reached_by_an_install_route_or_allowlisted(timer: Path) -> None:
    corpus = _installer_corpus()
    name = timer.name
    plain = name.removesuffix(".template")
    stem = plain.removesuffix(".timer").removeprefix("dynasty-")
    reached = (
        name in corpus
        or plain in corpus
        or f'install_simple_timer "{stem}"' in corpus
        or f'reconcile_timer_units "{stem}"' in corpus
        # unit loops like ``for unit in riskit-backup.service riskit-backup.timer``
        or plain.removesuffix(".timer") + ".timer" in corpus
        or stem + ".timer" in corpus
    )
    assert (
        reached or name in _MANUAL_UNITS
    ), f"{name}: no deploy/*.sh installer route and not in _MANUAL_UNITS (with a reason)"


def test_manual_allowlist_entries_have_reasons_and_exist() -> None:
    for unit, reason in _MANUAL_UNITS.items():
        assert reason.strip(), unit
        assert any(t.name == unit for t in _timers()), f"stale allowlist entry {unit}"


def test_every_simple_timer_stem_has_unit_files() -> None:
    body = (_DEPLOY / "install-systemd-service.sh").read_text(encoding="utf-8")
    stems = re.findall(r'^\s*install_simple_timer "([\w-]+)"', body, re.M)
    assert stems
    for stem in stems:
        for kind in ("service", "timer"):
            assert (_DEPLOY / "systemd" / f"dynasty-{stem}.{kind}.template").is_file(), stem


def test_installer_template_references_name_real_files() -> None:
    body = _installer_corpus()
    for ref in set(re.findall(r"(dynasty-[\w-]+\.(?:service|timer)\.template)", body)):
        assert (_DEPLOY / "systemd" / ref).is_file(), f"installer names missing template {ref}"
