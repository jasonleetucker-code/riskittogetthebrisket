"""Value-weighted NFL-franchise exposure (C2-EXP-01, CE-06).

The manifest's evidence for this unit is a **non-influence test**, and
that is the spine of this file: exposure is descriptive, and the way it
is kept descriptive is structural — no flag in the payload, and no edge
in the import graph along which it could reach a grade.

The rest is the two things a share can be wrong about: its denominator,
and what it silently counts as a team.
"""

from __future__ import annotations

import ast
import pathlib

from src.roster_intel.core import build_meaningful_core
from src.roster_intel.exposure import (
    NON_FRANCHISE_TOKENS,
    build_nfl_exposure,
    exposure_from_core,
    simulation_exposure_change,
)
from src.roster_intel.simulation import simulate_roster_change
from src.ros.lineup import RosterPlayer

REPO = pathlib.Path(__file__).resolve().parents[2]

_SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"]


def P(pid, pos, val):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val)


def _roster():
    return [
        P("QB1", "QB", 900),
        P("RB1", "RB", 800),
        P("RB2", "RB", 700),
        P("RB3", "RB", 400),
        P("WR1", "WR", 850),
        P("WR2", "WR", 750),
        P("WR3", "WR", 650),
        P("TE1", "TE", 600),
    ]


_TEAMS = {
    "QB1": "MIN",
    "RB1": "MIN",
    "RB2": "PHI",
    "RB3": "PHI",
    "WR1": "MIN",
    "WR2": "KC",
    "WR3": "KC",
    "TE1": "FA",
}


def _core(pool=None):
    return build_meaningful_core(pool or _roster(), _SLOTS)


# ══ Non-influence — the manifest's acceptance evidence ═════════════


def test_the_payload_carries_no_flag_verdict_or_penalty():
    """Descriptive only.  ``MIN 18.2% → 22.4%`` is a fact; whether it is
    good is a trade judgement built on top, and a roster fact that
    quietly becomes an opinion is not auditable."""
    payload = exposure_from_core(_core(), teams=_TEAMS).to_dict()
    blob = repr(payload).lower()
    for banned in (
        "flag",
        "verdict",
        "grade",
        "penalty",
        "recommend",
        "warning",
        "concentrationrisk",
        "overexposed",
    ):
        assert banned not in blob, banned


def test_nothing_in_the_trade_or_roster_chain_imports_exposure():
    """The structural half.  A number cannot influence a grade it is not
    reachable from, and this is cheaper to keep true than to keep
    checking.  The dependency arrow runs exposure → simulation, never
    back."""
    importers = set()
    for path in (REPO / "src").rglob("*.py"):
        if path.name == "exposure.py" or path.parent.name == "roster_intel":
            if path.name != "__init__.py":
                continue
        text = path.read_text(encoding="utf-8")
        if "roster_intel.exposure" in text or "roster_intel import exposure" in text:
            importers.add(path.relative_to(REPO).as_posix())
    assert importers <= {
        "src/roster_intel/__init__.py",
        "src/api/roster_intelligence.py",
        # Team Assignment (NFL Team Affinity, 2026-09-01) reads
        # ``nfl_team_by_player``/``NON_FRANCHISE_TOKENS`` — the same pure
        # canonical-name -> NFL-team join ``roster_intelligence.py``
        # already uses — for player-to-franchise attribution.  It is not
        # part of the trade/roster GRADING chain this test guards: it
        # computes no flag, verdict, grade, penalty or recommendation,
        # same as ``exposure.py`` itself.
        "src/api/team_assignment.py",
    }, importers


def test_exposure_does_not_import_the_trade_lane_or_annotate_a_simulation():
    """``simulation_exposure_change`` takes ``Any`` on purpose: importing
    ``RosterSimulation`` for an annotation would create the very edge the
    separation exists to avoid."""
    tree = ast.parse((REPO / "src/roster_intel/exposure.py").read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m.startswith("src.trade") for m in modules), modules
    assert "src.roster_intel.simulation" not in modules


def test_computing_exposure_changes_nothing_about_the_simulation():
    """Behavioural.  Exposure reads the simulation's cores; the
    simulation is byte-identical whether or not anybody looks."""
    sim = simulate_roster_change(_roster(), _SLOTS, incoming=[P("NEW", "RB", 600)])
    before = sim.to_dict()
    simulation_exposure_change(sim, teams={**_TEAMS, "NEW": "MIN"})
    assert sim.to_dict() == before


# ══ FA is not a franchise ══════════════════════════════════════════


def test_free_agents_get_their_own_bucket_and_never_a_franchise_share():
    """25 of 660 rostered players on the live board carry ``FA`` — tying
    the largest franchise by headcount, though only 6 are priced.
    Counting it as a 33rd franchise would report the ABSENCE of a team as
    an exposure to one."""
    exposure = exposure_from_core(_core(), teams=_TEAMS)
    fa = next(b for b in exposure.buckets if b.team == "FA")
    assert fa.is_franchise is False
    assert fa.share > 0  # he is still real value on the roster
    assert "FA" not in {b.team for b in exposure.franchises}
    # …and the concentration statistics see franchises only.
    assert exposure.top_franchise_share == max(b.share for b in exposure.franchises)


def test_the_non_franchise_token_set_is_matched_case_and_whitespace_insensitively():
    exposure = build_nfl_exposure(
        ["a", "b"],
        teams={"a": " fa ", "b": "min"},
        values={"a": 100.0, "b": 100.0},
    )
    assert {(b.team, b.is_franchise) for b in exposure.buckets} == {
        ("FA", False),
        ("MIN", True),
    }
    assert "FA" in NON_FRANCHISE_TOKENS


# ══ Missing is never zero ══════════════════════════════════════════


def test_an_unpriced_player_is_reported_and_never_weighted():
    exposure = build_nfl_exposure(
        ["a", "b"],
        teams={"a": "MIN", "b": "MIN"},
        values={"a": 100.0, "b": None},
    )
    assert exposure.unpriced_ids == frozenset({"b"})
    assert exposure.priced_value == 100.0
    assert exposure.buckets[0].player_ids == ("a",)


def test_a_priced_player_with_no_known_team_is_reported_not_bucketed():
    """Bucketing him as a franchise called UNKNOWN would give that
    franchise a share of your roster."""
    exposure = build_nfl_exposure(
        ["a", "b"],
        teams={"a": "MIN"},
        values={"a": 100.0, "b": 400.0},
    )
    assert exposure.unknown_team_ids == frozenset({"b"})
    assert {b.team for b in exposure.buckets} == {"MIN"}
    assert exposure.buckets[0].share == 100.0  # of the PRICED, placeable value


def test_an_empty_population_has_an_unmeasured_top_share_not_a_zero_one():
    exposure = build_nfl_exposure([], teams={}, values={})
    assert exposure.top_franchise_share is None
    assert exposure.franchise_hhi is None
    assert exposure.priced_value == 0.0


def test_a_franchise_you_own_nobody_from_is_genuinely_zero_percent():
    """The one case where 0.0 is a real answer rather than a missing
    one — and the missing cases have their own sets, so the two cannot
    be confused."""
    exposure = exposure_from_core(_core(), teams=_TEAMS)
    assert exposure.share_of("BUF") == 0.0
    assert exposure.share_of("min") > 0.0  # case-insensitive


# ══ Two scopes, named ══════════════════════════════════════════════


def test_core_and_full_roster_are_different_answers_and_say_which_they_are():
    core = _core()
    core_exposure = exposure_from_core(core, teams=_TEAMS)
    full = build_nfl_exposure(
        [p.player_id for p in _roster()],
        teams=_TEAMS,
        values={p.player_id: p.ros_value for p in _roster()},
        scope="full_roster",
    )
    assert core_exposure.scope == "meaningful_core"
    assert full.scope == "full_roster"
    # Same roster here (the core takes everyone), so the shares agree —
    # what matters is that each names its own denominator.
    assert core_exposure.priced_value == full.priced_value


def test_the_core_scope_uses_the_cores_own_values():
    """So exposure and Team Strength cannot disagree about what a member
    is worth."""
    core = _core()
    exposure = exposure_from_core(core, teams=_TEAMS)
    assert exposure.priced_value == sum(m.value for m in core.members)


# ══ Before → after ═════════════════════════════════════════════════


def test_an_exited_franchise_is_as_visible_as_an_entered_one():
    """Reporting only the after side would make an exit invisible, which
    is the direction a diversification story is most likely to be told
    badly."""
    sim = simulate_roster_change(_roster(), _SLOTS, outgoing_ids=["WR2", "WR3"])
    out = simulation_exposure_change(sim, teams=_TEAMS)
    kc = next(r for r in out["changes"] if r["team"] == "KC")
    assert kc["shareBefore"] > 0
    assert kc["shareAfter"] == 0.0
    assert kc["delta"] < 0


def test_an_entered_franchise_reports_a_before_of_zero_not_an_absence():
    sim = simulate_roster_change(_roster(), _SLOTS, incoming=[P("NEW", "RB", 950)])
    out = simulation_exposure_change(sim, teams={**_TEAMS, "NEW": "BUF"})
    buf = next(r for r in out["changes"] if r["team"] == "BUF")
    assert buf["shareBefore"] == 0.0
    assert buf["shareAfter"] > 0.0


def test_moved_is_a_strict_subset_of_changes():
    sim = simulate_roster_change(_roster(), _SLOTS, incoming=[P("NEW", "RB", 950)])
    out = simulation_exposure_change(sim, teams={**_TEAMS, "NEW": "BUF"})
    assert len(out["moved"]) <= len(out["changes"])
    assert all(abs(r["delta"]) > 0 for r in out["moved"])


def test_a_no_op_transaction_moves_no_exposure():
    sim = simulate_roster_change(_roster(), _SLOTS)
    out = simulation_exposure_change(sim, teams=_TEAMS)
    assert out["moved"] == []


# ══ Handcuffs are reported, never judged ═══════════════════════════


def test_same_franchise_same_position_pairs_are_reported_without_a_claim():
    """The spec's carve-out is a guard against a flag.  The honest way to
    satisfy it is not a heuristic that guesses intent — it is to report
    the pair and flag nothing.  Measured on the live board this finds
    real handcuffs (Saquon Barkley + Tank Bigsby, both PHI RB)."""
    exposure = exposure_from_core(_core(), teams=_TEAMS)
    pairs = {
        (p["team"], p["position"]): tuple(p["playerIds"])
        for p in exposure.to_dict()["handcuffPairs"]
    }
    assert pairs[("KC", "WR")] == ("WR2", "WR3")
    assert ("PHI", "RB") in pairs
    # Reported, with nothing said about why.
    row = exposure.to_dict()["handcuffPairs"][0]
    assert set(row) == {"team", "position", "playerIds"}


def test_free_agents_never_form_a_handcuff_pair():
    pool = _roster() + [P("TE2", "TE", 500)]
    exposure = exposure_from_core(_core(pool), teams={**_TEAMS, "TE2": "FA"})
    assert all(p["team"] != "FA" for p in exposure.to_dict()["handcuffPairs"])


# ══ Determinism ════════════════════════════════════════════════════


def test_buckets_are_ordered_largest_first_and_deterministic_under_input_order():
    import random

    ids = [p.player_id for p in _roster()]
    values = {p.player_id: p.ros_value for p in _roster()}
    expected = [
        (b.team, round(b.share, 6))
        for b in build_nfl_exposure(ids, teams=_TEAMS, values=values).buckets
    ]
    assert expected == sorted(expected, key=lambda x: (-x[1], x[0]))
    rng = random.Random(20260818)
    for _ in range(15):
        shuffled = list(ids)
        rng.shuffle(shuffled)
        got = [
            (b.team, round(b.share, 6))
            for b in build_nfl_exposure(shuffled, teams=_TEAMS, values=values).buckets
        ]
        assert got == expected


def test_shares_sum_to_one_hundred_over_the_priced_placeable_population():
    exposure = exposure_from_core(_core(), teams=_TEAMS)
    assert abs(sum(b.share for b in exposure.buckets) - 100.0) < 1e-9
