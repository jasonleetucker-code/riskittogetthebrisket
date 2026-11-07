"""Master-site-audit W26-F003 regression (CW-40 P1 re-adjudication, 2026-11-06) -- PARTIAL.

Claim: /draft downloaded the full /api/data contract (11.95 MB) to read 46.8 KB of team
names, from three call sites, two with ``cache: "no-store"``.

Closed by #2079 and pinned here (offline): every /draft read of ``/api/data`` goes through
``draftContractUrl`` (``view=compact``); no bare ``/api/data`` fetch remains; the compact
view is well under the full contract's size on the pinned tracked archive board.

Still open: the mount-time read needs only ``sleeper.teams`` but still pulls the whole
compact view (measured ~39% of the full contract, not ~0.4%), and two of the three call
sites still pass ``cache: "no-store"``, defeating the HTTP cache/ETag path.  The strict xfail
states the repaired shape (no no-store contract read); it flips when that lands.
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "frontend" / "app" / "draft" / "page.jsx"
ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20261106_194518.zip"


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_no_draft_read_of_api_data_bypasses_the_compact_view_url():
    src = _page()
    assert "draftContractUrl" in src
    # No literal /api/data (or /api/dynasty-data) fetch target in the page.
    assert not re.search(r"fetch\(\s*[`\"']/api/(data|dynasty-data)", src)
    assert not re.search(r"[`\"']/api/data\?(?!view=compact)", src)


def test_compact_view_is_a_fraction_of_the_full_contract():
    if not ARCHIVE.is_file():
        pytest.skip("pinned archive bundle absent")
    from src.api.compact_view import compact_contract
    from src.api.data_contract import build_api_data_contract

    with zipfile.ZipFile(ARCHIVE) as zf:
        name = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        raw = json.loads(zf.read(name))
    full = build_api_data_contract(raw)
    full_bytes = len(json.dumps(full))
    compact_bytes = len(json.dumps(compact_contract(full)))
    assert compact_bytes < 0.5 * full_bytes  # measured 0.39 on this board


def _no_store_contract_reads(src: str) -> int:
    count = 0
    for m in re.finditer(r"draftContractUrl\([^)]*\)", src):
        # the fetch that consumes it follows within a short comment block
        window = src[m.end() : m.end() + 1000]
        fetch = re.search(r"fetch\(\s*url\s*,\s*\{([^}]*)\}", window)
        if fetch and "no-store" in fetch.group(1):
            count += 1
    return count


@pytest.mark.xfail(
    strict=True,
    reason="W26-F003 PARTIAL: two /draft contract reads still use cache: no-store",
)
def test_draft_contract_reads_use_the_http_cache():
    assert _no_store_contract_reads(_page()) == 0
