"""TC-07 / TC-10 — recent real trades touching the calculator's assets.

``src.trade.market_trade_reference`` is a display projection of the canonical
underlying-trade ledger.  Pinned here, on a synthetic ledger persisted through
the ledger owner's own writer:

* asset touch — players by canonical id only, picks at two NAMED grades
  (exact / round), different refinements never match;
* privacy — KTC + Sharp visible (anonymized), own-league only for the
  requested league, unknown families withheld; no host/league/tx/manager id
  or underlying-trade id in the output;
* format tags and dispositions are the ledger's own, verbatim; UNKNOWN stays
  ``None`` (never the target league's format);
* evidence timing is the ledger owner's ``format_timing_cap``;
* no valuation is read or computed.
"""

from __future__ import annotations

import ast
import json
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
        "host": "sleeper",
        "hostLeagueId": "998877665544332211",
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
        "caveats": [],
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


@pytest.fixture
def ledger_root(tmp_path):
    ref._reset_cache_for_tests()
    groups = [
        # KTC: Jefferson + 2027 Early 1st  <->  Unresolved name
        _group(
            "utrade:ktc_trade_database:1",
            date_="2026-10-01",
            families=[ref.SOURCE_KTC],
            sides=[[_player("6794"), _pick(2027, 1, tier="early")], [_unresolved("J. Smith")]],
            fmt=KTC_FMT,
        ),
        # Sharp: 2027 generic 1st <-> Chase; exact-at-trade evidence.
        _group(
            "utrade:sleeper:998877665544332211:112233445566778899",
            date_="2026-09-20",
            families=[ref.SOURCE_SHARP],
            members=["sleeper_sharp_discovery:998877665544332211:112233445566778899"],
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
            members=[
                "sleeper_sharp_discovery:1:2",
                f"own_league_sleeper:{OTHER}:556",
            ],
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
    report.persist_canonical_ledger(
        groups, root=tmp_path, built_at="2026-10-08T08:52:00Z", extra_meta={"targetLeague": LEAGUE}
    )
    yield tmp_path
    ref._reset_cache_for_tests()


def _run(root, **kw):
    kw.setdefault("today", TODAY)
    return ref.reference_trades(kw.pop("league", LEAGUE), root=root, **kw)


def _ids_by_date(body):
    return [t["occurredDate"] for t in body["trades"]]


def test_no_ledger_is_unavailable_not_empty(tmp_path):
    ref._reset_cache_for_tests()
    body = ref.reference_trades(LEAGUE, player_ids=["6794"], root=tmp_path, today=TODAY)
    assert body["state"] == "unavailable"
    assert body["reason"] == "trade_ledger_not_built"
    assert body["ledger"] is None


def test_no_assets_is_its_own_state(ledger_root):
    body = _run(ledger_root)
    assert body["state"] == "no_assets"
    assert body["trades"] == []
    assert body["ledger"]["builtAt"] == "2026-10-08T08:52:00Z"


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


def test_generic_query_pick_matches_refined_trades_at_round_grade(ledger_root):
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
        ("2026-09-20", "exact"),
        ("2026-10-01", "round"),
    ]


def test_owned_pick_identity(ledger_root):
    body = _run(ledger_root, pick_asset_ids=[f"pick:{LEAGUE}:2028:r2:o3"])
    assert _ids_by_date(body) == ["2026-09-10"]
    pick = body["trades"][0]["sides"][0][0]
    assert pick["match"] == "exact"
    assert pick["label"] == "2028 Round 2"  # board name, never the internal id
    assert body["trades"][0]["ownLeagueTrade"] is True
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


def test_privacy_no_host_ids_or_trade_ids_in_output(ledger_root):
    body = _run(ledger_root, player_ids=["6794", "7564"], pick_names=["2027 Early 1st"])
    blob = json.dumps(body)
    for secret in (*SECRET_IDS, "cap-secret", "f" * 64, "utrade:", "ktc-123", "vftFavoredSide"):
        assert secret not in blob, secret
    sharp = [t for t in body["trades"] if t["sourceFamilies"] == [ref.SOURCE_SHARP]]
    assert sharp and sharp[0]["provenance"] == ["SHARP_DISCOVERY"]
    assert all(len(t["id"]) == 16 for t in body["trades"])


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
    assert body["truncated"] is True and body["matchingTrades"] == 3


def test_cache_invalidates_on_rebuild(ledger_root):
    assert _run(ledger_root, player_ids=["9999"])["trades"] == []
    report.persist_canonical_ledger(
        [
            _group(
                "utrade:ktc_trade_database:new",
                date_="2026-10-07",
                families=[ref.SOURCE_KTC],
                sides=[[_player("9999")], [_player("1")]],
                fmt=KTC_FMT,
            )
        ],
        root=ledger_root,
        built_at="2026-10-09T00:00:00Z",
    )
    assert _ids_by_date(_run(ledger_root, player_ids=["9999"])) == ["2026-10-07"]


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
    assert not any(m.startswith(("src.api", "src.canonical", "src.bdvm")) for m in imported)
    for forbidden in ("rankDerivedValue", "ktc_adjust_package", "displayValue"):
        assert forbidden not in text, forbidden
