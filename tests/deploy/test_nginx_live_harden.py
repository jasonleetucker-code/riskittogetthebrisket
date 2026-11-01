"""``deploy/nginx_live_harden.sh`` patches the LIVE nginx site in place.

The live site is certbot-managed and pins its :443 listeners to specific
addresses (Tailscale Serve holds :443 on the tailnet address), so the repo
template cannot be installed over it.  These tests pin the patcher's
contract on a fixture that mirrors the live structure (documentation-range
addresses only): it adds exactly one ``include`` per chaseupside server
block, changes no listener / certificate / location line, is idempotent,
refuses configs where server-level headers would be masked or duplicated,
and restores the previous file when ``nginx -t`` fails.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "nginx_live_harden.sh"
_SNIPPET = _REPO / "deploy" / "nginx" / "snippets" / "chaseupside-security-headers.conf"
_FIXTURE = Path(__file__).parent / "fixtures" / "nginx_live_dynasty_site.conf"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _run(tmp_path: Path, *args: str, live: Path | None = None, **env: str):
    live = live or tmp_path / "dynasty"
    if not live.exists():
        live.write_bytes(_FIXTURE.read_bytes())
    full_env = {
        "PATH": __import__("os").environ["PATH"],
        "LIVE_SITE": live.as_posix(),
        "SNIPPET_DEST": (tmp_path / "snippets" / "chaseupside-security-headers.conf").as_posix(),
        "SNIPPET_SRC": _SNIPPET.as_posix(),
        "SKIP_PROBE": "1",
        "ALLOW_NON_ROOT_APPLY": "1",
        **env,
    }
    (tmp_path / "snippets").mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", _SCRIPT.as_posix(), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        check=False,
    )


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _fake_bin(tmp_path: Path, name: str, rc: int) -> str:
    p = tmp_path / name
    p.write_text(f"#!/usr/bin/env bash\nexit {rc}\n", encoding="utf-8")
    p.chmod(0o755)
    return p.as_posix()


def test_dry_run_changes_nothing_and_prints_the_sha(tmp_path):
    live = tmp_path / "dynasty"
    live.write_bytes(_FIXTURE.read_bytes())
    before = _sha(live)
    r = _run(tmp_path, live=live)
    assert r.returncode == 0, r.stderr
    assert _sha(live) == before
    assert before in r.stdout
    assert "lines to insert: 2" in r.stdout
    assert not (tmp_path / "snippets" / "chaseupside-security-headers.conf").exists()


def test_apply_adds_exactly_one_include_per_chaseupside_block(tmp_path):
    live = tmp_path / "dynasty"
    live.write_bytes(_FIXTURE.read_bytes())
    original = live.read_text(encoding="utf-8").splitlines()
    ok = _fake_bin(tmp_path, "nginx", 0)
    r = _run(
        tmp_path,
        "--apply",
        "--expect-sha256",
        _sha(live),
        live=live,
        NGINX_BIN=ok,
        SYSTEMCTL_BIN=ok,
    )
    assert r.returncode == 0, r.stderr
    patched = live.read_text(encoding="utf-8").splitlines()
    added = [ln for ln in patched if "chaseupside-security-headers.conf" in ln]
    assert len(added) == 2
    # Every original line survives, in order, byte-for-byte.
    assert [ln for ln in patched if ln not in added] == original
    for needle in (
        "listen 203.0.113.10:443 ssl;",
        "listen [2001:db8::10]:443 ssl;",
        "ssl_certificate ",
    ):
        assert sum(needle in ln for ln in patched) == sum(needle in ln for ln in original)
    assert (tmp_path / "snippets" / "chaseupside-security-headers.conf").exists()


def test_rerun_is_idempotent(tmp_path):
    live = tmp_path / "dynasty"
    live.write_bytes(_FIXTURE.read_bytes())
    ok = _fake_bin(tmp_path, "nginx", 0)
    _run(
        tmp_path,
        "--apply",
        "--expect-sha256",
        _sha(live),
        live=live,
        NGINX_BIN=ok,
        SYSTEMCTL_BIN=ok,
    )
    once = live.read_bytes()
    r = _run(tmp_path, live=live)
    assert r.returncode == 0, r.stderr
    assert "include already present" in r.stdout
    assert live.read_bytes() == once


def test_apply_refuses_without_the_reviewed_sha(tmp_path):
    live = tmp_path / "dynasty"
    live.write_bytes(_FIXTURE.read_bytes())
    r = _run(tmp_path, "--apply", "--expect-sha256", "0" * 64, live=live)
    assert r.returncode != 0
    assert live.read_bytes() == _FIXTURE.read_bytes()


def test_failed_nginx_t_restores_the_previous_file(tmp_path):
    live = tmp_path / "dynasty"
    live.write_bytes(_FIXTURE.read_bytes())
    r = _run(
        tmp_path,
        "--apply",
        "--expect-sha256",
        _sha(live),
        live=live,
        NGINX_BIN=_fake_bin(tmp_path, "nginx", 1),
        SYSTEMCTL_BIN=_fake_bin(tmp_path, "systemctl", 0),
    )
    assert r.returncode != 0
    assert live.read_bytes() == _FIXTURE.read_bytes()
    assert not (tmp_path / "snippets" / "chaseupside-security-headers.conf").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        # a location-level add_header would silently mask the server-level ones
        ("location /_next/ {\n", "location /_next/ {\n        add_header Cache-Control public;\n"),
        # a server-level duplicate of a header the snippet adds
        (
            "    client_max_body_size 10m;\n",
            "    client_max_body_size 10m;\n    add_header X-Frame-Options DENY;\n",
        ),
    ],
)
def test_refuses_configs_it_cannot_reason_about(tmp_path, mutation):
    live = tmp_path / "dynasty"
    live.write_text(_FIXTURE.read_text(encoding="utf-8").replace(*mutation, 1), encoding="utf-8")
    before = live.read_bytes()
    r = _run(tmp_path, live=live)
    assert r.returncode != 0
    assert live.read_bytes() == before


def test_snippet_matches_the_declared_template_headers():
    template = (_REPO / "deploy" / "nginx" / "chaseupside.com.conf").read_text(encoding="utf-8")
    snippet = _SNIPPET.read_text(encoding="utf-8")
    declared = [
        ln.strip()
        for ln in template.splitlines()
        if ln.strip().startswith("add_header") and "Report-Only" not in ln
    ]
    for line in set(declared):
        assert line in snippet, f"snippet is missing a header the template declares: {line}"
