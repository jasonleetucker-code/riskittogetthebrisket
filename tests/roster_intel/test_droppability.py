"""Droppability as a canonical consumer interface (C2-DROP-01).

The manifest's disposition for this unit is **CONSOLIDATE** and its
evidence is **parity**, so that is what this file is mostly about: the
cut ladder reached through the roster chain and the cut ladder reached
through the Perfect Draft board are the SAME ladder, produced by the
same owner, and there is exactly one place the arithmetic lives.

The rest guards the two ways an adapter goes wrong — it grows a second
implementation, or it quietly answers a different question than the
surface it claims parity with.
"""

from __future__ import annotations

import ast
import json
import pathlib
import random

import pytest

from src.draft.context import build_roster_context
from src.draft.displacement import MAX_LADDER_RUNGS
from src.league_intel.replacement import ScarcityComponents
from src.roster_intel.droppability import (
    SCARCITY_MULTIPLIER_BAND,
    SCARCITY_REORDER_RATIO,
    TeamNotInLeague,
    league_droppability,
    team_droppability,
)
from src.ros.lineup import load_league_starter_slots

REPO = pathlib.Path(__file__).resolve().parents[2]


def _row(pid, name, pos, value):
    return {
        "playerId": pid,
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "rankDerivedValue": value,
        "assetClass": "offense",
    }


_ROSTER_A = ["Star QB", "Star WR", "Bench WR", "Deep WR", "Ghost Body"]
_ROSTER_B = ["Other QB", "Other WR"]


def _contract(roster_a=None, roster_b=None):
    """A league that starts QB×1 + WR×1, with a free-agent pool.

    ``Ghost Body`` is on the roster and absent from ``playersArray``
    entirely — the unpriced case, which must survive to the consumer.
    """
    return {
        "meta": {"leagueKey": "pd_main"},
        "playersArray": [
            _row("qb1", "Star QB", "QB", 8000),
            _row("wr1", "Star WR", "WR", 7000),
            _row("wr2", "Bench WR", "WR", 1500),
            _row("wr3", "Deep WR", "WR", 900),
            _row("qb2", "Other QB", "QB", 6000),
            _row("wr4", "Other WR", "WR", 2500),
            _row("fa1", "Free WR", "WR", 1200),
            _row("fa2", "Free QB", "QB", 3000),
        ],
        "sleeper": {
            "rosterPositions": ["QB", "WR", "BN", "BN", "BN"],
            "positions": {
                "Star QB": "QB",
                "Star WR": "WR",
                "Bench WR": "WR",
                "Deep WR": "WR",
                "Other QB": "QB",
                "Other WR": "WR",
            },
            "teams": [
                {
                    "name": "Alpha",
                    "ownerId": "owner-a",
                    "roster_id": 1,
                    "players": list(roster_a or _ROSTER_A),
                    "playerIds": [],
                },
                {
                    "name": "Beta",
                    "ownerId": "owner-b",
                    "roster_id": 2,
                    "players": list(roster_b or _ROSTER_B),
                    "playerIds": [],
                },
            ],
        },
    }


@pytest.fixture(autouse=True)
def _registry(tmp_path, monkeypatch):
    from src.api import league_registry

    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "pd_main",
                "leagues": [
                    {
                        "key": "pd_main",
                        "displayName": "PD Main",
                        "sleeperLeagueId": "L-PD-MAIN",
                        "scoringProfile": "prof_a",
                        "active": True,
                        "rosterSettings": {
                            "teamCount": 2,
                            "rosterSize": 5,
                            "taxiSize": 0,
                            "starters": {"QB": 1, "WR": 1},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield
    league_registry.reload_registry()


# ══ Parity — the manifest's acceptance evidence ════════════════════


def test_the_ladder_is_identical_to_the_draft_surfaces():
    """THE parity test.  Same team, same slots, same exclusions — the
    two surfaces must produce the same ladder object, not merely
    similar numbers.  If this ever drifts there are two definitions of
    what a cut costs, which is the failure C2-DROP-01 exists to close.
    """
    contract = _contract()
    slots = load_league_starter_slots("pd_main")
    draft = build_roster_context(contract, "pd_main", owner_id="owner-a")
    mine = team_droppability(contract, owner_id="owner-a", starter_slots=slots)
    assert mine["cutLadder"] == draft["cutLadder"]
    assert mine["waiverValues"] == draft["waiverValues"]


def test_parity_holds_without_being_handed_the_draft_surfaces_slots():
    """The adapter resolves its own slots through the C2-U1 truth ladder
    and must land on the same lineup the draft board uses.  Measured on
    the live 12-team board (21 slots, identical); pinned here so a
    change to either resolver shows up as a failure rather than as two
    surfaces quietly disagreeing about who is undroppable."""
    contract = _contract()
    draft = build_roster_context(contract, "pd_main", owner_id="owner-a")
    mine = team_droppability(contract, owner_id="owner-a")
    assert mine["slotSource"] == "sleeper_roster_positions"
    assert mine["cutLadder"] == draft["cutLadder"]


def test_every_team_in_the_league_matches_the_draft_surface():
    contract = _contract()
    slots = load_league_starter_slots("pd_main")
    everyone = league_droppability(contract, starter_slots=slots)
    assert set(everyone) == {"owner-a", "owner-b"}
    for owner, payload in everyone.items():
        draft = build_roster_context(contract, "pd_main", owner_id=owner)
        assert payload["cutLadder"] == draft["cutLadder"], owner


# ══ One owner, no second implementation ════════════════════════════


def _module_source(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_the_adapter_contains_no_cut_cost_arithmetic():
    """Structural.  The adapter may call the owner and shape a payload;
    the moment it computes a cost of its own there are two answers.

    Docstrings are stripped before matching — this module's prose
    quotes the owner's formula to explain the boundary, and a guard
    that trips on its own explanation teaches people to stop
    explaining."""
    tree = ast.parse(_module_source("src/roster_intel/droppability.py"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body[0].value.value = ""
    source = ast.unparse(tree)
    # The owner's ECC formula, its scarcity band, and its feasibility solver.
    # Reading a stamp the owner wrote (``r.value_basis == "assumedWaiver"``)
    # is a read, not arithmetic, and is deliberately not banned.
    for banned in ("max(0", "0.85", "1.15", "solve_optimal_assignment"):
        assert banned not in source, banned

    # The roster JOIN is delegated, and ``playersArray`` is the tell: touching
    # the board rows directly is how a second definition of who is on a roster
    # gets written.  (This replaced a ban on ``RosterAsset(`` when
    # ``pool_cut_ladder`` arrived — that entry point is handed a pool the
    # caller already built, so constructing the owner's own dataclass from it
    # is a type conversion, not a join.  The ban was a proxy for the join;
    # this is the join.)
    assert "playersArray" not in source
    assert "build_roster_assets" in source

    # And the ladder has exactly one origin: the owner, called once per
    # public entry point — ``team_droppability`` (contract-backed) and
    # ``pool_cut_ladder`` (an arbitrary post-trade roster).  An exact count
    # rather than "at least one", so adding a third path is a deliberate act
    # that updates this number, not something that slips through.
    calls = [
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls.count("build_cut_ladder") == 2


def test_the_cut_ladder_owner_has_exactly_two_callers():
    """``build_cut_ladder`` is the ladder.  Two production call sites is
    the intended state — the draft board and this adapter — and a third
    is how a page-local variant starts."""
    callers = set()
    for path in (REPO / "src").rglob("*.py"):
        if "build_cut_ladder(" in path.read_text(encoding="utf-8"):
            callers.add(path.relative_to(REPO).as_posix())
    assert callers == {
        "src/draft/displacement.py",
        "src/draft/context.py",
        "src/roster_intel/droppability.py",
    }


def test_the_scarcity_band_is_read_from_the_owner_not_restated():
    """A duplicated constant in a module whose point is that it
    duplicates nothing.  Derived, so retuning the owner's band cannot
    leave this module quietly wrong."""
    from src.draft import displacement

    assert SCARCITY_MULTIPLIER_BAND == (
        displacement._SCARCITY_BASE,
        displacement._SCARCITY_BASE + displacement._SCARCITY_GAIN,
    )


# ══ Scarcity is optional, and its effect is BOUNDED ════════════════


def _scarcity(rng):
    return {
        pos: ScarcityComponents(
            position=pos,
            lineup_scarcity=None,
            roster_scarcity=None,
            waiver_scarcity=rng.random(),
            elite_separation=None,
            starter_separation=None,
            replacement_gap=None,
        )
        for pos in ("QB", "WR")
    }


def test_scarcity_is_inert_by_default_and_says_so():
    out = team_droppability(_contract(), owner_id="owner-a")
    assert out["scarcityApplied"] is False
    assert any("multiplier inert" in n for n in out["notes"])


def test_scarcity_cannot_reorder_candidates_beyond_the_declared_ratio():
    """The honest statement of the divergence between this surface (no
    ROS snapshot, so no scarcity) and the draft board (which has one).

    Not "they might differ" — the multiplier lives in a bounded band, so
    it can only swap two candidates whose inert costs are within
    ~1.353x.  Anything wider keeps its order whatever scarcity says."""
    contract = _contract()
    inert = team_droppability(contract, owner_id="owner-a")["cutLadder"]["rungs"]
    cost = {r["name"]: r["effectiveCutCost"] for r in inert}
    order = {r["name"]: r["rung"] for r in inert}

    rng = random.Random(20260818)
    for _ in range(25):
        scarce = team_droppability(contract, owner_id="owner-a", scarcity=_scarcity(rng))
        new_order = {r["name"]: r["rung"] for r in scarce["cutLadder"]["rungs"]}
        assert scarce["scarcityApplied"] is True
        for a in order:
            for b in order:
                if a == b or a not in new_order or b not in new_order:
                    continue
                lo, hi = sorted((cost[a], cost[b]))
                if lo > 0 and hi / lo > SCARCITY_REORDER_RATIO:
                    assert (order[a] < order[b]) == (new_order[a] < new_order[b]), (a, b)


# ══ Missing is never zero ══════════════════════════════════════════


def test_an_unpriced_rostered_player_is_costed_as_assumed_waiver_not_as_free():
    """``Ghost Body`` is on the roster and on no board row.  He must
    reach the consumer stamped, because the board's tail floor is "the
    noisiest number in the league" and a join miss on a real asset must
    not read as a free cut."""
    out = team_droppability(_contract(), owner_id="owner-a")
    rungs = {r["name"]: r for r in out["cutLadder"]["rungs"]}
    assert "Ghost Body" in rungs
    assert rungs["Ghost Body"]["valueBasis"] == "assumedWaiver"
    assert out["counts"]["assumedWaiverRungs"] >= 1
    assert "Ghost Body" in out["unmatchedRosterPlayers"]
    assert any("verify before releasing" in n for n in out["notes"])


def test_a_player_the_lineup_needs_is_never_offered_as_a_cut():
    """Droppability is a matching, not a per-position count.  Alpha
    starts one QB and rosters one, so that QB is undroppable however
    cheap the arithmetic would make him."""
    out = team_droppability(_contract(), owner_id="owner-a")
    undroppable = {u["name"] for u in out["cutLadder"]["undroppable"]}
    assert "Star QB" in undroppable
    assert "Star QB" not in {r["name"] for r in out["cutLadder"]["rungs"]}


def test_the_waiver_population_is_league_wide_not_this_teams_bench():
    """A player on a RIVAL roster is exactly as unavailable as one on
    yours, so he cannot set the waiver level."""
    out = team_droppability(_contract(), owner_id="owner-a")
    assert out["waiverValues"]["QB"] == 3000.0  # Free QB, not Other QB (6000)
    assert out["waiverValues"]["WR"] == 1200.0  # Free WR, not Other WR (2500)


def test_an_unavailable_key_is_removed_from_the_waiver_population():
    """The named input the draft board uses for auction rookies.  There
    is no auction here, so it defaults empty — but it must still work,
    because that is what keeps it an INPUT rather than a second rule."""
    out = team_droppability(_contract(), owner_id="owner-a", unavailable_keys=["Free QB"])
    assert "QB" not in out["waiverValues"]


# ══ Refusals ═══════════════════════════════════════════════════════


def test_an_unknown_team_raises_rather_than_answering_for_another_one():
    with pytest.raises(TeamNotInLeague):
        team_droppability(_contract(), owner_id="nobody")


def test_a_contract_with_no_rosters_raises():
    with pytest.raises(TeamNotInLeague):
        team_droppability({"playersArray": []}, owner_id="owner-a")


def test_league_droppability_skips_an_unresolvable_team_rather_than_failing():
    contract = _contract()
    contract["sleeper"]["teams"].append({"name": "Nameless", "players": []})
    out = league_droppability(contract)
    assert set(out) == {"owner-a", "owner-b"}


# ══ Stamps ═════════════════════════════════════════════════════════


def test_the_payload_names_its_owner_its_scale_and_its_slot_source():
    out = team_droppability(_contract(), owner_id="owner-a")
    assert out["owner"] == "src/draft/displacement.py"
    assert out["valueScale"] == "rankDerivedValue"
    assert out["slotSource"] == "sleeper_roster_positions"
    assert out["team"] == {"ownerId": "owner-a", "teamName": "Alpha", "rosterId": 1}


def test_caller_supplied_slots_are_stamped_as_such():
    out = team_droppability(_contract(), owner_id="owner-a", starter_slots=["QB", "WR"])
    assert out["slotSource"] == "caller"
    assert out["starterSlots"] == ["QB", "WR"]


def test_max_rungs_is_honoured():
    out = team_droppability(_contract(), owner_id="owner-a", max_rungs=1)
    assert len(out["cutLadder"]["rungs"]) == 1
    assert MAX_LADDER_RUNGS > 1


def test_it_does_not_mutate_the_contract_it_was_given():
    contract = _contract()
    before = json.dumps(contract, sort_keys=True)
    team_droppability(contract, owner_id="owner-a")
    league_droppability(contract)
    assert json.dumps(contract, sort_keys=True) == before
