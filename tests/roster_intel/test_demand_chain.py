"""The starter → remaining → reserve chain, and the one owner behind it.

Integration's non-blocking findings 4, 5, 6 and 10, written RED-first.
All four are the same defect wearing different clothes: ``core.py``
re-derived slot demand instead of consuming ``lineup.slot_demand``, so
it needed private tables of its own and reached into the owner's
privates to make them agree.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from src.roster_intel.core import build_meaningful_core, reserve_demand, reserve_slot_list
from src.ros.lineup import RosterPlayer, slot_demand

REPO = pathlib.Path(__file__).resolve().parents[2]

#: The live league's RAW roster_positions — bench slots included, exactly
#: as Sleeper publishes them and as ``resolve_starter_slots`` receives them.
_RAW_ROSTER_POSITIONS = [
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX",
    "SUPER_FLEX", "K", "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
    "BN", "BN", "BN", "IR", "TAXI",
]  # fmt: skip


def P(pid, pos, val, **kw):
    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=val, **kw)


# ══ F2 — bench slots are not roster demand ═════════════════════════


def test_bench_ir_and_taxi_slots_generate_no_reserve_demand():
    """RED before the fix.  ``BN``/``IR``/``TAXI`` are not lineup slots —
    ``lineup.NON_LINEUP_SLOTS`` says so and ``slot_demand`` already
    excludes them — but ``core.py`` counted the raw list itself and
    reported ``BN: 37, IR: 1, TAXI: 1`` as positions with demand.

    Not reachable from production today because every traced caller
    passes already-filtered slots. That is exactly the kind of guard
    that stops being true when someone adds a caller.
    """
    demand = reserve_demand(_RAW_ROSTER_POSITIONS)
    for bench in ("BN", "IR", "TAXI"):
        assert bench not in demand.by_slot, bench
        assert bench not in demand.starter_basis, bench


def test_reserve_demand_agrees_with_the_canonical_slot_demand_owner():
    """The basis must BE the owner's answer, not a second derivation that
    happens to match.  Dedicated positions come from
    ``slot_demand().dedicated`` and flex capacity from
    ``slot_demand().flex_capacity``; nothing else may appear."""
    canonical = slot_demand(_RAW_ROSTER_POSITIONS)
    demand = reserve_demand(_RAW_ROSTER_POSITIONS)

    expected_keys = (set(canonical.dedicated) | set(canonical.flex_capacity)) - {
        "K",
        "DEF",
        "SUPER_FLEX",
    }
    assert set(demand.starter_basis) == expected_keys

    for pos, n in canonical.dedicated.items():
        if pos in {"K", "DEF"}:
            continue
        expected = int(n) + (canonical.flex_capacity.get("SUPER_FLEX", 0) if pos == "QB" else 0)
        assert demand.starter_basis[pos] == expected, pos


# ══ F3 — no private table of flex slots ════════════════════════════


def test_a_flex_slot_the_owner_knows_about_is_never_silently_zeroed():
    """RED before the fix.  ``_RESERVE_FLEX_SLOTS`` was a private 7-tuple
    that had to be kept in lockstep with the owner's table by hand.  A
    flex slot present in the owner but missing from that tuple produced
    NO reserve demand and vanished from ``starter_basis`` — so
    ``weakness`` emitted no rungs for it either. Silently.

    Parametrised over every flex slot the owner declares, so adding one
    there can never leave this behind.
    """
    from src.ros.lineup import slot_demand as canonical_slot_demand

    flex_slots = set(canonical_slot_demand(["FLEX", "SUPER_FLEX", "IDP_FLEX"]).flex_capacity)
    assert flex_slots  # sanity: the owner does declare flex slots

    for slot in sorted(_declared_flex_slots()):
        if slot == "SUPER_FLEX":
            continue  # folds into QB by owner decision — covered separately
        demand = reserve_demand(["QB", slot, slot])
        assert slot in demand.starter_basis, slot
        assert demand.starter_basis[slot] == 2, slot


def _declared_flex_slots() -> set[str]:
    """Every flex slot the CANONICAL owner declares, read from it."""
    from src.ros import lineup

    return set(lineup._FLEX_SLOT_DEMAND_KEYS)


def test_core_keeps_no_private_flex_or_slot_table():
    """Structural.  ``_RESERVE_FLEX_SLOTS`` is gone and nothing replaced
    it — the flex slots come from the owner's own answer."""
    source = (REPO / "src/roster_intel/core.py").read_text(encoding="utf-8")
    assert "_RESERVE_FLEX_SLOTS" not in source


def test_no_roster_intel_module_imports_a_lineup_private():
    """RED before the fix. ``core.py`` imported ``_FLEX_SLOT_DEMAND_KEYS``
    and ``weakness.py`` imported ``_is_dedicated`` — the public
    ``slot_demand()`` contract already answers both questions.

    ``tests/lineup/test_single_owner.py`` has a guard for this but is
    parametrised over three files, none of them the new ones."""
    offenders = {}
    for path in sorted((REPO / "src/roster_intel").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src.ros"):
                private = [a.name for a in node.names if a.name.startswith("_")]
                if private:
                    offenders[path.name] = private
    assert offenders == {}, offenders


def test_weakness_does_not_import_from_cores_privates_either():
    tree = ast.parse((REPO / "src/roster_intel/weakness.py").read_text(encoding="utf-8"))
    private = [
        a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("src.roster_intel")
        for a in node.names
        if a.name.startswith("_")
    ]
    assert private == []


# ══ F1 — the league's CONFIGURED flex eligibility is consumed ══════


_CONFIGURED = {"FLEX": ("WR", "TE")}  # a league whose FLEX excludes RB


def test_a_configured_flex_that_excludes_rb_does_not_seat_an_rb():
    """RED before the fix.  ``build_meaningful_core`` was called without
    the league's configured eligibility, so a registry that narrows FLEX
    was ignored in favour of the owner's defaults — and the starter
    solve seated a player the league does not allow there."""
    pool = [P("QB1", "QB", 900), P("RB1", "RB", 800), P("WR1", "WR", 100)]
    core = build_meaningful_core(
        pool, ["QB", "FLEX"], slot_eligibility=_CONFIGURED, config={"reserveMultiplier": 1.0}
    )
    seated = {m.player_id: m.slot for m in core.members if m.role == "starter"}
    assert seated.get("FLEX") is None or seated.get("FLEX") != "RB1"
    flex_holder = next((pid for pid, slot in seated.items() if slot == "FLEX"), None)
    assert flex_holder == "WR1", seated


def test_configured_eligibility_reaches_reserve_demand_too():
    """The even-split and flex-capacity answers both depend on it, so a
    core that solves starters with the league's rules and computes
    reserves with the defaults is internally inconsistent."""
    narrow = reserve_demand(["FLEX"], slot_eligibility={"FLEX": ("WR",)})
    wide = reserve_demand(["FLEX"])
    # Flex capacity is the same either way — one slot is one slot — but
    # the call must ACCEPT the override rather than reject it.
    assert narrow.starter_basis == wide.starter_basis == {"FLEX": 1}


# ══ Every player counts exactly once, under configured eligibility ══


@pytest.mark.parametrize(
    "eligibility",
    [None, {"FLEX": ("WR", "TE")}, {"FLEX": ("RB",), "IDP_FLEX": ("LB",)}],
)
def test_no_player_is_counted_twice_whatever_the_flex_rules_are(eligibility):
    pool = [
        P("QB1", "QB", 900), P("QB2", "QB", 500),
        P("RB1", "RB", 800), P("RB2", "RB", 700), P("RB3", "RB", 400),
        P("WR1", "WR", 850), P("WR2", "WR", 750), P("WR3", "WR", 650),
        P("TE1", "TE", 600), P("TE2", "TE", 300),
        P("LB1", "LB", 550), P("LB2", "LB", 250),
    ]  # fmt: skip
    slots = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "IDP_FLEX"]
    core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
    ids = [m.player_id for m in core.members]
    assert len(ids) == len(set(ids)), ids
    starters = {m.player_id for m in core.members if m.role == "starter"}
    reserves = {m.player_id for m in core.members if m.role == "reserve"}
    assert not (starters & reserves)


def test_reserve_slots_are_derived_from_the_same_basis_the_starters_used():
    demand = reserve_demand(_RAW_ROSTER_POSITIONS)
    slots = reserve_slot_list(demand)
    assert set(slots) <= set(demand.starter_basis)
    assert len(slots) == demand.total()


# ══ F1, caller side — the ENDPOINT consumes the league's own rules ══


def test_the_endpoint_solves_with_the_leagues_configured_flex_not_the_defaults(
    tmp_path, monkeypatch
):
    """RED before the fix. ``build_meaningful_core`` accepted
    ``slot_eligibility`` all along; nobody passed it. So a registry that
    narrows FLEX was ignored and the endpoint seated a player the league
    does not allow there — and ``stamp_optimal_lineups`` did the same, so
    both surfaces were wrong TOGETHER, which is the worst version: they
    agree, so nothing looks broken.
    """
    import json

    from src.api import league_registry, roster_intelligence

    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "narrow",
                "leagues": [
                    {
                        "key": "narrow",
                        "displayName": "Narrow",
                        "sleeperLeagueId": "L-NARROW",
                        "scoringProfile": "p",
                        "active": True,
                        "rosterSettings": {
                            "teamCount": 2,
                            "starters": {"QB": 1, "FLEX": 1},
                            # This league's FLEX does NOT accept RB.
                            "flexEligible": ["WR", "TE"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    try:
        contract = {
            "meta": {"leagueKey": "narrow"},
            "playersArray": [
                {"canonicalName": n, "displayName": n, "position": p, "rankDerivedValue": v}
                for n, p, v in [("QB1", "QB", 900), ("RB1", "RB", 800), ("WR1", "WR", 100)]
            ],
            "sleeper": {
                "rosterPositions": ["QB", "FLEX", "BN"],
                "positions": {"QB1": "QB", "RB1": "RB", "WR1": "WR"},
                "teams": [{"ownerId": "o1", "name": "T", "players": ["QB1", "RB1", "WR1"]}],
            },
        }
        out = roster_intelligence.build_league_roster_intelligence(contract, team_count=2)
        members = out["teams"]["o1"]["core"]["members"]
        flex = next((m for m in members if m["slot"] == "FLEX"), None)
        assert flex is not None, members
        # RB1 is the highest-value FLEX-eligible player under the DEFAULTS
        # and is illegal under this league's own rules.
        assert flex["playerId"] == "WR1", flex
    finally:
        league_registry.reload_registry()


def test_the_lineup_stamp_and_the_endpoint_use_the_same_eligibility_source():
    """Structural: both call ``contract_slot_eligibility``, so they cannot
    resolve the league's rules differently."""
    import ast

    for rel in ("src/api/data_contract.py", "src/api/roster_intelligence.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "contract_slot_eligibility(" in src, rel
    tree = ast.parse((REPO / "src/api/data_contract.py").read_text(encoding="utf-8"))
    names = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "contract_slot_eligibility" in names


def test_absent_configuration_means_defaults_not_an_empty_eligibility_set():
    """An empty list would make the slot UNFILLABLE. "Not configured" and
    "configured to accept nobody" are different leagues."""
    from src.ros.lineup import configured_slot_eligibility

    assert configured_slot_eligibility({}) == {}
    assert configured_slot_eligibility({"flexEligible": []}) == {}
    assert configured_slot_eligibility(None) == {}
    assert configured_slot_eligibility({"flexEligible": ["WR"]}) == {"FLEX": ("WR",)}
