"""DYN10 item 8: rookie-source coverage stamp (additive, display-only)."""

from __future__ import annotations

import copy

import pytest

from src.draft import rookie_source_coverage as rsc
from tests.api import test_draft_capital_batch_f as _bf
from tests.api.test_draft_capital_multi_year import _run

server_mod = _bf.server_mod


def _m(weight=1.0, **kw):
    return {"appliedWeight": weight, "contributedToBlend": True, **kw}


def _row(i, meta, value=5000.0):
    return {
        "rookie": True,
        "playerId": f"p{i}",
        "canonicalName": f"Rookie {i}",
        "displayName": f"Rookie {i}",
        "position": "WR",
        "rankDerivedValue": value - i,
        "sourceRankMeta": meta,
    }


def _entry(key, status, coverage="offense", reason="r", label="L"):
    return {
        "key": key,
        "displayName": key.upper(),
        "coverage": coverage,
        "status": status,
        "statusLabel": label,
        "reason": reason,
    }


def test_row_counts_only_voting_sources():
    cov = rsc.row_coverage(
        _row(
            1,
            {
                "ktc": _m(),
                "idpTradeCalc": _m(0.0),  # zero weight: did not vote
                "dlfRookieSf": _m(hampelDropped=True),  # outlier-dropped
                "x": _m(contributedToBlend=False),
                "y": _m(),
            },
        )
    )
    assert cov["votingSourceCount"] == 2
    assert cov["votingSources"] == ["ktc", "y"]
    assert cov["state"] == "low"
    assert cov["reason"] is None


def test_row_with_enough_sources_is_ok():
    cov = rsc.row_coverage(_row(1, {k: _m() for k in "abc"}))
    assert (cov["votingSourceCount"], cov["state"]) == (3, "ok")


@pytest.mark.parametrize("meta", [None, {}, "junk", []])
def test_unknown_count_is_null_with_reason_never_zero(meta):
    cov = rsc.row_coverage(_row(1, meta))
    assert cov["votingSourceCount"] is None
    assert cov["votingSources"] is None
    assert cov["state"] == "unknown"
    assert cov["reason"] == "source_meta_unavailable"


def test_measured_zero_voters_is_zero_and_low():
    cov = rsc.row_coverage(_row(1, {"a": _m(0.0)}))
    assert cov["votingSourceCount"] == 0 and cov["state"] == "low"


def _contract():
    rows = [
        _row(1, {"ktc": _m(), "dlfSf": _m(), "idp": _m()}),
        _row(2, {"ktc": _m()}),
        _row(3, None),
    ]
    entries = [
        _entry("ktc", "active_100"),
        _entry("dlfSf", "active_75"),
        _entry("idp", "stale", reason="old"),
        _entry("dlfRookieSf", "data_issue", "rookie", reason="vendor empty"),
        _entry("dlfRookieIdp", "testing", "rookie", reason="owner hold"),
        _entry("flockFantasySfRookies", "seasonal", "rookie", reason="graduated"),
        _entry("fantasyPros", "active_100"),  # not rookie-relevant: dropped
    ]
    return {"playersArray": rows, "sourceVotingStatus": {"sources": entries}}


def test_pool_block_classifies_sources():
    pool = rsc.build_pool_coverage(_contract())
    assert pool["state"] == "available"
    by = {s["key"]: s for s in pool["sources"]}
    assert set(by) == {
        "ktc",
        "dlfSf",
        "idp",
        "dlfRookieSf",
        "dlfRookieIdp",
        "flockFantasySfRookies",
    }
    assert by["ktc"]["state"] == "voting" and by["ktc"]["rookiesPriced"] == 2
    assert by["dlfSf"]["state"] == "voting"
    # "idp" voted on a pool row but its status says stale: status wins.
    assert by["idp"]["state"] == "stale"
    assert by["dlfRookieSf"]["state"] == "missing"
    assert by["dlfRookieSf"]["reason"] == "vendor empty"
    assert by["dlfRookieIdp"]["state"] == "held"
    assert by["flockFantasySfRookies"]["state"] == "seasonal"
    assert pool["votingCount"] == 2 and pool["relevantCount"] == 6
    assert pool["poolSize"] == 3
    assert pool["lowCoverageRows"] == 1 and pool["unknownRows"] == 1


def test_active_source_that_priced_no_pool_rookie_is_missing():
    c = _contract()
    c["sourceVotingStatus"]["sources"].append(_entry("rk", "active_100", "rookie"))
    by = {s["key"]: s for s in rsc.build_pool_coverage(c)["sources"]}
    assert by["rk"]["state"] == "missing" and by["rk"]["rookiesPriced"] == 0


@pytest.mark.parametrize(
    "contract,reason",
    [
        (None, "contract_unavailable"),
        ({"playersArray": []}, "source_voting_status_unavailable"),
        (
            {"playersArray": [], "sourceVotingStatus": {"sources": []}},
            "source_voting_status_unavailable",
        ),
    ],
)
def test_unavailable_pool_has_null_counts_not_zero(contract, reason):
    pool = rsc.build_pool_coverage(contract)
    assert pool["state"] == "unavailable" and pool["reason"] == reason
    assert pool["votingCount"] is None and pool["relevantCount"] is None
    assert pool["lowCoverageRows"] is None and pool["unknownRows"] is None


def test_builder_does_not_mutate_the_contract():
    c = _contract()
    before = copy.deepcopy(c)
    rsc.build_pool_coverage(c)
    assert c == before


# --- server wiring --------------------------------------------------------------


def _pool(with_cov: bool, n=72):
    out = []
    for i in range(n):
        r = {
            "name": f"Rookie {i:02d}",
            "pos": "WR",
            "value": float(7300 - 83 * i),
            "ktcRaw": None,
            "idpRaw": None,
            "assetClass": "offense",
            "staleVendors": [],
            "dispersionCV": None,
            "singleSource": False,
        }
        if with_cov:
            r["sourceCoverage"] = rsc.row_coverage(_row(i, {"ktc": _m()} if i else None))
        out.append(r)
    return out


def test_wiring_adds_fields_and_changes_no_value(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod, "_our_rookie_pool", lambda *_a, **_k: _pool(False))
    base = _run(server_mod, monkeypatch)
    monkeypatch.setattr(server_mod, "_our_rookie_pool", lambda *_a, **_k: _pool(True))
    withcov = _run(server_mod, monkeypatch)

    def strip(res):
        out = copy.deepcopy(res)
        out.pop("rookieSourceCoverage", None)
        for p in out["picks"]:
            p.pop("rookieSourceCoverage", None)
        return out

    # Byte-identical once the additive fields are removed.
    assert strip(withcov) == strip(base)
    named = [p for p in withcov["picks"] if p.get("rookieName")]
    assert named
    assert named[0]["rookieSourceCoverage"]["state"] == "unknown"
    assert named[0]["rookieSourceCoverage"]["votingSourceCount"] is None
    assert named[1]["rookieSourceCoverage"]["votingSourceCount"] == 1
    assert named[1]["rookieSourceCoverage"]["state"] == "low"
    assert "rookieSourceCoverage" in withcov  # pool block (dict or unavailable)


def test_coverage_is_private_and_absent_from_public_responses():
    server = pytest.importorskip("server")
    assert "rookieSourceCoverage" in server._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS
    payload = {
        "picks": [
            {
                "overallPick": 1,
                "dollarValue": 60.0,
                "rookieName": "X",
                "rookieSourceCoverage": {"votingSourceCount": 1},
            }
        ],
        "rookieSourceCoverage": {"state": "available", "sources": []},
    }
    red = server._redact_draft_capital_for_public(payload)
    assert "rookieSourceCoverage" not in red["picks"][0]
    assert "rookieSourceCoverage" not in red
    assert red["picks"][0]["dollarValue"] == 60.0
    # Shared cache object untouched.
    assert "rookieSourceCoverage" in payload
    assert "rookieSourceCoverage" in payload["picks"][0]


def test_our_rookie_pool_stamps_coverage_without_changing_value(monkeypatch):
    # Not the ``server_mod`` fixture: it stubs ``_our_rookie_pool`` out.
    server_mod = pytest.importorskip("server")
    contract = {
        "playersArray": [_row(1, {"a": _m(), "b": _m()}), _row(2, None)],
    }
    monkeypatch.setattr(server_mod, "latest_contract_data", contract)
    pool = server_mod._our_rookie_pool(72)
    assert [r["value"] for r in pool] == [4999.0, 4998.0]
    assert pool[0]["sourceCoverage"]["votingSourceCount"] == 2
    assert pool[1]["sourceCoverage"]["votingSourceCount"] is None
