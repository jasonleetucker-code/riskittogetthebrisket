"""The advisor reads the board stamp through the shared owner (#1871).

``trade_analyze_runtime.contract_generation`` is the ONE reader the analyze
receipt (``analyze_service.contract_provenance``), the analyze in-flight key
and the N-team ledger snapshot (``trade_ledger``) share: top-level
``generatedAt`` with a ``meta.generatedAt`` fallback.  The advisor publishes
an opaque token of the ledger snapshot's generation and keeps no private rule.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

from src.api.trade_analyze_runtime import contract_generation
from src.trade import analyze_service, public_advisor, trade_ledger


def _gen(contract) -> str:
    return public_advisor.public_generation(
        SimpleNamespace(generation=trade_ledger._generation(contract))
    )


def test_top_level_and_meta_fallback_name_the_same_generation() -> None:
    top = {"generatedAt": "2026-10-20T05:00:00+00:00"}
    legacy = {"meta": {"generatedAt": "2026-10-20T05:00:00+00:00"}}
    assert _gen(top) == _gen(legacy)
    assert contract_generation(top) == contract_generation(legacy)


def test_top_level_stamp_wins_over_meta() -> None:
    both = {"generatedAt": "A", "meta": {"generatedAt": "B"}}
    assert _gen(both) == _gen({"generatedAt": "A"})
    assert analyze_service.contract_provenance(both)["boardStamp"] == "A"


def test_the_public_token_is_opaque_and_stable() -> None:
    a = _gen({"generatedAt": "2026-10-20T05:00:00+00:00"})
    assert a == _gen({"generatedAt": "2026-10-20T05:00:00+00:00"})
    assert a != _gen({"generatedAt": "2026-10-20T07:00:00+00:00"})
    assert "2026" not in a and len(a) == 16


def test_advisor_has_no_private_stamp_reader() -> None:
    src = inspect.getsource(public_advisor)
    assert 'get("meta")' not in src
    assert "generatedAt" not in src
    assert "snap.generation" in inspect.getsource(public_advisor.public_generation)
