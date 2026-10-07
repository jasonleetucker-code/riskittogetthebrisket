"""A curl status probe must report curl's code OR the fallback, never both.

``code=$(curl ... --write-out '%{http_code}' URL || echo 000)`` concatenates:
when curl writes ``200`` and then fails (e.g. a timeout mid-body), the capture
becomes ``200000`` — the prod-e2e-smoke preflight reported "HTTP 200000" for a
healthy site on 2026-10-07. Assign the fallback on failure instead.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# A $( ... ) capture containing --write-out and ending in `|| echo <digits>)`.
_CONCAT = re.compile(r"\$\(\s*curl[^)]*--write-out[^)]*\|\|\s*echo\s+\d+\s*\)", re.S)


def test_no_workflow_concatenates_curl_status_with_a_fallback():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8").replace("\\n", " ")
        if _CONCAT.search(text):
            offenders.append(path.name)
    assert offenders == [], f"curl status capture concatenates a fallback: {offenders}"


def test_prod_smoke_liveness_probe_requests_compression():
    text = (WORKFLOWS / "prod-e2e-smoke.yml").read_text(encoding="utf-8")
    probe = text[text.index("/api/public/league\"") - 400 : text.index("/api/public/league\"")]
    assert "--compressed" in probe, "the ~2.5 MB liveness probe must ask for gzip"
