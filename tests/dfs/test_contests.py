"""DFS contests: payout ladders, exact ties, rake vs overlay, entry caps, presets, API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.dfs import api as dfs_api
from src.dfs.contests import (
    ContestError,
    PayoutBand,
    dollars_to_cents,
    entry_upper_bound,
    parse_contest,
    parse_payout_text,
    tied_payout,
    validate_contest,
)

BASE = {"name": "Test GPP", "platform": "draftkings", "sport": "nfl", "format": "classic"}


def _contest(**kw):
    return parse_contest({**BASE, "entryFee": "10", **kw})


# ── money + parsing ───────────────────────────────────────────────────


def test_money_is_exact_integer_cents():
    assert dollars_to_cents("1,000.50", "x") == 100050
    assert dollars_to_cents("$25", "x") == 2500
    assert dollars_to_cents(0.1, "x") == 10  # str(0.1) → "0.1" → exact
    for bad in ("1.005", "-3", "abc", "", None, True, "NaN", "Infinity"):
        with pytest.raises(ContestError):
            dollars_to_cents(bad, "x")


def test_payout_text_parses_ranges_and_refuses_unreadable_lines():
    bands = parse_payout_text("1 $1,000\n2: 100\n3-5 $20.50\n6th–10th 5\n\n")
    assert [(b.min_rank, b.max_rank, b.prize_cents) for b in bands] == [
        (1, 1, 100000),
        (2, 2, 10000),
        (3, 5, 2050),
        (6, 10, 500),
    ]
    with pytest.raises(ContestError) as exc:
        parse_payout_text("1 $1000\nfirst place: a lot\n")
    assert exc.value.code == "PAYOUT_UNREADABLE" and exc.value.detail["lines"][0]["line"] == 2


# ── ties (DFS-§17-02, test item 20/21) ────────────────────────────────


def test_two_way_tie_for_first_splits_1000_and_100_into_550_each():
    ladder = [PayoutBand(1, 1, 100000), PayoutBand(2, 2, 10000)]
    r = tied_payout(ladder, 1, 2, "split_positions")
    assert r == {"state": "exact", "eachCents": 55000, "exact": "55000", "pooledCents": 110000}


def test_tie_across_the_cash_line_pools_the_unpaid_rank_too():
    ladder = [PayoutBand(1, 3, 1000)]  # ranks 1-3 pay $10, rank 4 pays nothing
    r = tied_payout(ladder, 3, 2, "split_positions")
    assert r["eachCents"] == 500  # ($10 + $0) / 2


def test_uneven_split_is_reported_exactly_not_rounded():
    ladder = [PayoutBand(1, 1, 100), PayoutBand(2, 3, 0)]
    r = tied_payout(ladder, 1, 3, "split_positions")
    assert r["state"] == "exact_fraction" and r["exact"] == "100/3" and r["eachCents"] is None


def test_unknown_tie_rule_makes_tied_payouts_unavailable():
    r = tied_payout([PayoutBand(1, 1, 100000), PayoutBand(2, 2, 10000)], 1, 2, "unknown")
    assert r["state"] == "unavailable"


# ── validation ────────────────────────────────────────────────────────


def test_overlaps_and_overpaid_ranks_are_errors_gaps_and_inversions_are_review_flags():
    c = _contest(capacity=100, payoutText="1 100\n2-4 20\n3 30\n")
    assert any("overlap" in e for e in validate_contest(c)["errors"])
    c = _contest(capacity=3, payoutText="1 100\n2-5 20\n")
    assert any("capacity is 3" in e for e in validate_contest(c)["errors"])
    c = _contest(capacity=100, payoutText="1 100\n2 150\n5 10\n")
    rep = validate_contest(c)
    assert rep["ok"]  # unusual schedules are flagged, not rewritten or refused
    assert any("pays more" in w for w in rep["warnings"]) and any(
        "No prize listed" in w for w in rep["warnings"]
    )
    assert [b.prize_cents for b in c.ladder] == [10000, 15000, 1000]


def test_missing_ladder_blocks_evaluation_and_hypothetical_suppresses_exact_ev():
    rep = validate_contest(_contest(capacity=100))
    assert not rep["ok"] and "PAYOUT_INCOMPLETE" in rep["errors"][0]
    rep = validate_contest(_contest(capacity=100, payoutText="1 500", ladderSource="hypothetical"))
    assert rep["ok"] and rep["derived"]["exactEvAllowed"] is False


def test_payout_shape_is_descriptive():
    h2h = validate_contest(_contest(capacity=2, payoutText="1 18"))
    assert h2h["derived"]["payoutShape"]["shape"] == "head_to_head"
    du = validate_contest(_contest(capacity=100, payoutText="1-45 20"))
    assert du["derived"]["payoutShape"]["shape"] == "double_up"
    gpp = validate_contest(_contest(capacity=1000, payoutText="1 2000\n2-10 200\n11-200 20"))
    assert gpp["derived"]["payoutShape"]["shape"] == "tournament"


# ── economics (test items 22/23) ──────────────────────────────────────


def _econ(**kw):
    return validate_contest(_contest(payoutText="1 700\n2 200", **kw))["derived"]["economics"]


def test_full_contest_rake():
    e = _econ(capacity=100, currentEntries=100)
    assert e["state"] == "raked" and e["effectiveRake"] == pytest.approx(0.1)


def test_underfilled_but_still_raked_is_not_an_overlay():
    e = _econ(capacity=100, currentEntries=95, guaranteed=True)
    assert e["state"] == "raked" and "NOT an overlay" in e["note"]


def test_overlay_only_when_guaranteed():
    assert _econ(capacity=100, currentEntries=80, guaranteed=True)["state"] == "overlay"
    assert (
        _econ(capacity=100, currentEntries=80, guaranteed=False)["state"]
        == "underfilled_not_guaranteed"
    )
    assert _econ(capacity=100, currentEntries=80)["state"] == "underfilled_guarantee_unknown"


def test_unknown_field_free_and_ticket_contests_are_distinct_states():
    assert _econ(capacity=100)["state"] == "field_unknown"
    assert _econ(capacity=100, currentEntries=0)["state"] == "empty_contest"
    free = parse_contest({**BASE, "entryMethod": "free", "payoutText": "1 10"})
    assert validate_contest(free)["derived"]["economics"]["state"] == "free_contest"
    tix = _contest(entryMethod="ticket", payoutText="1 10")
    assert validate_contest(tix)["derived"]["economics"]["state"] == "ticket_entry"


# ── entry cap (DFS-§7-03, test item 28) ───────────────────────────────


def test_entry_cap_is_min_of_allowance_capacity_and_budget():
    c = _contest(
        capacity=100,
        currentEntries=90,
        maxEntriesPerUser=20,
        existingUserEntries=3,
        payoutText="1 700",
    )
    r = entry_upper_bound(c, spend_limit_cents=5000)  # $50 / $10 = 5
    assert r["upperBound"] == 5 and r["binding"] == ["affordable"]
    assert r["terms"] == {"remainingAllowance": 17, "openCapacity": 10, "affordable": 5}
    assert r["recommendation"]["state"] == "unavailable"


def test_entry_cap_never_infers_a_budget_and_allows_zero():
    c = _contest(
        capacity=100,
        currentEntries=100,
        maxEntriesPerUser=1,
        existingUserEntries=0,
        payoutText="1 700",
    )
    r = entry_upper_bound(c, None)
    assert r["upperBound"] is None and "spendLimit" in r["missing"]
    assert entry_upper_bound(c, 10**6)["upperBound"] == 0  # contest is full


def test_free_entries_need_no_budget():
    free = parse_contest(
        {
            **BASE,
            "entryMethod": "free",
            "capacity": 10,
            "currentEntries": 2,
            "maxEntriesPerUser": 1,
            "existingUserEntries": 0,
        }
    )
    assert entry_upper_bound(free, None)["upperBound"] == 1


# ── presets ───────────────────────────────────────────────────────────


def test_presets_are_explicit_and_none_claims_validation():
    data = json.loads(
        (Path(__file__).resolve().parents[2] / "config/dfs/presets.json").read_text(
            encoding="utf-8"
        )
    )
    ids = {p["id"] for p in data["presets"]}
    assert {
        "h2h",
        "fifty_fifty",
        "double_up",
        "multiplier",
        "small_field_gpp",
        "large_field_gpp",
    } <= ids
    assert {"single_entry", "three_max", "twenty_max", "one_fifty_max", "single_game"} <= ids
    for p in data["presets"]:
        assert (
            p["validationState"] == "unsupported" and p["requiredModels"] and p["objective"]["id"]
        )
    cash = {
        p["objective"]["id"]
        for p in data["presets"]
        if p["id"] in ("fifty_fifty", "double_up", "h2h")
    }
    gpp = {
        p["objective"]["id"]
        for p in data["presets"]
        if p["id"] in ("small_field_gpp", "large_field_gpp")
    }
    assert cash.isdisjoint(gpp)  # cash and GPP are different decision logic, not a relabel


# ── API ───────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RISKIT_FEATURE_DFS_WORKSPACE", raising=False)
    feature_flags.reload()
    app = FastAPI()
    app.include_router(dfs_api.router)
    dfs_api.configure_session_resolver(
        lambda req: {"username": req.headers["x-user"]} if req.headers.get("x-user") else None
    )
    yield TestClient(app)
    feature_flags.reload()


CONTEST = {
    **BASE,
    "entryFee": "20",
    "capacity": 100,
    "currentEntries": 100,
    "maxEntriesPerUser": 3,
    "existingUserEntries": 0,
    "tieRule": "split_positions",
    "payoutText": "1 $1,000\n2 $100\n3-10 $50",
}


def test_validate_save_version_and_cap_through_the_api(client):
    h = {"x-user": "alice"}
    r = client.post(
        "/api/dfs/contests/validate", json={"contest": CONTEST, "spendLimit": "50"}, headers=h
    ).json()
    assert r["report"]["ok"] and r["report"]["tiePreview"]["eachCents"] == 55000
    assert r["entryCap"]["upperBound"] == 0  # full contest
    saved = client.post("/api/dfs/contests", json={"contest": CONTEST}, headers=h).json()
    assert saved["version"] == 1
    v2 = client.post(
        "/api/dfs/contests",
        json={"contest": {**CONTEST, "currentEntries": 80}, "contestId": saved["contestId"]},
        headers=h,
    ).json()
    assert v2["version"] == 2 and v2["contestId"] == saved["contestId"]
    cap = client.post(
        f"/api/dfs/contests/{saved['contestId']}/entry-cap", json={"spendLimit": "50"}, headers=h
    ).json()
    assert cap["version"] == 2 and cap["entryCap"]["upperBound"] == 2  # $50 / $20
    listing = client.get("/api/dfs/contests", headers=h).json()["contests"]
    assert len(listing) == 1 and listing[0]["version"] == 2


def test_contests_are_private_to_their_owner(client):
    saved = client.post(
        "/api/dfs/contests", json={"contest": CONTEST}, headers={"x-user": "alice"}
    ).json()
    m = {"x-user": "mallory"}
    assert client.get(f"/api/dfs/contests/{saved['contestId']}", headers=m).status_code == 404
    assert (
        client.post(
            "/api/dfs/contests",
            json={"contest": CONTEST, "contestId": saved["contestId"]},
            headers=m,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/dfs/contests/{saved['contestId']}/entry-cap", json={}, headers=m
        ).status_code
        == 404
    )
    assert client.get("/api/dfs/contests", headers=m).json()["contests"] == []


def test_contest_must_name_a_registered_capability(client):
    r = client.post(
        "/api/dfs/contests/validate",
        json={"contest": {**CONTEST, "sport": "cricket"}},
        headers={"x-user": "a"},
    )
    assert r.status_code == 422 and r.json()["error"] == "INVALID_CONTEST"


def test_presets_endpoint(client):
    assert len(client.get("/api/dfs/presets", headers={"x-user": "a"}).json()["presets"]) == 15
