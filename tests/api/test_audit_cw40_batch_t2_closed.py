"""CW-40 Batch T2 -- findings CONFIRMED CLOSED on ``main`` (2026-11-07).

Re-adjudicated offline from the live code path (synthetic leagues, fixture snapshots, source-shape
guards on the frontend files); never the August repro, never the live board or network:

* W07-F002  /settings 'Default 1.15x' + 'Reset to default' writing a TE override -- the manual
            override is withdrawn at ingress and the page shows the premium read-only;
* W11-F003  FAAB saturation at the top of the free-agent pool;
* W11-F004  FAAB output not monotone in value;
* W11-F005  /waivers FAAB hint changes with the position filter;
* W11-F007  two different FAAB dollar figures on /waivers;
* W12-F001  rankings table verdict contradicts the popup verdict (different gap floors);
* W12-F004  /edge panels sort and headline source dispersion as the retail-vs-consensus gap
            (JS half: ``frontend/__tests__/audit-cw40-batch-t2-closed.test.js``);
* W19-F001  hardcoded retired-owner list erased 2024 franchises from public aggregates;
* W19-F003  public trade grades silently dropped unpriced assets;
* W30-F003  two power-ranking engines on one tab.

Unit-level pins that predate this file are named in each docstring; these add end-to-end /
behavioural guarantees from this re-audit.
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# W07-F002 -- the TE override cannot be written from /settings and is ignored by the server
# ---------------------------------------------------------------------------


def test_w07_f002_manual_tep_keys_are_ignored_at_ingress():
    """The stock body that used to switch the board onto the override branch now normalizes to
    'no override' (and is flagged as withdrawn, never silently dropped)."""
    from src.api import data_contract as dc

    body = {"tep_multiplier": 1.15, "tepMultiplier": 1.45, "tep_native_multiplier": 1.3}
    assert dc._TEP_OVERRIDES_DISABLED is True
    assert dc.normalize_tep_multiplier(body) is None
    assert dc.normalize_tep_native_multiplier(body) is None
    assert dc.withdrawn_tep_override_note(body) == dc.TEP_OVERRIDE_WITHDRAWN_NOTE
    # "asked for nothing" must not read like "asked and was refused"
    assert dc.withdrawn_tep_override_note({"siteWeights": {}}) is None


def test_w07_f002_settings_page_no_longer_writes_a_tep_override():
    page = _read("frontend/app/settings/page.jsx")
    # The audited surface: a slider whose 'Reset to default' called update('tepMultiplier', 1.15).
    assert 'update("tepMultiplier"' not in page
    assert "update('tepMultiplier'" not in page
    assert 'update("tepNativeMultiplier"' not in page
    assert 'data-testid="tep-premium-readonly"' in page


def test_w07_f002_dynasty_data_hook_does_not_send_the_tep_knobs():
    hook = _read("frontend/components/useDynastyData.js")
    call = re.search(r"await fetchDynastyData\(\{(.*?)\}\)", hook, re.S)
    assert call, "fetchDynastyData call not found"
    args = call.group(1)
    assert "tepMultiplier" not in args and "tepNativeMultiplier" not in args


def test_w07_f002_stored_auto_sentinel_is_not_promoted_to_1_15():
    """The audited one-way migration coerced a stored ``null`` (auto) to 1.15.  The default is
    the auto sentinel and the only migration restores auto."""
    use_settings = _read("frontend/components/useSettings.js")
    assert re.search(r"tepMultiplier:\s*null", use_settings)
    read_fn = use_settings.split("function readSettings")[1].split("function writeSettings")[0]
    assert "tepDefaultV3Applied" not in read_fn
    assert "tepMultiplier = null" in read_fn  # restores auto; never writes 1.15


# ---------------------------------------------------------------------------
# W11-F003/F004/F005/F007 -- FAAB: one engine, objective ceiling vs recommended bid
# ---------------------------------------------------------------------------

from datetime import date  # noqa: E402

from src.trade import faab_engine as FE  # noqa: E402
from src.trade import waiver as W  # noqa: E402

BUDGET = 100


def _board() -> list[float]:
    return [max(50.0, 9999.0 * math.exp(-i / 160.0)) for i in range(700)]


def _league() -> FE.LeagueContext:
    return FE.LeagueContext(
        original_budget=BUDGET,
        team_count=12,
        starters_per_team=20,
        current_week=8,
        in_season=True,
    )


def _anchors(available_top: float = 900.0) -> FE.Anchors:
    return FE.resolve_anchors(
        _board(),
        _league(),
        available_values=[available_top - 8.0 * i for i in range(60)],
    )


def _rec(value: float, *, remaining: int = 100, anchors: FE.Anchors | None = None) -> dict:
    return FE.recommend(
        FE.PlayerInput(name="Target", value=float(value), position="WR"),
        _league(),
        FE.TeamContext(
            owner_id="me",
            faab_remaining=remaining,
            open_roster_spots=1,
            need_level="neutral",
            competitive_status="bubble",
            risk_posture="balanced",
        ),
        anchors=anchors or _anchors(),
        rivals=[
            FE.RivalTeam(
                owner_id=f"r{i}",
                faab_remaining=60 + 5 * i,
                aggression=1.0,
                need_level="neutral",
                low_sample=False,
            )
            for i in range(5)
        ],
    )


def test_w11_f003_best_free_agent_does_not_set_the_price_ceiling():
    """The audited share was ``value / max(value, best free agent)``: every player at or above the
    wire's best priced identically.  The ceiling is now anchored to league-format values, so the
    objective worth keeps rising past the best available free agent and a barren wire does not
    cap it."""
    wire_top = 1908.0
    anchors = _anchors(available_top=wire_top)
    above = [wire_top, 2300.0, 3000.0, 4500.0, 7000.0]
    raws = [FE.objective_ceiling(v, anchors)[1] for v in above]
    assert all(b > a for a, b in zip(raws, raws[1:])), raws
    bids = [_rec(v, anchors=anchors)["bids"]["maxRational"] for v in above]
    assert len(set(bids)) > 2, bids
    # No all-in threshold missing: an elite player is worth the whole original budget.
    assert FE.objective_ceiling(9999.0, anchors)[0] == 1.0
    assert FE.objective_ceiling(0.0, anchors)[0] == 0.0


def test_w11_f003_a_weaker_wire_never_prices_the_same_player_higher():
    league = _league()
    rich = FE.resolve_anchors(
        _board(), league, available_values=[1400.0 - 8.0 * i for i in range(60)]
    )
    barren = FE.resolve_anchors(
        _board(), league, available_values=[300.0 - 2.0 * i for i in range(60)]
    )
    assert FE.objective_ceiling(1500.0, barren)[0] >= FE.objective_ceiling(1500.0, rich)[0]


def test_w11_f004_worth_and_ladder_are_monotone_in_value():
    """8,362 of 39,903 pairs inverted in the audit.  At a real balance every rung and the worth
    are now non-decreasing in value (the narrow tiny-balance exception is pinned in
    ``tests/trade/test_faab_integrity_invariants.py`` and is out of this regime)."""
    anchors = _anchors()
    values = list(range(0, 10000, 125))
    outs = [_rec(v, remaining=100, anchors=anchors) for v in values]
    objective = [o["objective"]["dollars"] for o in outs]
    assert objective == sorted(objective)
    for rung in ("conservative", "recommended", "aggressive", "clearing", "maxRational"):
        seq = [o["bids"][rung] for o in outs]
        assert seq == sorted(seq), (rung, seq)


def test_w11_f004_the_legacy_position_blend_and_trending_kicker_are_gone():
    """The audited inversions came from a 0.5-weight position blend and a x1.20 trending kicker in
    ``faab_recommender.py``.  Their names must not return as bid multipliers."""
    src = _read("src/trade/faab_recommender.py")
    for retired in ("_position_blend", "position_blend", "_trending_kicker", "TRENDING_KICKER"):
        assert retired not in src, retired


def _wire() -> tuple[dict, list[dict]]:
    rows = [
        {
            "displayName": f"P{i}",
            "canonicalName": f"P{i}",
            "position": ["QB", "RB", "WR", "TE", "DL", "LB", "DB"][i % 7],
            "rankDerivedValue": v,
            "sourceCount": 3,
            "rookie": False,
            "canonicalConsensusRank": None,
        }
        for i, v in enumerate(_board()[:420])
    ]
    teams = [
        {"ownerId": "me", "faabRemaining": 70, "players": [f"P{i}" for i in range(0, 270, 3)]},
        {"ownerId": "o1", "faabRemaining": 90, "players": [f"P{i}" for i in range(1, 270, 3)]},
        {"ownerId": "o2", "faabRemaining": 45, "players": [f"P{i}" for i in range(2, 270, 3)]},
    ]
    return {"playersArray": rows}, teams


def _listed(contract, teams, **kw) -> dict[str, dict]:
    out = W.find_waiver_targets(
        contract,
        teams,
        team_owner_id="me",
        league_budget=BUDGET,
        roster_size=60,
        today=date(2026, 10, 29),
        **kw,
    )
    return {c["name"]: c for cs in out["by_position"].values() for c in cs}


def test_w11_f005_list_bid_is_independent_of_how_many_rows_are_shown(monkeypatch):
    """The audited denominator was the max of the DISPLAYED rows, so narrowing the list moved a
    player's printed dollars.  Whatever subset the page asks for, a player's figure is the same."""
    monkeypatch.setattr(W, "_rookies_eligible_today", lambda: True)
    contract, teams = _wire()
    wide = _listed(contract, teams, per_position_limit=1000)
    narrow = _listed(contract, teams, per_position_limit=2)
    assert narrow and len(narrow) < len(wide)
    for name, cand in narrow.items():
        assert cand["bid"] == wide[name]["bid"], name


def test_w11_f005_client_holds_no_bid_arithmetic():
    """The 'FAAB hint' column's mechanism was a client port with a filtered-list denominator."""
    logic = _read("frontend/lib/waiver-logic.js")
    page = _read("frontend/app/waivers/page.jsx")
    assert not re.search(r"export\s+(?:function|const)\s+computeFaabHint", logic)
    assert "topAddValue" not in page
    assert "computeFaabHint" not in page


def test_w11_f007_list_and_desk_are_one_engine(monkeypatch):
    """The /waivers table figure and the bid desk's must come from the same engine call; the
    desk's legacy keys are the engine's own numbers (one figure, two posture settings at most)."""
    from src.trade import faab_recommender as FR

    anchors = _anchors()
    rivals = [FE.RivalTeam(owner_id="r", faab_remaining=80, aggression=1.0, low_sample=False)]
    desk = FR.recommend_faab(
        add_player_value=2600,
        add_player_position="WR",
        add_player_name="Target",
        team_faab_remaining=70,
        league_budget=BUDGET,
        anchors=anchors,
        rivals=rivals,
        team_count=12,
        starters_per_team=20,
        current_week=8,
        in_season=True,
        open_roster_spots=1,
    )
    eng = FE.recommend(
        FE.PlayerInput(name="Target", value=2600.0, position="WR"),
        _league(),
        FE.TeamContext(faab_remaining=70, open_roster_spots=1),
        anchors=anchors,
        rivals=rivals,
    )
    assert desk["bids"] == eng["bids"]
    assert desk["standard"] == eng["bids"]["recommended"]
    assert desk["max"] == eng["bids"]["maxRational"]


# ---------------------------------------------------------------------------
# W12-F001 / W12-F004 (Python half) -- one gap definition across table, popup and /edge
# ---------------------------------------------------------------------------


def test_w12_f001_table_and_popup_share_one_gap_floor():
    """The audit: marketAction required a 10-rank gap, getPlayerEdge a 3-rank gap, so 83 rows
    showed HOLD in the table and a Sell High card in the popup.  Both now import the SAME
    value-ratio floor from thresholds.js and neither defines its own."""
    display = _read("frontend/lib/display-helpers.js")
    trade = _read("frontend/lib/trade-logic.js")
    for name, src in (("display-helpers", display), ("trade-logic", trade)):
        assert re.search(
            r'import \{[^}]*MARKET_GAP_MIN_VALUE_RATIO[^}]*\} from "\./thresholds\.js"', src
        ), name
    assert "MARKET_GAP_MIN_DIFF" not in display
    assert "MIN_EDGE_RANK_GAP" not in trade
    assert re.search(
        r"export const MARKET_GAP_MIN_VALUE_RATIO = ", _read("frontend/lib/thresholds.js")
    )


def test_w12_f004_edge_page_premium_panels_gate_and_sort_on_the_gap():
    page = _read("frontend/app/edge/page.jsx")
    start = page.index("const premiumBy")
    block = page[start : start + 700]
    assert "marketGapAtLeast" in block and "marketGapRatioOf" in block
    assert "sourceRankSpread" not in block


# ---------------------------------------------------------------------------
# W19-F001 -- retired owners stay in public history
# ---------------------------------------------------------------------------


def test_w19_f001_retiring_an_owner_does_not_change_the_public_records(monkeypatch):
    """Retirement is a current-state label (C9-HIST-01).  Building the fixture league with its
    record-holder flagged retired must leave every record category byte-identical; under the
    audited behaviour the retired owner's roster-weeks vanished and 5 of 10 categories changed."""
    from src.public_league import identity, records
    from tests.public_league.fixtures import build_test_snapshot

    baseline = records.build_section(build_test_snapshot())
    holder = baseline["singleWeekHighest"][0]["ownerId"]
    assert holder

    monkeypatch.setattr(identity, "_RETIRED_OWNER_IDS", frozenset({holder}))
    snapshot = build_test_snapshot()
    assert snapshot.managers.by_owner_id[holder].is_retired is True
    retired_view = records.build_section(snapshot)

    assert json.dumps(retired_view, sort_keys=True) == json.dumps(baseline, sort_keys=True)
    # and the retired owner still holds the record under their own id
    assert retired_view["singleWeekHighest"][0]["ownerId"] == holder


# ---------------------------------------------------------------------------
# W19-F003 -- an unpriced asset makes a public trade grade UNAVAILABLE, never a partial grade
# ---------------------------------------------------------------------------


def _trade(assets_recv_a, assets_sent_a):
    return {
        "createdAt": 1759665600000,
        "sides": [
            {"receivedAssets": assets_recv_a, "sentAssets": assets_sent_a},
            {"receivedAssets": assets_sent_a, "sentAssets": assets_recv_a},
        ],
    }


def test_w19_f003_unresolved_asset_yields_unavailable_grade_not_a_partial_grade():
    from src.public_league import activity

    pick = {"kind": "pick", "season": "2025", "round": 1, "label": "2025 R1"}
    player = {"kind": "player", "playerId": "1", "playerName": "Priced Guy"}

    def resolve(asset, _instant):
        return 4000.0 if asset.get("kind") == "player" else None  # board cannot price the pick

    feed = [_trade([player], [pick])]
    activity._apply_trade_grades(feed, resolve)
    for side in feed[0]["sides"]:
        grade = side["grade"]
        assert grade["available"] is False
        assert grade["grade"] is None
        assert grade["reason"] == "no_historical_evidence"
        assert grade["missingAssets"], "the omitted asset must be named"


def test_w19_f003_today_band_is_unavailable_for_an_unpriced_asset():
    from src.public_league import activity

    pick = {"kind": "pick", "season": "2025", "round": 1, "label": "2025 R1"}
    player = {"kind": "player", "playerId": "1", "playerName": "Priced Guy"}
    feed = [_trade([player], [pick])]
    activity._apply_current_grades(
        feed, lambda asset: 4000.0 if asset.get("kind") == "player" else None
    )
    for side in feed[0]["sides"]:
        assert side["currentGrade"]["available"] is False
        assert side["currentGrade"]["reason"] == "unpriced_today"


def test_w19_f003_fully_priced_trade_still_gets_a_grade():
    """Control: the fail-closed branch must not swallow trades whose assets all resolve."""
    from src.public_league import activity

    a = {"kind": "player", "playerId": "1", "playerName": "A"}
    b = {"kind": "player", "playerId": "2", "playerName": "B"}
    feed = [_trade([a], [b])]
    activity._apply_trade_grades(
        feed, lambda asset, _i: 5000.0 if asset["playerId"] == "1" else 3000.0
    )
    for side in feed[0]["sides"]:
        assert side["grade"].get("available") is not False
        assert side["grade"]["grade"] is not None or "label" in side["grade"]


def test_w19_f003_current_board_resolver_maps_unpriced_to_none_not_zero():
    """``server._current_board_valuation`` wraps the contract resolver so a miss is ``None`` --
    the contract resolver's own 0.0 would otherwise be summed as a real (dropped) value."""
    src = _read("server.py")
    block = src[src.index("def _current_board_valuation") :]
    block = block[: block.index("@app.post")]
    assert "value if value and value > 0 else None" in block


# ---------------------------------------------------------------------------
# W30-F003 -- one power engine
# ---------------------------------------------------------------------------


def test_w30_f003_no_module_imports_the_retired_legacy_power_engine():
    legacy = REPO / "src" / "public_league" / "power.py"
    assert not legacy.exists()
    offenders = []
    for path in list((REPO / "src").rglob("*.py")) + [REPO / "server.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mod = None
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = {a.name for a in node.names}
                if mod == "src.public_league" and "power" in names:
                    offenders.append(str(path))
            elif isinstance(node, ast.Import):
                if any(a.name == "src.public_league.power" for a in node.names):
                    offenders.append(str(path))
            if mod == "src.public_league.power":
                offenders.append(str(path))
    assert offenders == []


def test_w30_f003_power_surfaces_read_the_canonical_engine():
    overview = _read("src/public_league/overview.py")
    assert "power_v2" in overview
    client = _read("frontend/app/league/LeagueClient.jsx")
    assert client.count('lazySection("power")') == 1
    assert 'import("./sections/ros-power.jsx")' in client
