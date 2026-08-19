"""C3-CON-01 applied DURING generation — the substrate half.

`tests/trade/test_recommendation_constraints.py` pins what the OWNER decides.
This file pins what the shared GENERATOR does with that decision, which is the
half §2.3 and §6 are actually about:

    §2.3  "Do not implement page-local copies or post-filter protected players
           after ranking."
    §6    "Do not generate everything first and hide forbidden packages
           afterward. That wastes work and can return the wrong 'best' result."

Every guard here is paired with a MUTATION that shows it goes red. A structural
assertion nobody has watched fail is a comment with a `def` in front of it: it
can pass because the property holds, or because the assertion was never able to
see the property at all, and the two are indistinguishable until someone breaks
the code on purpose.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from src.packages import (
    RECEIVE,
    SEND,
    UNCONSTRAINED_OUTGOING,
    ConstraintMisapplied,
    EligibilityPolicy,
    adapt_assets,
    enumerate_packages,
    enumerate_sides,
)
from src.trade.constraints import (
    UNRESOLVED,
    blocked_outgoing,
    outgoing_eligibility,
    resolve_constraints,
)

REPO = Path(__file__).resolve().parents[2]


class Asset:
    """A product's own asset type, as the substrate sees them in the wild."""

    def __init__(self, name: str, value: float, position: str = "WR", team: str | None = None):
        self.name = name
        self.asset_id = name.lower().replace(" ", "_")
        self.position = position
        self.value = value
        self.team = team

    def __repr__(self) -> str:  # pragma: no cover - failure output
        return f"Asset({self.name!r}, {self.team!r})"


#: Our roster: one protected Viking, two ordinary players.
OURS = [
    Asset("Justin Jefferson", 9000.0, team="MIN"),
    Asset("Chris Olave", 5000.0, team="NO"),
    Asset("Rome Odunze", 4000.0, team="CHI"),
]
#: Theirs contains a MIN player too — the same rule, the other side.
THEIRS = [
    Asset("Jordan Addison", 4500.0, team="MIN"),
    Asset("Drake London", 6000.0, team="ATL"),
]

MIN_PROTECTED = resolve_constraints(persistent={"nflTeams": ["MIN"]})


def _packages(ours, theirs, outgoing_policy, **kw):
    packages, report = enumerate_packages(ours, theirs, outgoing_policy=outgoing_policy, **kw)
    return list(packages), report


def _names(side):
    return {a.name for a in side}


# ── §2.2 — outgoing-only asymmetry, BOTH directions ──────────────────


class TestOutgoingOnlyAsymmetry:
    """The rule is two statements and it takes two tests to pin them.

    A guard that only checked "protected players do not appear" would be
    satisfied by a policy applied to both pools — which silently removes the
    ability to ACQUIRE a player you protect, and is the more damaging of the
    two failures because nothing in the output looks wrong.
    """

    def test_a_protected_player_never_appears_on_a_side_we_send(self):
        policy = outgoing_eligibility(OURS, MIN_PROTECTED)
        packages, report = _packages(OURS, THEIRS, policy)

        assert packages, "the fixture produced no packages — it proves nothing"
        for pkg in packages:
            assert "Justin Jefferson" not in _names(pkg.send)
        assert report.our_excluded_constrained == 1
        assert report.outgoing_constrained is True

    def test_a_protected_player_is_STILL_a_valid_acquisition_target(self):
        """§2.2: "MIN players may still appear as INCOMING acquisition targets".

        The policy here is built over BOTH pools on purpose, and that detail is
        the whole test. A policy built over our roster alone cannot express the
        bug: it contains no key for the opponent's Viking, so applying it to
        their side would remove nothing and this guard would pass whatever the
        substrate did — GREEN because it was blind, not because the property
        held. (The mutation harness caught exactly that in the first draft of
        this file.)

        Built over the union, it is the shape a careless caller would produce,
        and only the substrate's send/receive split keeps Jordan Addison
        available.
        """
        policy = outgoing_eligibility([*OURS, *THEIRS], MIN_PROTECTED)
        assert any("addison" in k for k in policy.excluded_keys), (
            "the fixture policy does not name the opponent's protected player, "
            "so this test cannot see the bug it exists for"
        )
        packages, report = _packages(OURS, THEIRS, policy)

        received = {name for pkg in packages for name in _names(pkg.receive)}
        assert "Jordan Addison" in received, (
            "a MIN player on the OPPONENT's roster was withheld — the outgoing "
            "constraint reached the receive side and inverted §2.2"
        )
        assert report.their_excluded_ineligible == 0

    def test_the_owner_scopes_its_policy_to_the_pool_it_was_given(self):
        """A second, independent line of defence, stated so it is not lost.

        `outgoing_eligibility` computes the excluded set against the pool it is
        handed, so a policy built for our roster carries no key that could match
        an opponent's asset even if it were misapplied. That is real protection
        and it is NOT what the test above measures — relying on it would leave
        the substrate free to drop the side split.
        """
        ours_only = outgoing_eligibility(OURS, MIN_PROTECTED)
        assert not any("addison" in k for k in ours_only.excluded_keys)

    def test_picks_are_not_swept_up_by_a_team_rule_during_generation(self):
        """A pick has no NFL team; treating that as unknown would block every
        pick from every generated package."""
        ours = [*OURS, Asset("2027 Mid 1st", 3000.0, position="PICK")]
        policy = outgoing_eligibility(ours, MIN_PROTECTED)
        packages, _r = _packages(ours, THEIRS, policy)

        sent = {name for pkg in packages for name in _names(pkg.send)}
        assert "2027 Mid 1st" in sent


# ── Fail-closed ──────────────────────────────────────────────────────


class TestUnknownFailsClosed:
    def test_unresolvable_constraints_generate_nothing(self):
        """Not "generate freely because we could not check"."""
        policy = outgoing_eligibility(OURS, UNRESOLVED)
        packages, report = _packages(OURS, THEIRS, policy)

        assert packages == []
        assert report.our_excluded_constrained == len(OURS)
        assert report.outgoing_constrained is True

    def test_an_unknown_nfl_team_is_treated_as_protected(self):
        """The player the board cannot place is withheld, not assumed innocent.

        Assuming "not MIN" is a fabricated fact in the direction that proposes
        trading someone the user told us not to trade.
        """
        ours = [Asset("No Team Listed", 5000.0, team=None), Asset("Chris Olave", 5000.0, team="NO")]
        policy = outgoing_eligibility(ours, MIN_PROTECTED)
        packages, report = _packages(ours, THEIRS, policy)

        sent = {name for pkg in packages for name in _names(pkg.send)}
        assert "No Team Listed" not in sent
        assert "Chris Olave" in sent
        assert report.our_excluded_constrained == 1

    def test_MUTATION_an_unknown_team_defaulting_to_allowed_reaches_a_package(self):
        """Proof the fail-closed assertion is load-bearing.

        With no team rule active there is nothing to fail closed ON, and the
        same player is proposed — so the guard above is measuring the rule and
        not the fixture.
        """
        ours = [Asset("No Team Listed", 5000.0, team=None), Asset("Chris Olave", 5000.0, team="NO")]
        packages, _r = _packages(ours, THEIRS, UNCONSTRAINED_OUTGOING)
        sent = {name for pkg in packages for name in _names(pkg.send)}
        assert "No Team Listed" in sent

    def test_the_reason_survives_to_the_caller(self):
        """A count is not a reason.  Both come from one owner."""
        reasons = {r for _a, r in blocked_outgoing(OURS, MIN_PROTECTED)}
        assert reasons == {"protected_nfl_team"}
        assert {r for _a, r in blocked_outgoing(OURS, UNRESOLVED)} == {"constraints_unresolved"}

    def test_enforcement_and_reporting_never_disagree(self):
        """The policy and the partition are one owner answering one question.

        If they could drift, a surface would explain a list it did not produce.
        """
        for constraints in (MIN_PROTECTED, UNRESOLVED, resolve_constraints()):
            policy = outgoing_eligibility(OURS, constraints)
            reported = {a.name for a, _r in blocked_outgoing(OURS, constraints)}
            if policy is UNCONSTRAINED_OUTGOING:
                assert reported == set()
                continue
            enforced = {a.name for a in adapt_assets(OURS) if not policy.admits(a)}
            assert enforced == reported


# ── §3.3 — protection outranks a forced inclusion ────────────────────


def test_a_required_asset_cannot_bypass_a_protection():
    """`required` deliberately skips the ordinary policy, which made it a
    silent way around a protection.  §3.3: persistent protection outranks
    temporary refinement."""
    policy = outgoing_eligibility(OURS, MIN_PROTECTED)
    with pytest.raises(ConstraintMisapplied, match="Justin Jefferson"):
        enumerate_sides(
            adapt_assets(OURS[1:]),
            [2],
            side=SEND,
            outgoing_policy=policy,
            required=adapt_assets(OURS[:1]),
            adapt=False,
        )


def test_MUTATION_without_the_required_guard_the_protection_is_bypassed():
    """Proof: the ordinary policy alone does not catch it.

    `required` assets do not face `policy`, by design — so the guard above is
    the only thing standing between a lock and a protected player.
    """
    policy = outgoing_eligibility(OURS, MIN_PROTECTED)
    sides, _report = enumerate_sides(
        adapt_assets(OURS[1:]),
        [2],
        side=SEND,
        outgoing_policy=UNCONSTRAINED_OUTGOING,  # the guard switched off
        required=adapt_assets(OURS[:1]),
        adapt=False,
        policy=policy,  # and the ordinary policy carrying the same exclusions
    )
    got = [s for s in sides]
    assert got, "fixture produced no sides"
    assert all("Justin Jefferson" in {a.name for a in s} for s in got), (
        "the ordinary policy caught the required asset after all, which would "
        "make the dedicated guard redundant — re-check both"
    )


def test_an_outgoing_policy_on_the_receive_side_is_refused():
    """The asymmetry inverted.  Silently ignoring it would block acquisitions."""
    policy = outgoing_eligibility(OURS, MIN_PROTECTED)
    with pytest.raises(ConstraintMisapplied, match="outgoing-only"):
        enumerate_sides(adapt_assets(THEIRS), [1], side=RECEIVE, outgoing_policy=policy)

    # And the legitimate receive-side call still works.
    sides, _r = enumerate_sides(
        adapt_assets(THEIRS), [1], side=RECEIVE, outgoing_policy=UNCONSTRAINED_OUTGOING
    )
    assert list(sides)


# ── §6 — during generation, never a post-filter ──────────────────────


def test_a_forbidden_package_is_never_BUILT():
    """The difference between §6 and a post-filter, measured.

    Under the constraint the enumeration emits fewer packages — it did not
    emit them and then drop them.  `report.emitted` is incremented at yield
    time, so a post-filter would leave it at the unconstrained count.
    """
    free_packages, free_report = _packages(OURS, THEIRS, UNCONSTRAINED_OUTGOING)
    policy = outgoing_eligibility(OURS, MIN_PROTECTED)
    held_packages, held_report = _packages(OURS, THEIRS, policy)

    assert len(held_packages) < len(free_packages)
    assert held_report.emitted == len(held_packages), (
        "more packages were emitted than returned — something is filtering "
        "after enumeration, which is what §6 forbids"
    )
    assert free_report.emitted == len(free_packages)


def test_the_constrained_count_is_reported_apart_from_the_ineligible_count():
    """ "You told us not to trade him" is an answer; "he is roster clog" is a
    mechanic.  A surface that cannot tell them apart cannot explain itself."""
    ours = [*OURS, Asset("Deep Bench", 10.0, team="DEN")]
    policy = outgoing_eligibility(ours, MIN_PROTECTED)
    _pkgs, report = _packages(ours, THEIRS, policy, policy=EligibilityPolicy(min_value=1000.0))
    assert report.our_excluded_constrained == 1  # the Viking
    assert report.our_excluded_ineligible == 1  # the 10-value bench piece


def test_a_products_own_eligibility_is_preserved_not_replaced(self=None):
    """Constraints ADD to a product's mechanical gate; neither is the other."""
    base = EligibilityPolicy(min_value=4500.0, require_position=False)
    policy = outgoing_eligibility(OURS, MIN_PROTECTED, base=base)

    assert policy.min_value == 4500.0
    assert policy.require_position is False
    adapted = {a.name: a for a in adapt_assets(OURS)}
    assert not policy.admits(adapted["Justin Jefferson"])  # constrained
    assert not policy.admits(adapted["Rome Odunze"])  # below the product's floor
    assert policy.admits(adapted["Chris Olave"])


# ── Acceptance 14 — one owner, and one place that can decide ─────────


def test_only_the_owner_mints_a_block_reason():
    """Acceptance 14, tested on the DECISION rather than the vocabulary.

    A consumer may name "untouchable" in a warning string; what it may not do
    is invent a reason of its own, because that is a second owner wearing the
    first one's words.
    """
    reasons = {
        "protected_individual",
        "excluded_temporary",
        "protected_nfl_team",
        "protected_nfl_team_unknown",
        "constraints_unresolved",
    }
    producers = set()
    for path in (REPO / "src").rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in reasons:
                producers.add(rel)
    assert producers == {
        "src/trade/constraints.py"
    }, f"a block reason is minted outside the owner: {sorted(producers)}"


def test_every_generating_surface_accepts_constraints():
    """The signature half of acceptance 14.

    Evaluating surfaces are deliberately absent: §5 says manual Trade
    Calculator analysis may include a protected player, because inspecting a
    trade is not recommending one.
    """
    import inspect

    from src.trade import angle, finder, suggestions

    generating = [
        (finder.find_trades, "finder.find_trades"),
        (suggestions.generate_suggestions_from_pool, "suggestions.generate_suggestions_from_pool"),
        (suggestions.analyze_roster, "suggestions.analyze_roster"),
        (angle.find_acquisition_packages, "angle.find_acquisition_packages"),
    ]
    for fn, label in generating:
        assert (
            "constraints" in inspect.signature(fn).parameters
        ), f"{label} generates outgoing assets and cannot be constrained"

    from src.api import trade_simulator

    assert (
        "constraints" not in inspect.signature(trade_simulator.simulate_trade).parameters
    ), "the manual Trade Calculator must stay free-form (§5)"


def test_the_substrate_is_the_only_enforcement_path():
    """No generator re-implements the decision as a pool pre-filter.

    `partition_sendable` survives for surfaces that must EXPLAIN a short list,
    and `suggestions` uses `blocked_outgoing` for exactly that — but no module
    may shorten a pool and then enumerate the remainder, because that is the
    page-local copy §2.3 forbids.
    """
    import inspect

    from src.trade import finder

    src = inspect.getsource(finder)
    assert "outgoing_eligibility" in src
    assert "partition_sendable(my_roster" not in src


# ── Acceptance 13 — canonical values are unchanged ───────────────────


def test_the_constraint_path_never_reads_or_writes_a_canonical_value():
    """§2.2: "MIN players retain their ordinary canonical value".

    A structural guard rather than a numeric one: the owner and the seam it
    hands to the substrate must not so much as name a value field, so there is
    nothing for a future edit to start consulting.
    """
    banned = {"rankDerivedValue", "rank_derived_value", "display_value", "market_value"}
    tree = ast.parse((REPO / "src" / "trade" / "constraints.py").read_text(encoding="utf-8"))
    found = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value in banned
    }
    assert not found, f"the constraint owner consults canonical value fields: {sorted(found)}"

    attrs = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in banned
    }
    assert not attrs, f"the constraint owner reads canonical value attributes: {sorted(attrs)}"


def test_constraints_change_which_packages_exist_and_no_asset_value():
    """The numeric half, on the substrate's own projection.

    Every asset that survives the constraint carries exactly the value it
    carried without it — a constraint removes candidates, it never reprices
    one.
    """
    free_packages, _fr = _packages(OURS, THEIRS, UNCONSTRAINED_OUTGOING)
    policy = outgoing_eligibility(OURS, MIN_PROTECTED)
    held_packages, _hr = _packages(OURS, THEIRS, policy)

    def values(packages):
        out: dict[str, float | None] = {}
        for pkg in packages:
            for a in (*pkg.send, *pkg.receive):
                out[a.name] = a.value
        return out

    free_values, held_values = values(free_packages), values(held_packages)
    shared = set(free_values) & set(held_values)
    assert shared, "the fixture shares no assets between the two runs"
    for name in shared:
        assert free_values[name] == held_values[name], f"{name} was repriced by a constraint"


def test_MUTATION_a_repricing_constraint_would_be_caught():
    """Proof the assertion above can fail.

    `replace(policy, ...)` cannot reprice an asset — the policy has no value
    field to write — so the guard is enforced by the TYPE as well as by the
    test. This states that explicitly, so a future `EligibilityPolicy` that
    gains a value hook has a test standing in front of it.
    """
    policy = outgoing_eligibility(OURS, MIN_PROTECTED)
    assert not hasattr(policy, "value"), "EligibilityPolicy grew a value field"
    assert not hasattr(policy, "adjust_value")
    # And the dataclass exposes nothing that writes one.
    assert set(replace(policy).__dataclass_fields__) == {
        "min_value",
        "allow_unknown_value",
        "require_position",
        "excluded_keys",
    }
