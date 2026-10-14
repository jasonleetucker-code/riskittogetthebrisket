"""TC-09 / C4-MTL-03 — comparable real trades for the calculator package.

``src.trade.comparable_trades`` ranks visible ledger trades by a declared
similarity model.  Pinned here on a synthetic ledger persisted through the
ledger owner's own writer (fixtures shared with the TC-07 tests):

* overlap is the GATE — a trade sharing no asset is never returned, however
  "similar" it is otherwise;
* identity is TC-07's — players by canonical id, picks at exact / round
  grades, a different tier never matches, unresolved matches nothing;
* alignment is symmetric (works whichever side the package lists first) and
  an asset that moved the OTHER way scores lower than the same asset moving
  the same way;
* the format component is the ledger's disposition only for THIS league;
  otherwise it is the configured unknown score — low, never neutral;
* privacy and projection are TC-07's (withheld rows counted, no ids leak);
* no canonical value is read and none is computed;
* config weights are the single source of the numbers.
"""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

import pytest

from src.trade import comparable_trades as ct
from src.trade import market_trade_reference as ref
from tests.trade.test_market_trade_reference import (
    KTC_FMT,
    LEAGUE,
    OTHER,
    SECRET_IDS,
    TODAY,
    _fixture_groups,
    _group,
    _persist,
    _pick,
    _player,
    _privacy,
    _unresolved,
)

REPO = Path(__file__).resolve().parents[2]
JEFF, CHASE, LAMB = "6794", "7564", "6786"


def _ktc(gid, date_, sides, *, disposition="BROAD_CONTEXT", target=LEAGUE):
    return _group(
        gid,
        date_=date_,
        families=[ref.SOURCE_KTC],
        sides=sides,
        fmt=KTC_FMT,
        host="mfl",
        host_league_id="777777777777777777",
        disposition=disposition,
        target=target,
    )


def _run(root, a=(), b=(), *, a_picks=(), b_picks=(), a_owned=(), **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("privacy", _privacy())
    return ct.comparable_trades(
        kw.pop("league", LEAGUE),
        side_a=ct.SideRefs(player_ids=a, pick_names=a_picks, pick_asset_ids=a_owned),
        side_b=ct.SideRefs(player_ids=b, pick_names=b_picks),
        root=root,
        **kw,
    )


def _ids(body):
    return [t["occurredDate"] for t in body["trades"]]


@pytest.fixture
def root(tmp_path):
    _persist(
        tmp_path,
        [
            # Same 1-for-1, same direction, recent.
            _ktc("utrade:ktc_trade_database:c1", "2026-10-01", [[_player(JEFF)], [_player(CHASE)]]),
            # Same two players, but with a third asset: a 2-for-1.
            _ktc(
                "utrade:ktc_trade_database:c2",
                "2026-10-01",
                [[_player(JEFF), _pick(2027, 1, tier="early")], [_player(CHASE)]],
            ),
            # Only Jefferson, for an unrelated player.
            _ktc("utrade:ktc_trade_database:c3", "2026-10-01", [[_player(JEFF)], [_player(LAMB)]]),
            # Jefferson and Chase on the SAME side (they moved together, i.e.
            # in opposite direction relative to a Jefferson-for-Chase package).
            _ktc(
                "utrade:ktc_trade_database:c4",
                "2026-10-01",
                [[_player(JEFF), _player(CHASE)], [_player(LAMB)]],
            ),
            # Shares nothing with the package.
            _ktc(
                "utrade:ktc_trade_database:c5", "2026-10-02", [[_player("1111")], [_player("2222")]]
            ),
            # Same 1-for-1, a year old.
            _ktc("utrade:ktc_trade_database:c6", "2025-11-01", [[_player(JEFF)], [_player(CHASE)]]),
        ],
    )
    return tmp_path


def _by_shape(body):
    return {
        tuple(tuple(a["canonicalId"] for a in side) for side in t["sides"]): t
        for t in body["trades"]
    }


def test_no_ledger_is_unavailable_not_empty(tmp_path):
    body = _run(tmp_path, a=[JEFF])
    assert body["state"] == "unavailable" and body["reason"] == "trade_ledger_not_built"
    assert body["methodology"]["status"] == "PRIOR_UNVALIDATED"


def test_empty_package_is_no_assets(root):
    body = _run(root)
    assert body["state"] == "no_assets" and body["trades"] == []


def test_overlap_is_the_gate(root):
    body = _run(root, a=[JEFF], b=[CHASE])
    for t in body["trades"]:
        ids = {a["canonicalId"] for side in t["sides"] for a in side}
        assert ids & {f"player:{JEFF}", f"player:{CHASE}"}
    assert "2026-10-02" not in _ids(body)  # the no-overlap trade


def test_exact_same_trade_ranks_first_and_says_why(root):
    body = _run(root, a=[JEFF], b=[CHASE])
    top = body["trades"][0]
    assert top["occurredDate"] == "2026-10-01"
    assert [len(s) for s in top["sides"]] == [1, 1]
    comp = top["comparability"]
    assert comp["components"]["assetOverlap"]["score"] == 1.0
    assert comp["components"]["topology"]["score"] == 1.0
    keys = [r["key"] for r in comp["reasons"]]
    assert keys[:2] == ["sharedExact", "topology"]
    assert "Same 1-for-1 shape" in [r["text"] for r in comp["reasons"]]


def test_alignment_is_symmetric(root):
    ab = _run(root, a=[JEFF], b=[CHASE])
    ba = _run(root, a=[CHASE], b=[JEFF])
    assert [t["comparability"]["score"] for t in ab["trades"]] == [
        t["comparability"]["score"] for t in ba["trades"]
    ]


def test_opposite_direction_scores_below_same_direction(root):
    trades = _by_shape(_run(root, a=[JEFF], b=[CHASE]))
    same = trades[((f"player:{JEFF}",), (f"player:{CHASE}",))]
    together = trades[((f"player:{JEFF}", f"player:{CHASE}"), (f"player:{LAMB}",))]
    assert together["comparability"]["alignment"]["oppositeDirectionMatches"] == 1
    assert "oppositeDirection" in [r["key"] for r in together["comparability"]["reasons"]]
    assert (
        together["comparability"]["components"]["assetOverlap"]["score"]
        < same["comparability"]["components"]["assetOverlap"]["score"]
    )


def test_partial_overlap_and_shape_mismatch_rank_lower(root):
    body = _run(root, a=[JEFF], b=[CHASE])
    trades = _by_shape(body)
    exact = trades[((f"player:{JEFF}",), (f"player:{CHASE}",))]["comparability"]["score"]
    plus_pick = next(t for t in body["trades"] if [len(s) for s in t["sides"]] == [2, 1])
    one_shared = trades[((f"player:{JEFF}",), (f"player:{LAMB}",))]["comparability"]["score"]
    assert exact > plus_pick["comparability"]["score"] > one_shared
    assert plus_pick["comparability"]["components"]["topology"]["score"] < 1.0


def test_recency_orders_otherwise_identical_trades(root):
    body = _run(root, a=[JEFF], b=[CHASE])
    same = [
        t
        for t in body["trades"]
        if [a["canonicalId"] for s in t["sides"] for a in s]
        == [f"player:{JEFF}", f"player:{CHASE}"]
    ]
    assert [t["occurredDate"] for t in same] == ["2026-10-01", "2025-11-01"]
    assert same[0]["comparability"]["score"] > same[1]["comparability"]["score"]


def test_pick_grades_follow_tc07(tmp_path):
    _persist(
        tmp_path,
        [
            _ktc(
                "utrade:ktc_trade_database:p1",
                "2026-10-01",
                [[_pick(2027, 1, tier="early")], [_player(JEFF)]],
            ),
            _ktc(
                "utrade:ktc_trade_database:p2",
                "2026-10-01",
                [[_pick(2027, 1, tier="late")], [_player(LAMB)]],
            ),
            _ktc("utrade:ktc_trade_database:p3", "2026-10-01", [[_pick(2027, 1)], [_player(LAMB)]]),
        ],
    )
    body = _run(tmp_path, a_picks=["2027 Early 1st"])
    texts = [r["text"] for t in body["trades"] for r in t["comparability"]["reasons"]]
    assert any(t.startswith("Same asset: 2027 Early 1st") for t in texts)
    assert any(
        t.startswith("Same pick round: 2027 1.") or t.startswith("Same pick round: 2027")
        for t in texts
    )
    # The Late 1st never matches an Early 1st package.
    for t in body["trades"]:
        assert all(a["canonicalId"] != "mpick:2027:r1:tlate" for side in t["sides"] for a in side)
    assert len(body["trades"]) == 2


def test_unresolved_ledger_asset_matches_nothing(tmp_path):
    _persist(
        tmp_path,
        [
            _ktc(
                "utrade:ktc_trade_database:u1",
                "2026-10-01",
                [[_unresolved("Justin Jefferson")], [_player(LAMB)]],
            )
        ],
    )
    assert _run(tmp_path, a=[JEFF])["trades"] == []


def test_format_component_uses_this_leagues_disposition_only(tmp_path):
    cfg = ct.load_comparable_config()
    _persist(
        tmp_path,
        [
            _ktc(
                "utrade:ktc_trade_database:f1",
                "2026-10-01",
                [[_player(JEFF)], [_player(CHASE)]],
                disposition="NATIVE_COMPARABLE",
            ),
            _ktc(
                "utrade:ktc_trade_database:f2",
                "2026-09-30",
                [[_player(JEFF)], [_player(CHASE)]],
                disposition="NATIVE_COMPARABLE",
                target=OTHER,
            ),
        ],
    )
    body = _run(tmp_path, a=[JEFF], b=[CHASE])
    fmt = {t["occurredDate"]: t["comparability"]["components"]["format"] for t in body["trades"]}
    assert fmt["2026-10-01"] == {
        "score": cfg["formatScores"]["NATIVE_COMPARABLE"],
        "weight": cfg["weights"]["format"],
        "state": "known",
    }
    # Computed for another league: unknown, scored LOW — not the native score
    # and not a neutral 0.5.
    assert fmt["2026-09-30"]["state"] == "unknown"
    assert fmt["2026-09-30"]["score"] == cfg["unknownFormatScore"] < 0.5


def test_score_is_the_configured_weighted_mean(root):
    cfg = ct.load_comparable_config()
    body = _run(root, a=[JEFF], b=[CHASE])
    for t in body["trades"]:
        comps = t["comparability"]["components"]
        total = sum(cfg["weights"].values())
        expect = sum(cfg["weights"][k] * comps[k]["score"] for k in ct.COMPONENTS) / total
        assert t["comparability"]["score"] == pytest.approx(expect, abs=1e-3)


def test_min_score_drops_weak_candidates_and_counts_them(root):
    cfg = {**ct.load_comparable_config(), "minScore": 0.99}
    body = _run(root, a=[JEFF], b=[CHASE], config=cfg)
    assert body["trades"] == [] and body["belowMinScore"] >= 1
    assert body["methodology"]["minScore"] == 0.99


def test_limit_truncates_after_ranking(root):
    body = _run(root, a=[JEFF], b=[CHASE], limit=1)
    assert len(body["trades"]) == 1 and body["truncated"] is True
    assert body["candidates"] > 1


def test_privacy_rules_and_projection_are_tc07s(tmp_path):
    _persist(tmp_path, _fixture_groups())
    body = _run(tmp_path, a=[JEFF])
    families = {f for t in body["trades"] for f in t["sourceFamilies"]}
    assert "mystery_lane" not in families
    assert body["withheld"].get(ref.WITHHELD_UNKNOWN_FAMILY) == 1
    assert body["withheld"].get(ref.WITHHELD_OTHER_LEAGUE) == 1
    text = json.dumps(body)
    for secret in SECRET_IDS:
        assert secret not in text
    assert "utrade:" not in text


def test_methodology_names_what_is_not_measured(root):
    body = _run(root, a=[JEFF])
    not_included = body["methodology"]["notIncluded"]
    assert {"packageValueProximity", "pickHorizon"} <= set(not_included)
    assert "never" in body["methodology"]["statement"].lower()


def test_module_reads_no_value_and_computes_none():
    src = (REPO / "src/trade/comparable_trades.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    strings = {
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    for banned in ("rankDerivedValue", "value", "targetPriceAuthority", "ktcMarket"):
        assert banned not in strings, banned
    imports = {
        a.name if isinstance(n, ast.Import) else (n.module or "")
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not any("data_contract" in m or "market_trade_format" in m for m in imports)


def test_today_default_does_not_crash(root):
    body = ct.comparable_trades(
        LEAGUE,
        side_a=ct.SideRefs(player_ids=[JEFF]),
        side_b=ct.SideRefs(),
        root=root,
        privacy=_privacy(),
    )
    assert body["state"] == "ok"
    assert date.fromisoformat(body["since"])
