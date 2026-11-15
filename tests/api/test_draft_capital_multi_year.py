"""Batch E — multi-year draft capital on the rookie-auction curve (dynasty_main).

Drives the real workbook builder (``server._fetch_draft_capital``) for a
12-team x 6-round league registered as ``dynasty_main``, with a stubbed
Sleeper league and a stubbed 72-pick workbook, and pins (owner decisions
2026-10-18, ``docs/draft/DRAFT_VALUATION_WORKSTREAM.md`` Batch E):

* 216 unique owned-pick identities across the upcoming class and the two
  later classes, each exactly once;
* every class totals exactly $1,200 in whole dollars, All Years $3,600, and
  every team figure is the exact sum of the picks that team owns;
* the later classes are priced on the canonical rookie-auction curve —
  frozen 2026 provisional inputs + the class's own spine — through the
  per-year published allocation (current, else THAT year's last known good,
  else unavailable; never another year's dollars, never $0);
* round-level pricing for a class with no draft order: a round keeps its
  exact curve dollars, no slot is invented;
* per-year ``budgetBasis`` / ``curveId`` / ``spineYears`` / ``inputMode``;
* draft order from THE owner (``reverse_record_lower_pf``): standings to date
  are a labelled forecast, verified final standings are the rule's order;
* no double count of the upcoming class for the /trade stack.
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from datetime import datetime, timezone

import pytest

from src.api import draft_capital_classes as dcc
from src.api import draft_capital_order as dco
from src.draft.rookie_auction.published import REPO_STORE

YEAR = datetime.now(timezone.utc).year
LEAGUE_ID = "TEST_BATCH_E_LEAGUE"
LEAGUE_KEY = "dynasty_main"
TEAMS, ROUNDS = 12, 6


def _seed_reference():
    seed = next((REPO_STORE / LEAGUE_KEY / "2027").glob("*.json"))
    rec = json.loads(seed.read_text("utf-8"))
    return [float(r["dollars"]) for r in rec["referenceDollars"]]


REFERENCE = _seed_reference()
NAMES = {s: f"N{s:02d}" for s in range(1, TEAMS + 1)}


def _fake_workbook():
    picks = [
        {"round": r, "pick": s, "value": REFERENCE[(r - 1) * TEAMS + s - 1], "owner": NAMES[s]}
        for r in range(1, ROUNDS + 1)
        for s in range(1, TEAMS + 1)
    ]
    return [], picks, dict(NAMES), {}, [], list(REFERENCE)


def _sleeper(*, traded, records=None, status="in_season", later_draft=None):
    """A league whose YEAR rookie draft is complete AND rostered (retired), so
    its owned classes are YEAR+1 (the workbook class) .. YEAR+3."""
    records = records or {}
    rosters = []
    for rid in range(1, TEAMS + 1):
        w, lo, t, pf = records.get(rid, (0, 0, 0, 0))
        rosters.append(
            {
                "roster_id": rid,
                "owner_id": f"u{rid}",
                "players": [f"p{rid}_{k}" for k in range(ROUNDS)],
                "settings": {"wins": w, "losses": lo, "ties": t, "fpts": pf, "fpts_decimal": 0},
            }
        )
    users = [
        {"user_id": f"u{rid}", "display_name": f"Team-{NAMES[rid]}", "metadata": {}}
        for rid in range(1, TEAMS + 1)
    ]
    draft = {
        "draft_id": "D1",
        "season": str(YEAR),
        "status": "complete",
        "settings": {"rounds": ROUNDS, "player_type": 1},
        "slot_to_roster_id": {str(s): s for s in range(1, TEAMS + 1)},
    }
    picks = [
        {"player_id": f"p{rid}_{k}", "metadata": {"years_exp": "0"}}
        for rid in range(1, TEAMS + 1)
        for k in range(ROUNDS)
    ]
    drafts = [draft] + ([later_draft] if later_draft else [])
    meta = {
        "season": str(YEAR),
        "status": status,
        "settings": {
            "draft_rounds": ROUNDS,
            "num_teams": TEAMS,
            "playoff_week_start": 15,
            "start_week": 1,
            "league_average_match": 1,
        },
    }
    return {
        "meta": meta,
        f"/league/{LEAGUE_ID}/rosters": rosters,
        f"/league/{LEAGUE_ID}/users": users,
        f"/league/{LEAGUE_ID}/drafts": drafts,
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
    # Team 1 holds team 2's YEAR+2 first, and team 12's YEAR+3 first.
    {"season": str(YEAR + 2), "round": 1, "roster_id": 2, "owner_id": 1},
    {"season": str(YEAR + 3), "round": 1, "roster_id": 12, "owner_id": 1},
    # Team 5 holds team 3's YEAR+1 second (the workbook class).
    {"season": str(YEAR + 1), "round": 2, "roster_id": 3, "owner_id": 5},
    # Traded and traded back: not traded.
    {"season": str(YEAR + 2), "round": 3, "roster_id": 4, "owner_id": 4},
]


@pytest.fixture
def server_mod(monkeypatch):
    server = pytest.importorskip("server")
    import src.api.draft_class_evidence as dce

    monkeypatch.setattr(server, "_parse_draft_data", _fake_workbook)
    monkeypatch.setattr(server, "_sleeper_league_id_for_draft", lambda _k=None: LEAGUE_ID)
    monkeypatch.setattr(server, "_our_rookie_pool", lambda *_a, **_k: [])
    monkeypatch.setattr(
        server._league_registry,
        "league_key_for_sleeper_id",
        lambda lid: LEAGUE_KEY if lid == LEAGUE_ID else None,
    )
    monkeypatch.setattr(dce, "read_snapshot", lambda _lid: None)
    return server


def _run(server, monkeypatch, traded=TRADED, **sleeper_kwargs):
    monkeypatch.setattr(
        server.urllib.request, "urlopen", _urlopen(_sleeper(traded=traded, **sleeper_kwargs))
    )
    result = server._fetch_draft_capital(LEAGUE_KEY)
    assert "error" not in result, result
    return result


def _every(result):
    return result["picks"] + result["additionalClassPicks"]


# --- identities, totals, reconciliation -------------------------------------------------


def test_216_unique_identities_each_once(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    every = _every(result)
    assert result["availableYears"] == [YEAR + 1, YEAR + 2, YEAR + 3]
    assert len(every) == 216
    ids = [p["assetId"] for p in every]
    assert all(ids) and len(set(ids)) == 216
    keys = {(p["season"], p["round"], p["originRosterId"]) for p in every}
    assert len(keys) == 216
    assert keys == {
        (y, r, o)
        for y in (YEAR + 1, YEAR + 2, YEAR + 3)
        for r in range(1, ROUNDS + 1)
        for o in range(1, TEAMS + 1)
    }
    traded = next(p for p in every if p["assetId"] == f"pick:{LEAGUE_KEY}:{YEAR + 2}:r1:o2")
    assert traded["currentOwnerRosterId"] == 1 and traded["isTraded"] is True
    back = next(p for p in every if p["assetId"] == f"pick:{LEAGUE_KEY}:{YEAR + 2}:r3:o4")
    assert back["isTraded"] is False and back["currentOwnerRosterId"] == 4


def test_each_class_is_exactly_1200_whole_dollars_and_all_years_3600(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    every = _every(result)
    assert all(isinstance(p["dollarValue"], int) and p.get("isUnpriced") is not True for p in every)
    by_class = defaultdict(int)
    owned = defaultdict(int)
    owned_by_year = defaultdict(int)
    for p in every:
        by_class[p["season"]] += p["dollarValue"]
        owned[p["currentOwner"]] += p["dollarValue"]
        owned_by_year[(p["currentOwner"], p["season"])] += p["dollarValue"]
    assert dict(by_class) == {YEAR + 1: 1200, YEAR + 2: 1200, YEAR + 3: 1200}
    for season, rows in result["teamTotalsByYear"].items():
        assert sum(r["auctionDollars"] for r in rows) == 1200
        for r in rows:
            assert r["auctionDollars"] == owned_by_year.get((r["team"], int(season)), 0)
    for r in result["allYearsTeamTotals"]:
        assert isinstance(r["auctionDollars"], int)
        assert r["auctionDollars"] == owned.get(r["team"], 0)
    assert result["allYearsSummary"]["totalDollars"] == 3600
    assert result["budgetPolicy"]["allYearsBudget"] == 3600
    assert result["budgetPolicy"]["unpricedClasses"] == []
    for t in result["teamTotals"]:
        assert t["auctionDollars"] == owned_by_year.get((t["team"], YEAR + 1), 0)


def test_no_upcoming_class_double_count_for_the_trade_stack(server_mod, monkeypatch):
    """/trade's stack (``pick-stack.js::ownedPickStackInventory``) treats a
    season in ``coveredPickYears`` and every PRICED ``picks`` assetId as
    already inside ``teamTotals``; ``additionalClassPicks`` never feeds
    ``teamTotals``.  So the upcoming class must live in ``picks`` only, fully
    priced, and ``teamTotals`` must be that class alone."""
    result = _run(server_mod, monkeypatch)
    assert result["coveredPickYears"] == [YEAR + 1]
    assert result["upcomingDraftYear"] == YEAR + 1
    assert {p["season"] for p in result["picks"]} == {YEAR + 1}
    assert YEAR + 1 not in {p["season"] for p in result["additionalClassPicks"]}
    wb_ids = {p["assetId"] for p in result["picks"]}
    assert len(wb_ids) == 72 and None not in wb_ids
    assert not wb_ids & {p["assetId"] for p in result["additionalClassPicks"]}
    assert all(p.get("isUnpriced") is not True for p in result["picks"])
    assert sum(t["auctionDollars"] for t in result["teamTotals"]) == 1200


# --- the later classes' curve -------------------------------------------------------


def _allocation(year):
    return dcc.resolve_class_curve_allocation(LEAGUE_KEY, year, persist=False)


def test_later_classes_follow_their_own_published_allocation_round_level(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    for season in (YEAR + 2, YEAR + 3):
        alloc = _allocation(season)
        assert alloc.allocation_state == "current" and sum(alloc.final_whole_dollars) == 1200
        rows = [p for p in result["additionalClassPicks"] if p["season"] == season]
        assert len(rows) == 72
        for p in rows:
            assert p["slotStatus"] == "unknown" and p["slot"] is None
            assert p["pick"] == f"R{p['round']}"
            assert p["curveMethod"] == "workbook_rookie_auction"
            assert p["inputMode"] == "frozen_fallback"
            assert p["valueBasis"] == "rookie_auction_round_share"
            assert p["roundShareRule"] == dcc.ROUND_SHARE_RULE
        for rnd in range(1, ROUNDS + 1):
            curve = alloc.final_whole_dollars[(rnd - 1) * TEAMS : rnd * TEAMS]
            got = [p["dollarValue"] for p in rows if p["round"] == rnd]
            # The round keeps its exact curve dollars; shares differ by <= $1.
            assert sum(got) == sum(curve)
            assert max(got) - min(got) <= 1
            assert all(min(curve) <= d <= max(curve) for d in got)


def test_per_year_api_fields(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    classes = result["budgetPolicy"]["classes"]
    assert sorted(classes) == [str(YEAR + 1), str(YEAR + 2), str(YEAR + 3)]
    for season in (YEAR + 2, YEAR + 3):
        block = classes[str(season)]
        assert block["budgetBasis"] == "per_class_pool" and block["budget"] == 1200
        assert block["inputMode"] == "frozen_fallback" and block["provisional"] is True
        assert block["spineYears"] == [2024, 2025, 2026]
        assert block["curveId"] == (
            "draft_data_workbook_v1|frozen_fallback:2026_spreadsheet_baseline|spine:2024-2025-2026"
        )
        assert block["allocationState"] == "current"
        assert block["recordChecksum"]
        assert block["draftYear"] == season
    assert classes[str(YEAR + 2)]["recordChecksum"] != classes[str(YEAR + 3)]["recordChecksum"]
    wb = classes[str(YEAR + 1)]
    assert wb["budgetBasis"] == "per_class_pool" and wb["curveMethod"] == "workbook_rookie_auction"
    policy = result["budgetPolicy"]
    assert set(policy["classCurveMethods"].values()) == {"workbook_rookie_auction"}
    assert policy["interimCurveLabel"] is None
    assert YEAR + 2 in policy["provisionalClasses"] and YEAR + 3 in policy["provisionalClasses"]
    assert policy["provisionalCurveLabel"] == dcc.PROVISIONAL_CURVE_LABEL


def test_failed_refresh_serves_that_years_last_known_good_never_another_year(
    server_mod, monkeypatch
):
    real_inputs = dcc.class_curve_inputs

    def broken(league_key, year):
        if int(year) == YEAR + 3:
            from src.draft.rookie_auction.snapshots import SnapshotIntegrityError

            raise SnapshotIntegrityError("frozen baseline edited")
        return real_inputs(league_key, year)

    monkeypatch.setattr(dcc, "class_curve_inputs", broken)
    seeded = (REPO_STORE / LEAGUE_KEY / str(YEAR + 3)).is_dir()
    result = _run(server_mod, monkeypatch)
    block = result["budgetPolicy"]["classes"][str(YEAR + 3)]
    rows = [p for p in result["additionalClassPicks"] if p["season"] == YEAR + 3]
    if seeded:
        # The SAME year's stored allocation, labelled — not YEAR+2's.
        assert block["allocationState"] == "last_known_good"
        assert "frozen baseline edited" in block["failedRefresh"]["reason"]
        assert sum(p["dollarValue"] for p in rows) == 1200
    else:
        assert block["allocationState"] == "unavailable"
        assert all(p["dollarValue"] is None for p in rows)
    # The healthy class is untouched.
    assert result["budgetPolicy"]["classes"][str(YEAR + 2)]["allocationState"] == "current"


def test_no_verified_allocation_leaves_the_class_unpriced(server_mod, monkeypatch, tmp_path):
    from src.draft.rookie_auction.snapshots import SpineUnavailableError

    real_resolve = dcc.resolve_class_curve_allocation

    def no_store(league_key, year, **kw):
        if int(year) == YEAR + 3:
            monkeypatch.setattr(
                dcc,
                "class_curve_inputs",
                lambda *_a: (_ for _ in ()).throw(SpineUnavailableError("no spine")),
            )
            return real_resolve(
                league_key, year, store_dirs=[tmp_path / "empty"], write_dir=tmp_path / "w"
            )
        return real_resolve(league_key, year, **kw)

    monkeypatch.setattr(dcc, "resolve_class_curve_allocation", no_store)
    result = _run(server_mod, monkeypatch)
    rows = [p for p in result["additionalClassPicks"] if p["season"] == YEAR + 3]
    assert rows and all(p["isUnpriced"] is True and p["dollarValue"] is None for p in rows)
    assert all(p["unpricedReason"].startswith("no_verified_class_allocation") for p in rows)
    policy = result["budgetPolicy"]
    assert policy["unpricedClasses"] == [YEAR + 3]
    assert policy["allYearsBudget"] == 2400
    assert policy["classes"][str(YEAR + 3)]["allocationState"] == "unavailable"
    assert policy["classes"][str(YEAR + 3)]["curveId"] is None
    assert result["allYearsSummary"]["totalDollars"] == 2400


def test_known_slots_take_their_slot_dollars(server_mod, monkeypatch):
    """A later class whose Sleeper draft object carries an order prices each
    pick at its slot (KNOWN), not a round share."""
    order = {str(s): TEAMS + 1 - s for s in range(1, TEAMS + 1)}  # roster 12 picks first
    later = {"draft_id": "D2", "season": str(YEAR + 2), "status": "pre_draft"}
    later["slot_to_roster_id"] = order
    result = _run(server_mod, monkeypatch, later_draft=later)
    alloc = _allocation(YEAR + 2)
    rows = [p for p in result["additionalClassPicks"] if p["season"] == YEAR + 2]
    for p in rows:
        assert p["slotStatus"] == "known"
        assert p["slot"] == TEAMS + 1 - p["originRosterId"]
        assert p["valueBasis"] == "rookie_auction_slot"
        assert p["dollarValue"] == alloc.dollars_by_slot()[f"{p['round']}.{p['slot']:02d}"]
    assert sum(p["dollarValue"] for p in rows) == 1200


# --- draft order -----------------------------------------------------------------------


def _records(final=False):
    games = 28 if final else 10
    # wins chosen so roster 7 is worst; 11 and 12 tie on record (12 lower PF).
    wins = {1: 9, 2: 2, 3: 6, 4: 6, 5: 7, 6: 6, 7: 0, 8: 8, 9: 8, 10: 5, 11: 2, 12: 2}
    pf = {1: 2021, 2: 1572, 3: 1736, 4: 1892, 5: 1971, 6: 1919}
    pf.update({7: 1354, 8: 2068, 9: 2192, 10: 1888, 11: 1474, 12: 1362})
    scale = 2 if final else 1
    return {rid: (wins[rid] * scale, games - wins[rid] * scale, 0, pf[rid]) for rid in wins}


def _slot_of(result, rid):
    p = next(p for p in result["picks"] if p["round"] == 1 and p["originRosterId"] == rid)
    return p["pickInRound"], p["slotStatus"]


def test_standings_to_date_are_a_labelled_forecast_by_the_owner_rule(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch, records=_records())
    assert result["draftOrder"]["basis"] == "standings_to_date"
    assert result["draftOrder"]["final"] is False
    assert result["draftOrder"]["rule"] == "reverse_record_lower_pf"
    # Worst record first; tied on record → LOWER Points For first (12 before 11
    # before 2 at two wins).  Points For alone would have put 12 at slot 2.
    assert _slot_of(result, 7) == (1, "projected")
    assert _slot_of(result, 12) == (2, "projected")
    assert _slot_of(result, 11) == (3, "projected")
    assert _slot_of(result, 2) == (4, "projected")
    assert _slot_of(result, 1) == (12, "projected")  # best record (9 wins)
    # Ownership follows the reshuffle: untraded picks stay with their origin.
    for p in result["picks"]:
        if not p["isTraded"]:
            assert p["currentOwnerRosterId"] == p["originRosterId"]
    assert sum(t["auctionDollars"] for t in result["teamTotals"]) == 1200


def test_verified_final_standings_are_the_rules_order(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch, records=_records(final=True), status="post_season")
    assert result["draftOrder"]["basis"] == "final_standings"
    assert result["draftOrder"]["final"] is True
    assert _slot_of(result, 7) == (1, "final_standings")
    assert _slot_of(result, 12) == (2, "final_standings")
    assert {p["slotStatus"] for p in result["picks"]} == {"final_standings"}
    # Later classes stay round-level: their seasons are unplayed.
    assert {p["slotStatus"] for p in result["additionalClassPicks"]} == {"unknown"}


def test_no_games_played_keeps_the_existing_projected_order(server_mod, monkeypatch):
    result = _run(server_mod, monkeypatch)
    assert result["draftOrder"]["basis"] == "unavailable"
    assert result["draftOrder"]["reason"] == "no_games_played"
    assert _slot_of(result, 1) == (1, "projected")


@pytest.mark.parametrize("field", ["wins", "losses", "ties", "fpts", "fpts_decimal"])
def test_board_with_a_missing_record_field_keeps_projected_order_with_reason(
    server_mod, monkeypatch, field
):
    """An unknown win / loss / tie / PF makes the standings unverifiable: the
    draft order is ``unavailable`` with the reason, the slots stay the existing
    projected order — the missing value is never read as 0."""
    responses = _sleeper(traded=TRADED, records=_records(final=True))
    meta = responses["meta"]
    meta["status"] = "post_season"
    del responses[f"/league/{LEAGUE_ID}/rosters"][6]["settings"][field]  # roster 7
    monkeypatch.setattr(server_mod.urllib.request, "urlopen", _urlopen(responses))
    result = server_mod._fetch_draft_capital(LEAGUE_KEY)
    assert "error" not in result, result
    assert result["draftOrder"]["basis"] == "unavailable"
    assert result["draftOrder"]["reason"] == f"standings_record_missing:roster_7:{field}"
    assert {p["slotStatus"] for p in result["picks"]} == {"projected"}
    # Roster 7 has the worst record, yet without its full record it is NOT moved
    # to slot 1: the last draft's order stands.
    assert _slot_of(result, 7) == (7, "projected")
    assert sum(t["auctionDollars"] for t in result["teamTotals"]) == 1200


@pytest.mark.parametrize("field", ["playoff_week_start", "start_week", "league_average_match"])
def test_board_with_unknown_season_length_is_never_final(server_mod, monkeypatch, field):
    responses = _sleeper(traded=TRADED, records=_records(final=True), status="post_season")
    del responses["meta"]["settings"][field]
    monkeypatch.setattr(server_mod.urllib.request, "urlopen", _urlopen(responses))
    result = server_mod._fetch_draft_capital(LEAGUE_KEY)
    assert "error" not in result, result
    order = result["draftOrder"]
    assert order["basis"] == "standings_to_date" and order["final"] is False
    assert order["reason"] == f"regular_season_length_unknown:{field}"
    assert {p["slotStatus"] for p in result["picks"]} == {"projected"}


# --- the adapters, as units ---------------------------------------------------------


def _rosters(records):
    return [
        {
            "roster_id": rid,
            "settings": {"wins": w, "losses": lo, "ties": t, "fpts": pf, "fpts_decimal": 50},
        }
        for rid, (w, lo, t, pf) in records.items()
    ]


def _meta(status="complete", season=2026):
    return {
        "season": str(season),
        "status": status,
        "settings": {"playoff_week_start": 15, "start_week": 1, "league_average_match": 1},
    }


def _rows(rosters):
    rows, reason = dco.sleeper_standings_rows(rosters)
    assert reason is None
    return rows


def test_final_standings_need_every_regular_season_game():
    rec = _records(final=True)
    rows = _rows(_rosters(rec))
    assert dco.regular_season_final(_meta(), rows)[0] is True
    assert dco.regular_season_final(_meta(status="in_season"), rows)[0] is False
    short = dict(rec)
    short[3] = (11, 16, 0, 1736)  # 27 games
    ok, reason = dco.regular_season_final(_meta(), _rows(_rosters(short)))
    assert ok is False and reason.startswith("records_not_final:expected_28_games:3")


@pytest.mark.parametrize("field", ["playoff_week_start", "start_week", "league_average_match"])
def test_unknown_season_length_is_not_defaulted(field):
    """An unknown game count is never 1 game a week or week 1: without it,
    "final" cannot be verified."""
    meta = _meta()
    del meta["settings"][field]
    ok, reason = dco.regular_season_final(meta, _rows(_rosters(_records(final=True))))
    assert ok is False and reason == f"regular_season_length_unknown:{field}"


def test_inconsistent_season_length_is_not_final():
    meta = _meta()
    meta["settings"]["league_average_match"] = 7
    ok, reason = dco.regular_season_final(meta, _rows(_rosters(_records(final=True))))
    assert ok is False and reason == "regular_season_length_unknown:inconsistent_settings"


@pytest.mark.parametrize("field", ["wins", "losses", "ties", "fpts", "fpts_decimal"])
def test_a_missing_record_field_is_unknown_never_zero(field):
    rosters = _rosters(_records())
    del rosters[4]["settings"][field]  # roster 5
    rows, reason = dco.sleeper_standings_rows(rosters)
    assert rows is None and reason == f"standings_record_missing:roster_5:{field}"
    order = dco.class_slot_order(
        league_key="dynasty_main",
        league_meta=_meta(status="in_season"),
        rosters=rosters,
        class_year=2027,
        roster_ids=range(1, 13),
    )
    assert order.basis == "unavailable" and order.slot_by_roster is None
    assert order.ordered is False and order.final is False
    assert order.reason == f"standings_record_missing:roster_5:{field}"


def test_a_missing_roster_is_unknown():
    rosters = [r for r in _rosters(_records()) if r["roster_id"] != 9]
    rows, reason = dco.sleeper_standings_rows(rosters, range(1, 13))
    assert rows is None and reason == "standings_roster_missing:9"


def test_class_slot_order_is_scoped_to_the_rule_and_the_next_class():
    rosters = _rosters(_records())
    kw = {"league_meta": _meta(status="in_season"), "rosters": rosters, "roster_ids": range(1, 13)}
    other = dco.class_slot_order(league_key="dynasty_new", class_year=2027, **kw)
    assert other.basis == "unavailable" and other.reason.startswith("no_recorded_draft_order_rule")
    later = dco.class_slot_order(league_key="dynasty_main", class_year=2028, **kw)
    assert later.basis == "unavailable"
    assert later.reason == "standings_of_2026_do_not_decide_class_2028"
    no_season = dco.class_slot_order(
        league_key="dynasty_main",
        league_meta={"status": "in_season"},
        rosters=rosters,
        class_year=2027,
        roster_ids=range(1, 13),
    )
    assert no_season.basis == "unavailable" and no_season.reason == "league_season_unknown"
    order = dco.class_slot_order(league_key="dynasty_main", class_year=2027, **kw)
    assert order.ordered and order.final is False
    assert order.slot_by_roster[7] == 1 and order.slot_by_roster[12] == 2


def test_round_share_refuses_a_class_with_an_unidentified_pick():
    alloc = _allocation(2028)
    rows = [
        {"season": 2028, "round": r, "slot": None, "assetId": f"pick:x:2028:r{r}:o{o}"}
        for r in range(1, 7)
        for o in range(1, 13)
    ]
    rows[3]["assetId"] = None
    dcc.price_classes_on_curve(rows, {2028: alloc}, team_count=12, rounds=6)
    assert all(r["dollarValue"] is None and r["isUnpriced"] for r in rows)
    assert rows[0]["unpricedReason"] == "asset_id_missing:round_1"


def test_final_tie_on_record_and_points_for_is_not_called_final():
    rec = _records(final=True)
    rec[12] = (rec[11][0], rec[11][1], 0, rec[11][3])  # identical record AND PF
    order = dco.class_slot_order(
        league_key="dynasty_main",
        league_meta=_meta(),
        rosters=_rosters(rec),
        class_year=2027,
        roster_ids=range(1, 13),
    )
    assert order.final is False
    assert order.reason == "final_standings_tied_on_record_and_points_for"
    assert order.unresolved_ties == ((11, 12),)


def test_price_classes_refuses_a_class_of_the_wrong_shape():
    alloc = _allocation(2028)
    rows = [
        {"season": 2028, "round": r, "slot": None, "assetId": f"a{r}{o}", "originRosterId": o}
        for r in range(1, 7)
        for o in range(1, 11)  # 10 teams, not 12
    ]
    dcc.price_classes_on_curve(rows, {2028: alloc}, team_count=10, rounds=6)
    assert all(r["dollarValue"] is None and r["isUnpriced"] for r in rows)
    assert rows[0]["unpricedReason"].startswith("class_shape_mismatch")


def test_unconfigured_league_has_no_class_curve():
    out = dcc.resolve_class_curve_allocation("dynasty_new", 2028, persist=False)
    assert out.allocation_state == "unavailable"
    assert out.unavailable_reason == "league_not_configured:dynasty_new"
    assert out.final_whole_dollars is None


def test_served_record_decides_input_mode_and_curve_id():
    """A last-known-good or promoted record describes ITSELF: the per-year
    fields come from the served record's provenance, never from the request."""
    from types import SimpleNamespace

    def served(prov):
        return SimpleNamespace(
            receipt={"formulaVersion": "draft_data_workbook_v1", "provenance": prov},
            record_checksum="ab" * 32,
            allocation_state="current",
            effective_at=None,
            last_valid_at=None,
            failed_refresh=None,
            unavailable_reason=None,
            warning=None,
        )

    promoted = served(
        {
            "source": "canonical_class_snapshot",
            "classSnapshotSha256": "cd" * 32,
            "spineYears": [2025, 2026, 2027],
        }
    )
    block = dcc.class_valuation_block(promoted, draft_year=2028, budget=1200, priced=True)
    assert block["inputMode"] == "actual" and block["provisional"] is False
    assert block["curveId"] == "draft_data_workbook_v1|actual:" + "cd" * 8 + "|spine:2025-2026-2027"
    unknown = served({"source": "draft_data_workbook"})
    block = dcc.class_valuation_block(unknown, draft_year=2027, budget=1200, priced=True)
    assert block["inputMode"] is None and block["spineYears"] is None
    assert block["curveId"] == "draft_data_workbook_v1|record:" + "ab" * 8
