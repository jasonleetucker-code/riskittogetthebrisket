"""C3-CON-01 / V1-130 — the ONE recommendation-constraint owner.

Binding spec: `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md`
§2-§4, §6, §7. Owner rows 1.5 / 2.10 / 2.11.

The scope note from the V1 completion contract is load-bearing: **the OWNER is
V1-required; the wider constraint feature set is not.** So these prove
resolution and application, not the UI, the storage service, or the
promote-to-permanent action.

The distinction the whole module turns on: **a constraint is not a valuation
rule.** A protected player keeps his canonical value, stays a valid incoming
target, and is fully analysable in the manual calculator. Only automatically
generated recommendations are constrained, and only on the side you give away.
"""

from __future__ import annotations

from src.trade.constraints import (
    UNRESOLVED,
    TradeConstraints,
    partition_sendable,
    resolve_constraints,
)


def _row(name: str, team: str | None = None, position: str = "RB", value: int = 5000):
    return {
        "displayName": name,
        "canonicalName": name,
        "name": name,
        "team": team,
        "position": position,
        "pos": position,
        "rankDerivedValue": value,
        "assetClass": "player",
    }


def _contract(*rows):
    return {"playersArray": list(rows)}


# ── §2.2 — NFL-team outgoing protection ───────────────────────────────


def test_a_protected_team_blocks_outgoing_and_nothing_else():
    """Acceptance 9: blocked outgoing, still a valid incoming target.

    `may_send` is the ONLY question this owner answers. There is deliberately
    no `may_receive` — an acquisition target is never constrained, so a
    "receiving" check would be a place for someone to add one.
    """
    contract = _contract(_row("Jefferson", "MIN"), _row("Chase", "CIN"))
    c = resolve_constraints(contract=contract, persistent={"nflTeams": ["MIN"]})

    assert c.may_send(_row("Chase", "CIN")) is True
    assert c.may_send(_row("Jefferson", "MIN")) is False
    assert c.block_reason(_row("Jefferson", "MIN")) == "protected_nfl_team"
    assert not hasattr(c, "may_receive"), "incoming is never constrained"


def test_team_identity_is_resolved_dynamically_from_the_board():
    """Acceptance 11: joining/leaving the team updates protection.

    Team identity is read from the canonical board on every resolution rather
    than stored with the rule, so there is no stored state to migrate when a
    player is traded in real life.
    """
    joined = resolve_constraints(
        contract=_contract(_row("Mover", "MIN")), persistent={"nflTeams": ["MIN"]}
    )
    left = resolve_constraints(
        contract=_contract(_row("Mover", "DAL")), persistent={"nflTeams": ["MIN"]}
    )
    bare = {"name": "Mover"}  # the caller's object carries no team at all
    assert joined.may_send(bare) is False
    assert left.may_send(bare) is True


def test_an_individual_rule_survives_the_player_leaving_the_team():
    """§2.2's last sentence, stated as a test."""
    c = resolve_constraints(
        contract=_contract(_row("Mover", "DAL")),
        persistent={"nflTeams": ["MIN"], "untouchables": ["Mover"]},
    )
    assert c.block_reason({"name": "Mover"}) == "protected_individual"


def test_an_unknown_nfl_team_fails_closed():
    """Measured: 4 non-pick players on the 2026-08-18 board carry no `team`.

    Assuming such a player is NOT on the protected team is a fabricated fact,
    in the direction that proposes trading someone the user protected.
    """
    c = resolve_constraints(
        contract=_contract(_row("Unknown Guy", None)), persistent={"nflTeams": ["MIN"]}
    )
    assert c.block_reason({"name": "Unknown Guy"}) == "protected_nfl_team_unknown"


def test_picks_are_never_swept_up_by_a_team_rule():
    """A pick has no NFL team, and unknown-therefore-protected would block them all.

    Measured on the live board: 0 of 162 pick rows are blocked by the MIN rule.
    """
    c = resolve_constraints(
        contract=_contract(_row("2027 Early 1st", None, position="PICK")),
        persistent={"nflTeams": ["MIN"]},
    )
    assert c.may_send({"name": "2027 Early 1st", "position": "PICK"}) is True
    # ...but an individual rule still reaches a pick if a user names one.
    named = resolve_constraints(
        contract=_contract(_row("2027 Early 1st", None, position="PICK")),
        persistent={"untouchables": ["2027 Early 1st"]},
    )
    assert named.block_reason({"name": "2027 Early 1st", "position": "PICK"}) == (
        "protected_individual"
    )


def test_a_different_user_is_unaffected():
    """Acceptance 10. Constraints are per (user, league) data, never a player flag."""
    contract = _contract(_row("Jefferson", "MIN"))
    jason = resolve_constraints(contract=contract, persistent={"nflTeams": ["MIN"]})
    someone_else = resolve_constraints(contract=contract, persistent=None)
    assert jason.may_send({"name": "Jefferson"}) is False
    assert someone_else.may_send({"name": "Jefferson"}) is True
    assert someone_else.active is False


def test_no_configured_preference_is_not_a_failure():
    """ "Nothing configured" and "we could not check" are different answers."""
    c = resolve_constraints(contract=_contract(), persistent=None)
    assert c.resolution_failed is False
    assert c.active is False


# ── §3.3 — LOCK / EXCLUDE interaction ─────────────────────────────────


def test_exclude_blocks_and_lock_requires():
    c = resolve_constraints(refinement={"exclude": ["Benched"], "lock": ["Wanted"]})
    assert c.block_reason({"name": "Benched"}) == "excluded_temporary"
    assert c.required_outgoing() == frozenset({"wanted"})


def test_lock_and_exclude_on_the_same_player_resolves_to_exclude():
    """Acceptance 3. Contradictory state is rejected, not silently ordered.

    EXCLUDE wins: the user said keep him out, and honouring the LOCK instead
    would force a player into a package they just refused.
    """
    c = resolve_constraints(refinement={"lock": ["Both"], "exclude": ["Both"]})
    assert c.required_outgoing() == frozenset()
    assert c.block_reason({"name": "Both"}) == "excluded_temporary"
    assert any("EXCLUDE wins" in n for n in c.notes)


def test_persistent_protection_outranks_a_temporary_lock():
    """§3.3's last rule, and the one a naive implementation gets backwards.

    A LOCK must not be able to force a protected player into a recommendation.
    """
    c = resolve_constraints(
        persistent={"untouchables": ["Protected"]}, refinement={"lock": ["Protected"]}
    )
    assert c.required_outgoing() == frozenset()
    assert c.block_reason({"name": "Protected"}) == "protected_individual"
    assert any("outranks" in n for n in c.notes)


def test_multiple_constraints_are_honoured_together():
    """Acceptance 4."""
    c = resolve_constraints(
        contract=_contract(_row("A", "MIN"), _row("B", "CIN"), _row("C", "DAL")),
        persistent={"nflTeams": ["MIN"], "untouchables": ["B"]},
        refinement={"exclude": ["C"]},
    )
    assert [c.may_send({"name": n}) for n in ("A", "B", "C")] == [False, False, False]


# ── Fail-closed ───────────────────────────────────────────────────────


def test_unresolved_refuses_everything_with_a_reason():
    """ "We could not check your untouchables" must never render as "you have none"."""
    assert UNRESOLVED.resolution_failed is True
    assert UNRESOLVED.may_send({"name": "Anyone"}) is False
    assert UNRESOLVED.block_reason({"name": "Anyone"}) == "constraints_unresolved"
    assert UNRESOLVED.active is True


def test_partition_returns_the_blocked_half_rather_than_dropping_it():
    """A short list has to be explainable — same posture as roster capacity."""
    assets = [{"name": "Keep"}, {"name": "Blocked"}]
    c = resolve_constraints(persistent={"untouchables": ["Blocked"]})
    sendable, blocked = partition_sendable(assets, c)
    assert [a["name"] for a in sendable] == ["Keep"]
    assert [(a["name"], why) for a, why in blocked] == [("Blocked", "protected_individual")]


def test_an_inactive_constraint_set_is_a_pass_through():
    assets = [{"name": "A"}, {"name": "B"}]
    sendable, blocked = partition_sendable(assets, TradeConstraints())
    assert sendable == assets and blocked == []
    sendable, blocked = partition_sendable(assets, None)
    assert sendable == assets and blocked == []


# ── Acceptance 13 — values are untouched ──────────────────────────────


def test_resolution_never_reads_or_writes_a_canonical_value():
    """A constraint is not a valuation rule.

    Structural: no name containing `value` is read anywhere in the module's
    resolution path. `rankDerivedValue` appears in these fixtures precisely so
    a change that started consulting it would have something to consult.
    """
    import ast
    import inspect

    from src.trade import constraints as module

    tree = ast.parse(inspect.getsource(module))
    banned = {"rankDerivedValue", "rank_derived_value", "display_value", "market_value"}
    hits = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in banned
    }
    assert not hits, f"the constraint owner reads canonical value fields: {sorted(hits)}"

    before = _row("Jefferson", "MIN", value=9999)
    c = resolve_constraints(contract=_contract(before), persistent={"nflTeams": ["MIN"]})
    c.may_send(before)
    assert before["rankDerivedValue"] == 9999


# ── §6 / acceptance 14 — applied during generation, by ONE owner ──────


def test_the_finder_enforces_constraints_INSIDE_enumeration():
    """§6: reject forbidden state and generate only feasible packages.

    This guard used to pin a WEAKER property — that `find_trades` called
    `partition_sendable(my_roster)` textually before `_generate_packages`, i.e.
    that the caller shortened its own pool first. That satisfies §6's letter and
    misses §2.3's point: a pool pre-filter is a page-local rule, and the ninth
    surface to be written will have its own or none.

    What is pinned now is that the constraint reaches the SHARED GENERATOR as
    eligibility. `find_trades` builds an outgoing policy from the owner and
    hands it to `substrate.enumerate_packages`, which refuses to enumerate at
    all without one — so a forbidden package is never constructed, rather than
    constructed and then dropped.
    """
    import ast
    import inspect

    from src.trade import finder

    source = inspect.getsource(finder)
    tree = ast.parse(source)
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "outgoing_eligibility" in called, (
        "`finder` no longer builds an outgoing policy from the constraint owner "
        "— recommendations are unconstrained"
    )

    find_src = inspect.getsource(finder.find_trades)
    assert "partition_sendable(my_roster" not in find_src, (
        "the retired pool pre-filter is back; enforcement belongs to the "
        "substrate so every consumer inherits it"
    )

    gen_src = inspect.getsource(finder._generate_packages)
    assert "outgoing_policy=outgoing_policy" in gen_src, (
        "the outgoing policy is not reaching enumerate_packages"
    )


def test_the_substrate_cannot_generate_without_a_constraint_decision():
    """The property that makes "1 owner, N consumers" hold for consumer N+1.

    Not a convention and not a review checklist: `outgoing_policy` has no
    default, so a new product that forgets it gets a TypeError rather than an
    unconstrained recommendation. `None` is refused too — an unset variable and
    a considered "nothing protects this roster" must not look the same.
    """
    import pytest as _pytest

    from src.packages import ConstraintMisapplied, enumerate_packages, enumerate_sides

    with _pytest.raises(TypeError, match="outgoing_policy"):
        enumerate_packages([], [])
    with _pytest.raises(TypeError, match="outgoing_policy"):
        enumerate_sides([], [1], side="send")
    with _pytest.raises(ConstraintMisapplied, match="must not be None"):
        enumerate_packages([], [], outgoing_policy=None)


def test_every_outgoing_asset_constrained_is_an_honest_no_result():
    """Acceptance 5: impossible constraints do not weaken the parent rules.

    The finder returns nothing AND says why, rather than quietly relaxing the
    protection to find something.
    """
    from src.trade import finder

    players = {
        f"P{i}": {
            "_finalAdjusted": 6000 - i * 100,
            "position": "RB",
            "_sites": 6,
            "_canonicalSiteValues": {"ktcSfTep": 5000 - i * 100, "idpTradeCalc": 5000 - i * 100},
        }
        for i in range(8)
    }
    teams = [
        {"name": "Us", "ownerId": "1", "roster_id": 1, "players": ["P0", "P1"], "picks": []},
        {"name": "Them", "ownerId": "2", "roster_id": 2, "players": ["P2", "P3"], "picks": []},
    ]
    c = resolve_constraints(persistent={"untouchables": ["P0", "P1"]})
    result = finder.find_trades(players, "Us", ["Them"], teams, constraints=c)

    assert result["trades"] == []
    assert result["metadata"]["noResultReason"] == "all_outgoing_assets_constrained"
    assert result["metadata"]["constraintsBlockedOutgoing"] == 2
    assert result["warnings"], "a no-result state must explain itself"


def test_there_is_exactly_one_constraint_owner():
    """Acceptance 14: no page-local copies.

    A second module deciding "may this player be recommended outgoing" is the
    duplication this row exists to prevent.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"\b(untouchable|protected_nfl_team|excluded_outgoing)\b", re.I)
    owners = set()
    for path in (root / "src").rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            owners.add(rel)
    assert owners <= {
        "src/trade/constraints.py",
        "src/trade/finder.py",
    }, f"constraint vocabulary appears outside the owner and its consumers: {sorted(owners)}"
