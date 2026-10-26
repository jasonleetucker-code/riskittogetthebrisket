"""Replacement-level SHADOW (IDP accuracy, Lane B): definitions, adversarial cases, evidence.

Layout:

* synthetic rosters -- every definition and every guard (missing is never zero,
  unknown health is not healthy, one free agent goes to one team, whole-roster
  evaluation is not a sum of per-player deltas);
* the committed evidence artifact -- invariants any regeneration must keep;
* the pinned real rosters -- recomputed when the gitignored Sleeper cache is
  present (skipped, with the reason, when it is not).

The exact lineup solver is the production one (``src.ros.lineup``), injected the
same way the offline report injects it.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
import statistics
from pathlib import Path

import pytest

from src.league_valuation import replacement_shadow as rs

# The report script loads the module by path and reuses this very object (sys.modules),
# so there is exactly one copy of its classes in the process.
from scripts.idp_accuracy.replacement_report import SolverPort  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "docs/valuation/idp_accuracy/evidence/b_replacement_2026-10-25.json"
CACHE = REPO / "data/idp_accuracy/cache"

CFG = rs.load_config()
PORT = SolverPort()
SLOTS = ["QB", "RB", "WR", "FLEX", "DL", "LB", "DB"]
WEEKS = (1, 2, 3, 4, 5, 6)


def rec(
    pid: str,
    pos: str,
    weekly,
    *,
    name: str | None = None,
    fps: tuple[str, ...] = (),
    team: str | None = "AAA",
    status: str | None = "Active",
    inj: str | None = None,
    value: float | None = None,
    team_weeks=None,
) -> rs.PlayerRecord:
    if not isinstance(weekly, dict):
        weekly = {w: float(p) for w, p in zip(WEEKS, weekly)}
    return rs.PlayerRecord(
        player_id=pid,
        name=name or pid,
        position=pos,
        fantasy_positions=tuple(fps) or (pos,),
        nfl_team=team,
        status=status,
        injury_status=inj,
        board_value=value,
        weekly=weekly,
        team_weeks=team_weeks,
    )


def flat(pts: float, n: int = 6) -> list[float]:
    return [pts] * n


def book(*records: rs.PlayerRecord) -> dict[str, rs.PlayerRecord]:
    return {r.player_id: r for r in records}


def small_cfg(**overrides):
    c = copy.deepcopy(CFG)
    for dotted, v in overrides.items():
        node = c
        parts = dotted.split("__")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = v
    return c


# ── configuration and units ─────────────────────────────────────────────────


def test_config_id_matches_content_and_a_silent_edit_is_refused(tmp_path):
    assert CFG["paramSetId"] == rs.param_set_id_for(CFG)
    edited = copy.deepcopy(CFG)
    edited["window"]["minGames"]["value"] = 2  # a PRIOR changed without a new id
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match its content"):
        rs.load_config(p)


def test_every_constant_in_the_config_is_classified():
    def walk(node, path=""):
        if isinstance(node, dict):
            if "value" in node:
                assert node.get("classification") in {"PRIOR", "CONVENTION", "STRUCTURAL"}, path
                assert node.get("why"), path
            for k, v in node.items():
                walk(v, f"{path}.{k}")

    walk(CFG)


def test_ppg_is_none_below_min_games_never_zero():
    r = rec("a", "DB", {1: 10.0, 2: 12.0})
    assert rs.ppg_of(r, WEEKS, min_games=3) is None
    assert rs.ppg_of(r, WEEKS, min_games=2) == 11.0
    assert rs.ppg_of(rec("b", "DB", {}), WEEKS) is None


# ── health: injury status and byes; a missing status is UNKNOWN ──────────────


@pytest.mark.parametrize(
    "team,status,inj,state",
    [
        ("AAA", "Active", None, rs.AVAILABLE),
        ("AAA", "Active", "", rs.AVAILABLE),
        ("AAA", "Active", "Questionable", rs.UNCERTAIN),
        ("AAA", "Active", "Out", rs.UNAVAILABLE),
        ("AAA", "Active", "IR", rs.UNAVAILABLE),
        ("AAA", "Active", "Doubtful", rs.UNAVAILABLE),
        ("AAA", "Inactive", None, rs.UNAVAILABLE),
        ("AAA", "Injured Reserve", None, rs.UNAVAILABLE),
        (None, "Active", None, rs.UNAVAILABLE),
        ("AAA", None, None, rs.UNKNOWN),
        ("AAA", "", None, rs.UNKNOWN),
        ("AAA", "Some New Status", None, rs.UNKNOWN),
        ("AAA", "Active", "MysteryDesignation", rs.UNKNOWN),
    ],
)
def test_strict_health(team, status, inj, state):
    h = rs.classify_health(nfl_team=team, status=status, injury_status=inj, cfg=CFG)
    assert h.state == state
    assert h.usable == (state in (rs.AVAILABLE, rs.UNCERTAIN))


def test_missing_status_is_never_healthy_but_the_legacy_rule_said_it_was():
    strict = rs.classify_health(nfl_team="AAA", status=None, injury_status=None, cfg=CFG)
    loose = rs.classify_health_loose(nfl_team="AAA", status=None, injury_status=None, cfg=CFG)
    assert strict.state == rs.UNKNOWN and not strict.usable
    assert loose.usable  # Investigation B's shadow rule: kept only to reproduce it


# ── pools: who is a replacement, and every exclusion is counted ──────────────


def fa_pool_fixture():
    return book(
        rec("healthy_star", "DB", [14, 12, 15, 13, 16, 14], value=1500, name="Healthy Star"),
        rec("hurt_star", "DB", [20, 22, 21, 19, 20, 22], value=2600, inj="Out", name="Hurt Star"),
        rec("unknown_health", "DB", [12, 12, 12, 12, 12, 12], status=None, value=1400),
        rec("prospect", "DB", {}, value=2400, name="High Priced Prospect"),  # 0 games, high value
        rec("two_games", "DB", {1: 25.0, 2: 24.0}, value=1300),
        rec("flat_zero", "DB", [0, 0, 0, 0, 0, 0], value=1200),
        rec(
            "unpriced_producer",
            "DB",
            [13, 13, 13, 13, 13, 13],
            value=None,
            name="Unpriced Producer",
        ),
        rec("questionable", "DB", [9, 9, 9, 9, 9, 9], inj="Questionable", value=900),
    )


def test_census_counts_every_exclusion_and_never_zeroes_an_unpriced_player():
    records = fa_pool_fixture()
    census = rs.build_census(records, set(), weeks=WEEKS, cfg=CFG, positions=("DB",))
    pool = census.pool("DB")
    assert {e.player_id for e in pool.entries} == {
        "healthy_star",
        "unpriced_producer",
        "questionable",
    }
    assert dict(pool.excluded) == {
        "health_unavailable": 1,  # the injured star
        "health_unknown": 1,  # missing status
        "no_games": 1,  # the priced prospect with no production
        "below_min_games": 1,
        "zero_production": 1,
    }
    assert pool.unpriced == 1  # counted, not valued at zero
    assert [e.player_id for e in pool.by_value()] == ["healthy_star", "questionable"]
    assert all(e.value is not None for e in pool.by_value())
    # the ppg order includes the unpriced producer; the value order cannot
    assert [e.player_id for e in pool.by_ppg()][:2] == ["healthy_star", "unpriced_producer"]


def test_injured_high_value_free_agent_does_not_set_the_level_but_the_legacy_anchor_did():
    records = fa_pool_fixture()
    census = rs.build_census(records, set(), weeks=WEEKS, cfg=CFG, positions=("DB",))
    assert rs.level_best(census.pool("DB").entries, "value").value == 1500.0
    legacy = rs.build_census(
        records,
        set(),
        weeks=WEEKS,
        cfg=CFG,
        positions=("DB",),
        rule=rs.PoolRule.legacy_b(health="none"),
    )
    assert (
        rs.level_best(legacy.pool("DB").entries, "value").value == 2600.0
    )  # the injured star set it
    loose = rs.build_census(
        records,
        set(),
        weeks=WEEKS,
        cfg=CFG,
        positions=("DB",),
        rule=rs.PoolRule.legacy_b(health="loose"),
    )
    # the loose rule drops the Out player but KEEPS the missing-status player and the zero-production prospect
    ids = {e.player_id for e in loose.pool("DB").entries}
    assert "hurt_star" not in ids and {"unknown_health", "prospect"} <= ids
    assert (
        rs.level_best(loose.pool("DB").entries, "value").value == 2400.0
    )  # the zero-production prospect


def test_zero_production_prospect_is_not_a_weekly_replacement_whatever_his_price():
    records = book(
        rec("prospect", "LB", {}, value=2300),
        rec("grinder", "LB", [8, 9, 7, 8, 9, 7], value=700),
    )
    pool = rs.build_census(records, set(), weeks=WEEKS, cfg=CFG, positions=("LB",)).pool("LB")
    assert [e.player_id for e in pool.entries] == ["grinder"]
    assert rs.level_best(pool.entries, "value").value == 700.0
    assert rs.level_best(pool.entries, "ppg").value == pytest.approx(8.0)


def test_unpriced_best_producer_sets_the_ppg_level_and_leaves_the_value_level_to_priced_players():
    records = book(
        rec("unpriced", "DL", flat(14.0), value=None, name="Unpriced Edge"),
        rec("priced_a", "DL", flat(9.0), value=800),
        rec("priced_b", "DL", flat(8.0), value=600),
    )
    pool = rs.build_census(records, set(), weeks=WEEKS, cfg=CFG, positions=("DL",)).pool("DL")
    assert rs.level_best(pool.entries, "ppg").set_by == ("Unpriced Edge",)
    v = rs.level_best(pool.entries, "value")
    assert v.value == 800.0 and v.n == 2  # the unpriced player is not in the value pool
    assert pool.unpriced == 1


def test_levels_with_too_small_a_pool_are_undefined_with_a_reason_never_zero():
    records = book(rec("a", "DL", flat(9.0), value=800), rec("b", "DL", flat(8.0), value=600))
    entries = (
        rs.build_census(records, set(), weeks=WEEKS, cfg=CFG, positions=("DL",)).pool("DL").entries
    )
    for lvl in (
        rs.level_rank(entries, "ppg", 3),
        rs.level_topk_median(entries, "ppg", 5),
        rs.level_best([], "ppg"),
        rs.level_pool_mean([], "value"),
        rs.level_banded_top([], "ppg"),
    ):
        assert lvl.value is None and lvl.reason
    # the LI-5 banded tier uses what exists (a pool of two) and says how many
    banded = rs.level_banded_top(entries, "ppg")
    assert banded.value == pytest.approx(8.5) and banded.n == 2


def test_multi_eligible_free_agent_is_a_candidate_at_every_position_he_may_fill():
    records = book(
        rec("hybrid", "DL", flat(12.0), fps=("DL", "LB"), value=1000, name="Edge Hybrid")
    )
    sleeper = rs.build_census(records, set(), weeks=WEEKS, cfg=CFG, positions=("DL", "LB"))
    assert len(sleeper.pool("DL").entries) == 1 and len(sleeper.pool("LB").entries) == 1
    nominal = rs.build_census(
        records,
        set(),
        weeks=WEEKS,
        cfg=CFG,
        positions=("DL", "LB"),
        rule=rs.PoolRule.nominal_only(),
    )
    assert len(nominal.pool("DL").entries) == 1 and len(nominal.pool("LB").entries) == 0


def test_eligibility_uncertainty_reports_how_much_a_hybrid_moves_a_level():
    team = [
        rec("t_dl", "DL", flat(11.0), value=2000),
        rec("t_lb", "LB", flat(10.0), value=1900),
    ]
    fas = [
        rec("hybrid", "DL", flat(12.0), fps=("DL", "LB"), value=1000),
        rec("lb_fa", "LB", flat(6.0), value=500),
    ]
    records = book(*team, *fas)
    out = rs.eligibility_uncertainty(
        records,
        {"T01": ["t_dl", "t_lb"]},
        PORT,
        ["DL", "LB"],
        weeks=WEEKS,
        cfg=CFG,
        positions=("DL", "LB"),
    )
    assert out["LB"]["viablePoolMultiEligible"] == 1
    assert out["LB"]["sleeperMinusNominal"]["d2_bestPpg"] == pytest.approx(
        12.0 - 6.0
    )  # hybrid raises the LB level
    assert out["DL"]["sleeperMinusNominal"].get("d2_bestPpg", 0.0) == pytest.approx(0.0)


# ── D1: the league-wide starter threshold, FLEX and SUPER_FLEX included ─────


def test_starter_threshold_counts_flex_occupants_at_their_own_position():
    slots = ["RB", "WR", "FLEX"]
    t1 = [rec("rb1", "RB", flat(12.0)), rec("wr1", "WR", flat(14.0)), rec("wr2", "WR", flat(13.0))]
    t2 = [rec("rb2", "RB", flat(11.0)), rec("rb3", "RB", flat(10.0)), rec("wr3", "WR", flat(9.0))]
    records = book(*t1, *t2)
    th = rs.starter_thresholds(
        {"T01": [r.player_id for r in t1], "T02": [r.player_id for r in t2]},
        records,
        PORT,
        slots,
        value_of=lambda r: rs.ppg_of(r, WEEKS),
    )
    # team 1's FLEX goes to its second WR; team 2's FLEX goes to its second RB
    assert th.slot_fill["FLEX"] == {"WR": 1, "RB": 1}
    assert th.by_position["WR"].marginals == [13.0, 9.0]
    assert th.by_position["RB"].marginals == [12.0, 10.0]
    assert th.by_position["WR"].median_marginal() == pytest.approx(11.0)
    assert th.starters_per_team("WR") == 1.5


def test_hybrid_is_counted_at_the_slot_he_fills_or_at_his_listed_position_on_request():
    team = [rec("dl", "DL", flat(9.0)), rec("hyb", "DL", flat(15.0), fps=("DL", "LB"))]
    records = book(*team)
    ids = {"T01": ["dl", "hyb"]}
    by_slot = rs.starter_thresholds(
        ids, records, PORT, ["LB", "DL"], value_of=lambda r: rs.ppg_of(r, WEEKS)
    )
    nominal = rs.starter_thresholds(
        ids,
        records,
        PORT,
        ["LB", "DL"],
        value_of=lambda r: rs.ppg_of(r, WEEKS),
        attribution=rs.ATTR_NOMINAL,
    )
    assert by_slot.by_position["LB"].starters == [15.0] and by_slot.by_position["DL"].starters == [
        9.0
    ]
    assert (
        sorted(nominal.by_position["DL"].starters) == [9.0, 15.0]
        and "LB" not in nominal.by_position
    )


def test_unknown_value_is_not_a_candidate_not_a_zero():
    team = [rec("known", "WR", flat(10.0)), rec("no_games", "WR", {})]
    th = rs.starter_thresholds(
        {"T01": ["known", "no_games"]},
        book(*team),
        PORT,
        ["WR", "WR"],
        value_of=lambda r: rs.ppg_of(r, WEEKS),
    )
    assert th.by_position["WR"].starters == [
        10.0
    ]  # one WR slot filled; the other is not a 0.0 starter


# ── the host rule for a played week ──────────────────────────────────────────


def test_host_zero_fill_starts_a_non_player_over_a_negative_scorer_only_in_realised_weeks():
    records = book(rec("fumbler", "RB", {1: -3.0}), rec("bye_week_rb", "RB", {2: 5.0}))
    realised = rs.WeeklyEngine(records, PORT, ["RB"], (1, 2), zero_fill_rostered=True)
    # week 1: the non-player (0.0) beats the -3.0; week 2: the 5.0 starts
    assert realised.solve(["fumbler", "bye_week_rb"], 1).score == 0.0
    assert realised.solve(["fumbler", "bye_week_rb"], 2).score == 5.0
    projected = rs.WeeklyEngine(records, PORT, ["RB"], (1, 2), zero_fill_rostered=False)
    assert (
        projected.solve(["fumbler", "bye_week_rb"], 1).score == -3.0
    )  # no projection => not a candidate
    assert realised.starter_weeks(["fumbler", "bye_week_rb"]) == {
        "bye_week_rb": [2]
    }  # non-player is no starter


# ── D5: every free agent goes to ONE team ────────────────────────────────────


def alloc_fixture():
    # two teams with the same hole at DB; one free agent is the best claim for both
    t1 = [rec("a_db", "DB", flat(5.0)), rec("a_dl", "DL", flat(9.0)), rec("a_lb", "LB", flat(9.0))]
    t2 = [rec("b_db", "DB", flat(7.0)), rec("b_dl", "DL", flat(9.0)), rec("b_lb", "LB", flat(9.0))]
    fas = [
        rec("star", "DB", flat(16.0), name="Star FA"),
        rec("second", "DB", flat(11.0), name="Second FA"),
        rec("third", "DB", flat(8.0), name="Third FA"),
    ]
    return book(*t1, *t2, *fas), {
        "T01": [r.player_id for r in t1],
        "T02": [r.player_id for r in t2],
    }


def test_two_teams_wanting_the_same_free_agent_split_them_by_total_gain():
    records, teams = alloc_fixture()
    slots = ["DB", "DL", "LB"]
    engine = rs.WeeklyEngine(records, PORT, slots, WEEKS)
    census = rs.build_census(records, {p for r in teams.values() for p in r}, weeks=WEEKS, cfg=CFG)
    alloc = rs.allocate_free_agents(
        teams, engine, census, cfg=small_cfg(allocation__rounds__value=1), roster_cap=None
    )
    assert alloc.round1_top_choice_collisions == 1  # both teams' best claim is the star
    got = {c.team: c.name for c in alloc.claims}
    # T01 (DB 5.0) gains 11 from the star, T02 (DB 7.0) gains 9: the star goes to T01, T02 takes the second
    assert got == {"T01": "Star FA", "T02": "Second FA"}
    assert len({c.player_id for c in alloc.claims}) == len(
        alloc.claims
    )  # nobody is allocated twice
    assert alloc.round1_independent_gain > alloc.round1_matched_gain  # competition costs something


def test_matching_total_equals_the_brute_force_optimum_on_seeded_instances():
    import random

    slots = ["DB", "DL"]
    for seed in range(8):
        rng = random.Random(seed)
        team_rows, ids = [], {}
        for t in ("T01", "T02", "T03"):
            members = [
                rec(f"{t}_db", "DB", flat(round(rng.uniform(3, 12), 1))),
                rec(f"{t}_dl", "DL", flat(round(rng.uniform(3, 12), 1))),
            ]
            team_rows += members
            ids[t] = [m.player_id for m in members]
        fa_rows = [
            rec(
                f"fa{i}",
                rng.choice(["DB", "DL"]),
                flat(round(rng.uniform(4, 16), 1)),
                name=f"FA{i}",
            )
            for i in range(4)
        ]
        records = book(*team_rows, *fa_rows)
        engine = rs.WeeklyEngine(records, PORT, slots, WEEKS)
        census = rs.build_census(
            records, {p for r in ids.values() for p in r}, weeks=WEEKS, cfg=CFG
        )
        alloc = rs.allocate_free_agents(
            ids, engine, census, cfg=small_cfg(allocation__rounds__value=1), roster_cap=None
        )

        def gain(team, fa):
            return (engine.score(ids[team] + [fa]) - engine.score(ids[team])) / len(WEEKS)

        teams_l, fas_l = sorted(ids), [r.player_id for r in fa_rows]
        best = 0.0
        for perm in itertools.permutations(fas_l + [None] * len(teams_l), len(teams_l)):
            best = max(best, sum(gain(t, f) for t, f in zip(teams_l, perm) if f is not None))
        assert alloc.round1_matched_gain == pytest.approx(best, abs=1e-9), seed


def test_a_claim_needs_a_free_drop_when_the_roster_is_at_the_cap_and_it_is_exact():
    records, teams = alloc_fixture()
    teams = {t: r + [f"{t}_bench"] for t, r in teams.items()}
    for t in teams:
        records[f"{t}_bench"] = rec(f"{t}_bench", "WR", flat(1.0))  # never starts at these slots
    slots = ["DB", "DL", "LB"]
    engine = rs.WeeklyEngine(records, PORT, slots, WEEKS)
    census = rs.build_census(records, {p for r in teams.values() for p in r}, weeks=WEEKS, cfg=CFG)
    alloc = rs.allocate_free_agents(
        teams, engine, census, cfg=small_cfg(allocation__rounds__value=1), roster_cap=4
    )
    assert alloc.teams_without_free_drop == 0
    assert all(c.drop and c.drop.endswith("_bench") for c in alloc.claims)
    final = rs.apply_claims(teams, alloc.claims)
    assert all(len(final[t]) == 4 for t in final)


# ── D6: the replacement THIS roster would use after the transaction ──────────


def test_team_specific_replacement_depends_on_the_roster_after_the_transaction():
    records, teams = alloc_fixture()
    for r in (
        rec("a_wr", "WR", flat(12.0)),
        rec("b_wr", "WR", flat(12.0)),
        rec("wr_fa", "WR", flat(10.0), name="WR FA"),
    ):
        records[r.player_id] = r
    slots = ["DB", "WR"]
    engine = rs.WeeklyEngine(records, PORT, slots, WEEKS)
    census = rs.build_census(
        records, {p for r in teams.values() for p in r} | {"a_wr", "b_wr"}, weeks=WEEKS, cfg=CFG
    )
    pool = [e for pl in census.pools.values() for e in pl.entries]
    # T01 keeps its WR: the WR free agent helps nobody, the DB free agent fills its DB hole
    keeps = rs.team_replacement_after(["a_db", "a_wr"], pool, engine, positions=("DB", "WR"))
    assert keeps.by_position["WR"]["state"] == "internal_promotion_only"
    assert keeps.by_position["DB"]["claim"] == "Star FA"
    # T01 trades the WR away: now the WR free agent is its best WR claim
    loses = rs.team_replacement_after(["a_db"], pool, engine, positions=("DB", "WR"))
    assert loses.by_position["WR"]["claim"] == "WR FA" and loses.by_position["WR"][
        "gainPerWeek"
    ] == pytest.approx(10.0)
    # competition: with the star already taken elsewhere, the DB claim falls to the next free agent
    contested = rs.team_replacement_after(
        ["a_db"], pool, engine, positions=("DB",), exclude={"star"}
    )
    assert contested.by_position["DB"]["claim"] == "Second FA"


# ── marginal optimised contribution: whole roster, never a sum ───────────────


def test_marginal_contribution_is_a_whole_roster_solve_and_may_be_negative_over_a_better_backfill():
    ros = [
        rec("rb_hi", "RB", flat(20.0)),
        rec("rb_lo", "RB", flat(10.0)),
        rec("rb_bench", "RB", flat(4.0)),
    ]
    backfill = rec("fa_rb", "RB", flat(12.0), name="Backfill RB")
    records = book(*ros, backfill)
    engine = rs.WeeklyEngine(records, PORT, ["RB", "RB"], WEEKS)
    spec = {"RB": {"fa": rs.ReplacementSpec("fa", backfill)}}
    out = rs.marginal_contributions({"T01": [r.player_id for r in ros]}, engine, spec)
    # lineup is rb_hi + rb_lo = 30; without rb_hi the next man up (rb_bench) starts: 14 -> loses 16
    assert out["rb_hi"]["contribution_empty"] == pytest.approx(16.0)
    assert out["rb_lo"]["contribution_empty"] == pytest.approx(6.0)
    assert out["rb_bench"]["contribution_empty"] == 0.0 and out["rb_bench"]["startWeeks"] == 0
    # with the 12.0 backfill: without rb_hi lineup = 12 + 10; without rb_lo = 20 + 12
    assert out["rb_hi"]["contribution_over_fa"] == pytest.approx(30.0 - 22.0)
    assert out["rb_lo"]["contribution_over_fa"] == pytest.approx(
        30.0 - 32.0
    )  # worse than the free backfill
    # the bench player would be replaced by the better backfill if he were the one dropped: holding him costs a spot
    assert out["rb_bench"]["contribution_over_fa"] == pytest.approx(30.0 - 32.0)
    # contributions are NOT additive: removing both starters costs more than the sum of the singles
    assert sum(out[p]["contribution_empty"] for p in ("rb_hi", "rb_lo")) == pytest.approx(22.0)
    both_gone = engine.per_week(["rb_bench"])[0]
    assert (30.0 - both_gone) > 22.0  # 26 lost, not 22


# ── whole-roster package evaluation ──────────────────────────────────────────


def package_fixture():
    ros = [
        rec("rb1", "RB", flat(20.0)),
        rec("rb2", "RB", flat(10.0)),
        rec("wr1", "WR", flat(15.0)),
        rec("wr2", "WR", flat(9.0)),
        rec("bench", "WR", flat(2.0)),
    ]
    other = [
        rec("star_rb", "RB", flat(25.0), name="Star RB"),
        rec("no_line", "RB", {}, name="Unpriced Prospect"),
    ]
    return book(*ros, *other), [r.player_id for r in ros]


def test_package_is_a_whole_before_after_roster_and_the_naive_sum_double_counts():
    records, roster = package_fixture()
    engine = rs.WeeklyEngine(records, PORT, ["RB", "RB"], WEEKS)
    res = rs.evaluate_package(roster, give=["rb2"], get=["star_rb"], engine=engine)
    assert res.status == "ok"
    # before: RB 20 + 10 = 30 (WR players cannot fill RB-only slots here); after: 25 + 20 = 45
    assert res.before_per_week == pytest.approx(30.0) and res.after_per_week == pytest.approx(45.0)
    assert res.delta_per_week == pytest.approx(15.0)
    # naive: removing rb2 alone costs (bench WR cannot cover) 10; adding star alone gains 25 + 20 - 30 = 15 -> 5
    assert res.naive_sum_of_player_deltas == pytest.approx(5.0)
    assert res.interaction == pytest.approx(10.0)  # the double count the whole-roster solve avoids
    assert len(res.per_week_delta) == len(WEEKS)


def test_package_refuses_a_player_the_team_does_not_hold_and_never_scores_an_unpriced_get_as_zero():
    records, roster = package_fixture()
    engine = rs.WeeklyEngine(records, PORT, ["RB", "RB"], WEEKS)
    assert (
        rs.evaluate_package(roster, ["ghost"], ["star_rb"], engine).status == "give_not_on_roster"
    )
    assert rs.evaluate_package(roster, ["rb2"], ["rb1"], engine).status == "get_already_on_roster"
    incomplete = rs.evaluate_package(roster, ["rb2"], ["no_line"], engine)
    assert incomplete.status == "incomplete" and incomplete.unpriced_get == ["no_line"]
    assert incomplete.delta_per_week is None  # not evaluated as a 0-point player


def test_package_over_the_cap_drops_the_free_never_starter_first():
    records, roster = package_fixture()
    engine = rs.WeeklyEngine(records, PORT, ["RB", "RB"], WEEKS)
    res = rs.evaluate_package(roster, give=[], get=["star_rb"], engine=engine, roster_cap=5)
    assert res.over_cap_by == 1
    assert res.forced_drops and res.forced_drops[0] in {
        "wr1",
        "wr2",
        "bench",
    }  # none of them starts at RB
    assert res.delta_per_week == pytest.approx(15.0)  # the drop cost nothing


# ── the winner's curse and the interval definition ───────────────────────────


def noisy_league(seed=3, n_fa=40, weeks=6):
    import random

    rng = random.Random(seed)
    team = [
        rec(f"s{i}", "DB", [max(0.0, rng.gauss(14, 4)) for _ in range(weeks)]) for i in range(12)
    ]
    fas = [
        rec(
            f"f{i}",
            "DB",
            [max(0.0, rng.gauss(7, 5)) for _ in range(weeks)],
            value=500 + i,
            name=f"FA{i}",
        )
        for i in range(n_fa)
    ]
    return book(*team, *fas), {"T01": [r.player_id for r in team]}


def test_conditional_interval_contains_its_point_and_the_best_of_noise_is_flagged_as_inflated():
    records, teams = noisy_league()
    slots = ["DB", "DB", "DB"]
    flat_, det, aux = rs.compute_level_set(
        records, teams, PORT, slots, weeks=WEEKS, cfg=CFG, positions=("DB",), detail=True
    )
    cis = rs.conditional_level_cis(
        records, det, aux, weeks=WEEKS, cfg=CFG, replicates=200, positions=("DB",)
    )
    for k, cell in cis["DB"].items():
        if cell["ci95"] is not None:
            lo, hi = cell["ci95"]
            assert lo - 1e-9 <= cell["point"] <= hi + 1e-9, k
    resel = rs.reselection_bootstrap(
        records, teams, PORT, slots, weeks=WEEKS, cfg=CFG, replicates=60, positions=("DB",)
    )
    best = resel["DB"]["d2_bestPpg"]
    assert (
        best["reselection"]["meanMinusPoint"] > 0
    )  # a maximum of resampled noise sits above the observed one
    assert 0.0 <= best["identityStability"]["sameChoiceShare"] <= 1.0


def test_shrinkage_pulls_a_three_game_wonder_toward_his_group_and_leaves_a_stable_player_alone():
    import random

    rng = random.Random(1)
    fas = [rec(f"f{i}", "DL", [max(0.0, rng.gauss(4, 3)) for _ in range(6)]) for i in range(40)]
    wonder = rec("wonder", "DL", [30.0, 28.0, 31.0])
    steady = rec("steady", "DL", [8.0, 8.1, 7.9, 8.0, 8.0, 8.1])
    records = book(*fas, wonder, steady)
    eb = rs.fit_eb(records, set(), WEEKS, min_games=3)
    raw_wonder = rs.ppg_of(records["wonder"], WEEKS)
    assert eb.mean["wonder"] < raw_wonder - 1.0  # regressed
    assert abs(eb.mean["steady"] - rs.ppg_of(records["steady"], WEEKS)) < abs(
        eb.mean["wonder"] - raw_wonder
    )


def test_public_artifact_guard_rejects_identifiers_and_allows_player_names():
    rs.assert_public_artifact({"setBy": ["Christian Izien"], "n": 3})
    with pytest.raises(ValueError):
        rs.assert_public_artifact({"teams": [{"roster_id": 4}]})
    with pytest.raises(ValueError):
        rs.assert_public_artifact(
            {"note": "league 1234567890123456789"}, forbidden_values=["1234567890123456789"]
        )


# ── the committed evidence ───────────────────────────────────────────────────


@pytest.fixture(scope="module")
def evidence():
    assert EVIDENCE.exists(), "regenerate with scripts/idp_accuracy/replacement_report.py"
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_evidence_is_aggregate_only(evidence):
    text = EVIDENCE.read_text(encoding="utf-8")
    assert not re.search(r"\b1\d{18}\b", text), "a Sleeper league/user/roster id leaked"
    rs.assert_public_artifact(evidence)
    assert evidence["status"] == "SHADOW_RESEARCH"
    assert evidence["pins"]["configParamSetId"] == CFG["paramSetId"]


def test_evidence_intervals_contain_their_points_and_undefined_levels_say_why(evidence):
    cells = 0
    for p, table in evidence["levels"]["raw"]["byPosition"].items():
        for label, row in table["levels"].items():
            for unit, c in row.items():
                assert c["point"] != 0, (p, label, unit)  # a level is never a silent zero
                if c["point"] is None:
                    assert c.get("reason"), (p, label, unit)
                ci = c.get("ci95Conditional")
                if ci:
                    cells += 1
                    assert ci[0] - 1e-6 <= c["point"] <= ci[1] + 1e-6, (p, label, unit)
    assert cells >= 20


def test_evidence_reproduces_investigation_b_and_li5_exactly(evidence):
    rep = evidence["reproductionOfInvestigationB"]
    s = rep["shadowVsBOnPinnedInputs"]
    assert s["compared"] == 63 and s["equal"] == 63 and s["mismatches"] == []
    assert all(v["equal"] for v in rep["li5ParityOnTheSameRosters"].values())


def test_evidence_engine_reproduces_sleepers_best_ball_totals(evidence):
    bb = evidence["integrity"]["bestBallReproduction"]
    assert bb["teamWeeks"] == 72 and bb["withinRounding0.02"] == 72
    sc = evidence["integrity"]["scorerVsSleeperPlayerPoints"]
    assert sc["playerWeeksCompared"] == sc["exactWithin0.01"]


def test_evidence_every_cross_position_claim_keeps_kickers_separate_and_unpriced(evidence):
    k = evidence["levels"]["raw"]["byPosition"]["K"]
    assert all(
        row["value"]["point"] is None for row in k["levels"].values()
    )  # the board prices no kicker
    assert "K" not in evidence["headline"]


def test_evidence_consumers_were_only_read_never_flagged(evidence):
    ci = evidence["consumerImpact"]
    assert "nothing written back" in ci["scope"] and "no flag changed" in ci["scope"]
    assert ci["scarcityMultiplier"].startswith("inert")


# ── the pinned real rosters (skipped when the gitignored cache is absent) ────

needs_cache = pytest.mark.skipif(
    not CACHE.exists() or not any(CACHE.glob("*.json")),
    reason="pinned Sleeper cache (data/idp_accuracy/cache) not present",
)


@needs_cache
def test_real_rosters_engine_reproduces_sleepers_best_ball_and_scorer():
    import scripts.idp_accuracy.replacement_report as rr
    from src.api import league_registry
    from src.ros.lineup import resolve_starter_slots

    sl = rr.load_sleeper(rr.Fetcher(offline=True))
    pts, check = rr.score_weeks(sl)
    assert check["playerWeeksCompared"] == check["exactWithin0.01"] > 3000
    records = rr.build_records(sl, pts, {}, rr.infer_team_weeks(sl, pts))
    slots, _ = resolve_starter_slots(
        roster_positions=sl["league"].get("roster_positions"),
        roster_settings=league_registry.get_league_roster_settings(rr.LEAGUE_KEY),
    )
    bb = rr.best_ball_reproduction(sl, records, PORT, slots)
    assert bb["teamWeeks"] == 72 and bb["withinRounding0.02"] == 72


@needs_cache
def test_real_rosters_aggregate_invariants():
    import scripts.idp_accuracy.replacement_report as rr
    from src.api import league_registry
    from src.ros.lineup import resolve_starter_slots

    sl = rr.load_sleeper(rr.Fetcher(offline=True))
    pts, _ = rr.score_weeks(sl)
    records = rr.build_records(sl, pts, {}, rr.infer_team_weeks(sl, pts))
    labels = rr.anonymous_team_labels(sl["rosters"])
    teams = {labels[r["roster_id"]]: [str(p) for p in r["players"]] for r in sl["rosters"]}
    slots, _ = resolve_starter_slots(
        roster_positions=sl["league"].get("roster_positions"),
        roster_settings=league_registry.get_league_roster_settings(rr.LEAGUE_KEY),
    )
    assert len(teams) == 12 and all(len(r) == 58 for r in teams.values())
    flat_ = rs.compute_level_set(records, teams, PORT, slots, weeks=WEEKS, cfg=CFG)
    th = rs.starter_thresholds(
        teams, records, PORT, slots, value_of=lambda r: rs.ppg_of(r, WEEKS, min_games=3)
    )
    # nine IDP starters per team, three at each position, no IDP flex
    for p in ("DL", "LB", "DB"):
        assert th.starters_per_team(p) == 3.0
    for p in rs.POSITIONS:
        m = flat_[p]
        if m["d2_bestPpg"] is not None and m["d1_medianMarginalPpg"] is not None:
            assert (
                m["d2_bestPpg"] < m["starterMedianPpg"] * 1.5
            )  # a wire player is not another league's star
        assert m["qualifiedN"] <= m["viableN"] <= m["candidatesN"]
    assert statistics.fmean([flat_[p]["viableN"] for p in ("DL", "LB", "DB")]) > 50
