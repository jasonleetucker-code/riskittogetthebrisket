"""A curl status capture must report curl's code OR the fallback, never both.

``code=$(curl ... -w '%{http_code}' URL || echo 000)`` concatenates: when curl
writes ``200`` and then fails (e.g. a timeout mid-body) the capture becomes
``200000``. The prod-e2e-smoke preflight reported "HTTP 200000" for a healthy
site on 2026-10-07, and the identical pattern sat in 13 more places across the
workflows and the deploy scripts. Assign the fallback on failure instead:
``code=$(curl ...) || code=000``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCANNED = sorted((REPO / ".github" / "workflows").glob("*.yml")) + sorted(
    (REPO / "deploy").glob("*.sh")
)

# A $( ... ) capture running curl with -w / --write-out whose fallback
# `|| echo <digits>` (quoted or not) sits INSIDE the substitution.
_CONCAT = re.compile(
    r"\$\(\s*curl\b[^)]*?(?:-w\b|--write-out)[^)]*?\|\|\s*echo\s+\"?\d+\"?\s*\)",
    re.S,
)
_PUBLIC_LEAGUE_CAPTURE = re.compile(r"\$\(\s*curl\b[^)]*?/api/public/league\"\)", re.S)


def _joined(path: Path) -> str:
    """File text with CRLF normalized and backslash line continuations joined."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\\\n", " ")


def test_the_scan_covers_workflows_and_deploy_scripts():
    names = {p.name for p in SCANNED}
    assert {
        "deploy.yml",
        "health-check.yml",
        "deploy.sh",
        "rollback.sh",
        "verify-deploy.sh",
    } <= names


def test_the_pattern_catches_both_spellings_and_spares_the_fix():
    assert _CONCAT.search("code=$(curl -s -o /dev/null -w '%{http_code}' http://x || echo 000)")
    assert _CONCAT.search('c="$(curl --silent --write-out \'%{http_code}\' "$u" || echo "000")"')
    assert not _CONCAT.search('c="$(curl --silent --write-out \'%{http_code}\' "$u")" || c=000')


def test_no_curl_status_capture_concatenates_a_fallback():
    offenders = [p.relative_to(REPO).as_posix() for p in SCANNED if _CONCAT.search(_joined(p))]
    assert offenders == [], f"curl status capture concatenates a fallback: {offenders}"


def test_large_public_league_probes_request_compression():
    """The ~2.5 MB /api/public/league snapshot is probed by the smoke preflight
    and by the deploy's blocking warm-up; both must ask for gzip."""
    for name in ("prod-e2e-smoke.yml", "deploy.yml"):
        captures = _PUBLIC_LEAGUE_CAPTURE.findall(_joined(REPO / ".github" / "workflows" / name))
        assert captures, f"precondition: {name} probes /api/public/league"
        for capture in captures:
            assert "--compressed" in capture, f"{name}: {capture[:120]}"
