"""One team, one pool — even when Sleeper gives it no owner.

Integration found this and it is a REGRESSION, not inherited debt: the
extraction of ``contract_roster_pools`` out of ``stamp_optimal_lineups``
changed *where* a roster pool is built, and in doing so changed *what
identifies* it.  Inside the old loop the pool came from ``team["players"]``
per team, by construction.  Extracted, it is looked up by key — and the key
was ``ownerId``.

``ownerId`` is not an identity.  ``Dynasty Scraper.py:1094`` writes
``str(owner_id) if owner_id else ""`` with a comment about orphaned rosters
three lines above, and ``sleeper_overlay`` writes ``str(r.get("owner_id") or
"")``.  Sleeper's ``owner_id: null`` — an unclaimed or orphaned roster —
therefore arrives as ``""`` for EVERY such team, and a dict keyed on that keeps
only the last.  The survivor's roster is then published as the others'
``optimalLineup`` stamped ``available: true``: a chimera presented as fact,
which is worse than a refusal.

Zero of 177 tracked archives carry a duplicate or empty ``ownerId``, so this is
latent rather than firing — but it is a league state Sleeper genuinely supports
and the scraper explicitly anticipates, and the collision sits on the normal
serving path (``server.py`` re-stamps over overlay-rebuilt teams on every
``/api/data``).

**RED-first, and deliberately only half red.**  Of the four contract-level
cases, the two COLLISION cases fail against the unpatched branch and the two
IDENTITY cases pass — because the latter pin behaviour that was already correct
and must stay so.  A file that went fully red would not have distinguished "the
fix works" from "the fix changed everything", and the identity of an owned team
is precisely what must not change: roster intelligence publishes this key as
``ownerId`` and resolves ``?team=`` by it.

The three tests below the contract cases exercise ``roster_pool_key`` directly
and are green either way; they pin the properties the reconciliation named
(purity, no mutation) rather than the defect.
"""

from __future__ import annotations

from src.api.data_contract import contract_roster_pools, roster_pool_key, stamp_optimal_lineups

_SLOTS = ["QB", "RB", "WR"]


def _row(name, pos, value):
    return {
        "playerId": f"id_{name}",
        "canonicalName": name,
        "displayName": name,
        "position": pos,
        "rankDerivedValue": value,
    }


def _contract(teams):
    names = [n for t in teams for n in (t.get("players") or [])]
    return {
        "meta": {"leagueKey": "k"},
        "playersArray": [_row(n, ("QB", "RB", "WR")[i % 3], 900 - i) for i, n in enumerate(names)],
        "sleeper": {
            "rosterPositions": list(_SLOTS) + ["BN"],
            "positions": {n: ("QB", "RB", "WR")[i % 3] for i, n in enumerate(names)},
            "teams": teams,
        },
    }


# ══ Collision cases — RED without the fix (2 of the 4) ═════════════


def test_two_orphan_rosters_get_one_pool_each_not_a_shared_one():
    """Sleeper's ``owner_id: null`` reaches the contract as ``""``. Two of
    them are two teams, not one.

    A non-dict entry sits between them deliberately. This is the ONLY
    situation where a positional key exists at all, so it is the only
    place the verifier's care point can bite: ``contract_roster_pools``
    skips non-dict entries inside its loop while ``stamp_optimal_lineups``
    passes them through, and an index taken AFTER the skip would shift
    every later team by one — trading one silent misattribution for
    another. Testing the desync anywhere else would test nothing.
    """
    contract = _contract(
        [
            {"ownerId": "", "name": "Orphan A", "players": ["A1", "A2"]},
            {"ownerId": "", "name": "Orphan B", "players": ["B1", "B2"]},
            {"ownerId": "u9", "name": "Owned", "players": ["C1"]},
        ]
    )
    contract["sleeper"]["teams"].insert(1, "not-a-team")

    pools, _slots, _src = contract_roster_pools(contract)
    assert len(pools) == 3, sorted(pools)
    rosters = sorted(sorted(p.player_id for p in pool) for pool in pools.values())
    assert rosters == [["A1", "A2"], ["B1", "B2"], ["C1"]]

    # …and the stamp each team actually receives is its own roster, which is
    # the surface the chimera reached: `available: true` over someone else's
    # players is worse than a refusal.
    stamp_optimal_lineups(contract)
    stamped = [t for t in contract["sleeper"]["teams"] if isinstance(t, dict)]
    starters = {t["name"]: sorted(t["optimalLineup"]["starters"]) for t in stamped}
    assert starters["Orphan A"] == ["A1", "A2"]
    assert starters["Orphan B"] == ["B1", "B2"]
    assert starters["Owned"] == ["C1"]


def test_a_duplicated_non_empty_owner_id_also_does_not_merge_two_rosters():
    """An ambiguous ownerId is no more an identity than an absent one, and
    a rule that only special-cases the empty string would still merge
    these two."""
    contract = _contract(
        [
            {"ownerId": "dup", "name": "One", "players": ["A1"]},
            {"ownerId": "dup", "name": "Two", "players": ["B1"]},
        ]
    )
    pools, _slots, _src = contract_roster_pools(contract)
    assert len(pools) == 2
    assert sorted(sorted(p.player_id for p in v) for v in pools.values()) == [["A1"], ["B1"]]


# ══ Identity cases — GREEN before and after (2 of the 4) ═══════════


def test_a_distinct_owner_id_is_still_the_key_verbatim():
    """THE compatibility constraint. Roster intelligence publishes this key
    as ``ownerId`` and resolves ``?team=`` by it, so an owned team's key
    must not change — every real league is this case."""
    contract = _contract(
        [
            {"ownerId": "u1", "name": "One", "players": ["A1"]},
            {"ownerId": "u2", "name": "Two", "players": ["B1"]},
        ]
    )
    pools, _slots, _src = contract_roster_pools(contract)
    assert sorted(pools) == ["u1", "u2"]
    assert [p.player_id for p in pools["u1"]] == ["A1"]


def test_a_non_dict_entry_between_real_teams_does_not_shift_the_others():
    """GREEN before and after, and that is the point: with every ownerId
    distinct no positional key is ever minted, so a malformed entry in the
    list must not disturb the owned teams around it either way."""
    contract = _contract(
        [
            {"ownerId": "u1", "name": "One", "players": ["A1"]},
            {"ownerId": "u2", "name": "Two", "players": ["B1"]},
        ]
    )
    contract["sleeper"]["teams"].insert(1, "not-a-team")

    pools, _slots, _src = contract_roster_pools(contract)
    assert sorted(pools) == ["u1", "u2"]

    stamp_optimal_lineups(contract)
    stamped = [t for t in contract["sleeper"]["teams"] if isinstance(t, dict)]
    starters = {t["name"]: sorted(t["optimalLineup"]["starters"]) for t in stamped}
    assert starters == {"One": ["A1"], "Two": ["B1"]}


# ══ The key function itself ════════════════════════════════════════


def test_the_key_is_pure_in_its_arguments():
    """Pure in ``(teams, index, team)`` is what lets the builder and every
    consumer derive the same key from the same list without threading
    state — so the same inputs must always give the same answer, and it
    must read nothing else."""
    teams = [{"ownerId": "u1"}, {"ownerId": ""}, {"ownerId": ""}]
    first = [roster_pool_key(teams, i, t) for i, t in enumerate(teams)]
    assert first == [roster_pool_key(teams, i, t) for i, t in enumerate(teams)]
    assert first[0] == "u1"
    assert first[1] != first[2]
    assert teams == [{"ownerId": "u1"}, {"ownerId": ""}, {"ownerId": ""}]  # no mutation


def test_a_whitespace_only_owner_id_is_treated_as_absent():
    teams = [{"ownerId": "  "}, {"ownerId": "\t"}]
    keys = [roster_pool_key(teams, i, t) for i, t in enumerate(teams)]
    assert len(set(keys)) == 2
    assert all(not k.strip().isalnum() or k.startswith("__roster_") for k in keys)


def test_a_non_dict_team_still_gets_a_unique_positional_key():
    teams = ["junk", {"ownerId": "u1"}, None]
    assert roster_pool_key(teams, 0, "junk") == "__roster_0"
    assert roster_pool_key(teams, 2, None) == "__roster_2"
    assert roster_pool_key(teams, 1, teams[1]) == "u1"
