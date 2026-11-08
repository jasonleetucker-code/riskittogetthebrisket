"""MD-108 wiring: ``_fetch_draft_capital`` publishes the vendor comparison fields."""

from __future__ import annotations

import pytest

from tests.api import test_draft_capital_batch_f as _bf
from tests.api.test_draft_capital_multi_year import _run

server_mod = _bf.server_mod  # reuse the Batch E/F route harness fixture
NEW_FIELDS = ("rookieKtcComparableDollar", "rookieIdpComparableDollar")


def _pool(n=72, covered=45):
    pool = []
    for i in range(n):
        # Names differ from the "canonical" form only by case / whitespace.
        name = f"  ROOKIE {i:02d} " if i % 3 == 0 else f"Rookie {i:02d}"
        pool.append(
            {
                "name": name,
                "pos": "WR",
                "value": float(7300 - 83 * i),
                "ktcRaw": float(7000 - 90 * i) if i < covered else None,
                "idpRaw": None,
                "assetClass": "offense",
                "staleVendors": [],
                "dispersionCV": None,
                "singleSource": False,
            }
        )
    return pool


def test_comparable_dollars_land_on_the_right_picks_despite_name_noise(server_mod, monkeypatch):
    pool = _pool()
    monkeypatch.setattr(server_mod, "_our_rookie_pool", lambda *_a, **_k: pool)
    result = _run(server_mod, monkeypatch)
    if result["rookieDollarLadder"]["state"] != "computed":
        pytest.skip("canonical ladder unavailable in this environment")
    picks = sorted(result["picks"], key=lambda p: p["overallPick"])[:72]
    vc = result["vendorComparison"]["vendors"]["ktc"]
    assert vc["state"] == "comparable" and vc["covered"] == 45 and vc["common"] == 45
    assert vc["quoteKind"] == "derived_comparison_not_a_vendor_quote"
    for i, p in enumerate(picks):
        if i < 45:
            # Vendor orders the 45 exactly as we do: comparable == our ladder dollar.
            assert p["rookieKtcComparableDollar"] == p["rookieKtcValue"], i
        else:
            assert p["rookieKtcComparableDollar"] is None, i
        assert p["rookieIdpComparableDollar"] is None  # IDPTC lists nobody here
    assert result["vendorComparison"]["vendors"]["idpTradeCalc"]["state"] == (
        "no_vendor_observations"
    )


def test_a_short_pool_leaves_comparable_dollars_missing_not_zero(server_mod, monkeypatch):
    pool = _pool(60, covered=45)
    monkeypatch.setattr(server_mod, "_our_rookie_pool", lambda *_a, **_k: pool)
    result = _run(server_mod, monkeypatch)
    assert result["vendorComparison"]["vendors"]["ktc"]["state"] == "our_dollars_unavailable"
    named = [p for p in result["picks"] if p.get("rookieName")]
    assert named and all(p["rookieKtcComparableDollar"] is None for p in named)


def test_new_fields_are_private_and_absent_from_public_responses():
    server = pytest.importorskip("server")
    for f in NEW_FIELDS:
        assert f in server._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS
    payload = {
        "picks": [
            {
                "pick": "1.01",
                "overallPick": 1,
                "dollarValue": 60.0,
                "currentOwner": "Alpha",
                "rookieName": "X",
                "rookieKtcComparableDollar": 55.0,
                "rookieIdpComparableDollar": 54.0,
            }
        ],
        "vendorComparison": {"version": "vc_v1", "vendors": {}},
    }
    redacted = server._redact_draft_capital_for_public(payload)
    assert all(f not in redacted["picks"][0] for f in NEW_FIELDS)
    assert redacted["picks"][0]["dollarValue"] == 60.0
    # The cache's shared object is not mutated, and the counts-only receipt survives.
    assert payload["picks"][0]["rookieKtcComparableDollar"] == 55.0
    assert redacted["vendorComparison"]["version"] == "vc_v1"
