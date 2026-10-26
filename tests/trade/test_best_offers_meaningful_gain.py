"""Best Offers meaningful-gain qualification (owner decision 2026-10-18, Option B).

A positive VA-adjusted canonical gain of at least the fairness-band owner's
``absoluteMinimum`` qualifies a Best Offers package even when the shared
relative band rates it FAIR.  The band label, thresholds and
``equity_verdict`` output stay exactly as they are -- FAIR is not turned into
SLIGHT EDGE and ``win`` is not forced true -- and the rule is Best Offers ONLY:
the Trade Calculator verdict and the Package Builder keep the shared rule.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from src.trade import best_offers as bo
from src.trade.analyze_trade import equity_verdict
from src.valuation_math import fairness_bands

KTC = MARKET_KTC
IDPTC = MARKET_IDPTC
MIN = int(fairness_bands.ABSOLUTE_MINIMUM)


def _league(mine, theirs):
    """``mine`` / ``theirs``: ``(name, pos, board, ktc, idptc, team)``."""
    players, rows = {}, []
    for name, pos, board, ktc, idptc, team in (*mine, *theirs):
        sites = {k: v for k, v in ((KTC, ktc), (IDPTC, idptc)) if v is not None}
        players[name] = {"_canonicalSiteValues": dict(sites), "position": pos, "_sites": 8}
        rows.append(
            {
                "displayName": name,
                "canonicalName": name,
                "position": pos,
                "team": team,
                "rankDerivedValue": board,
                "canonicalSiteValues": dict(sites),
                "freshnessExcludedSources": [],
                "assetClass": "player",
            }
        )
    teams = [
        {"name": "Us", "ownerId": "1", "players": [m[0] for m in mine]},
        {"name": "Them", "ownerId": "2", "players": [t[0] for t in theirs]},
    ]
    return players, teams, {"playersArray": rows}


def _card(mine, theirs):
    players, teams, contract = _league(mine, theirs)
    result = bo.build_best_offers(players, "Us", teams, contract=contract, use_team_context=False)
    return next(o for o in result["opponents"] if o["team"] == "Them")


# ── the pure rule ──────────────────────────────────────────────────────────


def test_a_gain_of_at_least_the_minimum_but_below_the_slight_band_qualifies_as_fair():
    # 3-for-3: +595 after the Value Adjustment, 2.96% of the larger package
    # utility (fairness_bands_v2).  (The v1 example, +771 vs 7,390, read 3.09%
    # of the larger ADJUSTED side but 3.80% of the larger utility: SLIGHT.)
    equity = equity_verdict([9000, 8000, 7000], [9300, 8300, 7100])
    before = copy.deepcopy(equity)
    assert equity["band"]["level"] == "fair"
    assert equity["band"]["relativePct"] < fairness_bands.SLIGHT_PCT
    assert equity["vaAdjustedGap"] >= MIN
    q = bo.best_offers_qualification(equity)
    assert q is not None
    assert q["basis"] == bo.QUALIFICATION_MEANINGFUL_GAIN
    assert q["bandLevel"] == "fair" and q["bandLabel"] == "FAIR"
    assert q["minimumGain"] == MIN
    # The canonical verdict is read, never rewritten.
    assert equity == before
    assert equity["win"] is False


@pytest.mark.parametrize(
    ("send", "receive", "expected"),
    [
        (9000, 9000 + MIN, bo.QUALIFICATION_MEANINGFUL_GAIN),  # exactly the minimum
        (9000, 9000 + MIN - 1, None),  # one point short, FAIR
        (9000, 9300, bo.QUALIFICATION_MEANINGFUL_GAIN),
        (9300, 9000, None),  # negative gap of the same size
        (9000, 5000, None),  # a large negative gap never qualifies
        (5000, 6000, bo.QUALIFICATION_CANONICAL_WIN),  # past the band: a canonical win
    ],
)
def test_boundaries(send, receive, expected):
    equity = equity_verdict([send], [receive])
    q = bo.best_offers_qualification(equity)
    assert (q["basis"] if q else None) == expected


def test_a_canonical_win_keeps_its_shared_definition():
    equity = equity_verdict([5000], [6000])
    assert equity["win"] is True and equity["band"]["level"] != "fair"
    assert bo.best_offers_qualification(equity)["basis"] == bo.QUALIFICATION_CANONICAL_WIN


# ── end to end through Best Offers ─────────────────────────────────────────


def test_a_meaningful_fair_gain_reaches_the_card_truthfully_labelled():
    mine = [("Our WR", "WR", 9000, 9200, 9200, "CIN")]
    theirs = [("Their RB", "RB", 9300, 9000, 9000, "BUF")]  # +300, 3.23%: FAIR
    card = _card(mine, theirs)
    assert card["status"] == "qualified"
    offer = card["offer"]
    assert offer["canonical"]["win"] is False
    assert offer["canonical"]["band"]["label"] == "FAIR"
    assert offer["qualification"]["basis"] == bo.QUALIFICATION_MEANINGFUL_GAIN
    assert offer["qualification"]["gain"] == 300
    why = offer["whyThisHelpsUs"]
    assert "+300" in why and "FAIR" in why
    assert "clear win" not in why.lower()


def test_one_point_below_the_minimum_does_not_qualify_when_fair():
    mine = [("Our WR", "WR", 9000, 9200, 9200, "CIN")]
    theirs = [("Their RB", "RB", 9000 + MIN - 1, 9000, 9000, "BUF")]
    card = _card(mine, theirs)
    assert card["status"] == "no_result"
    assert card["noResultReason"] == "no_canonical_win"


def test_the_external_guard_still_applies_to_a_meaningful_gain():
    # +300 FAIR for us, but both calculators leave the opponent clearly behind.
    mine = [("Our WR", "WR", 9000, 6000, 6000, "CIN")]
    theirs = [("Their RB", "RB", 9300, 9000, 9000, "BUF")]
    card = _card(mine, theirs)
    assert card["status"] == "no_result"
    assert card["noResultReason"] == "opponent_not_even_on_any_calculator"


def test_whole_package_coverage_is_still_required():
    mine = [("Our WR", "WR", 9000, None, None, "CIN"), ("Our TE", "TE", 100, 200, 200, "CIN")]
    theirs = [("Their RB", "RB", 9300, 9000, 9000, "BUF")]
    # +9,100 board gain for "Our WR" alone would qualify, but no approved
    # calculator prices "Our WR": a package containing it can never qualify.
    card = _card(mine, theirs)
    if card["status"] == "qualified":
        assert "Our WR" not in [a["name"] for a in card["offer"]["send"]]
        assert card["offer"]["external"]["coverage"] == "complete"


def test_a_clear_win_keeps_the_canonical_win_basis_on_the_card():
    mine = [("Our WR", "WR", 4000, 5000, 5100, "CIN")]
    theirs = [("Their RB", "RB", 5000, 4800, 4900, "BUF")]
    offer = _card(mine, theirs)["offer"]
    assert offer["canonical"]["win"] is True
    assert offer["qualification"]["basis"] == bo.QUALIFICATION_CANONICAL_WIN


# ── no source-of-truth drift ──────────────────────────────────────────────


def test_the_threshold_is_the_band_owners_absolute_minimum(monkeypatch):
    equity = equity_verdict([9000], [9300])
    assert bo.best_offers_qualification(equity) is not None
    monkeypatch.setattr(fairness_bands, "ABSOLUTE_MINIMUM", 301.0)
    assert bo.best_offers_qualification(equity) is None


def test_best_offers_carries_no_second_threshold_constant():
    src = Path(bo.__file__).read_text(encoding="utf-8")
    assert not re.search(r"(?<![\w.])250(?![\w.])", src)


def test_the_rule_does_not_reach_the_calculator_verdict_or_the_package_builder():
    from src.trade import package_builder  # noqa: PLC0415

    equity = equity_verdict([9000], [9300])
    # The Trade Calculator's shared verdict is unchanged: FAIR, not a win.
    assert equity["win"] is False and equity["band"]["level"] == "fair"
    src = Path(package_builder.__file__).read_text(encoding="utf-8")
    assert "best_offers_qualification" not in src
    assert "qualification=" not in src
