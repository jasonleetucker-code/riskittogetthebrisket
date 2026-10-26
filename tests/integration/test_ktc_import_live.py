"""Live KTC import check — the one test that talks to keeptradecut.com.

ADVISORY TIER (``livedata`` in ``tests/conftest.py``): a KTC page change is
external source health, and a provider alone must not be able to turn every
PR red (CLAUDE.md "CI has two lanes").  The hard-gate coverage of the same
path is ``tests/trade/test_ktc_import_player_map.py``, which runs the real
embed forms from captured fixtures.

What this module must NOT do is what its predecessor did: it skipped on ANY
exception as "KTC upstream unreachable", so the 2026-10-13 layout change —
KTC moving the player map into ``<script id="ktc-players">`` — read as a
skip for as long as it lasted.  Only genuine unreachability skips now; a
layout change or id conflict FAILS.
"""

from __future__ import annotations

import pytest

from src.canonical import normalization_validator as nv
from src.trade import ktc_import

# The specific URL from the user's original bug report — one pick,
# three players, across two sides.
_BUG_URL = (
    "https://keeptradecut.com/trade-calculator"
    "?var=5&pickVal=0&teamOne=1934|1273|1712&teamTwo=1415"
    "&format=2&isStartup=0&tep=1"
)


def _resolve_live():
    try:
        return ktc_import.resolve_trade_url(_BUG_URL)
    except ktc_import.KtcUnreachable as exc:  # includes an open breaker
        pytest.skip(f"KTC upstream unreachable: {exc}")


def test_ktc_backend_returns_pick_with_valid_canonical_name():
    """Invariant 1: backend's resolve_trade_url returns
    '2027 Mid 4th' (or similar canonical pick name) for KTC ID 1712."""
    result = _resolve_live()
    pick_entries = [e for e in (result["sideOne"] + result["sideTwo"]) if e.get("isPick")]
    assert pick_entries, "Backend dropped the pick from the KTC URL"
    for pe in pick_entries:
        name = pe["name"]
        assert nv.is_valid_pick_name(name), (
            f"KTC pick name {name!r} doesn't match any canonical "
            f"pick shape — will never resolve in rowByName.get()"
        )


def test_ktc_backend_returns_all_four_assets():
    """The URL has 4 assets (3 players + 1 pick).  None should be
    silently dropped, and the map must come from KTC's full id index."""
    result = _resolve_live()
    total = len(result["sideOne"]) + len(result["sideTwo"])
    unresolved = len(result["unresolved"]["sideOne"]) + len(result["unresolved"]["sideTwo"])
    assert total + unresolved == 4, (
        f"KTC parsed 4 IDs but returned {total} resolved + "
        f"{unresolved} unresolved — something went missing"
    )
    assert result["playerMap"]["index"] == "trade_database_search_index", result["playerMap"]
