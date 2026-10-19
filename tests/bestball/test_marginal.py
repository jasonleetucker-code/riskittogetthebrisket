"""Marginal best-ball utility: discriminating cases.

Small synthetic rosters (means in league-scored ppg) for the behavioural
cases, the synthetic dynasty_main-shaped league for the whole-roster ones.
The fallback-constants points model is pinned so results do not depend on a
box's calibration artifact.
"""

from __future__ import annotations

from src.bestball.contracts import FREE_WAIVER_COST_ASSUMPTION, REPLACEMENT_KINDS, WaiverPool
from src.bestball.marginal import (
    marginal_bestball_utility,
    marginal_bestball_utility_for_roster,
    materiality_band_ppg,
    opened_slot_families,
    select_candidates,
)
from src.bestball.params import with_overrides
from src.bestball.replacement import waiver_candidates
from src.roster_intel.best_ball_utility import UtilityPlayer
from tests.fixtures.bestball.synthetic_league import (
    build_league,
    ppg_lookup_for,
    roster_for,
    rostered_ids,
)

SLOTS = ["QB", "RB", "WR", "WR", "TE", "TE", "FLEX"]


def P(pid, pos, ppg):
    return UtilityPlayer(pid, pid, pos, ppg)


def pool_of(*players, state="available", reason=None):
    ordered = tuple(sorted(players, key=lambda p: (-p.ppg, p.player_id)))
    return WaiverPool(ordered, (), (), {"test": True}, state, reason)


EMPTY_POOL = WaiverPool((), (), (), {"test": True}, "available", "no_free_agents")

ROSTER = [
    P("qb1", "QB", 22.0),
    P("rb1", "RB", 15.0),
    P("rb2", "RB", 11.0),
    P("wr1", "WR", 20.0),
    P("wr2", "WR", 19.0),
    P("wr3", "WR", 18.0),
    P("wr4", "WR", 17.0),
    P("wr5", "WR", 6.0),
    P("te1", "TE", 12.0),
    P("te2", "TE", 8.0),
]
WEAK_FA = pool_of(P("fa_te", "TE", 3.0), P("fa_wr", "WR", 4.0), P("fa_rb", "RB", 4.5))


def run(player_id, pool, params, points_model, roster=ROSTER, slots=SLOTS, **kw):
    return marginal_bestball_utility(
        roster, player_id, slots, waiver_pool=pool, params=params, points_model=points_model, **kw
    )


def _strip_timing(d):
    d = dict(d)
    d["basis"] = {k: v for k, v in d["basis"].items() if k not in ("elapsedS", "beforeSide")}
    return d


def test_thin_position_starter_is_material_and_precise(params, points_model):
    m = run("te1", WEAK_FA, params, points_model)
    band = materiality_band_ppg(params)
    assert m.state == "available"
    assert m.delta_ppg > band
    assert m.precision_ok is True
    assert m.mc_standard_error <= band / 2
    assert m.replacement.kind == "waiver_free_agent"
    assert m.replacement.player_id == "fa_te"
    assert m.predictive_basis == "unavailable" and m.predictive_sd is None


def test_redundant_bench_wr_is_inside_the_band(params, points_model):
    m = run("wr5", WEAK_FA, params, points_model)
    assert abs(m.delta_ppg) < materiality_band_ppg(params)
    assert m.state == "available"


def test_strong_backfill_gives_a_smaller_marginal_than_none_available(params, points_model):
    strong = run("te1", pool_of(P("fa_te_strong", "TE", 11.0)), params, points_model)
    none = run("te1", EMPTY_POOL, params, points_model)
    assert none.replacement.kind == "none_available"
    assert "stays empty" in none.replacement.assumption
    assert strong.replacement.kind == "waiver_free_agent"
    assert strong.delta_ppg < none.delta_ppg


def test_vacated_spot_is_never_silently_empty(params, points_model):
    for pool in (WEAK_FA, EMPTY_POOL):
        for p in ROSTER:
            m = run(p.player_id, pool, with_overrides(params, draws=30), points_model)
            r = m.replacement
            assert r.kind in REPLACEMENT_KINDS
            assert r.assumption
            assert r.cost_assumption == FREE_WAIVER_COST_ASSUMPTION
            if r.kind == "waiver_free_agent":
                assert r.player_id is not None and r.ppg is not None


def test_backfill_that_never_starts_is_internal_promotion(params, points_model):
    # A zero-projection TE is a real, assignable zero, but rostered depth
    # always outscores him: the vacated spot is absorbed internally.
    deep = ROSTER + [P("te3", "TE", 7.5), P("te4", "TE", 7.0)]
    m = run("te2", pool_of(P("fa_zero", "TE", 0.0)), params, points_model, roster=deep)
    assert m.replacement.kind == "internal_promotion_only"
    assert m.replacement.player_id is None
    assert "fa_zero" in m.replacement.assumption


def test_candidates_capped_per_opened_family_and_the_resolve_decides(params, points_model):
    assert opened_slot_families(P("x", "WR", 1.0), SLOTS) == ("WR", "FLEX")
    assert opened_slot_families(P("x", "QB", 1.0), SLOTS) == ("QB",)
    pool = pool_of(P("a_wr", "WR", 9.0), P("b_wr", "WR", 8.0), P("c_rb", "RB", 10.0))
    chosen = select_candidates(("WR", "FLEX"), pool.candidates, cap=1)
    # WR family -> best WR; FLEX family -> best RB/WR/TE (the RB).
    assert [c.player_id for c in chosen] == ["a_wr", "c_rb"]
    m = run("wr3", pool, params, points_model)
    assert m.basis["simulatedRosters"] == 3
    assert {c["playerId"] for c in m.basis["candidatesEvaluated"]} == {"a_wr", "c_rb"}
    best = max(m.basis["candidatesEvaluated"], key=lambda c: c["impactPpg"])
    assert m.replacement.player_id == best["playerId"]


def test_deterministic_under_fixed_seed(params, points_model):
    a = run("te1", WEAK_FA, params, points_model).to_dict()
    b = run("te1", WEAK_FA, params, points_model).to_dict()
    assert _strip_timing(a) == _strip_timing(b)


def test_doubling_draws_shrinks_se_but_never_moves_the_band(params, points_model):
    small = run("te1", WEAK_FA, with_overrides(params, draws=200), points_model)
    big = run("te1", WEAK_FA, with_overrides(params, draws=400), points_model)
    assert big.mc_standard_error < small.mc_standard_error
    assert big.basis["materialityBandPpg"] == small.basis["materialityBandPpg"]
    assert big.basis["materialityBandPpg"] == params["materialityPpg"]


def test_unprojected_or_absent_player_is_unavailable_not_zero(params, points_model):
    roster = ROSTER + [P("ghost", "WR", None)]
    m = run("ghost", WEAK_FA, params, points_model, roster=roster)
    assert (m.state, m.reason, m.delta_ppg) == ("unavailable", "player_unprojected", None)
    m2 = run("nobody", WEAK_FA, params, points_model)
    assert (m2.state, m2.reason) == ("unavailable", "player_not_on_roster")
    m3 = run("te1", WEAK_FA, params, points_model, slots=[])
    assert m3.reason == "starter_slots_unresolved"
    m4 = run("te1", WEAK_FA, params, points_model, weeks=[])
    assert m4.reason == "no_remaining_fantasy_weeks"


def test_unavailable_pool_is_partial_and_labelled_upper_bound(params, points_model):
    dead = WaiverPool((), ("fa1",), (), {}, "unavailable", "pricing_unavailable:x")
    m = run("te1", dead, params, points_model)
    assert m.state == "partial"
    assert m.reason == "waiver_pool_unavailable:pricing_unavailable:x"
    assert m.replacement.kind == "none_available"
    assert "upper bound" in m.replacement.assumption


def test_weeks_and_availability_flow_through_to_the_owner(params, points_model):
    roster = [p for p in ROSTER if p.player_id != "te1"] + [
        UtilityPlayer("te1", "te1", "TE", 12.0, availability={9: "unavailable"})
    ]
    m = run("te1", WEAK_FA, params, points_model, roster=roster, weeks=[8, 9])
    full = run("te1", WEAK_FA, params, points_model, weeks=[8, 9])
    assert m.weeks == (8, 9)
    assert m.basis["drawsPerWeek"] == 200.0
    # Out for half the remaining weeks -> worth less to this roster.
    assert m.delta_ppg < full.delta_ppg


def test_whole_roster_on_dynasty_main_shaped_league(params, fast_params, points_model):
    league = build_league()
    pool = waiver_candidates(
        league["contract"],
        rostered_ids(league),
        season=2026,
        scoring_settings={},
        params=params,
        ppg_lookup=ppg_lookup_for(league["ppg"]),
    )
    roster = roster_for(league, 0)
    out = marginal_bestball_utility_for_roster(
        roster,
        league["slots"],
        waiver_pool=pool,
        params=fast_params,
        max_players=8,
        points_model=points_model,
        owner_id="owner01",
    )
    assert len(out.entries) == 8
    assert out.runs == sum(e.basis["afterRuns"] for e in out.entries)
    # The before roster is simulated once and reused for every player.
    assert out.basis["beforeSide"] == {"computed": 1, "reused": out.runs - 1}
    for e in out.entries:
        assert e.state == "available"
        assert e.owner_id == "owner01"
        assert e.replacement.player_id not in set(rostered_ids(league))
        assert not (e.replacement.player_id or "").startswith("rookie")
    assert out.to_dict()["ownerId"] == "owner01"


def test_league_is_never_resolved_implicitly(monkeypatch, params, points_model):
    import src.ros.lineup as lineup

    def boom(*a, **k):
        raise AssertionError("bestball must never resolve a league's slots itself")

    monkeypatch.setattr(lineup, "load_league_starter_slots", boom)
    monkeypatch.setattr(lineup, "resolve_starter_slots", boom)
    m = run("te1", WEAK_FA, with_overrides(params, draws=30), points_model)
    assert m.state == "available"
