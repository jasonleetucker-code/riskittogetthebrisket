"""Structural guards on the bare-IP :80 server block.

Collaborative audit, finding S-2.  ``deploy/nginx/chaseupside.com.conf``
block 3 answers on the production IP over plain HTTP.  It used to
``include`` the full proxy snippet, which served the entire application —
including ``POST /api/auth/login`` — in cleartext.

nginx is not installed in CI, so ``nginx -t`` is not available to us.
These are text-structural checks rather than a real parse.  They are
narrow on purpose: each one pins a specific way the block has been, or
could plausibly be, wrong.  A checker that tried to be a general nginx
parser would be a second implementation to get wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

CONF = Path(__file__).resolve().parents[2] / "deploy" / "nginx" / "chaseupside.com.conf"

BARE_IP = "169.58.50.224"


def _bare_ip_block() -> str:
    """Return the source of the ``server`` block whose server_name is the IP.

    Brace-counts forward from the ``server_name <ip>;`` line back to the
    opening ``server {`` so the slice is the whole block and nothing else.
    """
    text = CONF.read_text(encoding="utf-8")
    marker = re.search(rf"^\s*server_name\s+{re.escape(BARE_IP)}\s*;", text, re.M)
    assert marker is not None, f"no server block with server_name {BARE_IP}"

    start = text.rindex("server {", 0, marker.start())
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    pytest.fail("unbalanced braces in the bare-IP server block")


def _uncommented(block: str) -> str:
    return "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


class TestBareIpBlockDoesNotServeTheApp:
    """The regression this file exists for."""

    def test_does_not_include_the_full_proxy_snippet(self):
        """Including the snippet serves every route, login included, over
        plain HTTP.  That is the pre-fix state."""
        body = _uncommented(_bare_ip_block())
        assert "chaseupside-proxy.conf" not in body, (
            "the bare-IP :80 block includes the full proxy snippet again — that "
            "serves POST /api/auth/login and every page in cleartext on the IP"
        )

    def test_redirects_everything_not_explicitly_allowed(self):
        body = _uncommented(_bare_ip_block())
        assert re.search(r"location\s+/\s*\{\s*return\s+301", body), (
            "the bare-IP block has no catch-all 301; paths other than the "
            "allow-listed ones would fall through"
        )

    def test_only_health_and_acme_answer_over_plain_http(self):
        """Any additional proxied location is a new cleartext surface."""
        body = _uncommented(_bare_ip_block())
        locations = set(re.findall(r"location\s+(\S+(?:\s+\S+)??)\s*\{", body))
        allowed = {"= /api/health", "^~ /.well-known/acme-challenge/", "/"}
        assert locations <= allowed, (
            f"unexpected plain-HTTP location(s) on the bare IP: {locations - allowed}. "
            "Every location here answers without TLS."
        )


class TestRedirectTargetIsValidatable:
    def test_redirect_does_not_use_host_variable(self):
        """``$host`` is the IP in this block, so ``https://$host`` sends
        clients to ``https://169.58.50.224`` — which no chaseupside.com
        certificate can validate.  It must be the literal domain."""
        body = _uncommented(_bare_ip_block())
        redirects = re.findall(r"return\s+301\s+(\S+)\s*;", body)
        assert redirects, "no 301 target found"
        for target in redirects:
            assert "$host" not in target, (
                f"bare-IP redirect target {target!r} uses $host, which resolves to "
                f"the IP — TLS would fail for every redirected client"
            )
            assert target.startswith("https://chaseupside.com"), (
                f"bare-IP redirect target {target!r} should point at the canonical " "HTTPS origin"
            )


class TestHealthEndpointStaysReachable:
    def test_health_is_an_exact_match_location(self):
        """A prefix ``location /api/health`` would also match
        ``/api/health-secrets``; more importantly an exact match is what
        beats the catch-all ``location /`` redirect in nginx's ordering."""
        body = _uncommented(_bare_ip_block())
        assert re.search(r"location\s+=\s+/api/health\s*\{", body), (
            "/api/health must be an exact-match location or the catch-all "
            "redirect will swallow it and any external monitor will break"
        )

    def test_health_proxies_to_a_declared_upstream(self):
        block = _bare_ip_block()
        upstream = re.search(r"proxy_pass\s+http://(\w+)\s*;", _uncommented(block))
        assert upstream is not None, "/api/health does not proxy anywhere"
        name = upstream.group(1)
        text = CONF.read_text(encoding="utf-8")
        assert re.search(
            rf"^upstream\s+{name}\s*\{{", text, re.M
        ), f"proxy_pass targets upstream {name!r}, which this file does not declare"
