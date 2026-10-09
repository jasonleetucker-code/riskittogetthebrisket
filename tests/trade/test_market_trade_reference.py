"""TC-07 / TC-10 — recent real trades touching the calculator's assets.

``src.trade.market_trade_reference`` is a display projection of the canonical
underlying-trade ledger.  Pinned here, on a synthetic ledger persisted through
the ledger owner's own writer:

* asset touch — players by canonical id only, picks at two NAMED grades
  (exact / round), different refinements never match;
* privacy — KTC visible; Sharp only with a cohort manager on the trade;
  own-league only for the requested league; a registry league (or its season
  chain) reached through another lane withheld; unknown families withheld;
  unverified game type withheld; no host/league/tx/manager id or
  underlying-trade id in the output (row ids are a per-process HMAC);
* format tags and dispositions are the ledger's own, verbatim; UNKNOWN stays
  ``None`` (never the target league's format);
* evidence timing is the ledger owner's ``format_timing_cap``;
* no valuation is read or computed.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from src.trade import market_trade_format as mtf
from src.trade import market_trade_reference as ref
from src.trade import market_trade_report as report

TODAY = date(2026, 10, 8)
LEAGUE = "dynasty_main"
OTHER = "dynasty_new"

SECRET_IDS = (
    "998877665544332211",  # host league id
    "112233445566778899",  # host tx id
    "777777777777777777",  # KTC league id
)


def _player(sid, label=None):
    cid = f"player:{sid}"
    return {
        "kind": "player",
        "canonicalId": cid,
        "matchKey": cid,
        "position": "WR",
        "vendorRef": sid,
        "label": label,
        "resolution": {"status": "resolved", "method": "sleeper_id"},
    }


def _pick(year, rnd, *, tier=None, slot=None, vendor_ref=None):
    from src.identity.picks import MarketPickRef

    r = MarketPickRef(year=year, round_num=rnd, tier=tier, slot=slot)
    return {
        "kind": "pick",
        "canonicalId": r.canonical_id,
        "matchKey": MarketPickRef(year=year, round_num=rnd).canonical_id,
        "vendorRef": vendor_ref or r.canonical_id,
        "label": vendor_ref or r.canonical_id,
        "pick": {"year": year, "round": rnd, "grade": r.grade, "vendorGrade": r.grade},
        "resolution": {"status": "resolved", "method": "pick_label"},
    }


def _unresolved(label):
    return {
        "kind": "unresolved",
        "canonicalId": None,
        "matchKey": f"unresolved:{label}",
        "vendorRef": "ktc-123",
        "label": label,
        "resolution": {"status": "unresolved", "method": "ktc_identity", "reason": "ambiguous"},
    }


KTC_FMT = mtf.format_from_ktc_settings(
    {
        "id": "777777777777777777",
        "teams": 12,
        "tep": 2,
        "ppr": 1,
        "leagueStartingLineup": {
            "count": 10,
            "position": [
                {"name": "QB", "limit": "1-2"},
                {"name": "RB", "limit": "2-4"},
                {"name": "WR", "limit": "3-5"},
                {"name": "TE", "limit": "1-3"},
            ],
        },
    }
)

SLEEPER_FMT = mtf.TradeMarketFormat(
    source=mtf.SOURCE_SLEEPER,
    dynasty_state=mtf.DYNASTY,
    teams=12,
    best_ball=False,
    season="2026",
    demand={"QB": (1, 2), "RB": (2, 4), "WR": (3, 5), "TE": (1, 3)},
    total_starters=11,
    idp_enabled=False,
    scoring={"rec": 0.5, "pass_td": 4.0},
)

# Partial discovery row: only team count known.
PARTIAL_FMT = mtf.TradeMarketFormat(source=mtf.SOURCE_SLEEPER, dynasty_state=mtf.DYNASTY, teams=10)

EXACT_EVIDENCE = {
    "timing": "at_or_before_trade",
    "exactAtTradeTime": True,
    "confirmationAfterTrade": "confirmed",
    "capturedAt": "2026-09-01T00:00:00Z",
    "captureId": "cap-secret",
    "payloadSha256": "f" * 64,
    "seasonLeagueId": "998877665544332211",
}
POST_TRADE_EVIDENCE = {"timing": "post_trade_capture", "exactAtTradeTime": False}


def _group(
    gid,
    *,
    date_,
    families,
    sides,
    fmt,
    members=None,
    league_key=None,
    evidence=None,
    format_source=None,
    target=LEAGUE,
    disposition="BROAD_CONTEXT",
    host="sleeper",
    host_league_id="998877665544332211",
):
    return {
        "underlyingTradeId": gid,
        "dedupeState": "CONFIRMED_UNIQUE",
        "members": members or [f"{families[0]}:{gid}"],
        "observationCount": len(members or [1]),
        "sourceFamilies": families,
        "provenance": ["KTC_MARKET"] if families == [ref.SOURCE_KTC] else ["SHARP_DISCOVERY"],
        "relations": [],
        "possibleOverlapWith": [],
        "representativeObservationId": (members or [f"{families[0]}:{gid}"])[0],
        "host": host,
        "hostLeagueId": host_league_id,
        "hostTxId": "112233445566778899",
        "occurredDate": date_,
        "occurredAtMs": None,
        "teamCount": len(sides),
        "sides": sides,
        "formatSource": format_source,
        "formatEvidence": evidence,
        "_format": fmt,
        "marketFormat": fmt.to_dict(),
        "vendorFlags": {"isUsedInVft": True, "vftFavoredSide": 0},
        "sampleProvenance": [{"lane": "sharp_discovery_graph", "discovery": "secret"}],
        "caveats": ["released_in_trade:1"] if families == [ref.SOURCE_SHARP] else [],
        "leagueKey": league_key,
        "targetLeague": target,
        "disposition": disposition,
        "strongestUnsupportedAxis": "teScoring",
        "comparability": {},
        "formatAuthority": None,
        "translation": None,
        "targetPriceAuthority": 0,
        "broadContextKind": "format_unknown",
        "dispositionReasons": ["te_scoring_unknown"],
    }


SHARP_LID, SHARP_TX = "998877665544332211", "112233445566778899"
REGISTRY_LID = "123412341234123412"


def _privacy(*, chain_resolved=True, cohort=None, registry=(REGISTRY_LID,)):
    """A fake PrivacyContext.  ``cohort`` maps (league, tx) -> True/False/None;
    the default says the fixture's Sharp trade has a cohort manager."""
    cohort = {(SHARP_LID, SHARP_TX): True} if cohort is None else cohort
    return lambda: ref.PrivacyContext(
        registry_league_ids=frozenset(registry),
        chain_resolved=chain_resolved,
        sharp_trade_has_cohort_manager=lambda lid, tx: cohort.get((lid, tx)),
    )


def _fixture_groups():
    return [
        # KTC (MFL-hosted): Jefferson + 2027 Early 1st  <->  Unresolved name
        _group(
            "utrade:ktc_trade_database:1",
            date_="2026-10-01",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794"), _pick(2027, 1, tier="early")], [_unresolved("J. Smith")]],
            fmt=KTC_FMT,
            host="mfl",
            host_league_id="777777777777777777",
        ),
        # Sharp: 2027 generic 1st <-> Chase; exact-at-trade evidence.
        _group(
            f"utrade:sleeper:{SHARP_LID}:{SHARP_TX}",
            date_="2026-09-20",
            families=[ref.SOURCE_SHARP],
            members=[f"sleeper_sharp_discovery:{SHARP_LID}:{SHARP_TX}"],
            sides=[[_pick(2027, 1)], [_player("7564")]],
            fmt=SLEEPER_FMT,
            evidence=EXACT_EVIDENCE,
            format_source="sleeper_league_capture_full",
        ),
        # KTC 2027 Late 1st only — must NOT match an Early 1st query.
        _group(
            "utrade:ktc_trade_database:2",
            date_="2026-09-15",
            families=[ref.SOURCE_KTC],
            sides=[[_pick(2027, 1, tier="late")], [_player("1111")]],
            fmt=KTC_FMT,
            host="mfl",
            host_league_id="777777777777777777",
        ),
        # Own league (this league): owned pick + Jefferson, post-trade capture.
        _group(
            "utrade:sleeper:own:1",
            date_="2026-09-10",
            families=[ref.SOURCE_OWN],
            members=[f"own_league_sleeper:{LEAGUE}:555"],
            league_key=LEAGUE,
            sides=[
                [_pick(2028, 2, vendor_ref=f"pick:{LEAGUE}:2028:r2:o3")],
                [_player("6794")],
            ],
            fmt=PARTIAL_FMT,
            evidence=POST_TRADE_EVIDENCE,
            format_source="season_league_settings_post_trade",
        ),
        # Own league of ANOTHER registry league (Sharp also saw it; rep is Sharp).
        _group(
            "utrade:sleeper:own:2",
            date_="2026-09-12",
            families=[ref.SOURCE_OWN, ref.SOURCE_SHARP],
            members=["sleeper_sharp_discovery:1:2", f"own_league_sleeper:{OTHER}:556"],
            league_key=None,
            sides=[[_player("6794")], [_player("2222")]],
            fmt=PARTIAL_FMT,
        ),
        # Unknown family.
        _group(
            "utrade:mystery:1",
            date_="2026-09-11",
            families=["mystery_lane"],
            sides=[[_player("6794")], [_player("3333")]],
            fmt=PARTIAL_FMT,
        ),
        # Too old for the lookback.
        _group(
            "utrade:ktc_trade_database:old",
            date_="2024-01-01",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794")], [_player("4444")]],
            fmt=KTC_FMT,
        ),
        # Undated — cannot be "recent".
        _group(
            "utrade:ktc_trade_database:undated",
            date_=None,
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794")], [_player("5555")]],
            fmt=KTC_FMT,
        ),
    ]


def _persist(root, groups, built_at="2026-10-08T08:52:00Z"):
    report.persist_canonical_ledger(
        groups, root=root, built_at=built_at, extra_meta={"targetLeague": LEAGUE}
    )


@pytest.fixture
def ledger_root(tmp_path):
    _persist(tmp_path, _fixture_groups())
    return tmp_path


def _run(root, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("privacy", _privacy())
    return ref.reference_trades(kw.pop("league", LEAGUE), root=root, **kw)


def _ids_by_date(body):
    return [t["occurredDate"] for t in body["trades"]]


def test_no_ledger_is_unavailable_not_empty(tmp_path):
    body = ref.reference_trades(LEAGUE, player_ids=["6794"], root=tmp_path, today=TODAY)
    assert body["state"] == "unavailable"
    assert body["reason"] == "trade_ledger_not_built"
    assert body["ledger"] is None


def test_no_assets_is_its_own_state(ledger_root):
    body = _run(ledger_root)
    assert body["state"] == "no_assets"
    assert body["trades"] == []
    assert body["ledger"]["builtAt"] == "2026-10-08T08:52:00Z"
    assert body["ledger"]["tradesInWindow"] == 6  # old + undated outside the window


def test_player_touch_by_canonical_id_newest_first(ledger_root):
    body = _run(ledger_root, player_ids=["6794"])
    assert body["state"] == "ok"
    # KTC 10-01 and own-league 09-10; other-league own, unknown family, old,
    # undated all absent.
    assert _ids_by_date(body) == ["2026-10-01", "2026-09-10"]
    assert body["withheld"] == {"own_league_other_league": 1, "unknown_source_family": 1}
    jeff = body["trades"][0]["sides"][0][0]
    assert jeff["canonicalId"] == "player:6794" and jeff["match"] == "exact"


def test_player_names_come_from_the_board_never_from_matching(ledger_root):
    names = {"6794": {"name": "Justin Jefferson", "position": "WR"}}
    body = _run(ledger_root, player_ids=["6794"], names=names)
    side0 = body["trades"][0]["sides"][0]
    assert side0[0]["label"] == "Justin Jefferson" and side0[0]["onBoard"] is True
    # Unresolved KTC asset keeps the vendor's text and never matches.
    other = body["trades"][0]["sides"][1][0]
    assert other["kind"] == "unresolved" and other["label"] == "J. Smith"
    assert other["match"] is None and other["unresolvedReason"] == "ambiguous"


def test_unresolved_ledger_asset_cannot_match_by_name(ledger_root):
    # Even a query that LOOKS like the vendor text never matches it.
    body = _run(ledger_root, player_ids=["J. Smith"])
    assert body["query"]["unresolved"] == [{"ref": "J. Smith", "reason": "invalid_player_id"}]
    assert body["state"] == "no_assets"


def test_pick_grades_exact_round_and_never_a_different_tier(ledger_root):
    body = _run(ledger_root, pick_names=["2027 Early 1st"])
    by_date = {t["occurredDate"]: t for t in body["trades"]}
    # KTC Early 1st -> exact; Sharp generic 2027 1st -> round; KTC Late 1st -> absent.
    assert set(by_date) == {"2026-10-01", "2026-09-20"}
    assert by_date["2026-10-01"]["sides"][0][1]["match"] == "exact"
    assert by_date["2026-09-20"]["sides"][0][0]["match"] == "round"
    assert by_date["2026-09-20"]["exactMatches"] == 0


def test_generic_vs_generic_is_round_never_exact(ledger_root):
    """B2: two generic "2027 1st" references are not provably the same pick —
    ``exact`` needs the same tier/slot or the same owned league pick."""
    body = _run(ledger_root, pick_names=["2027 Round 1"])
    matches = sorted(
        (t["occurredDate"], a["match"])
        for t in body["trades"]
        for s in t["sides"]
        for a in s
        if a["match"]
    )
    assert matches == [
        ("2026-09-15", "round"),
        ("2026-09-20", "round"),
        ("2026-10-01", "round"),
    ]
    assert all(t["exactMatches"] == 0 for t in body["trades"])


def test_owned_pick_identity(ledger_root):
    body = _run(ledger_root, pick_asset_ids=[f"pick:{LEAGUE}:2028:r2:o3"])
    assert _ids_by_date(body) == ["2026-09-10"]
    pick = body["trades"][0]["sides"][0][0]
    assert pick["match"] == "exact"
    assert pick["label"] == "2028 Round 2"  # board name, never the internal id
    assert body["trades"][0]["ownLeagueTrade"] is True
    # A different owned pick of the same round is only a round match.
    near = _run(ledger_root, pick_asset_ids=[f"pick:{LEAGUE}:2028:r2:o9"])
    assert near["trades"][0]["sides"][0][0]["match"] == "round"
    # Another league's owned pick is refused, not silently matched.
    other = _run(ledger_root, pick_asset_ids=[f"pick:{OTHER}:2028:r2:o3"])
    assert other["query"]["unresolved"][0]["reason"] == "owned_pick_other_league"
    assert other["state"] == "no_assets"


def test_other_league_sees_only_its_own_trades(ledger_root):
    body = _run(ledger_root, league=OTHER, player_ids=["6794"])
    dates = _ids_by_date(body)
    # Its own trade (09-12) visible; dynasty_main's own trade (09-10) withheld.
    assert "2026-09-12" in dates and "2026-09-10" not in dates
    assert body["withheld"]["own_league_other_league"] == 1


def test_game_type_must_be_verified_dynasty(tmp_path):
    """B3: unverified game type is not dynasty — withheld and counted."""
    unknown_type = mtf.TradeMarketFormat(source=mtf.SOURCE_SLEEPER, teams=12)
    redraft = mtf.TradeMarketFormat(source=mtf.SOURCE_SLEEPER, dynasty_state=mtf.REDRAFT)
    groups = [
        _group(
            "utrade:ktc_trade_database:u",
            date_="2026-10-02",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794")], [_player("1")]],
            fmt=unknown_type,
            host="mfl",
        ),
        _group(
            "utrade:ktc_trade_database:r",
            date_="2026-10-03",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794")], [_player("2")]],
            fmt=redraft,
            host="mfl",
        ),
        _group(
            "utrade:ktc_trade_database:d",
            date_="2026-10-01",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794")], [_player("3")]],
            fmt=KTC_FMT,
            host="mfl",
        ),
    ]
    _persist(tmp_path, groups)
    body = _run(tmp_path, player_ids=["6794"])
    assert _ids_by_date(body) == ["2026-10-01"]
    assert body["withheld"] == {ref.WITHHELD_GAME_TYPE: 2}
    assert body["trades"][0]["formatTags"]["dynastyState"] == mtf.DYNASTY


def test_sharp_rows_need_a_cohort_manager(ledger_root):
    """F5: a Sharp-lane trade is shown only when a cohort manager is on it."""
    seen = _run(ledger_root, player_ids=["7564"])
    assert _ids_by_date(seen) == ["2026-09-20"]
    no = _run(
        ledger_root, player_ids=["7564"], privacy=_privacy(cohort={(SHARP_LID, SHARP_TX): False})
    )
    assert no["trades"] == [] and no["withheld"] == {ref.WITHHELD_NO_COHORT_MANAGER: 1}
    unknown = _run(ledger_root, player_ids=["7564"], privacy=_privacy(cohort={}))
    assert unknown["trades"] == []
    assert unknown["withheld"] == {ref.WITHHELD_COHORT_UNVERIFIABLE: 1}


def test_registry_league_reached_through_another_lane_is_withheld(tmp_path):
    """F6: a registry league's trade seen only by the Sharp lane (or synced to
    KTC) must not appear as an anonymous row in another league's view."""
    groups = [
        _group(
            f"utrade:sleeper:{REGISTRY_LID}:9",
            date_="2026-10-02",
            families=[ref.SOURCE_SHARP],
            members=[f"sleeper_sharp_discovery:{REGISTRY_LID}:9"],
            sides=[[_player("6794")], [_player("1")]],
            fmt=SLEEPER_FMT,
            host_league_id=REGISTRY_LID,
        ),
        _group(
            "utrade:ktc_trade_database:reg",
            date_="2026-10-01",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794")], [_player("2")]],
            fmt=KTC_FMT,
            host="sleeper",
            host_league_id=REGISTRY_LID,
        ),
    ]
    _persist(tmp_path, groups)
    cohort = {(REGISTRY_LID, "9"): True}
    body = _run(tmp_path, player_ids=["6794"], privacy=_privacy(cohort=cohort))
    assert body["trades"] == []
    assert body["withheld"] == {ref.WITHHELD_REGISTRY_LEAGUE: 2}


def test_unresolved_registry_chain_fails_closed(ledger_root):
    """F6: without a resolved chain, anything that could be a Sleeper league is
    withheld; an MFL-hosted KTC row cannot be one of our leagues and stays."""
    body = _run(ledger_root, player_ids=["6794", "7564"], privacy=_privacy(chain_resolved=False))
    assert _ids_by_date(body) == ["2026-10-01", "2026-09-10"]  # KTC/MFL + own league
    assert body["withheld"][ref.WITHHELD_CHAIN_UNRESOLVED] == 1  # the Sharp row


def test_privacy_no_host_ids_or_trade_ids_in_output(ledger_root):
    body = _run(ledger_root, player_ids=["6794", "7564"], pick_names=["2027 Early 1st"])
    blob = json.dumps(body)
    for secret in (*SECRET_IDS, "cap-secret", "f" * 64, "utrade:", "ktc-123", "vftFavoredSide"):
        assert secret not in blob, secret
    sharp = [t for t in body["trades"] if t["sourceFamilies"] == [ref.SOURCE_SHARP]]
    assert sharp and sharp[0]["provenance"] == ["SHARP_DISCOVERY"]
    assert all(len(t["id"]) == 16 for t in body["trades"])


def test_row_id_is_a_keyed_hmac_not_a_joinable_hash():
    """F4: an unsalted sha256 of "utrade:sleeper:<league>:<tx>" could be joined
    against the Sharp audit's league/tx ids; a per-process HMAC cannot."""
    utid = f"utrade:sleeper:{SHARP_LID}:{SHARP_TX}"
    rid = ref._row_id(utid)
    assert rid == ref._row_id(utid)  # stable within the process
    assert rid != hashlib.sha256(utid.encode("utf-8")).hexdigest()[:16]
    assert len(ref._ROW_ID_KEY) == 32


def test_format_tags_pass_through_and_unknown_stays_unknown(ledger_root):
    body = _run(ledger_root, player_ids=["6794", "7564"])
    by_date = {t["occurredDate"]: t for t in body["trades"]}
    ktc = by_date["2026-10-01"]["formatTags"]
    assert ktc["superflex"] is True and ktc["teams"] == 12 and ktc["starters"] == 10
    assert ktc["ktcTepLevel"] == 2 and ktc["ktcPprCode"] == 1
    # KTC publishes no scoring card: PPR and TE scoring edge are UNKNOWN.
    assert ktc["pprPerReception"] is None and ktc["teScoringEdge"] is None
    sharp = by_date["2026-09-20"]["formatTags"]
    assert sharp["pprPerReception"] == 0.5 and sharp["superflex"] is True
    assert sharp["ktcTepLevel"] is None and sharp["idp"] is False and sharp["season"] == "2026"
    assert by_date["2026-09-20"]["caveats"] == ["released_in_trade:1"]
    partial = by_date["2026-09-10"]["formatTags"]
    assert partial["teams"] == 10
    for unknown in ("superflex", "starters", "idp", "pprPerReception", "bestBall", "teScoringEdge"):
        assert partial[unknown] is None, unknown


def test_disposition_passthrough_only_for_its_target_league(ledger_root):
    body = _run(ledger_root, player_ids=["6794"])
    fm = body["trades"][0]["formatMatch"]
    assert fm["appliesToThisLeague"] is True
    assert fm["disposition"] == "BROAD_CONTEXT" and fm["targetPriceAuthority"] == 0
    assert fm["broadContextKind"] == "format_unknown"
    other = _run(ledger_root, league=OTHER, player_ids=["6794"])
    fm2 = other["trades"][0]["formatMatch"]
    assert fm2["appliesToThisLeague"] is False and fm2["disposition"] is None
    assert fm2["reason"] == "disposition_computed_for_other_league"


def test_timing_is_the_ledger_owners_verdict(ledger_root):
    body = _run(ledger_root, player_ids=["6794", "7564"])
    by_date = {t["occurredDate"]: t for t in body["trades"]}
    exact = by_date["2026-09-20"]
    assert exact["formatTiming"] == "exact" and exact["formatTimingCap"] is None
    assert exact["formatEvidence"]["exactAtTradeTime"] is True
    assert "seasonLeagueId" not in exact["formatEvidence"]
    post = by_date["2026-09-10"]
    assert post["formatTiming"] == "post_trade"
    assert post["formatTimingCap"] == mtf.TIMING_CAP_POST_TRADE
    # Vendor-stated format with no dated evidence: unknown, never exact.
    ktc = by_date["2026-10-01"]
    assert ktc["formatTiming"] == "unknown" and ktc["formatEvidence"] is None


def test_limit_truncates_newest_first(ledger_root):
    body = _run(ledger_root, player_ids=["6794", "7564"], limit=1)
    assert _ids_by_date(body) == ["2026-10-01"]
    assert body["truncated"] is True


def test_scan_is_bounded(ledger_root, monkeypatch):
    monkeypatch.setattr(ref, "MAX_SCAN", 1)
    body = _run(ledger_root, player_ids=["6794", "7564"])
    assert body["scanned"] == 1 and body["scanCapped"] is True
    assert _ids_by_date(body) == ["2026-10-01"]


def test_both_asset_index_plans_select_the_same_rows(ledger_root, monkeypatch):
    q = dict(player_ids=["6794", "7564"], pick_names=["2027 Early 1st"])
    selective = _run(ledger_root, **q)
    monkeypatch.setattr(report, "_SELECTIVE_ASSET_HITS", 0)  # force the date-walk plan
    walked = _run(ledger_root, **q)
    strip = lambda b: [(t["occurredDate"], t["sides"]) for t in b["trades"]]  # noqa: E731
    assert strip(selective) == strip(walked) and len(strip(walked)) == 3


def test_asset_index_and_json_fallback_select_the_same_rows(ledger_root):
    """F7: the writer's ``trade_assets`` index selects by asset in SQL; a ledger
    built before that table existed answers the same through a JSON scan."""
    q = dict(player_ids=["6794", "7564"], pick_names=["2027 Early 1st"])
    indexed = _run(ledger_root, **q)
    conn = sqlite3.connect(report.ledger_file_path(ledger_root))
    assert conn.execute("SELECT COUNT(*) FROM trade_assets").fetchone()[0] > 0
    conn.execute("DROP TABLE trade_assets")
    conn.commit()
    conn.close()
    scanned = _run(ledger_root, **q)
    strip = lambda b: [(t["occurredDate"], t["sides"]) for t in b["trades"]]  # noqa: E731
    assert strip(indexed) == strip(scanned) and strip(indexed)


def test_rebuild_is_visible_immediately(ledger_root):
    assert _run(ledger_root, player_ids=["9999"])["trades"] == []
    _persist(
        ledger_root,
        [
            _group(
                "utrade:ktc_trade_database:new",
                date_="2026-10-07",
                families=[ref.SOURCE_KTC],
                sides=[[_player("9999")], [_player("1")]],
                fmt=KTC_FMT,
                host="mfl",
            )
        ],
        built_at="2026-10-09T00:00:00Z",
    )
    assert _ids_by_date(_run(ledger_root, player_ids=["9999"])) == ["2026-10-07"]


# ── The production privacy context, against its real owners ──────────────


def test_default_context_resolves_registry_chain(monkeypatch):
    from src.api import league_registry
    from src.trade import own_league_format_capture as olfc

    class _Cfg:
        def __init__(self, key, lid):
            self.key, self.sleeper_league_id = key, lid

    monkeypatch.setattr(
        league_registry, "all_leagues", lambda: [_Cfg(LEAGUE, "L1"), _Cfg(OTHER, "L2")]
    )
    full = olfc.OwnLeagueFormatIndex(
        captures={},
        seasons={LEAGUE: {"2025": "L0", "2026": "L1"}, OTHER: {"2026": "L2"}},
        state="ok",
    )
    monkeypatch.setattr(olfc, "load_index", lambda: full)
    ids, resolved = ref._registry_chain()
    assert ids == {"L0", "L1", "L2"} and resolved is True
    partial = olfc.OwnLeagueFormatIndex(captures={}, seasons={LEAGUE: {"2026": "L1"}}, state="ok")
    monkeypatch.setattr(olfc, "load_index", lambda: partial)
    ids, resolved = ref._registry_chain()
    assert {"L1", "L2"} <= ids and resolved is False


def test_default_context_checks_cohort_against_the_trades_managers(tmp_path, monkeypatch):
    from src.intel import ledger as intel_ledger
    from src.sharp import cohort as cohort_mod

    db = tmp_path / "intel.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE asset_movements (tx_id TEXT, league_id TEXT, user_id TEXT, "
        "counterparty_user_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO asset_movements VALUES (?, ?, ?, ?)",
        [("T1", "LG", "u1", "u2"), ("T2", "LG", "u3", "u4")],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(intel_ledger, "default_path", lambda: db)
    member = cohort_mod.CohortMember(
        manager_key="sleeper:u2", platform="sleeper", qualification_method="x", quality=1.0
    )
    monkeypatch.setattr(cohort_mod, "cohort_members", lambda **k: ([member], {}))
    monkeypatch.setattr(ref, "_registry_chain", lambda: (frozenset(), True))
    ctx = ref.default_privacy_context()
    try:
        assert ctx.sharp_trade_has_cohort_manager("LG", "T1") is True
        assert ctx.sharp_trade_has_cohort_manager("LG", "T2") is False
        assert ctx.sharp_trade_has_cohort_manager("LG", "T9") is None  # no record
    finally:
        ctx.close()


def test_module_reads_no_value_and_computes_none():
    path = Path(ref.__file__)
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any(
        m.startswith(("src.api.data_contract", "src.canonical", "src.bdvm")) for m in imported
    )
    for forbidden in ("rankDerivedValue", "ktc_adjust_package", "displayValue"):
        assert forbidden not in text, forbidden
