"""League Draft Capital lists EVERY Sleeper draft class (owner directive 2026-10-17).

``/league?tab=draft-capital`` for ``dynasty_main`` offered only
"All Years | 2027" while the league trades 2027, 2028 and 2029 picks.  Root
cause: the default league is served by the workbook builder
(``server._fetch_draft_capital``), and the workbook holds ONE draft, so the
year views — derived from the pick inventory — could only ever see that class.

These tests drive the real workbook builder with a stubbed Sleeper league and
a stubbed workbook, and pin:

* every owned class from the league-scoped resolver appears (the retired class
  does not), each pick exactly once, with origin + current owner + assetId;
* the workbook class keeps its dollars, ``teamTotals`` and ``coveredPickYears``
  (the auction budgets /draft, the auction room and /trade read);
* later classes come from Sleeper ownership + canonical round values, one
  $1200 pool per class, unpriced picks ``None`` never 0;
* per-year views filter, All Years sums without double counting;
* a failed /traded_picks refuses the board (no silent workbook ownership);
* the public projection stays free of rookie-board fields and raw Sleeper ids.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

YEAR = datetime.now(timezone.utc).year
LEAGUE_ID = "TEST_ALL_YEARS_LEAGUE"
LEAGUE_KEY = "all_years_league"


def _fake_workbook():
    # 2 teams x 2 rounds — the upcoming class, as the hand-maintained sheet
    # carries it.  Q (``value``) and L (per-pick dollars) both sum to 1200.
    workbook_picks = [
        {"round": 1, "pick": 1, "value": 700.0, "owner": "Ann"},
        {"round": 1, "pick": 2, "value": 300.0, "owner": "Bob"},
        {"round": 2, "pick": 1, "value": 120.0, "owner": "Ann"},
        {"round": 2, "pick": 2, "value": 80.0, "owner": "Bob"},
    ]
    return [], workbook_picks, {1: "Ann", 2: "Bob"}, {}, [], [700.0, 300.0, 120.0, 80.0]


def _contract():
    def row(name, value):
        return {
            "displayName": name,
            "canonicalName": name,
            "assetClass": "pick",
            "rankDerivedValue": value,
        }

    return {
        "currentDraftYear": YEAR + 1,
        "playersArray": [
            row(f"{YEAR + 2} Round 1", 4000),
            row(f"{YEAR + 2} Round 2", 2000),
            row(f"{YEAR + 3} Round 1", 3000),
            # YEAR + 3 round 2 deliberately absent: UNPRICED, never $0.
        ],
    }


def _sleeper(traded):
    """Sleeper responses for a league whose YEAR rookie class is drafted and
    rostered (so the resolver retires it) and whose owned classes are
    YEAR+1 .. YEAR+3."""
    rosters = [
        {"roster_id": 1, "owner_id": "u1", "players": ["r1", "r3"], "settings": {}},
        {"roster_id": 2, "owner_id": "u2", "players": ["r2", "r4"], "settings": {}},
    ]
    users = [
        {"user_id": "u1", "display_name": "Team-Ann", "metadata": {}},
        {"user_id": "u2", "display_name": "Team-Bob", "metadata": {}},
    ]
    draft = {
        "draft_id": "D1",
        "season": str(YEAR),
        "status": "complete",
        "settings": {"rounds": 2, "player_type": 1},
        "slot_to_roster_id": {"1": 1, "2": 2},
    }
    picks = [{"player_id": pid, "metadata": {"years_exp": "0"}} for pid in ("r1", "r2", "r3", "r4")]
    return {
        "meta": {"season": str(YEAR), "settings": {"draft_rounds": 2}},
        f"/league/{LEAGUE_ID}/rosters": rosters,
        f"/league/{LEAGUE_ID}/users": users,
        f"/league/{LEAGUE_ID}/drafts": [draft],
        f"/league/{LEAGUE_ID}/traded_picks": traded,
        "/draft/D1/picks": picks,
        "/draft/D1": draft,
    }


def _urlopen(responses):
    def fake(url, *args, **kwargs):
        target = url.full_url if hasattr(url, "full_url") else str(url)
        if target.rstrip("/").endswith(f"/league/{LEAGUE_ID}"):
            return io.BytesIO(json.dumps(responses["meta"]).encode())
        for suffix, payload in responses.items():
            if suffix != "meta" and target.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return io.BytesIO(json.dumps(payload).encode())
        raise OSError(f"unexpected urlopen({target})")

    return fake


TRADED = [
    # Ann holds Bob's YEAR+2 first.
    {"season": str(YEAR + 2), "round": 1, "roster_id": 2, "owner_id": 1},
    # Bob holds Ann's YEAR+1 second (the workbook class).
    {"season": str(YEAR + 1), "round": 2, "roster_id": 1, "owner_id": 2},
    # A pick traded and traded back is NOT traded (state, not history).
    {"season": str(YEAR + 3), "round": 1, "roster_id": 1, "owner_id": 1},
]


@pytest.fixture
def server_mod(monkeypatch):
    server = pytest.importorskip("server")
    import src.api.draft_class_evidence as dce

    monkeypatch.setattr(server, "_parse_draft_data", _fake_workbook)
    monkeypatch.setattr(server, "_sleeper_league_id_for_draft", lambda _k=None: LEAGUE_ID)
    monkeypatch.setattr(server, "_our_rookie_pool", lambda *_a, **_k: [])
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    monkeypatch.setattr(
        server._league_registry,
        "league_key_for_sleeper_id",
        lambda lid: LEAGUE_KEY if lid == LEAGUE_ID else None,
    )
    monkeypatch.setattr(dce, "read_snapshot", lambda _lid: None)
    return server


def _run(server, monkeypatch, traded=TRADED, **kwargs):
    monkeypatch.setattr(server.urllib.request, "urlopen", _urlopen(_sleeper(traded)))
    return server._fetch_draft_capital(**kwargs)


def _all_picks(result):
    return result["picks"] + result["additionalClassPicks"]


def _row(rows, team):
    return next(r for r in rows if r["team"] == team)


def test_every_owned_class_appears_and_the_retired_one_does_not(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    assert "error" not in result, result
    assert result["leagueDraftYears"]["retiredSeasons"] == [YEAR]
    assert result["availableYears"] == [YEAR + 1, YEAR + 2, YEAR + 3]
    seasons = {p["season"] for p in _all_picks(result)}
    assert seasons == {YEAR + 1, YEAR + 2, YEAR + 3}
    assert YEAR not in seasons  # a completed rookie class is never future capital
    # The workbook carries the upcoming class; Sleeper supplies the others.
    assert {p["season"] for p in result["picks"]} == {YEAR + 1}
    assert {p["season"] for p in result["additionalClassPicks"]} == {YEAR + 2, YEAR + 3}
    assert result["additionalClassesState"] == "observed"
    # 2 teams x 2 rounds per class.
    for season in (YEAR + 1, YEAR + 2, YEAR + 3):
        assert result["yearSummaries"][str(season)]["pickCount"] == 4


def test_each_pick_once_with_origin_owner_and_canonical_id(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    picks = _all_picks(result)
    keys = [(p["season"], p["round"], p["originRosterId"]) for p in picks]
    assert len(keys) == len(set(keys)) == 12
    ids = [p["assetId"] for p in picks]
    assert all(ids) and len(set(ids)) == 12
    assert all(i.startswith(f"pick:{LEAGUE_KEY}:") for i in ids)
    traded = next(p for p in picks if p["assetId"] == f"pick:{LEAGUE_KEY}:{YEAR + 2}:r1:o2")
    assert traded["currentOwnerRosterId"] == 1
    assert traded["currentOwner"] == "Team-Ann"
    assert traded["originalOwner"] == "Team-Bob"
    assert traded["isTraded"] is True
    back = next(p for p in picks if p["assetId"] == f"pick:{LEAGUE_KEY}:{YEAR + 3}:r1:o1")
    assert back["isTraded"] is False and back["currentOwner"] == "Team-Ann"
    # The workbook class follows Sleeper too (Bob holds Ann's second).
    wb = next(p for p in result["picks"] if p["round"] == 2 and p["originRosterId"] == 1)
    assert wb["currentOwner"] == "Team-Bob" and wb["isTraded"] is True


def test_future_classes_never_claim_a_slot(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    for p in result["additionalClassPicks"]:
        assert p["slotStatus"] == "unknown"
        assert p["slot"] is None and p["pickInRound"] is None
        assert p["pick"] == f"R{p['round']}"
    # Every pick of one future season + round prices identically.
    r1 = {
        p["dollarValue"]
        for p in result["additionalClassPicks"]
        if p["season"] == YEAR + 2 and p["round"] == 1
    }
    assert len(r1) == 1
    # The workbook class's slots are an estimate, labelled as such.
    assert all(p["slotStatus"] == "projected" for p in result["picks"])


def test_workbook_class_and_auction_budgets_are_unchanged(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    assert result["coveredPickYears"] == [YEAR + 1]
    assert result["upcomingDraftYear"] == YEAR + 1
    assert result["totalBudget"] == 1200
    assert sum(t["auctionDollars"] for t in result["teamTotals"]) == 1200
    for t in result["teamTotals"]:
        # ``auctionDollars`` is the workbook class only — never the later classes.
        assert t["draftCapitalByYear"][str(YEAR + 1)] == t["auctionDollars"]
    assert all(p["valueBasis"] == "workbook" for p in result["picks"])


def test_later_classes_are_one_pool_each_and_unpriced_is_none(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    # Owner decision 2026-10-18: "$1,200 per draft class".
    policy = result["budgetPolicy"]
    assert policy["basis"] == "per_class_pool"
    assert policy["status"] == "owner_confirmed"
    assert (policy["decidedBy"], policy["decidedAt"]) == ("owner", "2026-10-18")
    assert policy["classBudgets"] == {str(YEAR + k): 1200 for k in (1, 2, 3)}
    assert policy["unpricedClasses"] == []
    assert policy["allYearsBudget"] == 3600
    y2 = [p for p in result["additionalClassPicks"] if p["season"] == YEAR + 2]
    # 2 x 4000 + 2 x 2000 = 12000 of value → $400 per first, $200 per second.
    assert sorted(p["dollarValue"] for p in y2) == [200, 200, 400, 400]
    assert result["yearSummaries"][str(YEAR + 2)]["totalDollars"] == 1200
    y3 = [p for p in result["additionalClassPicks"] if p["season"] == YEAR + 3]
    priced = [p for p in y3 if not p["isUnpriced"]]
    unpriced = [p for p in y3 if p["isUnpriced"]]
    assert [p["round"] for p in unpriced] == [2, 2]
    for p in unpriced:
        assert p["dollarValue"] is None and p["adjustedDollarValue"] is None
        assert p["valueBasis"] is None and p["unpricedReason"]
    assert sorted(p["dollarValue"] for p in priced) == [600, 600]
    assert result["yearSummaries"][str(YEAR + 3)]["unpricedPickCount"] == 2
    # Raw canonical values are never published.
    assert all("_canonicalValue" not in p for p in result["additionalClassPicks"])
    # Owner addendum 2026-10-18: two value domains, labelled per class — the
    # later classes are an INTERIM generic-market curve, never the workbook's.
    assert policy["classCurveMethods"] == {
        str(YEAR + 1): "workbook_rookie_auction",
        str(YEAR + 2): "interim_generic_market",
        str(YEAR + 3): "interim_generic_market",
    }
    assert policy["interimCurveLabel"] == (
        "provisional estimate — final rookie-auction curve pending"
    )
    assert all(p["curveMethod"] == "workbook_rookie_auction" for p in result["picks"])
    assert all(p["curveMethod"] == "interim_generic_market" for p in result["additionalClassPicks"])


def _cents(v):
    return round(v * 100)


def test_every_class_reconciles_exactly_in_integer_cents(server_mod, monkeypatch):
    """Owner addendum 2026-10-18: exactly $1,200.00 per class — pick dollars,
    team totals, year totals and All Years, with no rounding drift.  The
    workbook class (YEAR+1) stays the exact workbook dollars."""
    result = _run(server_mod, monkeypatch)
    every = result["picks"] + result["additionalClassPicks"]
    for season in (YEAR + 1, YEAR + 2, YEAR + 3):
        rows = result["teamTotalsByYear"][str(season)]
        assert sum(_cents(r["auctionDollars"]) for r in rows) == 120000
        assert _cents(result["yearSummaries"][str(season)]["totalDollars"]) == 120000
        if season != YEAR + 1:  # workbook class: totals come from the sheet
            assert (
                sum(
                    _cents(p["dollarValue"])
                    for p in every
                    if p["season"] == season and not p["isUnpriced"]
                )
                == 120000
            )
    assert sum(_cents(t["auctionDollars"]) for t in result["teamTotals"]) == 120000
    assert sum(_cents(r["auctionDollars"]) for r in result["allYearsTeamTotals"]) == 360000
    assert _cents(result["allYearsSummary"]["totalDollars"]) == 360000


@pytest.mark.parametrize("n_values", [1, 3, 7, 40, 72])
def test_allocator_is_exact_and_deterministic(n_values):
    """Values that do not divide $1,200 evenly still total exactly $1,200.00,
    and the same input always allocates the same way."""
    from src.api import draft_capital_classes as dcc

    values = [1000.0 + (i % 5) * 333.3 for i in range(n_values)]
    for unit in (1, 50, 100):
        out = dcc.allocate_class_budget(values, 1200, unit_cents=unit)
        assert sum(_cents(v) for v in out) == 120000
        assert out == dcc.allocate_class_budget(values, 1200, unit_cents=unit)
        # Linear in value: never more than one unit off the exact share.
        total = sum(values)
        for v, d in zip(values, out):
            assert abs(_cents(d) - v * 120000 / total) <= unit
    assert dcc.allocate_class_budget([], 1200) == []


def test_per_year_filtering_counts_and_all_years_without_double_count(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    y2 = result["teamTotalsByYear"][str(YEAR + 2)]
    ann, bob = _row(y2, "Team-Ann"), _row(y2, "Team-Bob")
    assert (ann["pickCount"], ann["acquiredPickCount"], ann["tradedAwayPickCount"]) == (3, 1, 0)
    assert (bob["pickCount"], bob["acquiredPickCount"], bob["tradedAwayPickCount"]) == (1, 0, 1)
    assert ann["auctionDollars"] == 1000 and ann["rank"] == 1
    assert bob["auctionDollars"] == 200 and bob["rank"] == 2
    # Each season's team capital is the sum of that season's picks it holds.
    for season in (YEAR + 2, YEAR + 3):
        for r in result["teamTotalsByYear"][str(season)]:
            held = [
                p["dollarValue"]
                for p in result["additionalClassPicks"]
                if p["season"] == season and p["currentOwner"] == r["team"] and not p["isUnpriced"]
            ]
            assert r["auctionDollars"] == pytest.approx(sum(held))
    # All Years: every class once.
    all_rows = result["allYearsTeamTotals"]
    assert result["allYearsSummary"]["pickCount"] == 12
    assert sum(r["pickCount"] for r in all_rows) == 12
    for r in all_rows:
        assert r["auctionDollars"] == pytest.approx(
            sum(v for v in r["draftCapitalByYear"].values() if v is not None)
        )
    total = sum(r["auctionDollars"] for r in all_rows)
    # workbook 1200 + YEAR+2 1200 + YEAR+3 1200 (priced picks only).
    assert total == pytest.approx(3600)


def test_failed_traded_picks_refuses_the_board(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch, traded=OSError("sleeper down"))
    assert result["error"] == "pick_ownership_unavailable"
    assert result["pickOwnershipState"] == "unavailable"
    assert result["pickOwnershipReason"] == "traded_picks_fetch_failed"
    assert "picks" not in result and "teamTotals" not in result


def test_non_list_traded_picks_body_refuses_the_board(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch, traded={"error": "rate limited"})
    assert result["error"] == "pick_ownership_unavailable"


def test_workbook_only_mode_adds_no_classes(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch, apply_sleeper_trades=False)
    assert "error" not in result
    assert result["additionalClassPicks"] == []
    assert result["additionalClassesState"] == "not_requested"


def test_unregistered_league_gets_no_unidentified_classes(server_mod, monkeypatch):
    monkeypatch.setattr(server_mod._league_registry, "league_key_for_sleeper_id", lambda _l: None)
    result = _run(server_mod, monkeypatch)
    assert result["additionalClassPicks"] == []
    assert result["additionalClassesState"] == "unavailable"
    assert result["additionalClassesReason"] == "league_not_in_registry"


def test_public_projection_is_safe(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    public = server_mod._redact_draft_capital_for_public(result)
    private = set(server_mod._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS)
    for p in public["picks"] + public["additionalClassPicks"]:
        assert not (set(p) & private)
    blob = json.dumps(public)
    assert LEAGUE_ID not in blob  # no raw Sleeper league id anywhere
    assert "rankDerivedValue" not in blob and "_canonicalValue" not in blob
