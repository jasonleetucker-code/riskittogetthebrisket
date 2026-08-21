"""A blocking ceiling on the payload production actually serves (V1-79).

WHY THIS EXISTS
────────────────
Before this file, the only gate that looked like a production payload
budget was ``tests/api/test_launch_readiness.py::test_gzipped_payload_under_2mb``,
and neither half of that name was true:

* It is not blocking. ``test_launch_readiness.py`` sits in
  ``tests/conftest.py::_LIVEDATA_MODULES`` — the whole module, including
  this test, runs in the ``-m livedata`` step of
  ``.github/workflows/pr-validation.yml``, which is
  ``continue-on-error: true``. A PR can merge with it red.
* It does not measure a production payload. It calls
  ``json.dumps(contract)`` with **default separators** and
  ``gzip.compress`` at **default level 9** on the **full** contract —
  a shape ``server.py`` never sends. Production always serializes with
  ``separators=(",", ":")`` and compresses at ``compresslevel=5``
  (``server.py`` — the ``full_gzip``/``runtime_gzip``/``array_gzip``/
  ``compact_gzip`` precompute block), and the full view (``players`` +
  ``playersArray`` both present) is not one of the views any client
  requests: the frontend's default fetch is ``?view=app`` (→
  ``runtime_payload``, ``playersArray`` dropped) and desktop callers use
  ``?view=array`` (``players`` dropped) — see
  ``frontend/lib/device-profile.js::preferredDataView``.

``test_compact_view_byte_budget.py`` fixed a real inversion (compact was
briefly *larger* than array) with a RELATIVE assertion between two views.
That is the right shape for "did we accidentally duplicate encodings",
but it asserts no ceiling at all: a bug that doubled bytes in every view
equally would leave every relative assertion in that file green.

This file is the ceiling those two gaps leave open. It measures the two
views real clients receive, with the exact serialization ``server.py``
uses, against a budget expressed as bytes-per-row rather than an
absolute byte count — a hardcoded constant would either be so tight that
routine per-source coverage growth trips it for no code reason, or so
loose it stops meaning anything. Bytes-per-row is comparatively stable
run to run (it is the shape of one row's JSON, not how many rows a
scrape happened to return) and heavy headroom (60%) still catches the
failure mode this test exists for: an accidental duplicate encoding or
an unbounded per-row field roughly doubles bytes/row, not nudges it.

Measured 2026-08-20 (archive ``dynasty_export_20260820_230504.zip``,
1,111 rows, gzip level 5 — matching ``server.py`` exactly):

    view=app (runtime)   592.3 KB gz   545.95 bytes/row
    view=array           722.1 KB gz   665.51 bytes/row

Built from the tracked export archive via the shared fixture, so it is
reproducible and skips (never passes vacuously) rather than depending on
``exports/latest`` — the same discipline ``test_compact_view_byte_budget``
already established for this family of test.
"""

from __future__ import annotations

import gzip
import json

import pytest

from src.api.data_contract import build_api_data_contract
from tests.archive_fixtures import newest_complete_raw_payload

# Headroom over the bytes/row measured 2026-08-20. Wide on purpose: this
# must absorb organic per-row growth (a new source, a new stamped field)
# across many future scrapes without chasing every archive refresh, while
# still catching the failure mode it exists for — a duplicated encoding
# or an unbounded field roughly doubles bytes/row, not nudges it by 60%.
_HEADROOM = 1.60
_RUNTIME_BUDGET_BYTES_PER_ROW = 545.95 * _HEADROOM
_ARRAY_BUDGET_BYTES_PER_ROW = 665.51 * _HEADROOM

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
    return len(gzip.compress(raw, compresslevel=5))


def _runtime_view(contract: dict) -> dict:
    """``?view=app`` — the frontend's default fetch (``server.py``: ``runtime_payload``)."""
    payload = dict(contract)
    payload.pop("playersArray", None)
    payload["payloadView"] = "runtime"
    return payload


def _array_view(contract: dict) -> dict:
    """``?view=array`` — desktop clients (``server.py``: ``array_payload``)."""
    payload = dict(contract)
    payload.pop("players", None)
    payload["payloadView"] = "array"
    return payload


def _row_count(contract: dict) -> int:
    rows = contract.get("playersArray")
    if not isinstance(rows, list) or not rows:
        pytest.skip("contract carries no playersArray to scale the budget against")
    return len(rows)


def test_runtime_view_under_bytes_per_row_budget():
    """``?view=app`` — what a fresh page load actually fetches — has a ceiling."""
    contract = _contract()
    rows = _row_count(contract)
    gz = _wire_bytes(_runtime_view(contract))
    budget = rows * _RUNTIME_BUDGET_BYTES_PER_ROW
    assert gz <= budget, (
        f"view=app is {gz / 1024:.1f} KB gzipped over {rows} rows "
        f"({gz / rows:.1f} bytes/row) — over the {_RUNTIME_BUDGET_BYTES_PER_ROW:.1f} "
        f"bytes/row budget ({budget / 1024:.1f} KB total)."
    )


def test_array_view_under_bytes_per_row_budget():
    """``?view=array`` — the desktop view — has a ceiling."""
    contract = _contract()
    rows = _row_count(contract)
    gz = _wire_bytes(_array_view(contract))
    budget = rows * _ARRAY_BUDGET_BYTES_PER_ROW
    assert gz <= budget, (
        f"view=array is {gz / 1024:.1f} KB gzipped over {rows} rows "
        f"({gz / rows:.1f} bytes/row) — over the {_ARRAY_BUDGET_BYTES_PER_ROW:.1f} "
        f"bytes/row budget ({budget / 1024:.1f} KB total)."
    )
