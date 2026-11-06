"""Master-site-audit W03-F001 / W07-F001 / W08-F001 regression (CW-40, 2026-11-06).

The August audit measured that the stock frontend body
``{"tep_multiplier": 1.15}`` posted to ``/api/rankings/overrides?view=delta``
switched OFF the ADR-015 TE-basis conversion (``tep_multiplier_is_override``),
so /rankings and /trade rendered a different board from ``GET /api/data``
(627 of 740 ranks, 129-135 values, TEs by up to -21%) while
``isCustomized`` read false.

Closed on main by DEFECT-02 (#2003): the manual TE override is withdrawn at the
HTTP ingress and the frontend default is ``null`` (no POST).  This pins the
INVARIANT on a real, TE-bearing board built from the tracked export archive --
the tiny synthetic fixture the older tests use carries no tight ends, so it
cannot see the defect that was reported.  Deterministic, offline, isolated app.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import data_contract
from tests.api.test_overrides_response_cache import overrides_env  # noqa: F401 - fixture
from tests.archive_fixtures import newest_complete_raw_payload


@pytest.fixture(scope="module")
def raw_board():
    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived board available")
    return raw


def _rows(players):
    return {
        (r.get("id") or r.get("displayName")): (
            r.get("rankDerivedValue"),
            r.get("canonicalConsensusRank"),
            r.get("canonicalTierId"),
        )
        for r in players
    }


# The stock frontend body, plus the other two manual TE knobs, in ONE request:
# every one of them must be ignored (one pipeline build keeps this under ~10 s).
_STOCK_BODY = {"tep_multiplier": 1.15, "tepMultiplier": 1.45, "tep_native_multiplier": 1.3}


def test_posted_tep_body_serves_the_get_api_data_board(
    overrides_env,  # noqa: F811 - pytest fixture
    monkeypatch,
    raw_board,
):
    body = _STOCK_BODY
    base = data_contract.build_api_data_contract(raw_board)
    base_rows = _rows(base["playersArray"])
    assert any(
        str(r.get("position")) == "TE" and r.get("rankDerivedValue") for r in base["playersArray"]
    ), "board must carry priced tight ends or the check is vacuous"

    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(server, "latest_data", raw_board)
        monkeypatch.setattr(server, "latest_contract_data", {"meta": {"leagueKey": "main"}})
        monkeypatch.setattr(server, "latest_data_etag", "audit-tep")
        resp = c.post("/api/rankings/overrides?view=delta", json=body)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    delta_rows = _rows(payload["rankingsDelta"]["players"])
    compared = 0
    for rid, got in delta_rows.items():
        if rid in base_rows:
            assert got == base_rows[rid], rid
            compared += 1
    assert compared > 0
    assert payload["meta"]["tepMultiplierSource"] != "override"
    assert data_contract.TEP_OVERRIDE_WITHDRAWN_NOTE in payload["warnings"]
