"""The Next.js Image Optimization endpoint is refused at the nginx edge.

The app uses no ``next/image`` and ``frontend/next.config.mjs`` sets
``images.unoptimized: true`` (pinned by
``frontend/__tests__/next-image-optimizer-disabled.test.js``), so Next itself
answers 404.  ``deploy/nginx/chaseupside-proxy.conf`` blocks ``/_next/image``
as well, so a future Next default or config slip cannot silently re-expose the
optimizer's server-side fetch/decode surface (GHSA-2464-fhr4-w9xw).

nginx is not installed in CI, so these are narrow text-structural checks, in
the same posture as ``tests/api/test_nginx_bare_ip_block.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNIPPET = ROOT / "deploy" / "nginx" / "chaseupside-proxy.conf"
NEXT_CONFIG = ROOT / "frontend" / "next.config.mjs"

BLOCK = re.compile(r"^location\s+\^~\s+/_next/image\s*\{(?P<body>[^}]*)\}", re.MULTILINE)


def _uncommented(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _image_block_body() -> str:
    matches = list(BLOCK.finditer(_uncommented(SNIPPET.read_text(encoding="utf-8"))))
    assert len(matches) == 1, "expected exactly one `location ^~ /_next/image` block"
    return matches[0].group("body")


def test_optimizer_path_returns_404_at_the_edge():
    body = _image_block_body()
    assert re.search(r"^\s*return\s+404\s*;", body, re.MULTILINE), body


def test_optimizer_path_is_never_proxied_to_next():
    assert "proxy_pass" not in _image_block_body()


def test_block_is_a_prefix_match_not_exact():
    """``=`` would miss ``/_next/image/``, which Next routes to the same
    handler after stripping the trailing slash."""
    text = _uncommented(SNIPPET.read_text(encoding="utf-8"))
    assert not re.search(r"location\s+=\s+/_next/image\b", text)


def test_no_add_header_in_the_block():
    """A location-level add_header drops every server-level security header
    for that location (see the snippet's header comment)."""
    assert "add_header" not in _image_block_body()


def test_next_config_still_disables_the_optimizer():
    """The two layers must move together: with the nginx block present and
    ``unoptimized`` removed, every optimized ``<Image>`` would 404."""
    assert re.search(r"unoptimized\s*:\s*true", NEXT_CONFIG.read_text(encoding="utf-8"))
