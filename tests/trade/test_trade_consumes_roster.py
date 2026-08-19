"""REHEARSAL PROOF — Trade CONSUMES the Roster owners; it does not recreate them.

This file is the executable half of the final Trade/Roster integration
rehearsal.  It is deliberately **not** skipped and not marked ``livedata``:
every fixture is synthetic, so nothing here is a function of which sources
answered the last scrape.

It proves nine properties, each named in the dispatch that commissioned it.
Eight are stated as ordinary assertions.  The ninth — *the proving test fails
when the Roster integration is deliberately disconnected* — cannot be an
assertion about this tree, because a green test proves nothing about what it
would do if the code were wrong.  It is discharged by
``scripts/rehearsal_prove_trade_consumes_roster.py``, which mutates the
integration seam in place, re-runs the specific test that guards it, and
requires RED.  Each guard below names its mutation in ``MUTATION``.

    P1  the league's CONFIGURED slot_eligibility reaches BOTH of Trade's
        lineup consumers — the forced-drop / cut path and the team-impact
        starter projection — and DECIDES the answer in each
    P2  Trade contains no lineup solver of its own
    P3  Trade contains no Team Strength / Team Weakness of its own
    P4  Trade contains no replacement-level or cut-ladder SELECTION of its own
    P5  one player cannot be simultaneously retained and counted as a forced drop
    P6  an unknown roster limit stays UNKNOWN
    P7  an unpriced forced drop stays null, never zero
    P8  before -> apply transaction -> re-solve -> after is the exact order
    P9  see the mutation script
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.trade.roster_capacity import (
    assess_roster_capacity,
    build_capacity_context,
    simulate_final_legal_roster,
)

REPO = Path(__file__).resolve().parents[2]
TRADE_DIR = REPO / "src" / "trade"


# ── Fixtures ─────────────────────────────────────────────────────────
#
# A six-man roster with a four-slot lineup, which is the smallest shape in
# which FLEX can be load-bearing.  Values descend so the cut ladder has an
# unambiguous cheapest rung, and every arrival sits on a real opposing roster
# so waiver level is a measured number rather than the arrival's own value.

TINY_SETTINGS = {
    "teamCount": 12,
    "rosterSize": 6,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 1, "FLEX": 1},
}

#: TE1 is the CHEAPEST player and the ONLY tight end.  Under the declared
#: default FLEX rule (RB/WR/TE) he is redundant and therefore the cheapest
#: legal release; under a league that narrows FLEX to TE he is the only player
#: who can fill it, and releasing him would leave the lineup a slot short.
TINY_ROSTER = [
    ("QB1", 5000.0, "QB"),
    ("RB1", 4000.0, "RB"),
    ("WR1", 3000.0, "WR"),
    ("RB2", 800.0, "RB"),
    ("WR2", 700.0, "WR"),
    ("TE1", 600.0, "TE"),
]


def _row(name: str, value: float | None, position: str) -> dict:
    row = {
        "playerId": name.lower().replace(" ", "_"),
        "displayName": name,
        "canonicalName": name,
        "position": position,
        "fantasyPositions": [position],
    }
    if value is not None:
        row["rankDerivedValue"] = value
    return row


def _context(
    roster=TINY_ROSTER,
    *,
    settings=TINY_SETTINGS,
    arrivals=(("IN1", 6000.0, "WR"),),
):
    """A capacity context over ``roster``, with ``arrivals`` on an opponent."""
    free_agents = [
        _row(f"FA {i}", 200.0 + i, p) for i, p in enumerate(("QB", "RB", "WR", "TE", "RB", "WR"))
    ]
    rows = (
        [_row(n, v, p) for n, v, p in roster]
        + free_agents
        + [_row(n, v, p) for n, v, p in arrivals]
    )
    team = {
        "name": "Us",
        "ownerId": "owner-1",
        "roster_id": 1,
        "players": [n for n, _v, _p in roster],
        "playerIds": [n.lower().replace(" ", "_") for n, _v, _p in roster],
        "picks": [],
    }
    opponent = {
        "name": "Them",
        "ownerId": "owner-2",
        "roster_id": 2,
        "players": [n for n, _v, _p in arrivals],
        "playerIds": [n.lower().replace(" ", "_") for n, _v, _p in arrivals],
        "picks": [],
    }
    contract = {"playersArray": rows, "sleeper": {"teams": [team, opponent]}}
    return build_capacity_context(contract, None, team, roster_settings=settings)


def _module_sources() -> dict[str, ast.Module]:
    """Every ``src/trade`` module, parsed.  Sorted so failures are stable."""
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(TRADE_DIR.glob("*.py"))
    }


def _defined_names(tree: ast.Module) -> set[str]:
    """Names this module DEFINES — functions, classes, module-level bindings.

    Imports are deliberately excluded: importing ``assign_lineup`` is exactly
    what consuming the owner looks like, and is the opposite of a violation.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _imported_from(tree: ast.Module, module_prefix: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(module_prefix)
        for alias in node.names
    }


# ── P1 — the configured flex rule reaches the cut path AND decides ───


class TestP1ConfiguredSlotEligibilityReachesTheCutPath:
    """MUTATION: drop ``slot_eligibility=`` from the ``pool_cut_ladder`` call."""

    def test_the_context_carries_the_leagues_configured_rule(self):
        context = _context()
        # ``None`` here is honest: the test registry resolves no league, so
        # nothing is configured and the DECLARED defaults apply.  What matters
        # is that the field exists to carry it — the behavioural proof below
        # supplies one explicitly.
        assert hasattr(context, "slot_eligibility")

    def test_a_narrowed_flex_changes_which_player_is_released(self):
        """The proof that the rule DECIDES, not merely that it travels.

        Under the declared default FLEX (RB/WR/TE) the cheapest player, TE1,
        is redundant and is released.  Under a league whose FLEX admits only
        TE he is the only legal filler for it, so the ladder refuses that rung
        and takes the next-cheapest instead.  If the rule did not reach the
        ladder, both would answer TE1.
        """
        context = _context()
        acquiring = {"incoming_players": ["IN1"]}

        default_rule = assess_roster_capacity(
            dataclasses.replace(context, slot_eligibility=None), **acquiring
        )
        te_only_flex = assess_roster_capacity(
            dataclasses.replace(context, slot_eligibility={"FLEX": ("TE",)}), **acquiring
        )

        assert [d.name for d in default_rule.forced_drops] == ["TE1"]
        assert [d.name for d in te_only_flex.forced_drops] == ["WR2"]

    def test_an_empty_rule_is_not_configured_rather_than_nothing_eligible(self):
        """``{}`` must behave as the defaults, not as an unfillable lineup."""
        context = _context()
        empty = assess_roster_capacity(
            dataclasses.replace(context, slot_eligibility={}), incoming_players=["IN1"]
        )
        unset = assess_roster_capacity(
            dataclasses.replace(context, slot_eligibility=None), incoming_players=["IN1"]
        )
        assert [d.name for d in empty.forced_drops] == [d.name for d in unset.forced_drops]


# ── P2/P3/P4 — structural: Trade owns none of these concepts ─────────


#: Everything ``src/ros/lineup.py`` owns.  A ``src/trade`` module may IMPORT
#: any of these; defining one is a second owner.
_LINEUP_OWNER_NAMES = frozenset(
    {
        "assign_lineup",
        "solve_optimal_assignment",
        "resolve_starter_slots",
        "slot_eligible_positions",
        "player_eligible_for_slot",
        "configured_slot_eligibility",
        "lineup_position",
        "normalize_slot",
        "slot_demand",
        "flatten_starter_slots",
        "fillLineup",
        "project_starters_exact",
    }
)

#: Everything the C2 roster chain owns.
_ROSTER_INTEL_OWNER_NAMES = frozenset(
    {
        "build_team_strength",
        "build_team_weakness",
        "build_position_ranks",
        "build_meaningful_core",
        "reserve_demand",
        "rank_team_strengths",
        "simulate_roster_change",
        "TeamStrength",
        "TeamWeakness",
        "PositionStrength",
        "PositionNeed",
        "PositionRanks",
        "MeaningfulCore",
        "CoreMember",
        "RosterSimulation",
        "SlotMovement",
    }
)

#: Everything the cut-ladder / replacement-level owner owns.
_DISPLACEMENT_OWNER_NAMES = frozenset(
    {
        "build_cut_ladder",
        "pool_cut_ladder",
        "effective_cut_cost",
        "waiver_values_by_position",
        "team_droppability",
        "league_droppability",
        "CutLadder",
        "CutRung",
    }
)


@pytest.mark.parametrize(
    "owner, names",
    [
        ("src/ros/lineup.py", _LINEUP_OWNER_NAMES),
        ("src/roster_intel", _ROSTER_INTEL_OWNER_NAMES),
        ("src/draft/displacement.py", _DISPLACEMENT_OWNER_NAMES),
    ],
    ids=["lineup", "roster-intel", "cut-ladder"],
)
def test_no_trade_module_defines_a_name_another_owner_owns(owner, names):
    """P2 / P3 / P4.

    MUTATION: add ``def assign_lineup(...)`` (or ``build_team_strength``, or
    ``build_cut_ladder``) to any ``src/trade`` module.

    The check is on DEFINITION, not mention.  Trade is expected to say these
    names constantly — that is what consuming an owner looks like.  It is
    defining one that makes a second owner.
    """
    offenders = {
        name: sorted(defined & names)
        for name, tree in _module_sources().items()
        if (defined := _defined_names(tree)) & names
    }
    assert offenders == {}, f"{owner} owns these names; src/trade defines them again: {offenders}"


def test_trade_reaches_the_cut_ladder_through_the_adapter_not_the_board():
    """P4, sharpened.

    MUTATION: import ``build_cut_ladder`` in ``roster_capacity.py`` and call it.

    ``build_cut_ladder`` is the Perfect Draft board's entry point and
    ``pool_cut_ladder`` is the adapter #914 §14 names for C3-CAP-01.  Both
    reach one owner, so calling the wrong one is not a *second* ladder — but
    it IS a second route, and #922 threaded the configured flex rule through
    the adapter only.  Trade taking the board's door is how P1 silently
    regresses.
    """
    capacity = _module_sources()["roster_capacity.py"]
    from_displacement = _imported_from(capacity, "src.draft.displacement")
    from_roster_intel = _imported_from(capacity, "src.roster_intel")

    assert "build_cut_ladder" not in from_displacement
    assert "pool_cut_ladder" in from_roster_intel


def test_trade_does_not_recompute_a_lineup_after_the_owner_solved_one():
    """P2, sharpened: no ``src/trade`` module holds a slot -> positions table.

    MUTATION: add ``_FLEX = {"FLEX": ("RB", "WR", "TE")}`` to any trade module.

    Six such private tables existed before C2-U1 and every one of them could
    drift from the league's real rule.  The shape is recognisable: a mapping
    whose keys are slot names and whose values are position collections.
    """
    slot_names = {"FLEX", "SFLEX", "SUPER_FLEX", "IDP_FLEX", "REC_FLEX", "WRRB_FLEX"}
    positions = {"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"}
    offenders: list[str] = []

    for name, tree in _module_sources().items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
            if not keys or not keys <= slot_names:
                continue
            for value in node.values:
                if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
                    continue
                elts = {e.value for e in value.elts if isinstance(e, ast.Constant)}
                if elts and elts <= positions:
                    offenders.append(f"{name}:{node.lineno}")

    assert offenders == [], (
        "src/trade holds a private slot->positions table; the league's rule has "
        f"one owner (src/ros/lineup.configured_slot_eligibility): {offenders}"
    )


# ── P1b — the same rule reaches Trade's OTHER lineup consumer ────────


def test_the_configured_flex_rule_reaches_the_team_impact_starter_projection():
    """P1, second surface.

    MUTATION: drop ``slot_eligibility=`` from ``project_starters``'
    ``assign_lineup`` call.

    ``roster_capacity`` and ``team_impact`` both model this roster's lineup —
    one to decide which release is legal, one to score fit.  They must be
    handed the SAME rule.  Under the declared default FLEX the spare RB takes
    the flex seat; under a league whose FLEX admits only TE, the tight end
    does.  If the rule does not reach here, both answer the same.
    """
    from src.trade.team_impact import project_starters

    base = {
        "teamCount": 12,
        "rosterSize": 6,
        "taxiSize": 0,
        "starters": {"QB": 1, "RB": 1, "WR": 1, "FLEX": 1},
    }
    assets = [
        {"name": n, "displayName": n, "position": p, "basePos": p, "value": v}
        for n, v, p in (
            ("QB1", 5000, "QB"),
            ("RB1", 4000, "RB"),
            ("WR1", 3000, "WR"),
            ("RB2", 800, "RB"),
            ("TE1", 600, "TE"),
        )
    ]

    def _seated(settings):
        return {
            slot: [a["name"] for a in rows]
            for slot, rows in project_starters(assets, settings).items()
            if rows
        }

    default_rule = _seated(base)
    te_only_flex = _seated(dict(base, flexEligible=["TE"]))

    assert default_rule["RB"] == ["RB1", "RB2"]
    assert "TE" not in default_rule
    assert te_only_flex["RB"] == ["RB1"]
    assert te_only_flex["TE"] == ["TE1"]


def test_no_trade_module_reads_the_registrys_flex_keys_directly():
    """P1 / P2, structural.

    MUTATION: rebuild the two-entry ``eligibility_overrides`` map in
    ``suggestions.py``.

    ``configured_slot_eligibility`` is the one resolver from registry keys to
    a slot rule, and its docstring names ``trade/suggestions.py`` as the
    "two-entry variant" it replaced.  That variant was still here: it read
    ``flexEligible`` and ``idpFlexEligible`` and silently omitted
    ``sflexEligible``, so a league narrowing its Superflex was measured
    against the declared default.  Reading the raw keys anywhere in
    ``src/trade`` is how that comes back.
    """
    registry_keys = {"flexEligible", "sflexEligible", "idpFlexEligible"}
    offenders: list[str] = []
    for name, tree in _module_sources().items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in registry_keys:
                offenders.append(f"{name}:{node.lineno} {node.value!r}")

    assert offenders == [], (
        "src/trade reads the registry's flex keys directly; the one resolver is "
        f"src/ros/lineup.configured_slot_eligibility: {offenders}"
    )


# ── P5 — retained and dropped are disjoint ───────────────────────────


def test_a_forced_drop_is_never_also_retained():
    """P5.

    MUTATION: stop subtracting the forced drops in
    ``simulate_final_legal_roster`` (pass ``outgoing_ids=[]``).

    "Who must go" and "what the roster is afterwards" are computed in two
    places — capacity names the drops, the Roster owner re-solves the result.
    If the second does not consume the first, a released player keeps starting
    and the trade looks free.
    """
    context = _context()
    capacity = assess_roster_capacity(context, incoming_players=["IN1"])
    assert capacity.forced_drops, "fixture must actually force a drop"

    final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1"])
    dropped = {d.player_id for d in capacity.forced_drops}
    retained = {m["playerId"] for m in final["coreAfter"]["members"]}

    assert dropped & retained == set(), (
        f"{sorted(dropped & retained)} are reported as forced drops and are still "
        "in the post-trade meaningful core"
    )
    assert {d["playerId"] for d in final["cleanupApplied"]} == dropped


def test_a_drop_the_trade_acquired_leaves_from_the_incoming_side():
    """P5, the asymmetric half.

    A forced drop flagged ``acquiredInTrade`` was never on the before-roster,
    so removing him by id would be a no-op and he would arrive anyway.  He has
    to be withheld from the INCOMING side instead.
    """
    context = _context(arrivals=(("IN1", 6000.0, "WR"), ("IN2", 10.0, "WR")))
    capacity = assess_roster_capacity(context, incoming_players=["IN1", "IN2"])
    acquired = [d for d in capacity.forced_drops if d.acquired_in_trade]
    if not acquired:
        pytest.skip("this board does not cut an acquired player; nothing to prove here")

    final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1", "IN2"])
    retained = {m["playerId"] for m in final["coreAfter"]["members"]}
    assert {d.player_id for d in acquired} & retained == set()


# ── P6 — unknown stays unknown ───────────────────────────────────────


def test_an_unknown_roster_limit_stays_unknown():
    """P6.

    MUTATION: default the limit to a number when the registry answers nothing.

    Coercing an unknown cap to "unlimited" makes every trade look free, and
    coercing it to a guess invents forced drops.  Both are worse than saying
    so.
    """
    settings = dict(TINY_SETTINGS)
    settings.pop("rosterSize")
    capacity = assess_roster_capacity(_context(settings=settings), incoming_players=["IN1"])
    payload = capacity.to_dict()

    assert payload["rosterLimit"] is None
    assert payload["overLimitAfter"] is None
    assert payload["openSpotsAfter"] is None
    assert payload["requiresDrops"] is None
    assert payload["forcedDrops"] == []
    assert payload["forcedDropValue"] is None
    assert payload["certainty"] != "exact"


# ── P7 — an unpriced drop is null, never zero ────────────────────────


def test_an_unpriced_forced_drop_reports_null_and_is_counted_separately():
    """P7.

    MUTATION: coerce ``ForcedDrop.value`` to ``0.0`` when the board has no
    price, or include unpriced drops in ``forcedDropValue``.

    An unpriced player is the one whose release is most likely to be a
    mistake, and 0.0 makes him look like the safest possible cut.
    """
    roster = list(TINY_ROSTER[:-1]) + [("GHOST", None, "TE")]
    context = _context(roster=roster)
    capacity = assess_roster_capacity(context, incoming_players=["IN1"])

    payload = capacity.to_dict()
    unpriced = [d for d in payload["forcedDrops"] if d["value"] is None]
    assert unpriced, "fixture must force out the unpriced player"
    assert payload["unpricedForcedDrops"] == len(unpriced)

    priced_total = sum(d["value"] for d in payload["forcedDrops"] if d["value"] is not None)
    assert payload["forcedDropValue"] == pytest.approx(round(priced_total, 1))
    # The cut COST is still defined for him — that is a different quantity,
    # and publishing it is what keeps "we cannot price him" from reading as
    # "he is worthless".
    assert all(d["effectiveCutCost"] is not None for d in unpriced)


# ── P8 — the exact simulation order ──────────────────────────────────


def test_before_apply_resolve_after_is_the_order_and_the_owner_does_the_resolve():
    """P8.

    MUTATION: build the after-roster in ``roster_capacity`` and hand the owner
    a pre-applied pool with ``incoming=()`` / ``outgoing_ids=()``.

    The owner's contract is ``pool`` = the roster BEFORE, with the transaction
    supplied as arguments, because it re-solves BOTH states and diffs them.
    Applying the trade first collapses the two states into one and the
    before-lineup is lost.
    """
    seen: dict[str, object] = {}
    import src.trade.roster_capacity as rc

    real = rc.simulate_roster_change

    def spy(pool, starter_slots, **kwargs):
        seen["pool"] = [p.player_id for p in pool]
        seen["incoming"] = [p.player_id for p in kwargs.get("incoming", ())]
        seen["outgoing_ids"] = list(kwargs.get("outgoing_ids", ()))
        seen["slot_eligibility"] = kwargs.get("slot_eligibility")
        return real(pool, starter_slots, **kwargs)

    context = _context()
    capacity = assess_roster_capacity(context, incoming_players=["IN1"], outgoing_players=["WR1"])
    rc.simulate_roster_change = spy
    try:
        simulate_final_legal_roster(
            context,
            capacity,
            incoming_players=["IN1"],
            outgoing_players=["WR1"],
        )
    finally:
        rc.simulate_roster_change = real

    # BEFORE: the pre-trade roster, complete — the departing player included.
    assert seen["pool"] == [n.lower() for n, _v, _p in TINY_ROSTER]
    # APPLY: the transaction is an ARGUMENT, not something we did first.
    assert seen["incoming"] == ["in1"]
    assert "wr1" in seen["outgoing_ids"]
    # …and the required cleanup travels with it, so the re-solve is against
    # the FINAL LEGAL roster rather than an illegal one.
    for drop in capacity.forced_drops:
        if not drop.acquired_in_trade:
            assert drop.player_id in seen["outgoing_ids"]


def test_the_resolve_produces_a_cascade_arithmetic_cannot():
    """P8, the reason the order matters.

    A player who is in neither side of the trade nor in the cleanup still
    changes slot.  That is set-dependence — the property that makes a re-solve
    necessary and a value subtraction insufficient.
    """
    context = _context()
    capacity = assess_roster_capacity(context, incoming_players=["IN1"])
    final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1"])

    named = {"in1"} | {d.player_id for d in capacity.forced_drops}
    cascaded = [
        m
        for m in final["movements"]
        if m["playerId"] not in named and m["slotBefore"] != m["slotAfter"]
    ]
    assert cascaded, (
        "no untraded player changed slot; the fixture no longer exercises the "
        "cascade this property is about"
    )


def test_the_final_roster_block_grades_nothing():
    """The C2 boundary: roster information, never a verdict."""
    context = _context()
    capacity = assess_roster_capacity(context, incoming_players=["IN1"])
    final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1"])

    assert final["isVerdict"] is False
    # ``isVerdict`` is the DISCLAIMER, not a verdict — same naming device as
    # ``isValueDelta`` on the displacement block.
    graded = [
        k
        for k in final
        if k not in {"isVerdict"} and k.lower().endswith(("verdict", "grade", "score", "rating"))
    ]
    assert graded == []


def test_an_upper_bound_cleanup_says_so():
    """Taxi bracketing survives the re-solve rather than being flattened."""
    settings = dict(TINY_SETTINGS, taxiSize=2)
    context = _context(settings=settings)
    capacity = assess_roster_capacity(context, incoming_players=["IN1"])
    final = simulate_final_legal_roster(context, capacity, incoming_players=["IN1"])

    assert final["cleanupIsUpperBound"] == (capacity.certainty != "exact")
    if final["cleanupIsUpperBound"]:
        assert any("UPPER BOUND" in n for n in final["notes"])
