"""Both app processes bind LOOPBACK by default (owner directive 2026-11-01, P0).

Before this, uvicorn bound ``0.0.0.0:8000`` (``server.HOST``) and Next bound
``*:3000`` (``next start``'s default), so both raw app ports answered from the
internet, bypassing nginx.  nginx is the only legitimate client and it proxies
to ``127.0.0.1`` for both, so loopback loses nothing.

What this pins:

* the backend default is loopback, the env override works, and a blank
  override does NOT fall through to "all interfaces";
* ``uvicorn.run`` actually receives that value;
* the frontend's ``npm start`` binds 127.0.0.1 — and the systemd unit still
  runs ``npm start``, because that unit is installed only when missing, so
  package.json is the only place a bind change ships with a deploy;
* every on-box consumer (nginx upstreams, deploy / rollback / verify /
  healthcheck probes) and the E2E readiness probes address IPv4 loopback,
  which a 127.0.0.1 bind serves.  ``localhost`` / ``::1`` would not be
  guaranteed to.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import server

REPO = Path(__file__).resolve().parents[2]


def test_backend_default_bind_host_is_loopback():
    assert server.DEFAULT_BIND_HOST == "127.0.0.1"
    assert server._resolve_bind_host({}) == "127.0.0.1"


def test_backend_bind_host_env_override():
    assert server._resolve_bind_host({"RISKIT_BIND_HOST": "0.0.0.0"}) == "0.0.0.0"
    assert server._resolve_bind_host({"RISKIT_BIND_HOST": " 10.1.2.3 "}) == "10.1.2.3"


def test_blank_override_is_loopback_not_all_interfaces():
    for blank in ("", "   ", "\t"):
        assert server._resolve_bind_host({"RISKIT_BIND_HOST": blank}) == "127.0.0.1"


def test_module_host_follows_the_resolver():
    # The import-time value is whatever the test environment says; nobody
    # sets the variable in CI, so it must be loopback there.
    import os

    assert server.HOST == server._resolve_bind_host(os.environ)


def test_server_source_has_no_wildcard_bind_literal():
    src = (REPO / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "HOST" in names:
                assert not (isinstance(node.value, ast.Constant) and node.value.value == "0.0.0.0")


def test_uvicorn_run_binds_HOST():
    tree = ast.parse((REPO / "server.py").read_text(encoding="utf-8"))
    hosts = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "uvicorn"
        ):
            for kw in node.keywords:
                if kw.arg == "host":
                    hosts.append(kw.value)
    assert hosts, "uvicorn.run(host=...) not found in server.py"
    assert all(isinstance(h, ast.Name) and h.id == "HOST" for h in hosts)


def test_frontend_npm_start_binds_loopback():
    pkg = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    start = pkg["scripts"]["start"]
    assert re.search(r"(^|\s)(-H|--hostname)\s+127\.0\.0\.1(\s|$)", start), start
    assert "0.0.0.0" not in start


def test_frontend_unit_still_runs_npm_start():
    unit = (REPO / "deploy" / "systemd" / "dynasty-frontend.service.template").read_text(
        encoding="utf-8"
    )
    exec_lines = [ln for ln in unit.splitlines() if ln.startswith("ExecStart=")]
    assert exec_lines == ["ExecStart=__NPM_BIN__ start"]


def test_nginx_upstreams_are_ipv4_loopback():
    conf = (REPO / "deploy" / "nginx" / "chaseupside.com.conf").read_text(encoding="utf-8")
    for name, port in (("dynasty_backend", 8000), ("dynasty_frontend", 3000)):
        m = re.search(rf"upstream\s+{name}\s*\{{([^}}]*)\}}", conf)
        assert m, name
        assert re.search(rf"server\s+127\.0\.0\.1:{port}\s*;", m.group(1)), m.group(1)


def test_on_box_probes_default_to_ipv4_loopback():
    for rel in ("deploy/deploy.sh", "deploy/rollback.sh", "deploy/verify-deploy.sh"):
        body = (REPO / rel).read_text(encoding="utf-8")
        assert 'APP_HOST="${APP_HOST:-127.0.0.1}"' in body, rel
        assert 'FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"' in body, rel
    hc = (REPO / "deploy" / "systemd" / "dynasty-healthcheck.sh").read_text(encoding="utf-8")
    assert 'HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"' in hc
    wf = (REPO / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "APP_HOST: ${{ vars.PROD_APP_HOST || '127.0.0.1' }}" in wf


def test_e2e_readiness_probes_use_ipv4_loopback():
    cfg = (REPO / "tests" / "e2e" / "playwright.config.js").read_text(encoding="utf-8")
    assert 'url: "http://127.0.0.1:8000/api/status"' in cfg
    assert 'url: "http://127.0.0.1:3000"' in cfg
    wf = (REPO / ".github" / "workflows" / "e2e.yml").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8000/api/status" in wf
    assert "http://127.0.0.1:3000/login" in wf
