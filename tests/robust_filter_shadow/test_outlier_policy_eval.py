"""Evaluation harness for outlier-corroborated-v1 (pure functions, no I/O).

docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md fixes the
definitions; these tests pin that the harness applies them as written.
"""

from __future__ import annotations

import math
from datetime import date

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.robust_filter_shadow import outlier_policy_eval as E


def test_builds_pin_the_registered_flags():
    for name, flags in E.BUILDS.items():
        pins = dict(flags)
        assert pins["dlf_offense_only_vote"] is False
        assert pins["source_freshness_weighting"] is True
        assert pins["source_family_cap"] is True
        assert pins["idp_deep_tail_native_challenger"] is False
        for other in E.OTHER_FILTER_CHALLENGERS:
            assert pins[other] is False
        assert pins[E.POLICY_FLAG] is (name == "policy")
        assert pins[E.N3_FLAG] is (name == "n3")
    assert E.SEED == 2033


def test_decide_is_each_methods_own_rule():
    votes = {
        "ktcCrowdSfTep": 5050.0,
        "dlfSf": 4980.0,
        "fantasyProsSf": 5000.0,
        "draftSharks": 3000.0,
    }
    w = {k: 1.0 for k in votes}
    assert E.decide("incumbent", votes, w, "offense") == set(
        dc._hampel_filter_per_player(sorted(votes.items()))[1]
    )
    assert E.decide("incumbent", votes, w, "offense") == {"draftSharks"}
    assert E.decide("policy", votes, w, "offense") == set()
    assert E.decide("none", votes, w, "offense") == set()
    triple = {"idpTradeCalc": 6444.0, "dlfIdp": 6227.0, "draftSharksIdp": 3181.0}
    assert E.decide("incumbent", triple, w, "idp") == set()
    assert E.decide("n3", triple, w, "idp") == {"draftSharksIdp"}
    assert E.decide("policy", votes, w, "pick") == set()


def test_blend_is_the_pipelines_capped_count_aware_blend():
    votes = {"a": 1000.0, "b": 2000.0, "c": 3000.0}
    assert (
        E.blend(votes, {k: 1.0 for k in votes})
        == dc.count_aware_mean_median_blend(sorted(votes.values()))[0]
    )
    assert E.blend({}, {}) is None


def _rec(day: str, votes_by_row: dict, dropped=None):
    rows = {
        n: {"ac": "offense", "pos": "WR", "votes": v, "w": {k: 1.0 for k in v}, "blend": None}
        for n, v in votes_by_row.items()
    }
    variants = {
        m: {n: [1000.0, 1, sorted((dropped or {}).get(m, {}).get(n, [])), "high"] for n in rows}
        for m in ("incumbent", "policy", "n3")
    }
    return {
        "board": {"scrapeTimestamp": f"{day}T12:00:00+00:00", "complete": True},
        "rows": rows,
        "variants": variants,
    }


def test_m1_holds_the_family_out_of_both_methods_and_scores_its_later_vote():
    votes = {
        "ktcCrowdSfTep": 5050.0,
        "dlfSf": 4980.0,
        "fantasyProsSf": 5000.0,
        "draftSharks": 3000.0,
    }
    held = dict(votes, yahooBoone=4000.0)
    days = {
        date(2026, 10, 1): _rec("2026-10-01", {"P": held}),
        date(2026, 10, 8): _rec("2026-10-08", {"P": held}),
    }
    units = E.m1_units(days, 7, with_screen=False)
    yb = [u for u in units if u["family"] == "yahooBoone"]
    assert len(yb) == 1
    u = yb[0]
    # Draft Sharks is the disputed vote once Yahoo/Boone is held out.
    assert u["dropped"]["incumbent"] == ["draftSharks"] and u["dropped"]["policy"] == []
    target = math.log(4000.0)
    w = {k: 1.0 for k in votes}
    v_inc = E.blend({k: v for k, v in votes.items() if k != "draftSharks"}, w)
    v_pol = E.blend(votes, w)
    assert math.isclose(u["loss"]["incumbent"], abs(math.log(v_inc) - target))
    assert math.isclose(u["loss"]["policy"], abs(math.log(v_pol) - target))


def test_paired_stat_reports_the_disputed_mean():
    units = [
        {
            "day": "2026-10-01",
            "loss": {"incumbent": 0.3, "policy": 0.1, "n3": 0.3, "none": 0.1},
            "dropped": {"incumbent": ["x"], "policy": [], "n3": ["x"], "none": []},
        },
        {
            "day": "2026-10-09",
            "loss": {"incumbent": 0.2, "policy": 0.2, "n3": 0.2, "none": 0.2},
            "dropped": {"incumbent": [], "policy": [], "n3": [], "none": []},
        },
    ]
    stat = E.paired_stat(units, "policy")
    assert stat["n"] == 1 and math.isclose(stat["mean"], -0.2)
    assert E.paired_stat(units, "policy", disputed_only=False)["n"] == 2


def test_adversarial_pass_rule_and_screen_cases_run_on_a_small_board():
    rows = {}
    for i in range(40):
        level = 9000.0 - 180.0 * i
        rows[f"P{i}"] = {
            "dynastyNerdsSfTep": level,
            "flockFantasySf": level * 1.02,
            "fantasyCalc": level * 0.98,
            "ktcCrowdSfTep": level * 1.01,
        }
    rec = _rec("2026-10-01", rows)
    for i, n in enumerate(rec["variants"]["incumbent"]):
        rec["variants"]["incumbent"][n][1] = i + 1
    out = E.adversarial(rec)
    assert out["AD1c"]["policy"]["passRate"] == 1.0
    ad3 = {(c["source"], c["kind"]): c["flagged"] for c in out["AD3"]["cases"]}
    assert ad3[("dynastyNerdsSfTep", "values_x0.01")] is True
    assert ad3[("flockFantasySf", "reversed")] is True
    assert out["AD3"]["cleanBoardFlagged"] == {}
    assert op.board_screen([], dc.correlation_group_for)["flagged"] == {}
