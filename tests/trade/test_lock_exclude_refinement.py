"""C3-CON-03 — temporary LOCK / EXCLUDE refinement, end to end.

Binding spec: ``docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md``
§3-§4, §6.  LOCK and EXCLUDE apply to OUTGOING players only, are mutually
exclusive, are applied DURING generation (never a post-filter), never become
permanent, and a lock that cannot be honoured is an honest no-result — never a
silently unlocked result.
"""

from __future__ import annotations

import pytest

from src.packages import (
    UNCONSTRAINED_OUTGOING,
    ConstraintMisapplied,
    EligibilityPolicy,
    PackageShape,
    enumerate_packages,
)
from src.trade.constraints import (
    MAX_REFINEMENT_ASSETS,
    outgoing_eligibility,
    resolve_constraints,
    resolve_locked_outgoing,
    validate_refinement,
)


class _A:
    """A minimal attribute asset, the shape the finder's pool uses."""

    def __init__(self, name, value, position="WR", team="", is_pick=False):
        self.name = name
        self.value = value
        self.position = "PICK" if is_pick else position
        self.team = team
        self.asset_id = ""

    def __repr__(self):  # pragma: no cover - debug aid
        return f"_A({self.name})"


def _pool(*names_values, position="WR"):
    return [_A(n, v, position=position) for n, v in names_values]


# ── validate_refinement ───────────────────────────────────────────────


def test_absent_refinement_is_empty_not_an_error():
    assert validate_refinement(None) == ({"lock": [], "exclude": []}, [])


def test_lock_and_exclude_on_the_same_player_is_refused_not_guessed():
    clean, errors = validate_refinement({"lock": ["Bob"], "exclude": ["bob "]})
    assert clean is None
    assert errors and errors[0]["reason"] == "refinement_conflict"


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("Bob", "not_an_object"),
        ({"lock": "Bob"}, "not_a_list"),
        ({"lock": [7]}, "not_a_string"),
        ({"exclude": ["x"] * (MAX_REFINEMENT_ASSETS + 1)}, "too_many"),
    ],
)
def test_malformed_refinement_is_refused(raw, reason):
    clean, errors = validate_refinement(raw)
    assert clean is None
    assert errors[0]["reason"] == reason


# ── resolve: a lock is never silently dropped ─────────────────────────


def test_a_lock_on_a_protected_player_is_a_recorded_conflict():
    c = resolve_constraints(persistent={"untouchables": ["Bob"]}, refinement={"lock": ["Bob"]})
    assert c.lock_conflicts == {"bob": "protected_individual"}
    res = resolve_locked_outgoing(_pool(("Bob", 5000), ("Al", 4000)), c)
    assert not res.satisfiable
    assert res.no_result_reason == "lock_conflicts_with_protection"


def test_a_lock_blocked_by_an_nfl_team_rule_is_a_conflict():
    """The team rule needs the pool to decide — resolve_constraints cannot see it."""
    c = resolve_constraints(persistent={"nflTeams": ["MIN"]}, refinement={"lock": ["Jj"]})
    res = resolve_locked_outgoing([_A("Jj", 9000, team="MIN"), _A("Al", 4000, team="CIN")], c)
    assert res.conflicts == (("jj", "protected_nfl_team"),)
    assert not res.satisfiable


def test_a_lock_on_a_player_not_on_the_roster_is_unavailable():
    c = resolve_constraints(refinement={"lock": ["Ghost"]})
    res = resolve_locked_outgoing(_pool(("Al", 4000)), c)
    assert res.missing == ("ghost",)
    assert res.no_result_reason == "locked_player_unavailable"


def test_a_satisfiable_lock_returns_the_callers_own_object():
    pool = _pool(("Al", 4000), ("Bob", 3000))
    c = resolve_constraints(refinement={"lock": ["bob"]})
    res = resolve_locked_outgoing(pool, c)
    assert res.satisfiable and res.required == (pool[1],)


def test_a_temporary_exclude_is_never_written_to_the_persistent_shape():
    """§3.3: refinement lives in the request; the persistent block is unchanged."""
    persistent = {"untouchables": ["Cee"], "nflTeams": []}
    c = resolve_constraints(persistent=persistent, refinement={"exclude": ["Bob"]})
    assert persistent == {"untouchables": ["Cee"], "nflTeams": []}
    assert c.excluded_outgoing == frozenset({"bob"})
    assert c.protected_outgoing == frozenset({"cee"})


# ── substrate: required_send ──────────────────────────────────────────

_POLICY = EligibilityPolicy(min_value=0, allow_unknown_value=False, require_position=False)


def _pairs(ours, theirs, **kw):
    it, report = enumerate_packages(ours, theirs, policy=_POLICY, **kw)
    return list(it), report


def test_required_send_appears_in_every_package_and_skips_small_shapes():
    ours = _pool(("Al", 5000), ("Bob", 4000), ("Cee", 3000))
    theirs = _pool(("Xa", 5000), ("Yb", 4000), ("Zc", 3000))
    pairs, report = _pairs(
        ours,
        theirs,
        outgoing_policy=UNCONSTRAINED_OUTGOING,
        shapes=[PackageShape(1, 1), PackageShape(2, 2)],
        required_send=[ours[1], ours[2]],
    )
    assert pairs
    for pair in pairs:
        assert {a.name for a in pair.send} == {"Bob", "Cee"}
    assert report.shapes_skipped_for_required == ["1-for-1"]
    assert report.to_dict()["requiredSend"] == 2


def test_required_send_default_is_byte_identical():
    ours = _pool(("Al", 5000), ("Bob", 4000))
    theirs = _pool(("Xa", 5000), ("Yb", 4000))
    a, ra = _pairs(ours, theirs, outgoing_policy=UNCONSTRAINED_OUTGOING)
    b, rb = _pairs(ours, theirs, outgoing_policy=UNCONSTRAINED_OUTGOING, required_send=())
    assert [p.key for p in a] == [p.key for p in b]
    assert ra.to_dict() == rb.to_dict()
    assert "requiredSend" not in ra.to_dict()


def test_required_send_cannot_force_a_constrained_asset():
    ours = _pool(("Al", 5000), ("Bob", 4000))
    c = resolve_constraints(persistent={"untouchables": ["Bob"]})
    with pytest.raises(ConstraintMisapplied):
        _pairs(
            ours,
            _pool(("Xa", 5000)),
            outgoing_policy=outgoing_eligibility(ours, c),
            required_send=[ours[1]],
        )


def test_a_lock_never_licenses_a_topology_violation():
    """Locking two players cannot produce a 2-for-0-ish lopsided 3-for-1."""
    ours = _pool(("Al", 5000), ("Bob", 4000), ("Cee", 3000))
    theirs = _pool(("Xa", 9000))
    pairs, report = _pairs(
        ours,
        theirs,
        outgoing_policy=UNCONSTRAINED_OUTGOING,
        shapes=[PackageShape(3, 1)],
        required_send=[ours[0], ours[1]],
    )
    assert pairs == []
    assert report.topology_rejected > 0


# ── finder: lock survives regeneration, protected lock -> no-result ───


def _finder_fixture():
    # Our board undervalues what we hold relative to the market and overvalues
    # theirs, so packages are a board win for us and a market win for them —
    # the finder's arbitrage gate passes and real candidates come back.
    players = {}
    mine = [("Al", 6000), ("Bob", 5000), ("Cee", 4000), ("Dee", 3500)]
    theirs = [("Xa", 6900), ("Yb", 5800), ("Zc", 4700), ("Wd", 4100)]
    market = {n: v + 800 for n, v in mine} | {n: v - 800 for n, v in theirs}
    for name, value in mine + theirs:
        players[name] = {
            "_finalAdjusted": value,
            "ktcCrowdTradesSfTep": market[name],
            "position": "WR",
        }
    teams = [
        {"name": "Me", "ownerId": "1", "players": [n for n, _ in mine]},
        {"name": "Them", "ownerId": "2", "players": [n for n, _ in theirs]},
    ]
    contract = {
        "playersArray": [
            {
                "displayName": n,
                "canonicalName": n,
                "position": "WR",
                "rankDerivedValue": v,
                "assetClass": "player",
            }
            for n, v in mine + theirs
        ]
    }
    return players, teams, contract


def test_finder_every_trade_sends_the_locked_player():
    from src.trade.finder import find_trades

    players, teams, contract = _finder_fixture()
    c = resolve_constraints(contract=contract, refinement={"lock": ["Cee"]})
    result = find_trades(
        players, "Me", ["Them"], teams, contract=contract, constraints=c, use_team_context=False
    )
    trades = result["trades"]
    assert trades, result
    for t in trades:
        assert "Cee" in {a["name"] for a in t["give"]}, t
    assert result["metadata"]["lockedOutgoing"]["required"] == ["Cee"]


def test_finder_a_protected_lock_is_an_honest_no_result():
    from src.trade.finder import find_trades

    players, teams, contract = _finder_fixture()
    c = resolve_constraints(
        contract=contract,
        persistent={"untouchables": ["Cee"]},
        refinement={"lock": ["Cee"]},
    )
    result = find_trades(
        players, "Me", ["Them"], teams, contract=contract, constraints=c, use_team_context=False
    )
    assert result["trades"] == []
    assert result["metadata"]["noResultReason"] == "lock_conflicts_with_protection"
    assert "under current constraints" in result["metadata"]["noResultLabel"]


def test_finder_exclude_removes_the_player_from_outgoing_only():
    from src.trade.finder import find_trades

    players, teams, contract = _finder_fixture()
    c = resolve_constraints(contract=contract, refinement={"exclude": ["Al"]})
    result = find_trades(
        players, "Me", ["Them"], teams, contract=contract, constraints=c, use_team_context=False
    )
    assert result["trades"], result
    for t in result["trades"]:
        assert "Al" not in {a["name"] for a in t["give"]}


def test_finder_skip_targets_touches_the_incoming_side_only():
    from src.trade.finder import ARBITRAGE_CONTROL_KEY, find_trades

    players, teams, contract = _finder_fixture()
    result = find_trades(
        players,
        "Me",
        ["Them", {ARBITRAGE_CONTROL_KEY: {"skipTargets": ["Xa"]}}],
        teams,
        contract=contract,
        use_team_context=False,
    )
    assert result["trades"], result
    for t in result["trades"]:
        assert "Xa" not in {a["name"] for a in t["receive"]}
    assert result["metadata"]["skipTargets"] == ["xa"]
