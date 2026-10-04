"""C7-PICKGEN-01 — posture-aware picks in the arbitrage finder (Wave B).

Picks enter a generated trade only for a COMPLEMENTARY posture pair, only when
they beat (or rescue) the player-only core, never as filler; identity comes
from the canonical fold and market value from the native board row or, for an
unknown slot, the ``pick_market`` tier average (labelled, PRIOR).
"""

from __future__ import annotations

import pytest

from src.packages import UNCONSTRAINED_OUTGOING
from src.trade import finder
from src.trade.finder import Asset, TradeCandidate


def _a(name, value, *, pick=False):
    return Asset(
        name=name,
        position="PICK" if pick else "WR",
        team="",
        model_value=value,
        market_value=value,
        is_pick=pick,
        source_count=4,
        market_source="ktc",
    )


MY = [_a("Mine A", 5000), _a("Mine B", 3000)]
THEIRS = [_a("Theirs A", 5200), _a("Theirs B", 2800)]
MY_PICK = _a("2027 1st (Us)", 4000, pick=True)
OPP_PICK = _a("2027 1st (Them)", 4000, pick=True)


def _run(my_posture, opp_posture, monkeypatch=None, scorer=None):
    if scorer is not None:
        monkeypatch.setattr(finder, "_score_trade", scorer)
    return finder._posture_pick_packages(
        MY,
        THEIRS,
        [MY_PICK],
        [OPP_PICK],
        my_posture,
        opp_posture,
        UNCONSTRAINED_OUTGOING,
        equal_count_only=False,
    )


def _scorer(with_pick_score, core_score):
    def score(give, receive):
        has_pick = any(a.is_pick for a in give + receive)
        s = with_pick_score if has_pick else core_score
        if s is None:
            return None
        return TradeCandidate(give=give, receive=receive, arbitrage_score=s, flags=[])

    return score


@pytest.mark.parametrize(
    "mine,theirs",
    [
        ("HOLD", "REBUILD"),
        ("PUSH", "PUSH"),
        ("REBUILD", "RETOOL"),
        ("PUSH", "HOLD"),
        (None, "PUSH"),
    ],
)
def test_non_complementary_pairs_stay_player_only(mine, theirs, monkeypatch):
    out, pair = _run(mine, theirs, monkeypatch, _scorer(99.0, 1.0))
    assert out == []


def test_contender_may_send_its_own_pick_to_a_rebuilder(monkeypatch):
    out, pair = _run("PUSH", "REBUILD", monkeypatch, _scorer(10.0, 5.0))
    assert pair == "PUSH->REBUILD" and out
    for tc in out:
        assert MY_PICK in tc.give and OPP_PICK not in tc.receive
        assert "posture_aware_pick" in tc.flags


def test_rebuilder_may_ask_a_contender_for_its_pick(monkeypatch):
    out, pair = _run("RETOOL", "PUSH", monkeypatch, _scorer(10.0, 5.0))
    assert pair == "RETOOL->PUSH" and out
    for tc in out:
        assert OPP_PICK in tc.receive and MY_PICK not in tc.give


def test_a_pick_that_does_not_beat_its_player_only_core_is_never_added(monkeypatch):
    out, _ = _run("PUSH", "REBUILD", monkeypatch, _scorer(5.0, 5.0))
    assert out == []  # equal is not better: player-only stays preferred


def test_a_pick_may_rescue_a_core_that_failed_a_gate(monkeypatch):
    # The two-team objective mismatch a pick legitimately solves: the
    # player-only core gives the opponent nothing it would accept.
    out, _ = _run("PUSH", "REBUILD", monkeypatch, _scorer(3.0, None))
    assert out


def test_picks_never_change_player_topology(monkeypatch):
    out, _ = _run("PUSH", "REBUILD", monkeypatch, _scorer(10.0, 5.0))
    for tc in out:
        players_give = sum(1 for a in tc.give if not a.is_pick)
        players_recv = sum(1 for a in tc.receive if not a.is_pick)
        assert abs(players_give - players_recv) <= 1


# ── Owned-pick assets: identity and value come from the owners ───────


def _contract(pick_details):
    return {
        "currentDraftYear": 2026,
        "playersArray": [
            {
                "canonicalName": "2027 Round 1",
                "assetClass": "pick",
                "rankDerivedValue": 5800,
                "pickValueProvenance": {"class": "derived_uniform_tier_ev"},
            }
        ],
        "sleeper": {"teams": [{"name": "Us", "roster_id": 1, "pickDetails": pick_details}]},
    }


def _players(late=True):
    rows = {"2027 Early 1st": 7000, "2027 Mid 1st": 5900}
    if late:
        rows["2027 Late 1st"] = 5000
    return {
        n: {
            "_finalAdjusted": v,
            "position": "PICK",
            "_sites": 6,
            "_canonicalSiteValues": {"ktcCrowdTradesSfTep": v, "ktc": v},
        }
        for n, v in rows.items()
    }


_DETAIL = {
    "season": 2027,
    "round": 1,
    "fromRosterId": 1,
    "fromTeam": "Us",
    "ownerRosterId": 1,
    "slot": None,
    "assetId": "pick:dynasty_main:2027:r1:o1",
}


def test_unknown_slot_pick_takes_canonical_model_value_and_derived_market_value():
    c = _contract([_DETAIL])
    team = c["sleeper"]["teams"][0]
    assets, stats = finder._owned_pick_assets(team, c, _players(), {})
    assert stats == {"owned": 1, "priced": 1, "unpriced": 0}
    (a,) = assets
    assert a.name == "2027 1st (Us)" and a.asset_id == _DETAIL["assetId"]
    assert a.model_value == 5800  # the canonical generic row, untouched
    assert a.market_value == round((7000 + 5900 + 5000) / 3)
    assert a.market_derivation["isNativeMarketPrice"] is False


def test_missing_tier_leaves_the_pick_out_never_zero():
    c = _contract([_DETAIL])
    assets, stats = finder._owned_pick_assets(c["sleeper"]["teams"][0], c, _players(late=False), {})
    assert assets == [] and stats["unpriced"] == 1


def test_unpublished_inventory_yields_no_picks():
    c = _contract(None)
    assets, stats = finder._owned_pick_assets(c["sleeper"]["teams"][0], c, _players(), {})
    assert assets == [] and stats["owned"] == 0


def test_find_trades_without_postures_is_player_only_and_says_why():
    out = finder.find_trades(
        {
            "Mine A": {
                "_finalAdjusted": 5000,
                "_sites": 6,
                "_canonicalSiteValues": {"ktcSfTep": 5000},
            },
            "Theirs A": {
                "_finalAdjusted": 5500,
                "_sites": 6,
                "_canonicalSiteValues": {"ktcSfTep": 4500},
            },
        },
        "Us",
        ["Them"],
        [{"name": "Us", "players": ["Mine A"]}, {"name": "Them", "players": ["Theirs A"]}],
        market_top_n=0,
    )
    pg = out["metadata"]["pickGeneration"]
    assert pg["applied"] is False and pg["reason"] == "no_canonical_posture"


def test_finder_pick_takes_the_forecast_for_its_originating_franchise():
    from src.trade.pick_market import TierForecast

    c = _contract([_DETAIL])
    forecast = TierForecast({"early": 1.0, "mid": 0.0, "late": 0.0}, confidence=0.5, source="t")
    (with_fc,), _ = finder._owned_pick_assets(
        c["sleeper"]["teams"][0], c, _players(), {}, {1: (2027, forecast)}
    )
    (plain,), _ = finder._owned_pick_assets(c["sleeper"]["teams"][0], c, _players(), {})
    assert with_fc.market_value > plain.market_value  # leans toward Early (7000)
    assert with_fc.model_value == plain.model_value == 5800  # canonical value untouched
    # A forecast for a different class never applies.
    (other_year,), _ = finder._owned_pick_assets(
        c["sleeper"]["teams"][0], c, _players(), {}, {1: (2028, forecast)}
    )
    assert other_year.market_value == plain.market_value
