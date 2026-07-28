"""bdvm_api values cache: must be multi-entry.

The roster/trades path always computes with the default surplus mode
while /api/bdvm/values may carry a non-default one.  A single-slot
cache makes those two keys evict each other on every alternation —
every request becomes a cold multi-second engine run.  Pinned here:
alternating keys coexist.
"""

from __future__ import annotations

import unittest
from unittest import mock

from src.api import bdvm_api


def _contract():
    # No currentDraftYear → season 0 → no snapshot/context/schedule
    # lookups; run_valuation is mocked anyway.
    return {"generatedAt": "2026-07-28T00:00:00Z", "playersArray": []}


class TestValuesCacheIsMultiEntry(unittest.TestCase):
    def setUp(self):
        bdvm_api.reset_cache()
        self.addCleanup(bdvm_api.reset_cache)

    def test_alternating_surplus_modes_do_not_evict_each_other(self):
        contract = _contract()
        calls = []

        def fake_run_valuation(_contract, **kwargs):
            calls.append(kwargs.get("surplus_mode"))
            return {"status": "ok", "meta": {"surplusMode": kwargs.get("surplus_mode")}}

        with mock.patch.object(bdvm_api, "run_valuation", side_effect=fake_run_valuation):
            bdvm_api.get_bdvm_values(contract, "dynasty_main", surplus_mode="truncated")
            bdvm_api.get_bdvm_values(contract, "dynasty_main", surplus_mode="option")
            out = bdvm_api.get_bdvm_values(contract, "dynasty_main", surplus_mode="truncated")
        # third call is a cache hit — a single-slot cache would recompute
        self.assertEqual(calls, ["truncated", "option"])
        self.assertEqual(out["meta"]["surplusMode"], "truncated")

    def test_lru_evicts_oldest_beyond_capacity(self):
        contract = _contract()
        with mock.patch.object(
            bdvm_api,
            "run_valuation",
            side_effect=lambda _c, **kw: {"status": "ok", "meta": {}},
        ) as rv:
            for i in range(bdvm_api._VALUES_CACHE_MAX + 1):
                bdvm_api.get_bdvm_values(contract, f"league_{i}")
            first_count = rv.call_count
            # league_0 was evicted → recompute; league_1.. still cached
            bdvm_api.get_bdvm_values(contract, "league_0")
            self.assertEqual(rv.call_count, first_count + 1)
            bdvm_api.get_bdvm_values(contract, f"league_{bdvm_api._VALUES_CACHE_MAX}")
            self.assertEqual(rv.call_count, first_count + 1)


if __name__ == "__main__":
    unittest.main()
