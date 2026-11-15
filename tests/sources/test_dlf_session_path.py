"""The DLF session resolver matches what the fetch timer's script does.

``/api/health`` reported ``dlf_session.json`` as 96.6 days old (2026-10-26)
while the DLF fetch timer had refreshed its jar that day: health read the
bootstrap seed under the app directory, the timer keeps the live jar in
``/var/lib/dlf-fetch``.  ``src/sources/dlf_session.py`` is the one place that
knows where the jar lives; these tests pin that it resolves exactly like
``deploy/dlf_fetch_and_push.sh`` (the source of truth) and cannot drift from it.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.sources import dlf_session

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "dlf_fetch_and_push.sh"
SERVICE_TEMPLATE = REPO / "deploy" / "systemd" / "dynasty-dlf-fetch.service.template"


# ── the resolver ─────────────────────────────────────────────────────────


def test_default_is_the_timers_work_dir():
    assert dlf_session.dlf_fetch_work_dir({}) == Path("/var/lib/dlf-fetch")
    assert dlf_session.dlf_session_path({}) == Path("/var/lib/dlf-fetch/dlf_session.json")


def test_env_var_overrides_the_work_dir(tmp_path):
    env = {dlf_session.DLF_FETCH_WORK_DIR_ENV: str(tmp_path)}
    assert dlf_session.dlf_fetch_work_dir(env) == tmp_path
    assert dlf_session.dlf_session_path(env) == tmp_path / "dlf_session.json"


def test_empty_env_var_falls_back_like_bash_default_expansion():
    """``${DLF_FETCH_WORK_DIR:-default}`` treats an EMPTY value as unset.
    ``DLF_FETCH_WORK_DIR=`` in an EnvironmentFile must not resolve to ``.``."""
    env = {dlf_session.DLF_FETCH_WORK_DIR_ENV: ""}
    assert dlf_session.dlf_session_path(env) == Path("/var/lib/dlf-fetch/dlf_session.json")


def test_reads_os_environ_at_call_time_when_no_env_given(monkeypatch, tmp_path):
    monkeypatch.setenv(dlf_session.DLF_FETCH_WORK_DIR_ENV, str(tmp_path))
    assert dlf_session.dlf_session_path() == tmp_path / "dlf_session.json"
    monkeypatch.delenv(dlf_session.DLF_FETCH_WORK_DIR_ENV)
    assert dlf_session.dlf_session_path() == Path("/var/lib/dlf-fetch/dlf_session.json")


def test_health_path_routes_dlf_through_the_resolver_and_leaves_others_alone(tmp_path):
    work = tmp_path / "work"
    app = tmp_path / "app"
    env = {dlf_session.DLF_FETCH_WORK_DIR_ENV: str(work)}
    # DLF: the timer's jar, never the app-dir seed.
    assert (
        dlf_session.health_session_path("dlf_session.json", app, env) == work / "dlf_session.json"
    )
    # Everything else: unchanged -- still resolved against the app dir.
    for name in ("draftsharks_session.json", "idpshow_session.json"):
        assert dlf_session.health_session_path(name, app, env) == app / name


# ── parity with the shell script (the source of truth) ───────────────────


def test_constants_match_the_fetch_script():
    text = SCRIPT.read_text(encoding="utf-8")

    work_dir = re.search(
        r'^WORK_DIR="\$\{(?P<var>[A-Z0-9_]+):-(?P<default>[^}]+)\}"\s*$', text, re.MULTILINE
    )
    assert work_dir, "deploy/dlf_fetch_and_push.sh no longer defines WORK_DIR as ${VAR:-default}"
    assert work_dir["var"] == dlf_session.DLF_FETCH_WORK_DIR_ENV
    assert work_dir["default"] == dlf_session.DLF_FETCH_DEFAULT_WORK_DIR

    session_file = re.search(
        r'^SESSION_FILE="\$\{WORK_DIR\}/(?P<name>[^"]+)"\s*$', text, re.MULTILINE
    )
    assert (
        session_file
    ), "deploy/dlf_fetch_and_push.sh no longer keeps its jar at ${WORK_DIR}/<name>"
    assert session_file["name"] == dlf_session.DLF_SESSION_FILENAME


def test_systemd_unit_working_directory_is_the_default_work_dir():
    """The unit's ``WorkingDirectory`` is the same directory the script
    defaults to; if one moves, the other must be moved with it."""
    text = SERVICE_TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"^WorkingDirectory=(?P<dir>\S+)\s*$", text, re.MULTILINE)
    assert match, "dynasty-dlf-fetch.service.template has no WorkingDirectory="
    assert match["dir"] == dlf_session.DLF_FETCH_DEFAULT_WORK_DIR
