"""The live site template must never bind :443 on the wildcard address.

Incident 2026-10-01 (docs/ops/INCIDENT_2026-10-01_NGINX_TAILSCALE_443.md):
Tailscale Serve holds :443 on the box's tailnet address, so a wildcard
``listen 443`` / ``listen [::]:443`` cannot bind once tailscaled wins a restart
race.  An unattended OpenSSL upgrade restarted both; nginx stayed down 9.6 h.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIVE_TEMPLATE = ROOT / "deploy" / "nginx" / "chaseupside.com.conf"
LISTEN = re.compile(r"^\s*listen\s+([^;\s]+)", re.MULTILINE)
WILDCARD_443 = {"443", "[::]:443", "0.0.0.0:443", "*:443"}


def _listens(text: str) -> list[str]:
    return [m.group(1) for m in LISTEN.finditer(text)]


def test_no_wildcard_443_listener_in_the_live_site_template():
    listens = _listens(LIVE_TEMPLATE.read_text(encoding="utf-8"))
    targets = [t for t in listens if t == "443" or t.endswith(":443")]
    assert targets, "template must still serve :443"
    for target in targets:
        assert target not in WILDCARD_443, target
        assert "__PUBLIC_IPV4__" in target or "__PUBLIC_IPV6__" in target, target


def test_runbook_renders_the_placeholders_before_installing():
    runbook = (ROOT / "docs" / "runbooks" / "domain-cutover-chaseupside.md").read_text(
        encoding="utf-8"
    )
    assert "s/__PUBLIC_IPV4__/" in runbook
    assert '! grep -n "__PUBLIC_IPV" /tmp/chaseupside.com.conf' in runbook
