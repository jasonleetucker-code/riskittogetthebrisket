"""Trade surfaces as ONE decision system — end-to-end backend contract tests.

Finder (``/api/trade/finder``), Suggestions (``/api/trade/suggestions``),
Simulate (``/api/trade/simulate``), Analyze (``/api/trade/analyze``) and the
N-team route (``/api/trade/analyze-multi``, flag forced ON here only) are driven
through their REAL routes over one LABELLED synthetic 3-team IDP league, and
every expectation is derived by hand from the package-model definition below,
never read back from the code under test.

Independent oracle (``geom_q078_v1``, owner decision 2026-10-17): a package's
utility is ``U = sum q**(i-1) * v_i`` over its values sorted high to low, with
``q = 0.78``.  The adjusted gap of a trade from one team's side is
``U(receives) - U(sends)``; the raw gap is the plain sum difference.  Worked
numbers (all values are the synthetic board's ``rankDerivedValue``):

* 1-for-1  send 4800 / receive 5200            raw +400,  adjusted +400
* 2-for-1  send 2500+2000 / receive 5500       raw +1000, U_send = 2500 + 0.78*2000 = 4060, adjusted +1440
* 1-for-2  send 6000 / receive 4400+3000       raw +1400, U_recv = 4400 + 0.78*3000 = 6740, adjusted +740
* 2 picks  send 3600+3600 / receive 5200       raw -2000, U_send = 3600 + 0.78*3600 = 6408, adjusted -1208

Boundaries asserted: canonical asset value (``rankDerivedValue``) stays raw and
separate from Value Adjustment / team fit; missing is never zero; posture
interprets and never vetoes; no surface presents a model discrepancy as a
probability of acceptance; picks are real, distinct assets; the same trade has
the same package-model gap on every surface that claims that quantity.

No surface offers a "do nothing" comparison on ``main`` (the decision's own
coverage record says ``opportunity_cost`` is not wired); that absence is pinned
rather than papered over.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import server
import src.api.gameplan as gameplan
from src.api import feature_flags, league_registry
from src.roster_intel import best_ball_utility as bbu
from src.trade import trade_ledger as tl
from tests.api.test_league_routing import SCORING_CARD, _install_scoring_snapshots

KEY = "e2e"
Q = 0.78


def U(values):
    """Independent package-utility oracle (geom_q078_v1)."""
    return sum(Q**i * v for i, v in enumerate(sorted(values, reverse=True)))


# (id, name, position, board value) per roster id.  Us is FULL (8 of 8).
ROSTERS = {
    1: [
        ("11", "Us Qb", "QB", 6000.0),
        ("12", "Us Rb1", "RB", 5000.0),
        ("13", "Us Rb2", "RB", 4800.0),
        ("14", "Us Rb3", "RB", 4600.0),
        ("15", "Us Rb4", "RB", 3000.0),
        ("16", "Us Wr", "WR", 2500.0),
        ("17", "Us Lb", "LB", 2000.0),
        ("18", "Us Ghost", "WR", None),  # on the board, UNPRICED
    ],
    2: [
        ("21", "Them W1", "WR", 5200.0),
        ("22", "Them W2", "WR", 4400.0),
        ("23", "Them Rb", "RB", 2000.0),
        ("24", "Them Qb", "QB", 5500.0),
        ("25", "Them Dl", "DL", 3000.0),
        ("26", "Them Lb", "LB", 1500.0),
        ("27", "Them Ghost", "WR", None),
    ],
    3: [
        ("31", "Third Wr", "WR", 3500.0),
        ("32", "Third Rb", "RB", 3000.0),
        ("33", "Third Qb", "QB", 4500.0),
        ("34", "Third Te", "TE", 1800.0),
        ("35", "Third Db", "DB", 1700.0),
    ],
}
PICK_ROWS = {"2027 Round 1": 3600.0, "2027 Round 2": 1400.0}
NAMES = {1: "Us", 2: "Them", 3: "Third"}
R1_O1 = f"pick:{KEY}:2027:r1:o1"
R1_O2 = f"pick:{KEY}:2027:r1:o2"  # Them's 2027 first, owned by Us
PPG = {
    "11": 20, "12": 15, "13": 14, "14": 13, "15": 9, "16": 8, "17": 7,
    "21": 16, "22": 12, "23": 6, "24": 18, "25": 9, "26": 5, "31": 10,
}  # fmt: skip


def _row(pid, name, pos, value):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "assetClass": "idp" if pos in ("DL", "LB", "DB") else "offense",
        "position": pos,
        "pos": pos,
        "team": "FA",
        "rankDerivedValue": value,
        "values": {"full": value} if value else {},
    }


def build_contract():
    rows = [_row(*p) for ros in ROSTERS.values() for p in ros]
    for name, value in PICK_ROWS.items():
        rows.append(
            {
                "displayName": name,
                "canonicalName": name,
                "assetClass": "pick",
                "pos": "PICK",
                "rankDerivedValue": value,
                "values": {"full": value},
            }
        )
    players = {}
    for ros in ROSTERS.values():
        for _pid, name, pos, value in ros:
            if value:
                market = "idpTradeCalc" if pos in ("DL", "LB", "DB") else "ktcSfTep"
                players[name] = {
                    "position": pos,
                    "team": "FA",
                    "_finalAdjusted": value,
                    "_sites": 4,
                    "_canonicalSiteValues": {market: value},
                }
    # KTC's published tier rows for the 2027 class: the market side of an
    # owned pick whose slot is not yet known (finder pick generation reads them).
    for tier, value in (("Early", 4200.0), ("Mid", 3600.0), ("Late", 3000.0)):
        players[f"2027 {tier} 1st"] = {
            "position": "PICK",
            "team": "",
            "_finalAdjusted": value,
            "_sites": 4,
            "_canonicalSiteValues": {"ktcSfTep": value},
        }
    holder = {(rnd, o): o for rnd in (1, 2) for o in (1, 2, 3)}
    holder[(1, 2)] = 1  # Us owns TWO 2027 firsts of the same generic archetype
    teams = []
    for rid, ros in ROSTERS.items():
        details = [
            {
                "season": 2027,
                "round": rnd,
                "fromRosterId": origin,
                "ownerRosterId": rid,
                "slot": None,
                "label": f"2027 Round {rnd}",
                "assetId": f"pick:{KEY}:2027:r{rnd}:o{origin}",
            }
            for (rnd, origin), h in sorted(holder.items())
            if h == rid
        ]
        teams.append(
            {
                "name": NAMES[rid],
                "roster_id": rid,
                "ownerId": f"owner{rid}",
                "players": [n for _p, n, _pos, _v in ros],
                "playerIds": [p for p, _n, _pos, _v in ros],
                "picks": [d["label"] for d in details],
                "pickDetails": details,
                "pickOwnershipState": "observed",
                "pickOwnershipReason": None,
            }
        )
    return {
        "players": players,
        "generatedAt": "2026-11-08T00:00:00+00:00",
        "currentDraftYear": 2026,
        "meta": {"leagueKey": KEY},
        "playersArray": rows,
        "sleeper": {
            "teams": teams,
            "idToPlayer": {},
            "rosterSource": "live",
            "rosterFetchedAt": datetime.now(timezone.utc).isoformat(),
            "scoringSettings": dict(SCORING_CARD),
        },
    }


class _Posture:
    def __init__(self, label):
        self.label = label
        self.evidence = "measured"

    def to_dict(self):
        probs = {k: 0.05 for k in ("PUSH", "HOLD", "RETOOL", "REBUILD")}
        probs[self.label] = 0.85
        return {
            "label": self.label,
            "probabilities": probs,
            "confidence": "MEDIUM",
            "paramsVersion": "posture_v1_prior",
            "notes": ["SYNTHETIC_FIXTURE_POSTURE (LABELLED)"],
        }


class Env:
    def __init__(self, client, contract, monkeypatch):
        self.client, self.contract, self.mp = client, contract, monkeypatch

    def post(self, path, **body):
        payload = {"leagueKey": KEY, **body}
        res = self.client.post(path, json=payload)
        assert res.status_code == 200, res.text
        return res.json()

    def post_raw(self, path, **body):
        return self.client.post(path, json={"leagueKey": KEY, **body})

    def trade(self, path, team="owner1", **body):
        return self.post(path, team=team, **body)

    def set_postures(self, labels):
        """``{roster_id: label}`` through the real league-bundle seam."""
        by_owner = {f"owner{rid}": _Posture(lab) for rid, lab in labels.items()}
        self.mp.setattr(
            gameplan,
            "league_competitive_postures",
            lambda league_key, profile, c, *, build_if_missing=False: (
                by_owner,
                {"bundleFreshness": "fresh"},
            ),
        )

    def price(self, name, value):
        for row in self.contract["playersArray"]:
            if row["displayName"] == name:
                row["rankDerivedValue"] = value
                row["values"] = {"full": value}
        self.contract["players"][name] = {
            "position": "WR",
            "team": "FA",
            "_finalAdjusted": value,
            "_sites": 4,
            "_canonicalSiteValues": {"ktcSfTep": value},
        }


@pytest.fixture
def env(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": KEY,
                "leagues": [
                    {
                        "key": KEY,
                        "displayName": "E2E",
                        "sleeperLeagueId": "L-E2E",
                        "active": True,
                        "idpEnabled": True,
                        "rosterSettings": {
                            "teamCount": 3,
                            "rosterSize": 8,
                            "taxiSize": 0,
                            "starters": {"QB": 1, "RB": 2, "WR": 2, "FLEX": 1, "LB": 1, "DL": 1},
                            "flexEligible": ["RB", "WR", "TE"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    _install_scoring_snapshots(tmp_path, monkeypatch, {"L-E2E": SCORING_CARD})
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        bbu,
        "league_scored_ppg_by_id",
        lambda ids, *, season, scoring_settings: (
            {i: PPG[i] for i in ids if i in PPG},
            {"state": "available", "source": "TEST_PROJECTIONS", "season": season},
        ),
    )
    monkeypatch.setattr("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026)
    monkeypatch.setenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", "1")
    feature_flags.reload()
    monkeypatch.setenv("RISKIT_TRADE_DECISION_LOG_DIR", str(tmp_path / "decisions"))
    contract = build_contract()
    tl.clear_snapshot_memo()
    with TestClient(server.app, raise_server_exceptions=True) as client:
        monkeypatch.setattr(server, "latest_contract_data", contract)
        monkeypatch.setattr(
            server, "_get_auth_session", lambda r: {"username": "tester", "sleeper_user_id": "u1"}
        )
        yield Env(client, contract, monkeypatch)
    tl.clear_snapshot_memo()
    monkeypatch.delenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", raising=False)
    feature_flags.reload()
    league_registry.reload_registry()


def _market(result):
    """Market lens detail of an Analyze body OR an N-team per-team result."""
    return result["analysis"]["lenses"]["market"]["detail"]


def _pid(name):
    return next(p for ros in ROSTERS.values() for p, n, _pos, _v in ros if n == name)


def _walk(obj, path=""):
    """Every ``(key path, value)`` leaf of a JSON object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


# (label, request body, our sends, our receives, raw gap, adjusted gap)
SHAPES = [
    ("1v1", {"playersOut": ["Us Rb2"], "playersIn": ["Them W1"]}, [4800], [5200], 400, 400),
    (
        "2v1",
        {"playersOut": ["Us Wr", "Us Lb"], "playersIn": ["Them Qb"]},
        [2500, 2000],
        [5500],
        1000,
        1440,
    ),
    (
        "1v2",
        {"playersOut": ["Us Qb"], "playersIn": ["Them W2", "Them Dl"]},
        [6000],
        [4400, 3000],
        1400,
        740,
    ),
    (
        "2picks",
        {
            "picksOut": ["2027 Round 1", "2027 Round 1"],
            "pickAssetIdsOut": [R1_O1, R1_O2],
            "playersIn": ["Them W1"],
        },
        [3600, 3600],
        [5200],
        -2000,
        -1208,
    ),
]


# ══ 1. Hand-derived package arithmetic through Simulate + Analyze ══════════


@pytest.mark.parametrize(("label", "body", "send", "recv", "raw", "adj"), SHAPES)
def test_shape_numbers_are_hand_derived_and_raw_stays_raw(env, label, body, send, recv, raw, adj):
    # The oracle itself agrees with the worked numbers in the module docstring.
    assert sum(recv) - sum(send) == raw
    assert round(U(recv) - U(send)) == adj

    sim = env.trade("/api/trade/simulate", **body)
    ana = env.trade("/api/trade/analyze", **body)

    # Canonical asset equity: every asset keeps its raw board value, and the
    # headline ``equity`` is the RAW difference, never the adjusted one.
    assert sorted(a["value"] for a in sim["sending"]) == sorted(send)
    assert sorted(a["value"] for a in sim["receiving"]) == sorted(recv)
    assert sim["equity"] == raw
    assert ana["equity"] == raw

    m = _market(ana)
    assert m["sendingValue"] == sum(send) and m["receivingValue"] == sum(recv)
    assert m["rawGap"] == raw
    assert m["vaAdjustedGap"] == pytest.approx(adj, abs=1)
    # Positive-only adjustment: adjusted gap is exactly the utility gap, one
    # side carries zero adjustment, and neither adjustment is negative.
    assert m["receivingAdjusted"] - m["sendingAdjusted"] == pytest.approx(adj, abs=1)
    assert m["sendingValueAdjustment"] >= 0 and m["receivingValueAdjustment"] >= 0
    assert min(m["sendingValueAdjustment"], m["receivingValueAdjustment"]) == 0
    assert m["sendingAdjusted"] == pytest.approx(sum(send) + m["sendingValueAdjustment"])
    assert m["receivingAdjusted"] == pytest.approx(sum(recv) + m["receivingValueAdjustment"])
    assert m["packageModel"]["id"] == "geom_q078_v1"
    assert ana["packageModel"]["id"] == "geom_q078_v1"
    # Roster aggregates are raw board value too (picks are included).
    assert ana["delta"]["totalValue"] == raw


def test_one_for_one_band_and_adjustment_are_zero(env):
    m = _market(env.trade("/api/trade/analyze", **SHAPES[0][1]))
    # A single asset per side has no package effect.
    assert m["sendingValueAdjustment"] == 0 and m["receivingValueAdjustment"] == 0
    # 400 / 5200 = 7.69%: above the 3.5% "slight" line, below the 9% "unfair" line.
    assert m["band"]["level"] == "slight"
    assert m["band"]["relativePct"] == pytest.approx(7.69, abs=0.01)


def test_consolidation_value_adjustment_goes_to_the_star_side_only(env):
    m = _market(env.trade("/api/trade/analyze", **SHAPES[1][1]))
    # U_send = 4060 against raw 4500: the two-piece side is discounted by 440,
    # so the single-star side is credited +440 (positive-only display).
    assert m["receivingValueAdjustment"] == pytest.approx(440)
    assert m["sendingValueAdjustment"] == 0
    assert m["receivingAdjusted"] == pytest.approx(5940)


# ══ 2. Cross-surface consistency of the SAME quantity ══════════════════════


def test_finder_adjusted_totals_match_oracle_and_analyze(env):
    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"])
    trades = out["trades"]
    assert trades, "fixture must yield finder candidates"
    board = {n: v for ros in ROSTERS.values() for _p, n, _pos, v in ros}
    for t in trades:
        give = [a["name"] for a in t["give"]]
        recv = [a["name"] for a in t["receive"]]
        gv = [board[n] for n in give]
        rv = [board[n] for n in recv]
        # Raw model totals stay raw sums of the canonical board value.
        assert t["giveModelTotal"] == sum(gv) and t["receiveModelTotal"] == sum(rv)
        assert t["boardDelta"] == sum(rv) - sum(gv)
        # The adjusted pair is a DIFFERENTLY NAMED field and is the oracle's.
        assert t["adjustedGiveKtcTotal"] - t["adjustedReceiveKtcTotal"] == pytest.approx(
            U(gv) - U(rv), abs=1
        )
        assert t["rawGiveKtcTotal"] == sum(gv) and t["rawReceiveKtcTotal"] == sum(rv)
        # ...and Analyze Trade reads the same trade with the same gap.
        ana = env.trade(
            "/api/trade/analyze",
            playersOut=give,
            playersIn=recv,
            useTeamContext=False,
        )
        m = _market(ana)
        assert m["vaAdjustedGap"] == pytest.approx(
            -(t["adjustedGiveKtcTotal"] - t["adjustedReceiveKtcTotal"]), abs=1
        )
        assert ana["equity"] == t["boardDelta"]


def test_suggestions_gap_matches_oracle_and_analyze(env):
    # A roster that differs from the league team (one extra RB) takes the
    # count-based need path, which leaves offerable RB surplus on this board.
    roster = [n for _p, n, _pos, _v in ROSTERS[1]] + ["Third Rb"]
    out = env.post(
        "/api/trade/suggestions",
        roster=roster,
        league_rosters=[
            {
                "team_name": NAMES[r],
                "players": [n for _p, n, _pos, _v in ROSTERS[r] if n != "Third Rb"],
            }
            for r in (2, 3)
        ],
    )
    sugg = [
        s for k in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades") for s in out[k]
    ]
    assert sugg and out["totalSuggestions"] == len(sugg)
    board = {n: v for ros in ROSTERS.values() for _p, n, _pos, v in ros}
    for s in sugg:
        give = [a["name"] for a in s["give"]]
        recv = [a["name"] for a in s["receive"]]
        gv = [board[n] for n in give]
        rv = [board[n] for n in recv]
        # Totals are raw; ``gap`` is the package-model quantity (give - receive).
        assert s["giveTotal"] == sum(gv) and s["receiveTotal"] == sum(rv)
        assert s["gap"] == pytest.approx(U(gv) - U(rv), abs=1)
        if all(n in roster for n in give):
            ana = env.trade("/api/trade/analyze", playersOut=give, playersIn=recv)
            assert _market(ana)["vaAdjustedGap"] == pytest.approx(-s["gap"], abs=1)


@pytest.mark.parametrize(("label", "body", "send", "recv", "raw", "adj"), SHAPES)
def test_multi_team_route_agrees_with_two_team_analyze(env, label, body, send, recv, raw, adj):
    legs = [{"id": f"p:{_pid(n)}", "from": 1, "to": 2} for n in body.get("playersOut", [])]
    legs += [{"id": a, "from": 1, "to": 2} for a in body.get("pickAssetIdsOut", [])]
    legs += [{"id": f"p:{_pid(n)}", "from": 2, "to": 1} for n in body.get("playersIn", [])]
    multi = env.post("/api/trade/analyze-multi", teams=[1, 2], assets=legs)
    assert multi["rosters"]["state"] == "current"
    team1 = next(t for t in multi["teams"] if t["rosterId"] == 1)
    two = env.trade("/api/trade/analyze", **body)
    assert team1["fairness"]["gap"] == pytest.approx(adj, abs=1)
    assert team1["fairness"]["gap"] == pytest.approx(_market(two)["vaAdjustedGap"], abs=1)
    m1 = _market(team1)
    assert m1["rawGap"] == raw and m1["packageModel"]["id"] == "geom_q078_v1"
    # Conservation is on RAW priced totals only.
    assert multi["summary"]["conservation"]["balanced"] is True
    team2 = next(t for t in multi["teams"] if t["rosterId"] == 2)
    # The other team reads the same trade from its OWN perspective.
    assert team2["fairness"]["gap"] == pytest.approx(-adj, abs=1)


# ══ 3. Picks: real, distinct assets ════════════════════════════════════════


def test_two_picks_of_one_archetype_stay_distinct_assets(env):
    body = SHAPES[3][1]
    sim = env.trade("/api/trade/simulate", **body)
    ids = [a["assetId"] for a in sim["sending"]]
    assert sorted(ids) == sorted([R1_O1, R1_O2])
    assert [a["value"] for a in sim["sending"]] == [3600, 3600]
    # Both leave the inventory (3 picks -> 1), each worth the row, never merged.
    assert sim["before"]["byPosition"]["PICK"] == {"count": 3, "value": 8600}
    assert sim["after"]["byPosition"]["PICK"] == {"count": 1, "value": 1400}
    assert sim["ownedPickChecks"]["notOwnedBySender"] == []
    # The pair is priced as a TWO-piece package, not one pick counted twice.
    m = _market(env.trade("/api/trade/analyze", **body))
    assert m["sendingValue"] == 7200
    assert m["sendingAdjusted"] == pytest.approx(7200)
    assert m["receivingValueAdjustment"] == pytest.approx(7200 - 6408)


def test_picks_in_n_team_route_are_two_distinct_priced_legs(env):
    multi = env.post(
        "/api/trade/analyze-multi",
        teams=[1, 2],
        assets=[
            {"id": R1_O1, "from": 1, "to": 2},
            {"id": R1_O2, "from": 1, "to": 2},
            {"id": f"p:{_pid('Them W1')}", "from": 2, "to": 1},
        ],
    )
    team1 = next(t for t in multi["teams"] if t["rosterId"] == 1)
    assert [g["assetId"] for g in team1["gives"]] == [R1_O1, R1_O2]
    assert all(g["kind"] == "pick" and g["valueState"] == "priced" for g in team1["gives"])
    assert [g["value"] for g in team1["gives"]] == [3600, 3600]
    assert team1["fairness"]["gap"] == pytest.approx(-1208, abs=1)


def test_the_same_pick_cannot_be_sent_twice_to_double_count(env):
    res = env.post_raw(
        "/api/trade/analyze-multi",
        teams=[1, 2],
        assets=[
            {"id": R1_O1, "from": 1, "to": 2},
            {"id": R1_O1, "from": 1, "to": 2},
            {"id": f"p:{_pid('Them W1')}", "from": 2, "to": 1},
        ],
    )
    assert res.status_code in (400, 409, 422), res.text
    assert "teams" not in res.json()


def test_simulate_counts_one_real_pick_at_most_once(env):
    sim = env.trade(
        "/api/trade/simulate",
        picksOut=["2027 Round 1", "2027 Round 1"],
        pickAssetIdsOut=[R1_O1, R1_O1],
        playersIn=["Them W1"],
    )
    # One real pick left; the duplicate is reported, not priced a second time.
    assert sim["after"]["byPosition"]["PICK"]["count"] == 2
    assert sim["ownedPickChecks"]["repeatedOwnedPick"]


def test_picks_are_in_the_aggregate_asset_total(env):
    sim = env.trade("/api/trade/simulate", playersIn=[], playersOut=["Us Rb2"])
    # 8 players with Ghost unpriced + three picks at 3600+3600+1400.
    assert sim["before"]["totalValue"] == (
        6000 + 5000 + 4800 + 4600 + 3000 + 2500 + 2000 + 3600 + 3600 + 1400
    )


# ══ 4. IDP package in an IDP league ════════════════════════════════════════


def test_idp_for_idp_package_is_priced_and_lineup_aware(env):
    body = {"playersOut": ["Us Lb"], "playersIn": ["Them Dl"]}
    ana = env.trade("/api/trade/analyze", **body)
    assert ana["receiving"][0]["assetClass"] == "idp" and ana["receiving"][0]["value"] == 3000
    assert ana["sending"][0]["assetClass"] == "idp" and ana["sending"][0]["value"] == 2000
    assert ana["delta"]["byPosition"]["IDP"] == {"count": 0, "value": 1000}
    m = _market(ana)
    assert m["rawGap"] == 1000 and m["vaAdjustedGap"] == pytest.approx(1000)
    # The league starts 1 DL and 1 LB: Us has no DL, so the lineup changes.
    sd = ana["teamImpact"]["starterDelta"]
    assert sd["DL"] == 1 and sd["LB"] == -1


def test_finder_prices_idp_on_its_own_market_in_an_idp_league(env):
    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"])
    assert out["metadata"]["marketCoverage"]["idpTradeCalc"] > 0
    got_idp = [t for t in out["trades"] if any(a["position"] in ("DL", "LB") for a in t["receive"])]
    assert got_idp, "an IDP league must surface IDP targets, not silently go offense-only"


# ══ 5. Roster-full trades: forced drops reported WITH value, never filtered ═


def test_forced_drop_is_reported_with_value_and_the_trade_still_analyzes(env):
    env.price("Us Ghost", 300.0)  # a priced, cheapest-to-cut roster player
    body = SHAPES[2][1]  # 1-for-2 on an 8/8 roster
    sim = env.trade("/api/trade/simulate", **body)
    cap = sim["rosterCapacity"]
    assert (cap["sizeBefore"], cap["sizeAfter"], cap["rosterLimit"]) == (8, 9, 8)
    assert cap["requiresDrops"] is True and cap["overLimitAfter"] == 1
    assert [d["name"] for d in cap["forcedDrops"]] == ["Us Ghost"]
    assert cap["forcedDrops"][0]["value"] == 300
    assert cap["forcedDropValue"] == 300
    # Nothing was filtered: both incoming players are in the answer.
    assert sorted(a["name"] for a in sim["receiving"]) == ["Them Dl", "Them W2"]
    # The decision knows about the forced cut instead of hiding it.
    ana = env.trade("/api/trade/analyze", **body)
    assert ana["rosterCapacity"]["forcedDrops"] == cap["forcedDrops"]


def test_unpriced_forced_drop_is_null_valued_and_flagged_not_free(env):
    sim = env.trade("/api/trade/simulate", **SHAPES[2][1])
    cap = sim["rosterCapacity"]
    drop = cap["forcedDrops"][0]
    assert drop["name"] == "Us Ghost" and drop["value"] is None
    assert cap["unpricedForcedDrops"] == 1 and cap["forcedDropValue"] == 0
    ana = env.trade("/api/trade/analyze", **SHAPES[2][1])
    codes = {g["code"] for g in ana["analysis"]["decision"]["missingEvidence"]}
    assert "forced_drop_unpriced" in codes


def test_finder_with_a_full_roster_reports_capacity_and_filters_nothing(env):
    from src.trade.finder import find_trades

    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"])
    bare = find_trades(
        players=env.contract["players"],
        my_team="Us",
        opponent_teams=["Them"],
        sleeper_teams=env.contract["sleeper"]["teams"],
        contract=env.contract,
    )

    def key(t):
        return (
            tuple(sorted(a["name"] for a in t["give"])),
            tuple(sorted(a["name"] for a in t["receive"])),
        )

    assert {key(t) for t in out["trades"]} == {key(t) for t in bare["trades"]}
    growing = [t for t in out["trades"] if len(t["receive"]) > len(t["give"])]
    assert growing, "fixture must include roster-growing candidates"
    for t in growing:
        assert t["rosterCapacity"]["requiresDrops"] is True
        assert t["rosterCapacity"]["forcedDrops"], "a forced drop must be NAMED"


# ══ 6. Posture is interpretation, never a veto ═════════════════════════════


def _comparable(ana):
    """Everything that is value, not interpretation."""
    return {
        "equity": ana["equity"],
        "receiving": ana["receiving"],
        "sending": ana["sending"],
        "market": ana["analysis"]["lenses"]["market"],
        "capacity": ana["rosterCapacity"],
    }


@pytest.mark.parametrize(
    ("us", "them"),
    [("PUSH", "REBUILD"), ("REBUILD", "PUSH")],
    ids=["contender_to_rebuilder", "rebuilder_to_contender"],
)
def test_posture_changes_interpretation_but_not_value_or_votes(env, us, them):
    # A vet-for-pick style move: Us sends a star + takes two firsts' worth back.
    body = {"playersOut": ["Us Qb"], "playersIn": ["Them W2", "Them Dl"]}
    unknown = env.trade("/api/trade/analyze", **body)
    env.set_postures({1: us, 2: them, 3: "HOLD"})
    withp = env.trade("/api/trade/analyze", **body)
    assert withp["competitivePosture"]["available"] is True
    assert withp["competitivePosture"]["label"] == us
    # Value, assets, market lens and capacity are byte-identical.
    assert _comparable(withp) == _comparable(unknown)
    lens = withp["analysis"]["lenses"]["posture"]
    assert lens["votes"] is False
    dec = withp["analysis"]["decision"]
    expect = {"PUSH": "WIN_NOW", "REBUILD": "LONG_TERM"}[us]
    assert dec["strategy"]["used"] == expect
    assert dec["strategy"]["source"] != "posture_unknown"
    # Never the deciding component, never a gate.
    assert dec["deciding"] != "posture"
    assert "posture_unknown" not in {g["code"] for g in dec["missingEvidence"]}


def test_both_sides_of_one_trade_read_their_own_posture(env):
    env.set_postures({1: "PUSH", 2: "REBUILD", 3: "HOLD"})
    legs = [
        {"id": f"p:{_pid('Us Qb')}", "from": 1, "to": 2},
        {"id": f"p:{_pid('Them W2')}", "from": 2, "to": 1},
    ]
    multi = env.post("/api/trade/analyze-multi", teams=[1, 2], assets=legs)
    strat = {t["rosterId"]: t["analysis"]["decision"]["strategy"]["used"] for t in multi["teams"]}
    assert strat == {1: "WIN_NOW", 2: "LONG_TERM"}
    # Their market gaps are mirror readings of the SAME raw trade.
    gaps = {t["rosterId"]: t["fairness"]["gap"] for t in multi["teams"]}
    assert gaps[1] == pytest.approx(-gaps[2], abs=1)


# ══ 7. Missing evidence is explicit, never defaulted ═══════════════════════


def test_missing_manager_posture_is_unknown_not_hold(env):
    ana = env.trade("/api/trade/analyze", **SHAPES[0][1])
    assert ana["competitivePosture"]["available"] is False
    assert ana["competitivePosture"]["unavailableReason"]
    dec = ana["analysis"]["decision"]
    assert dec["strategy"]["source"] == "posture_unknown" and dec["strategy"]["used"] is None
    assert dec["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert "posture_unknown" in {g["code"] for g in dec["missingEvidence"]}


def test_finder_without_posture_names_why_it_generated_no_picks(env):
    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"])
    pg = out["metadata"]["pickGeneration"]
    assert pg["applied"] is False and pg["reason"] == "no_canonical_posture"
    assert pg["pickInclusiveReturned"] == 0


def test_finder_with_complementary_postures_accounts_for_every_owned_pick(env):
    env.mp.setattr(server, "_finder_postures", lambda *_a, **_k: {"Us": "PUSH", "Them": "REBUILD"})
    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"])
    pg = out["metadata"]["pickGeneration"]
    assert pg["applied"] is True and pg["myPosture"] == "PUSH"
    assert pg["pairs"]["Them"]["pair"] == "PUSH->REBUILD"
    assert pg["pairs"]["Them"]["pickInclusiveCandidates"] >= 1
    # Us owns three 2027 picks.  Two have a published KTC tier market; the
    # round-2 pick has none, so it is counted UNPRICED — never zeroed, never
    # dropped from the count.
    own = pg["myOwnedPicks"]
    assert own == {"owned": 3, "priced": 2, "unpriced": 1, "belowMinValue": 0}
    returned = [
        t for t in out["trades"] if any(a["position"] == "PICK" for a in t["give"] + t["receive"])
    ]
    assert pg["pickInclusiveReturned"] == len(returned)


def test_unpriced_players_are_unavailable_never_zero_in_the_decision(env):
    ana = env.trade("/api/trade/analyze", playersOut=["Us Ghost"], playersIn=["Them Ghost"])
    m = _market(ana)
    assert m["unpricedOut"] == ["Us Ghost"] and m["unpricedIn"] == ["Them Ghost"]
    dec = ana["analysis"]["decision"]
    assert dec["headline"] == "NOT_ENOUGH_EVIDENCE"
    codes = {g["code"] for g in dec["missingEvidence"]}
    assert {"no_priced_assets", "unpriced_assets"} <= codes


def test_a_partly_unpriced_package_is_marked_incomplete(env):
    ana = env.trade("/api/trade/analyze", playersOut=["Us Rb2", "Us Ghost"], playersIn=["Them W1"])
    m = _market(ana)
    assert m["unpricedOut"] == ["Us Ghost"]
    assert m["incomplete"] is True
    codes = {g["code"] for g in ana["analysis"]["decision"]["missingEvidence"]}
    assert "unpriced_assets" in codes
    assert ana["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: /api/trade/simulate and /analyze list an on-board but UNPRICED player in "
        "sending[]/receiving[] with value 0 (tier 'depth') — missing rendered as zero in the "
        "asset record, even though the market lens separately flags unpricedOut/unpricedIn."
    ),
)
def test_unpriced_asset_record_is_null_valued_not_zero(env):
    sim = env.trade("/api/trade/simulate", playersOut=["Us Ghost"], playersIn=["Them Ghost"])
    assert sim["sending"][0]["value"] is None
    assert sim["receiving"][0]["value"] is None


def test_no_suitable_trades_is_an_explicit_empty_with_a_reason(env):
    roster = [n for _p, n, _pos, _v in ROSTERS[1]]
    out = env.post(
        "/api/trade/suggestions",
        roster=roster,
        league_rosters=[{"team_name": "Them", "players": [n for _p, n, _pos, _v in ROSTERS[2]]}],
    )
    # Starter demand (RB x3 incl. flex, etc.) leaves nothing offerable.
    total = sum(len(out[k]) for k in ("sellHigh", "buyLow", "consolidation", "positionalUpgrades"))
    if total == 0:
        assert out["totalSuggestions"] == 0
        assert out["metadata"]["noResultReason"]
        assert out["metadata"]["noResultLabel"] == "No qualifying trade found"
    else:  # still fine: reason must be absent when results exist
        assert "noResultReason" not in out["metadata"]


def test_finder_with_no_resolvable_counterparty_explains_itself(env):
    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Nobody"])
    assert out["trades"] == []
    assert out["warnings"] and "Nobody" in " ".join(out["warnings"])


# ══ 8. No transaction, acceptance, and picks-in-engines boundaries ═════════


def test_no_do_nothing_comparison_is_offered_and_the_gap_is_stated(env):
    ana = env.trade("/api/trade/analyze", **SHAPES[0][1])
    cov = ana["analysis"]["decision"]["coverage"]
    records = cov if isinstance(cov, list) else cov.get("dimensions") or cov.get("records") or []
    opp = [r for r in records if r.get("dimension") == "opportunity_cost"]
    assert opp, "decision coverage must name opportunity cost"
    assert opp[0]["state"] == "unavailable" and opp[0]["exclusionReason"] == "not_wired"
    # An empty ledger is refused or neutral — never a recommendation to transact.
    res = env.post_raw("/api/trade/analyze", team="owner1", playersOut=[], playersIn=[])
    if res.status_code == 200:
        assert res.json()["analysis"]["decision"]["headline"] not in ("YES", "NO")
        assert res.json()["equity"] == 0


_ACCEPT = re.compile(r"accept|likel(y|ihood)|chance (they|he|she)|will (say|agree)", re.I)


def test_a_model_discrepancy_is_never_called_an_acceptance_probability(env):
    roster = [n for _p, n, _pos, _v in ROSTERS[1]]
    surfaces = {
        "finder": env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"]),
        "suggestions": env.post(
            "/api/trade/suggestions",
            roster=roster,
            league_rosters=[
                {"team_name": NAMES[r], "players": [n for _p, n, _pos, _v in ROSTERS[r]]}
                for r in (2, 3)
            ],
        ),
        "analyze": env.trade("/api/trade/analyze", **SHAPES[1][1]),
        "multi": env.post(
            "/api/trade/analyze-multi",
            teams=[1, 2],
            assets=[
                {"id": f"p:{_pid('Us Wr')}", "from": 1, "to": 2},
                {"id": f"p:{_pid('Them Qb')}", "from": 2, "to": 1},
            ],
        ),
    }
    for name, payload in surfaces.items():
        for path, leaf in _walk(payload):
            key = path.rsplit(".", 1)[-1]
            if isinstance(leaf, str) and key in ("counterpartyAcceptance",):
                assert leaf == "not_evaluated", (name, path, leaf)
                continue
            assert not _ACCEPT.search(key), (name, path)
            if isinstance(leaf, str) and "not evaluated" not in leaf:
                assert not _ACCEPT.search(leaf), (name, path, leaf)
    cov = surfaces["analyze"]["analysis"]["decision"]["coverage"]
    assert "not_evaluated" in json.dumps(cov)
    # Finder's data-confidence tier is not a probability and is not numeric-percent shaped.
    assert all(
        t["confidenceTier"] in ("high", "medium", "low") for t in surfaces["finder"]["trades"]
    )


def test_every_engine_values_picks_in_aggregates_and_discloses_pick_policy(env):
    # Analyze/Simulate: picks are inside the aggregate (see the total test).
    # Finder: its pick policy is explicit metadata (applied + reason).
    out = env.post("/api/trade/finder", myTeam="Us", opponentTeams=["Them"])
    assert "pickGeneration" in out["metadata"]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: /api/trade/suggestions evaluates roster-based dynasty trades but its response "
        "metadata/rosterAnalysis states NO pick policy — picks are in the asset pool yet are never "
        "offered or analysed, and nothing in the payload says so (the finder, by contrast, "
        "publishes metadata.pickGeneration)."
    ),
)
def test_suggestions_discloses_how_picks_are_treated(env):
    roster = [n for _p, n, _pos, _v in ROSTERS[1]]
    out = env.post(
        "/api/trade/suggestions",
        roster=roster,
        league_rosters=[{"team_name": "Them", "players": [n for _p, n, _pos, _v in ROSTERS[2]]}],
    )
    blob = json.dumps(out["metadata"]).lower() + json.dumps(out["rosterAnalysis"]).lower()
    assert "pick" in blob


def test_asset_only_mode_keeps_the_same_market_quantity(env):
    on = env.trade("/api/trade/analyze", **SHAPES[1][1])
    off = env.trade("/api/trade/analyze", useTeamContext=False, **SHAPES[1][1])
    assert off["teamContext"] == {"applied": False, "mode": "asset_only"}
    assert off["analysis"]["lenses"]["market"] == on["analysis"]["lenses"]["market"]
    assert off["equity"] == on["equity"]
