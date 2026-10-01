"""E2 (hill-alignment audit 2026-10-01): Phase 1c keys rank-decoding on value-set
MEMBERSHIP, not on the source's signal type.

``_compute_unified_rankings`` Phase 1c builds ``csv_rank_cross_market_keys`` from
every cross-market source that is ``not in _VALUE_BASED_SOURCES`` and decodes its
``canonicalSiteValues`` entry as a synthetic rank
(``rank = OFFSET - value / 100``). ``idpTradeCalc`` is a cross-market VALUE-signal
source: its ``canonicalSiteValues`` entry is a real 0-9999 value, not an encoding.
Today it escapes Phase 1c only because it is in ``_VALUE_BASED_SOURCES``. Any change
that takes it off the value path (the 2026-09-30 replay's first counterfactual did)
silently prices every IDPTC row near rank 9,900.

Repaired: Phase 1c now selects by the source's CSV signal type
(``data_contract._csv_signal_for(key) == "rank"``), per the patch recorded in
``docs/valuation/evidence/hill-trainer-repair-2026-10-01/README.md`` §E2. This test
was the failing-first ``xfail(strict=True)`` half of that repair; the marker was
removed with the fix and the test now guards it.
"""

from __future__ import annotations

import socket

import pytest

from src.api import data_contract as dc
from src.api import value_replay as vr
from tests.archive_fixtures import newest_complete_raw_payload

_PINNED_CONTEXT = {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": False}


@pytest.fixture(scope="module")
def raw():
    mp = pytest.MonkeyPatch()

    def refuse(*_a, **_k):
        raise OSError("network disabled in test_phase1c_signal_type_coupling")

    mp.setattr(socket.socket, "connect", refuse)
    mp.setattr(dc, "_resolve_league_context", lambda *_a, **_k: dict(_PINNED_CONTEXT))
    payload, _name = newest_complete_raw_payload()
    if payload is None:
        mp.undo()
        pytest.skip("no complete archived scrape")
    yield payload
    mp.undo()


def _idptc_effective_ranks(board) -> dict[str, int]:
    return {
        r["displayName"]: r["sourceRankMeta"]["idpTradeCalc"]["effectiveRank"]
        for r in board["playersArray"]
        if "idpTradeCalc" in (r.get("sourceRankMeta") or {})
    }


def test_a_value_signal_source_off_the_value_path_keeps_its_phase1_rank(raw):
    base = vr.build(raw)
    off = vr.build(
        raw,
        {"patch": ("_VALUE_BASED_SOURCES", dc._VALUE_BASED_SOURCES - {"idpTradeCalc"})},
    )
    before = _idptc_effective_ranks(base)
    after = _idptc_effective_ranks(off)
    assert before and after
    # A value-signal source's rank is its Phase 1 ordinal whatever path it votes by;
    # it must never be decoded from its value as if the value were a rank encoding.
    assert max(after.values()) < 5000
    assert after == before
