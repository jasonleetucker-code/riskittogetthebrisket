"""C3-CON-01 — persistent protections reach the generators that skipped them.

Measured 2026-10-14 (trade-discovery audit): ``/api/gameplan?partner=`` built
packages with no constraints at all, ``/api/bdvm/trades`` ignored them, and
both angle acquire mode and the gameplan generator truncated the outgoing pool
BEFORE applying them — so protected players occupied the top slots and then
vanished, offering fewer assets than the cap (or none).
"""

from __future__ import annotations

from src.trade.constraints import resolve_constraints

# ── roster_intel packages (/api/gameplan?partner=) ────────────────────


def _all_sent(result):
    return {
        a["name"]
        for bucket in ("frontier", "rejected")
        for cand in result.get(bucket) or []
        for a in cand.get("send") or []
    }


def test_gameplan_packages_cap_after_constraints_not_before():
    from src.roster_intel.packages import generate_packages
    from tests.roster_intel.test_packages import SLOTS, _our_pool, _ours, _theirs

    # Our assets in value order: RB2 (5000) then BENCH1 (2000); cap at one.
    c = resolve_constraints(persistent={"untouchables": ["RB2"]})
    capped_first = generate_packages(
        _our_pool(), SLOTS, our_assets=_ours()[:1], their_assets=_theirs(), constraints=c
    )
    assert _all_sent(capped_first) == set(), "the old order offered nothing"

    fixed = generate_packages(
        _our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs(), constraints=c, our_limit=1
    )
    sent = _all_sent(fixed)
    assert "RB2" not in sent
    assert sent == {"BENCH1"}
    assert fixed["constraintsBlockedOutgoing"] == 1


def test_gameplan_packages_unconstrained_cap_is_unchanged():
    from src.roster_intel.packages import generate_packages
    from tests.roster_intel.test_packages import SLOTS, _our_pool, _ours, _theirs

    a = generate_packages(_our_pool(), SLOTS, our_assets=_ours()[:1], their_assets=_theirs())
    b = generate_packages(
        _our_pool(), SLOTS, our_assets=_ours(), their_assets=_theirs(), our_limit=1
    )
    assert a["frontier"] == b["frontier"] and a["rejected"] == b["rejected"]


# ── BDVM double-positive scan (/api/bdvm/trades) ──────────────────────


def _bdvm():
    from src.bdvm.roster import analyze_rosters
    from tests.bdvm.test_roster import PARAMS, build_fixture

    payload, contract, meta = build_fixture()
    return analyze_rosters(payload, contract, PARAMS, league_cfg_meta=meta), PARAMS


def test_bdvm_protects_only_the_requesters_giving_side():
    from src.bdvm.roster import scan_double_positive_trades

    analysis, params = _bdvm()
    base = scan_double_positive_trades(analysis, params, team="OldTeam")
    gives = {n for t in base["trades"] for n in t["from"]["gives"]}
    assert "Young Stash Wr" in gives, "fixture: the stash is offered when unprotected"

    c = resolve_constraints(persistent={"untouchables": ["Young Stash Wr", "Young Wr"]})
    guarded = scan_double_positive_trades(
        analysis, params, team="OldTeam", constraints=c, constrained_owner_id="1"
    )
    assert all("Young Stash Wr" not in t["from"]["gives"] for t in guarded["trades"])
    # A protected NAME on the other roster is still a valid acquisition target:
    # protection is the requester's outgoing rule, never a league-wide block.
    received = {n for t in guarded["trades"] for n in t["to"]["gives"]}
    base_received = {n for t in base["trades"] for n in t["to"]["gives"]}
    if "Young Wr" in base_received:
        assert "Young Wr" in received


def test_bdvm_league_wide_scan_fails_closed_without_an_owner():
    from src.bdvm.roster import scan_double_positive_trades

    analysis, params = _bdvm()
    c = resolve_constraints(persistent={"untouchables": ["Young Stash Wr"]})
    out = scan_double_positive_trades(analysis, params, constraints=c)
    assert out["trades"] == []
    assert out["noResultReason"] == "constraints_owner_unresolved"


def test_bdvm_without_constraints_is_unchanged():
    from src.bdvm.roster import scan_double_positive_trades

    analysis, params = _bdvm()
    a = scan_double_positive_trades(analysis, params)
    b = scan_double_positive_trades(analysis, params, constraints=None)
    assert a == b


# ── angle acquire: constraints before the candidate-pool cap ──────────


def _angle_rows():
    def _row(name, value, team="CIN", position="WR"):
        return {
            "canonicalName": name,
            "displayName": name,
            "position": position,
            "team": team,
            "rankDerivedValue": value,
            "canonicalSiteValues": {"ktc": value - 150},
        }

    rows = [_row(f"Top{i}", 4000 - 100 * i) for i in range(3)]
    rows += [_row(f"Mid{i}", 2600 - 40 * i) for i in range(4)]
    rows.append(_row("Target", 2500))
    teams = [
        {"name": "Mine", "ownerId": "me", "players": [r["canonicalName"] for r in rows[:7]]},
        {"name": "Them", "ownerId": "them", "players": ["Target"]},
    ]
    return rows, teams


def _acquire(constraints, candidate_pool=3):
    from src.trade.angle import find_acquisition_packages

    rows, teams = _angle_rows()
    return find_acquisition_packages(
        rows,
        ["Target"],
        "me",
        teams,
        min_my_gain_pct=-100,
        max_market_gain_pct=100,
        include_idp=True,
        candidate_pool=candidate_pool,
        constraints=constraints,
    )


def test_angle_acquire_fills_the_pool_with_sendable_assets():
    c = resolve_constraints(persistent={"untouchables": ["Top0", "Top1", "Top2"]})
    result = _acquire(c)
    assert result.get("noResultReason") != "all_outgoing_assets_constrained", result
    sent = {p["name"] for cand in result["candidates"] for p in cand["players"]}
    assert sent and not sent & {"Top0", "Top1", "Top2"}


def test_angle_acquire_lock_appears_in_every_candidate():
    c = resolve_constraints(refinement={"lock": ["Mid3"]})
    result = _acquire(c, candidate_pool=7)
    assert result["candidates"], result
    for cand in result["candidates"]:
        assert "Mid3" in {p["name"] for p in cand["players"]}


def test_angle_acquire_protected_lock_is_a_no_result():
    c = resolve_constraints(persistent={"untouchables": ["Mid3"]}, refinement={"lock": ["Mid3"]})
    result = _acquire(c, candidate_pool=7)
    assert result["candidates"] == []
    assert result["noResultReason"] == "lock_conflicts_with_protection"


def test_bdvm_never_constrains_a_named_team_that_is_not_the_requester():
    """Review B3: ``team=<other>`` must not put the requester's rules on that
    team; the requester (side B here) is the one constrained."""
    from src.bdvm.roster import scan_double_positive_trades

    analysis, params = _bdvm()
    base = scan_double_positive_trades(analysis, params, team="OldTeam")
    c = resolve_constraints(persistent={"untouchables": ["Young Stash Wr", "Young Wr"]})
    # Requester is YoungTeam (owner "2"): OldTeam's side is untouched...
    other = scan_double_positive_trades(
        analysis, params, team="OldTeam", constraints=c, constrained_owner_id="2"
    )
    old_gives = {n for t in other["trades"] for n in t["from"]["gives"]}
    assert old_gives == {n for t in base["trades"] for n in t["from"]["gives"]}
    # ...and YoungTeam never sends its protected player.
    assert all("Young Wr" not in t["to"]["gives"] for t in other["trades"])


def test_bdvm_named_team_without_a_resolved_requester_fails_closed():
    from src.bdvm.roster import scan_double_positive_trades

    analysis, params = _bdvm()
    c = resolve_constraints(persistent={"untouchables": ["Young Stash Wr"]})
    out = scan_double_positive_trades(analysis, params, team="OldTeam", constraints=c)
    assert out["trades"] == [] and out["noResultReason"] == "constraints_owner_unresolved"
