"""The mobile view must not be the largest of the optimized views.

``preferredDataView()`` (``frontend/lib/device-profile.js``) routes mobile
and slow-network clients to ``?view=compact`` and everyone else to
``?view=array``.  So "compact" is a promise about bytes made to exactly the
clients least able to absorb a broken one.

That promise was inverted and stayed inverted, because no test measured it.
Measured 2026-08-18 on a 1,109-row contract, gzip level 6:

    before     array 631.8 KB gz    compact 735.0 KB gz    (+16.3%)
    after      array 631.8 KB gz    compact 491.0 KB gz    (-22.3%)

The cause was that ``compact_contract`` kept the legacy ``players`` dict
*and* ``playersArray`` — parallel encodings of the same rows — while the
array view dropped the dict, which is where the weight is.

This test asserts the RELATION, never an absolute size: an absolute number
is a function of how many rows the last scrape produced, and this file has
to stay in the deterministic gate.  Built from the tracked export archive
via the shared fixture, so it is reproducible and skips rather than passing
vacuously.
"""

from __future__ import annotations

import gzip
import json

import pytest

from src.api.compact_view import compact_contract
from src.api.data_contract import build_api_data_contract
from tests.archive_fixtures import newest_complete_raw_payload

_cache: dict | None = None


def _contract() -> dict:
    global _cache
    if _cache is None:
        raw, _archive = newest_complete_raw_payload()
        if raw is None:
            pytest.skip("no complete archived scrape to build a contract from")
        _cache = build_api_data_contract(raw)
    return _cache


def _wire_bytes(payload: dict) -> int:
    """Serialize and gzip exactly as ``server.py`` prepares a view."""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return len(gzip.compress(raw, compresslevel=6))


def _array_view(contract: dict) -> dict:
    payload = dict(contract)
    payload.pop("players", None)
    payload["payloadView"] = "array"
    return payload


def test_compact_is_smaller_over_the_wire_than_array():
    contract = _contract()
    array_gz = _wire_bytes(_array_view(contract))
    compact_gz = _wire_bytes(compact_contract(contract))
    assert compact_gz < array_gz, (
        f"the mobile 'compact' view is {compact_gz / 1024:.1f} KB gzipped against "
        f"array's {array_gz / 1024:.1f} KB — mobile and slow-network clients are "
        f"being sent MORE than desktop ({(compact_gz - array_gz) / array_gz:+.1%})."
    )


def test_compact_is_smaller_than_the_full_view():
    """The weaker claim, kept separately.

    If the strong assertion above ever has to be relaxed, this one must
    still hold, and a relaxation that breaks it too should say so out loud.
    """
    contract = _contract()
    assert _wire_bytes(compact_contract(contract)) < _wire_bytes(contract)


def test_compact_carries_the_array_encoding_and_not_the_dict():
    """The mechanism behind the sizes above, asserted on a real board.

    ``tests/api/test_compact_view`` pins this on a fixture; here it is
    checked against the shape the pipeline actually produces, so a change
    upstream that stops emitting ``playersArray`` cannot silently restore
    the duplicate encoding.
    """
    compact = compact_contract(_contract())
    assert isinstance(compact.get("playersArray"), list)
    assert compact["playersArray"], "compact emitted an empty playersArray"
    assert "players" not in compact
