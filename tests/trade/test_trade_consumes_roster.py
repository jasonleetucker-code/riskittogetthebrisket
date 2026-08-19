"""Trade CONSUMES canonical roster intelligence — it does not reproduce it.

What this file is for
=====================
Lane 1 (``src/roster_intel/``, ``src/ros/lineup.py``) owns the exact lineup,
the meaningful core, reserve demand, Team Strength / Weakness, the
before → apply → re-solve → after primitive (``simulate_roster_change``) and
the droppability adapter (``pool_cut_ladder``).  Lane 2 owns capacity
consequences, package construction, Value Adjustment, verdicts and
forced-drop accounting.

**The failure mode this file exists to prevent is not disagreement — it is
AGREEMENT.**  Two implementations that return the same number today, drift
apart tomorrow, and are indistinguishable from one owner until they do.  So
nothing here asserts "Trade's answer equals Roster's answer": that assertion
passes for a second implementation.  Every test instead either

* **perturbs the canonical owner** and requires Trade's answer to MOVE — a
  private copy is invisible to the perturbation and the test goes red; or
* **reads the import graph** and requires the edge to exist while the second
  implementation does not.

Synthetic contracts throughout.  Nothing here is a function of which sources
answered the last scrape, so it belongs in the hard gate rather than behind
``livedata``.

Known RED, deliberately not deleted
===================================
``test_the_cut_ladder_honours_configured_flex_eligibility`` FAILS against
Roster as it stands.  ``roster_intel.droppability.pool_cut_ladder`` accepts
``slot_eligibility``, documents that it applies it, and then executes
``del slot_eligibility``; ``draft.displacement.build_cut_ladder`` has no such
parameter at all, though ``solve_optimal_assignment`` has supported one since
C2-U1.  That is #922's own F1 finding left unclosed at exactly the entry point
#914 §14 directs this lane to consume.  Reported to Roster as **R1**; not
compensated for here, because a Trade-side workaround would make the second
owner this file exists to forbid.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.draft.displacement import CutCandidate, CutLadder
from src.ros.lineup import RosterPlayer, configured_slot_eligibility
from src.roster_intel import build_meaningful_core, pool_cut_ladder, simulate_roster_change
from src.trade import roster_capacity as rc

REPO = Path(__file__).resolve().parents[2]

# ── fixtures ────────────────────────────────────────────────────────────────
# Shapes deliberately match tests/trade/test_roster_capacity.py so the two
# files cannot drift into describing different leagues.

MAIN_SETTINGS = {
    "teamCount": 12,
    "rosterSize": 58,
    "taxiSize": 0,
    "starters": {
        "QB": 1, "RB": 2, "WR": 3, "TE": 2, "FLEX": 2,
        "SFLEX": 1, "K": 1, "DL": 3, "LB": 3, "DB": 3,
    },
}
#: 5 taxi slots and no taxi membership in the source — the bracketed case.
TAXI_SETTINGS = {
    "teamCount": 10,
    "rosterSize": 24,
    "taxiSize": 5,
    "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 2, "SFLEX": 1},
}
#: No ``rosterSize`` — the cap is UNKNOWN, and unknown is never unlimited.
NO_LIMIT_SETTINGS = {
    "teamCount": 12,
    "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1},
}

_POSITION_CYCLE = ("RB", "WR", "TE", "QB", "LB", "DB", "DL", "WR", "RB", "K")


def _row(name, value, position="RB", player_id=None):
    row = {
        "playerId": player_id or name.lower().replace(" ", "_"),
        "displayName": name,
        "canonicalName": name,
        "position": position,
        "fantasyPositions": [position],
    }
    if value is not None:
        row["rankDerivedValue"] = value
    return row


def _roster(n, *, base=1000.0):
    return [
        (f"Player {i:02d}", base + (n - i) * 10.0, _POSITION_CYCLE[i % len(_POSITION_CYCLE)])
        for i in range(n)
    ]


def _free_agents(count=12, *, base=300.0):
    return [
        _row(f"FA {i:02d}", base + i, _POSITION_CYCLE[i % len(_POSITION_CYCLE)])
        for i in range(count)
    ]


def _contract(roster, extra_rows=(), opponent=()):
    rows = [_row(n, v, p) for n, v, p in roster]
    rows.extend(extra_rows)
    team = {
        "name": "Test Team",
        "ownerId": "owner-1",
        "roster_id": 1,
        "players": [n for n, _v, _p in roster],
        "playerIds": [n.lower().replace(" ", "_") for n, _v, _p in roster],
        "picks": [],
    }
    teams = [team]
    if opponent:
        teams.append({
            "name": "Opponent", "ownerId": "owner-2", "roster_id": 2,
            "players": list(opponent),
            "playerIds": [n.lower().replace(" ", "_") for n in opponent],
            "picks": [],
        })
    return {"playersArray": rows, "sleeper": {"teams": teams}}, team


def _ctx(roster, settings=MAIN_SETTINGS, extra_rows=None, opponent=()):
    contract, team = _contract(roster, extra_rows or _free_agents(), opponent)
    return rc.build_capacity_context(contract, None, team, roster_settings=settings)


def _players(specs):
    """``RosterPlayer`` pool.  ``None`` value stays ``None`` — never 0.0."""
    return [
        RosterPlayer(
            player_id=name.lower().replace(" ", "_"),
            canonical_name=name,
            position=pos,
            ros_value=value,
            fantasy_positions=(pos,),
        )
        for name, value, pos in specs
    ]


# ── §1  the import edges exist, and the second implementations do not ───────


def _module_ast(rel):
    return ast.parse((REPO / rel).read_text(encoding="utf-8"), filename=rel)


def _imported_names(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                out.add(alias.asname or alias.name)
    return out


def _called_names(tree):
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


def test_roster_capacity_imports_the_canonical_cut_ladder():
    """W1: one route to the ladder, and it is the owner's adapter."""
    names = _imported_names(_module_ast("src/trade/roster_capacity.py"))
    assert "pool_cut_ladder" in names, (
        "roster_capacity must reach the cut ladder through "
        "roster_intel.droppability.pool_cut_ladder — the entry point #914 §14 "
        "names for C3-CAP-01 — not by calling draft.displacement directly."
    )


def test_roster_capacity_calls_no_second_cut_ladder():
    """Consuming the adapter AND the owner would be two routes, not one."""
    called = _called_names(_module_ast("src/trade/roster_capacity.py"))
    assert "build_cut_ladder" not in called, (
        "build_cut_ladder is still called directly; the adapter exists so "
        "there is exactly one way in."
    )


def test_team_impact_imports_the_canonical_simulation():
    """W2/W3: the before→after primitive is C2-SIM-01's, not this lane's."""
    names = _imported_names(_module_ast("src/trade/team_impact.py"))
    assert "simulate_roster_change" in names, (
        "lineup_displacement must REFINE simulate_roster_change (adding the "
        "arrived/departed split the owner cannot express — R2), never re-run "
        "its own before/after solve."
    )


def test_no_trade_module_keeps_a_private_slot_eligibility_table():
    """D4: slot rules have one owner (C2-U1)."""
    offenders = []
    for path in sorted((REPO / "src" / "trade").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src, filename=path.name)):
            if not isinstance(node, ast.Set):
                continue
            members = {e.value for e in node.elts if isinstance(e, ast.Constant)}
            if {"DL", "LB", "DB"} <= members:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "private IDP position vocabularies still present at "
        f"{offenders}; lineup_position / slot_eligible_positions / "
        "name_clean.normalize_position_family own this."
    )


# ── §2  the owner is on the LIVE path — perturbation, not comparison ────────


_SENTINEL_RUNG = CutCandidate(
    player_id="sentinel",
    name="Sentinel Cut",
    position="WR",
    effective_cut_cost=1.0,
    base_value=1.0,
    value_basis="board",
    waiver_value=0.0,
    scarcity_multiplier=1.0,
    rung=1,
)


def test_forced_drops_come_from_the_canonical_ladder(monkeypatch):
    """Perturb the owner; the forced drop must move with it.

    A private ladder in this lane would never surface ``Sentinel Cut``, so a
    second implementation fails here whatever it computes.
    """
    calls = []

    def fake_pool_cut_ladder(pool, slots, waiver_values, **kwargs):
        calls.append((list(pool), list(slots), dict(waiver_values), kwargs))
        return CutLadder(rungs=[_SENTINEL_RUNG])

    monkeypatch.setattr(rc, "pool_cut_ladder", fake_pool_cut_ladder, raising=True)

    ctx = _ctx(_roster(58))
    cap = rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])

    assert calls, "the canonical ladder was never called"
    assert [d.name for d in cap.forced_drops] == ["Sentinel Cut"]


def test_the_ladder_is_handed_the_leagues_real_slots(monkeypatch):
    """Consumption is not enough — the owner must get the right question."""
    seen = {}

    def spy(pool, slots, waiver_values, **kwargs):
        seen["slots"] = list(slots)
        return CutLadder(rungs=[_SENTINEL_RUNG])

    monkeypatch.setattr(rc, "pool_cut_ladder", spy, raising=True)
    ctx = _ctx(_roster(58))
    rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])

    assert seen["slots"] == list(ctx.starter_slots)
    assert seen["slots"], "an unguarded ladder can drop a player the lineup needs"


# ── §3  the eleven named behaviours ─────────────────────────────────────────


def test_1_the_lineup_guard_is_the_exact_solver(monkeypatch):
    """Behaviour 1 — exact lineup.

    Not "the answer matches a greedy" (it must not) but "the exact owner is
    what decided it".  C2-U1 measured the two production greedies at 0/10 and
    5/10 against Sleeper's own awarded lineups; the exact solver is 10/10.
    """
    import src.draft.displacement as disp

    calls = []
    real = disp.solve_optimal_assignment

    def spy(pool, slots, **kwargs):
        calls.append(len(slots))
        return real(pool, slots, **kwargs)

    monkeypatch.setattr(disp, "solve_optimal_assignment", spy, raising=True)

    ladder = pool_cut_ladder(
        _players([(f"P{i}", 1000.0 - i, _POSITION_CYCLE[i % 10]) for i in range(20)]),
        ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"],
        {"RB": 300.0, "WR": 300.0, "TE": 300.0, "QB": 300.0},
    )
    assert calls, "the cut ladder was not lineup-guarded by the exact solver"
    assert ladder.rungs


def test_2_the_simulation_honours_configured_flex_eligibility():
    """Behaviour 2, simulation half — the league's OWN flex rules reach the solve."""
    settings = {"flexEligible": ["WR"], "starters": {"WR": 1, "FLEX": 1}}
    eligibility = configured_slot_eligibility(settings)
    assert eligibility == {"FLEX": ("WR",)}

    pool = _players([("Wide One", 900.0, "WR"), ("Wide Two", 800.0, "WR"), ("Runner", 950.0, "RB")])
    slots = ["WR", "FLEX"]

    wide_open = simulate_roster_change(pool, slots)
    narrowed = simulate_roster_change(pool, slots, slot_eligibility=eligibility)

    seated_open = {m.canonical_name for m in wide_open.core_after.members if m.role == "starter"}
    seated_narrow = {m.canonical_name for m in narrowed.core_after.members if m.role == "starter"}
    assert "Runner" in seated_open, "default FLEX accepts an RB"
    assert "Runner" not in seated_narrow, (
        "a FLEX the league restricted to WR seated an RB — configured "
        "eligibility did not reach the solve"
    )


def test_2b_the_cut_ladder_honours_configured_flex_eligibility():
    """Behaviour 2, ladder half — KNOWN RED.  Roster-owned; see R1 in the docstring.

    ``pool_cut_ladder`` accepts ``slot_eligibility`` and executes
    ``del slot_eligibility``; ``build_cut_ladder`` cannot receive one.  So the
    ladder's lineup guard solves under DEFAULT eligibility while every other
    surface #922 hardened solves under the league's, and the only legal filler
    of a narrowed flex can be reported droppable.

    Left failing rather than xfailed: an incompatibility that belongs to
    another lane is reported, not absorbed.
    """
    settings = {"flexEligible": ["WR"], "starters": {"WR": 1, "FLEX": 1}}
    eligibility = configured_slot_eligibility(settings)
    pool = _players([("Wide One", 900.0, "WR"), ("Wide Two", 800.0, "WR"), ("Runner", 950.0, "RB")])
    slots = ["WR", "FLEX"]
    waiver = {"WR": 100.0, "RB": 100.0}

    wide_open = pool_cut_ladder(pool, slots, waiver)
    narrowed = pool_cut_ladder(pool, slots, waiver, slot_eligibility=eligibility)

    assert [r.name for r in wide_open.rungs] != [r.name for r in narrowed.rungs], (
        "R1: pool_cut_ladder ignored slot_eligibility. With FLEX narrowed to "
        "WR the roster fills both slots only with its two receivers, so "
        "'Wide Two' stops being droppable — the ladder cannot see that."
    )


def test_3_the_final_legal_roster_is_solved_by_the_canonical_owner(monkeypatch):
    """Behaviour 3 — C3-CAP-01's last two steps go through simulate_roster_change.

    The manifest sequence is ``before -> apply -> capacity/overage -> required
    legal cleanup -> apply optimal cleanup -> rerun roster intelligence ->
    evaluate``.  Perturbing the owner must move the answer; a private re-solve
    in this lane would be invisible to the patch.
    """
    seen = {}
    real = rc.simulate_roster_change

    def spy(pool, slots, **kwargs):
        seen["outgoing"] = list(kwargs.get("outgoing_ids") or [])
        seen["slots"] = list(slots)
        result = real(pool, slots, **kwargs)
        return dataclasses.replace(result, unavailable_reason="SENTINEL")

    monkeypatch.setattr(rc, "simulate_roster_change", spy, raising=True)

    roster = _roster(58)
    ctx = _ctx(roster, extra_rows=[*_free_agents(), _row("Arrival", 4000.0, "WR")])
    cap = rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])
    final = rc.simulate_final_legal_roster(ctx, cap, incoming_players=["Arrival"])

    assert final["unavailableReason"] == "SENTINEL", "the owner was not on the path"
    assert seen["slots"] == list(ctx.starter_slots)


def test_3b_the_cleanup_the_roster_is_resolved_against_is_the_capacity_answer():
    """The forced drops ARE the cleanup — not a second selection."""
    roster = _roster(58)
    ctx = _ctx(roster, extra_rows=[*_free_agents(), _row("Arrival", 4000.0, "WR")])
    cap = rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])
    final = rc.simulate_final_legal_roster(ctx, cap, incoming_players=["Arrival"])

    assert [d["name"] for d in final["cleanupApplied"]] == [d.name for d in cap.forced_drops]
    assert final["isVerdict"] is False, "this block reports a roster; it grades nothing"
    assert final["cleanupIsUpperBound"] == (cap.certainty != "exact")


def test_5_a_bench_promotion_is_reported_even_when_value_barely_moves():
    """Behaviour 5 — reserve / core consequences are not a value subtraction.

    C2-SIM-01's whole premise: acquiring a player can move a DIFFERENT player's
    seat, by a transaction that never mentioned him.
    """
    pool = _players([
        ("Star RB", 900.0, "RB"), ("Solid RB", 700.0, "RB"),
        ("Star WR", 950.0, "WR"), ("Bench RB", 400.0, "RB"),
    ])
    slots = ["RB", "WR", "FLEX"]
    incoming = _players([("New RB", 800.0, "RB")])

    sim = simulate_roster_change(pool, slots, incoming=incoming)
    assert sim.movements, "a seat changed hands and nothing reported it"
    kinds = {m.kind for m in sim.movements}
    assert kinds & {"promoted", "displaced", "moved"}


def test_6_an_unpriced_arrival_is_reported_never_seated_and_never_zero():
    """Behaviour 6 + 11 — missing is UNKNOWN, and 0.0 is a real value."""
    pool = _players([("Star WR", 950.0, "WR"), ("Solid WR", 700.0, "WR")])
    slots = ["WR", "FLEX"]

    unknown = simulate_roster_change(pool, slots, incoming=_players([("Mystery", None, "WR")]))
    real_zero = simulate_roster_change(pool, slots, incoming=_players([("Zero Man", 0.0, "WR")]))

    assert "mystery" in unknown.unpriced_incoming
    assert not real_zero.unpriced_incoming, "0.0 is assignable and contributes nothing"

    seated_unknown = {m.player_id for m in unknown.core_after.members}
    assert "mystery" not in seated_unknown, "an unpriced player was seated"
    seated_zero = {m.player_id for m in real_zero.core_after.members}
    assert "zero_man" in seated_zero, "a genuinely worthless player is still assignable"


def test_7_an_unknown_roster_limit_is_unknown_never_unlimited():
    """Behaviour 7 — coercing an unknown cap makes every trade look free."""
    ctx = _ctx(_roster(30), settings=NO_LIMIT_SETTINGS)
    cap = rc.assess_roster_capacity(ctx, incoming_players=["A", "B", "C"], outgoing_players=[])
    d = cap.to_dict()

    assert d["rosterLimit"] is None
    assert d["overLimitAfter"] is None
    assert d["requiresDrops"] is None
    assert d["forcedDrops"] == []
    assert any("UNKNOWN" in note for note in d["notes"])


def test_8_forced_drops_are_ladder_rungs_not_the_lowest_raw_value():
    """Behaviour 8 — the spec forbids ``package delta − lowest raw value`` by name.

    Built over the SAME post-trade pool the assessment builds (roster minus the
    outgoing, plus the arrival), because the arrival occupies a spot and is a
    legitimate cut candidate — "this trade forces you to release the player you
    just acquired" is a real answer, not a fixture bug.
    """
    roster = _roster(58)
    arrival_row = _row("Arrival", 4000.0, "WR")
    ctx = _ctx(roster, extra_rows=[*_free_agents(), arrival_row])
    cap = rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])
    assert cap.forced_drops, "a full roster taking a player must release someone"

    surviving = [
        RosterPlayer(
            player_id=a.player_id, canonical_name=a.name, position=a.position,
            ros_value=a.board_value, injured=a.injured,
            fantasy_positions=a.fantasy_positions,
        )
        for a in ctx.assets_by_key.values()
    ] + _players([("Arrival", 4000.0, "WR")])

    ladder = pool_cut_ladder(
        surviving, list(ctx.starter_slots), dict(ctx.waiver_values), scarcity=ctx.scarcity
    )
    assert ladder.rungs
    assert cap.forced_drops[0].name == ladder.rungs[0].name, (
        "the forced drop is not the canonical ladder's rung 1"
    )

    # And it is not merely the cheapest body: the ladder's lineup guard keeps
    # players the surviving roster needs, which a raw-value rule cannot see.
    ladder_names = {r.name for r in ladder.rungs}
    undroppable_names = {u.get("name") for u in ladder.undroppable}
    assert not (ladder_names & undroppable_names)


def test_9_taxi_occupancy_is_bracketed_not_assumed():
    """Behaviour 9 — guessing 0 invents drops; guessing full relief hides them."""
    ctx = _ctx(_roster(24), settings=TAXI_SETTINGS)
    cap = rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])
    d = cap.to_dict()

    assert d["certainty"] == "partial"
    assert d["taxiOccupiedMin"] == 0
    assert d["taxiOccupiedMax"] == TAXI_SETTINGS["taxiSize"]
    assert d["requiresDrops"] is None, "a range straddling zero cannot answer 'whether'"
    assert d["forcedDropsAreUpperBound"] is True


def test_10_an_outgoing_player_the_roster_does_not_hold_frees_no_spot():
    """Behaviour 10 — matched by MULTIPLICITY, and the discrepancy is published."""
    roster = _roster(58)
    ctx = _ctx(roster)
    held = roster[0][0]

    cap = rc.assess_roster_capacity(
        ctx, incoming_players=["Arrival"], outgoing_players=[held, "Never Rostered"]
    )
    d = cap.to_dict()
    assert d["outgoingNotOnRoster"] == 1

    # The same name twice frees exactly one spot, not two.
    twice = rc.assess_roster_capacity(
        ctx, incoming_players=["Arrival"], outgoing_players=[held, held]
    )
    assert twice.to_dict()["outgoingNotOnRoster"] == 1
    assert twice.size_after == cap.size_after


def test_10b_the_owner_reports_an_outgoing_id_it_does_not_hold():
    """Behaviour 10, owner half — 'I removed a player you do not have' is a caller bug."""
    pool = _players([("Star WR", 950.0, "WR")])
    sim = simulate_roster_change(pool, ["WR"], outgoing_ids=["ghost"])
    assert sim.outgoing_not_found == frozenset({"ghost"})


def test_11_an_unpriced_forced_drop_reports_no_value_rather_than_zero():
    """Behaviour 11 — an unjoinable name is a join miss, never a free cut."""
    roster = _roster(57)
    contract, team = _contract(roster, _free_agents())
    team["players"].append("Unjoinable Ghost")  # on the roster, absent from the board
    ctx = rc.build_capacity_context(contract, None, team, roster_settings=MAIN_SETTINGS)

    cap = rc.assess_roster_capacity(ctx, incoming_players=["Arrival"], outgoing_players=[])
    d = cap.to_dict()
    assert cap.size_before == 58, "an unresolved player still occupies a spot"
    for drop in d["forcedDrops"]:
        if drop["name"] == "Unjoinable Ghost":
            assert drop["value"] is None
            assert d["unpricedForcedDrops"] >= 1
            assert drop["valueBasis"] == "assumedWaiver"
            break


def test_11b_a_posture_over_an_entirely_unpriced_roster_is_not_balanced():
    """Behaviour 11, D1 — unknown must not be published as a real classification.

    ``_classify_window``'s five ``int(a.get("value") or 0)`` coercions are
    arithmetically equivalent to EXCLUDING unpriced assets (numerator and
    denominator drop the same players), so the ratio itself is sound.  What is
    not sound is ``or 1`` on the denominator: a roster whose assets are all
    unpriced returns ``"balanced"`` — the same answer as an empty roster —
    which is an unknown published as a verdict.
    """
    from src.trade.team_impact import _classify_window

    all_unpriced = [{"value": None} for _ in range(12)]
    assert _classify_window(all_unpriced, {}) != "balanced", (
        "a roster with nothing priced was classified 'balanced'; unknown is "
        "not a posture"
    )
