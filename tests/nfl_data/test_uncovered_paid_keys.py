"""``scoring_coverage.uncovered_paid_keys`` — paid rules a line leaves UNKNOWN.

Cards are real: the committed 2026-07-28 live cards and a fresh capture of
dynasty_main's public league object (148 scoring keys,
``tests/fixtures/li_scoring/dynasty_main_league_2026.json``).  Property
tests are seeded random sweeps (no hypothesis dependency in this repo).
"""

from __future__ import annotations

import ast
import json
import random
from pathlib import Path

import pytest

from src.nfl_data.scoring_coverage import Coverage, classify, uncovered_paid_keys
from src.ros import keyed_weekly_projections as kw
from src.ros.sportsdataio_weekly_projections import DERIVATIONS

ROOT = Path(__file__).resolve().parents[2]
LIVE_CARDS = json.loads(
    (ROOT / "tests/nfl_data/fixtures/live_scoring_cards_2026-07-28.json").read_text("utf-8")
)
LEAGUE = json.loads(
    (ROOT / "tests/fixtures/li_scoring/dynasty_main_league_2026.json").read_text("utf-8")
)
CARD = LEAGUE["scoring_settings"]

THRESHOLD_BONUSES = ("bonus_pass_yd_300", "bonus_pass_yd_400", "bonus_rec_yd_100")


def test_the_captured_card_is_dynasty_mains_148_key_card_without_chat_metadata():
    assert len(CARD) == 148
    assert LEAGUE["league_id"] == "1312006700437352448"
    prov = LEAGUE["_provenance"]
    assert prov["fetchedAt"].endswith("Z") and prov["leagueKey"] == "dynasty_main"
    banned = ("avatar", "metadata", "name", "draft_id", "group_id")
    assert not any(k in LEAGUE for k in banned)
    assert not any(k.startswith(("last_", "bracket", "loser_bracket")) for k in LEAGUE)


def test_the_derivation_table_is_the_providers_own_never_restated():
    assert all(isinstance(d, kw.LinearDerivation) for d in DERIVATIONS)
    targets = {d.target for d in DERIVATIONS}
    assert {"pass_inc", "idp_tkl", "fgmiss", "xpmiss"} <= targets
    # The module neither restates an identity nor imports a provider module
    # (which would pull a dormant, flag-gated provider into server.py's
    # import graph — pinned by tests/api/test_feature_flag_reachability.py).
    src = (ROOT / "src/nfl_data/scoring_coverage.py").read_text("utf-8")
    assert "LinearDerivation(" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("src.ros"), node.module


def test_default_derives_nothing_so_a_derivable_key_is_reported():
    card = {"pass_inc": -0.67}
    line = {"pass_att": 30.0, "pass_cmp": 20.0}
    assert uncovered_paid_keys(line, card) == ("pass_inc",)  # safe direction
    assert uncovered_paid_keys(line, card, derivations=DERIVATIONS) == ()


def test_linear_identities_are_derived_and_not_reported():
    card = {"pass_inc": -0.67, "idp_tkl": 0.5, "fgmiss": -1.0, "xpmiss": -3.15}
    line = {
        "pass_att": 30.0,
        "pass_cmp": 20.0,
        "idp_tkl_solo": 4.0,
        "idp_tkl_ast": 2.0,
        "fga": 2.0,
        "fgm": 1.7,
        "xpa": 3.0,
        "xpm": 2.9,
    }
    assert uncovered_paid_keys(line, card, derivations=DERIVATIONS) == ()
    # Drop one source term of each identity -> each becomes uncovered.
    for drop, target in (
        ("pass_cmp", "pass_inc"),
        ("idp_tkl_ast", "idp_tkl"),
        ("fgm", "fgmiss"),
        ("xpa", "xpmiss"),
    ):
        partial = {k: v for k, v in line.items() if k != drop}
        assert target in uncovered_paid_keys(partial, card, derivations=DERIVATIONS), drop


def test_position_gated_identity_needs_the_position():
    card = {"bonus_rec_te": 0.5}
    line = {"rec": 5.0}
    kw_ = {"derivations": DERIVATIONS}
    assert uncovered_paid_keys(line, card, **kw_) == ("bonus_rec_te",)
    assert uncovered_paid_keys(line, card, position="WR", **kw_) == ("bonus_rec_te",)
    assert uncovered_paid_keys(line, card, position="TE", **kw_) == ()
    assert uncovered_paid_keys(line, card, position="te", **kw_) == ()


@pytest.mark.parametrize("bonus", THRESHOLD_BONUSES)
def test_threshold_bonuses_are_never_derived_from_a_mean(bonus):
    card = {bonus: 3.0, "pass_yd": 0.04, "rec_yd": 0.1}
    line = {"pass_yd": 450.0, "rec_yd": 180.0}  # mean clears every threshold
    assert bonus in uncovered_paid_keys(line, card, position="QB", derivations=DERIVATIONS)


def test_explicit_zero_is_coverage_absent_and_non_numeric_are_not():
    card = {"pass_int": -2.0, "rush_td": 6.0, "rec_td": 6.0}
    out = uncovered_paid_keys({"pass_int": 0.0, "rush_td": None, "rec_td": "x"}, card)
    assert out == ("rec_td", "rush_td")


def test_non_numeric_rate_is_unknown_not_zero():
    assert uncovered_paid_keys({}, {"rec_td": "six"}) == ("rec_td",)


def test_team_level_rules_are_not_player_gaps():
    card = {"pts_allow_0": 10.0, "sack": 1.0, "def_st_td": 6.0, "rec_td": 6.0}
    assert uncovered_paid_keys({}, card) == ("rec_td",)
    for key in ("pts_allow_0", "sack", "def_st_td"):
        assert classify(key) is Coverage.NOT_APPLICABLE


def _random_line(rng: random.Random, keys: list[str]) -> dict[str, float]:
    return {k: round(rng.uniform(0.0, 9.0), 2) for k in keys if rng.random() < 0.5}


@pytest.mark.parametrize("card_name", ["dynasty_main_2026_live", "baseline", "dynasty_main"])
def test_property_zero_rate_never_reported_absent_paid_always_reported(card_name):
    card = CARD if card_name == "dynasty_main_2026_live" else LIVE_CARDS[card_name]
    keys = sorted(card)
    derivable_targets = {d.target for d in DERIVATIONS}
    rng = random.Random(20261019)
    for _ in range(60):
        line = _random_line(rng, keys)
        pos = rng.choice([None, "QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"])
        out = uncovered_paid_keys(line, card, position=pos, derivations=DERIVATIONS)
        assert list(out) == sorted(set(out))
        for key in out:
            assert float(card[key]) != 0.0, key  # a rate-0 key is never reported
            assert key not in line  # a carried key is never reported
        for key, rate in card.items():
            if float(rate) == 0.0 or key in line:
                continue
            if key in derivable_targets or classify(key) is Coverage.NOT_APPLICABLE:
                continue
            assert key in out, key  # an absent paid key is always reported
        # Never zero-filled: the caller's line is untouched.
        assert all(k in card for k in line)


def test_property_reporting_is_monotone_in_the_line():
    """Adding a numeric key to the line can only REMOVE uncovered keys."""
    keys = sorted(CARD)
    rng = random.Random(7)
    for _ in range(80):
        line = _random_line(rng, keys)
        before = set(uncovered_paid_keys(line, CARD, position="TE", derivations=DERIVATIONS))
        extra = rng.choice(keys)
        after = set(
            uncovered_paid_keys({**line, extra: 1.0}, CARD, position="TE", derivations=DERIVATIONS)
        )
        assert after <= before


def test_dynasty_main_reception_bands_are_paid_and_reported_when_unprojected():
    bands = ("rec_0_4", "rec_5_9", "rec_10_19", "rec_20_29", "rec_30_39", "rec_40p")
    assert all(float(CARD[b]) != 0.0 for b in bands)
    out = uncovered_paid_keys({"rec": 6.0, "rec_yd": 70.0}, CARD, position="WR")
    assert set(bands) <= set(out)
