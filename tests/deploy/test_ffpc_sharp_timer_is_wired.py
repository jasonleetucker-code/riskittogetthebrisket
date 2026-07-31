"""The optional FFPC collector must remain isolated, public-only, and scheduled."""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO / "deploy" / "install-ffpc-sharp-service.sh"
_SERVICE = _REPO / "deploy" / "ffpc-systemd" / "chase-upside-ffpc-sharp.service.template"
_TIMER = _REPO / "deploy" / "ffpc-systemd" / "chase-upside-ffpc-sharp.timer.template"
_SCRIPT = _REPO / "scripts" / "crawl_ffpc_sharp.py"
_CONFIG = _REPO / "config" / "sharp" / "ffpc_sources.json"


def test_all_ffpc_scheduler_artifacts_exist():
    for path in (_INSTALLER, _SERVICE, _TIMER, _SCRIPT, _CONFIG):
        assert path.is_file(), path


def test_service_is_read_only_public_collector():
    body = _SERVICE.read_text(encoding="utf-8")
    assert "scripts/crawl_ffpc_sharp.py --public-only" in body
    assert "ExecStart=" in body
    assert "Nice=10" in body


def test_timer_is_catch_up_safe_and_names_only_ffpc_service():
    body = _TIMER.read_text(encoding="utf-8")
    directives = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith("#")
    )
    assert "Persistent=true" in directives
    assert "Unit=__SERVICE_NAME__-ffpc-sharp.service" in directives
    assert "Requires=" not in directives.split("[Timer]", 1)[0]


def test_installer_refuses_disabled_or_authenticated_configuration():
    body = _INSTALLER.read_text(encoding="utf-8")
    assert '"enabled"' in body
    assert '"public_only"' in body
    assert '"authenticatedApi"' in body
    assert "daemon-reload" in body
    assert 'enable --now "${SERVICE_NAME}-ffpc-sharp.timer"' in body
