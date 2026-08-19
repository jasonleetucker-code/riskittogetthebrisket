"""Adversarial identity for the board→pool join (F6).

Integration's finding 9: ``_board_players`` keys each row by
``canonicalName`` only, taking the FIRST of ``canonicalName`` /
``displayName``, while ``_ages`` and ``_nfl_teams`` key by BOTH.  The
pool, meanwhile, is keyed by whatever string ``sleeper.teams[].players``
carries, and ``contract_roster_pools`` matches that against either name.

So a player whose roster entry matches only on ``displayName`` gets an
age and an NFL team but **no positional rank** — silently, behind a
fully shaped payload.  That is the exact failure mode #914 already hit
once (playerId vs name) and pinned by asserting the downstream
consequence; this is the same class, one field over.

0 of 660 live names hit it.  These fixtures make it hit.
"""

from __future__ import annotations

from src.api import roster_intelligence as ri

_SLOTS = ["QB", "RB", "WR", "TE", "FLEX"]


def _contract(roster, rows, positions=None):
    return {
        "meta": {"leagueKey": "k"},
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": list(_SLOTS) + ["BN"],
            "positions": positions or {n: "QB" if "QB" in n else "WR" for n in roster},
            "teams": [{"ownerId": "o1", "name": "T", "players": list(roster)}],
        },
    }


def _row(canonical, display, pos, value, **extra):
    return {
        "playerId": f"id_{canonical}",
        "canonicalName": canonical,
        "displayName": display,
        "position": pos,
        "rankDerivedValue": value,
        **extra,
    }


def _team(contract):
    out = ri.build_league_roster_intelligence(contract, team_count=12)
    return out["teams"]["o1"]


# ══ The alias case — RED before the fix ════════════════════════════


def test_a_roster_entry_matching_only_the_display_name_still_gets_a_rank():
    """The roster says "A. Jones"; the board's canonicalName is "Aaron
    Jones" and only its displayName matches. The pool keys the player by
    the roster string, so the rank lookup must use that same string."""
    contract = _contract(
        ["A. Jones", "QB Guy"],
        [
            _row("Aaron Jones", "A. Jones", "RB", 900.0, age=25.0, team="GB"),
            _row("QB Guy", "QB Guy", "QB", 800.0, age=27.0, team="KC"),
        ],
        positions={"A. Jones": "RB", "QB Guy": "QB"},
    )
    team = _team(contract)

    # He is in the core…
    assert "A. Jones" in {m["playerId"] for m in team["core"]["members"]}
    # …and his rung is MEASURED, not UNKNOWN.
    rb = next((n for n in team["weakness"]["needs"] if n["position"] == "RB"), None)
    assert rb is not None
    assert any(r["status"] != "unknown" for r in rb["rungs"]), rb

    # And the age/NFL-team joins, which already keyed by both names,
    # agree with it rather than being the only two that landed.
    assert team["agePortfolio"]["valueWeightedCoreAge"] is not None
    assert team["nflExposure"]["core"]["buckets"], team["nflExposure"]["core"]


def test_the_three_board_joins_key_the_same_way():
    """Structural-ish: whatever key set the age and NFL-team joins use,
    the rank join must use it too. They disagreed by construction."""
    contract = _contract(
        ["A. Jones"],
        [_row("Aaron Jones", "A. Jones", "RB", 900.0, age=25.0, team="GB")],
        positions={"A. Jones": "RB"},
    )
    rank_keys = {k for k, _pos, _v in ri._board_players(contract, pool_keys={"A. Jones"})}
    assert "A. Jones" in rank_keys
    assert "A. Jones" in set(ri._ages(contract))
    assert "A. Jones" in set(ri._nfl_teams(contract))


# ══ No silent fallback that invents a plausible-but-wrong roster ═══


def test_one_board_row_never_becomes_two_ranked_players():
    """The naive repair — emit a row per name, like the age join does —
    would double the ranked population for every player whose two names
    differ, inflating "top 12 QB" and giving one player two ranks."""
    contract = _contract(
        ["A. Jones"],
        [_row("Aaron Jones", "A. Jones", "RB", 900.0)],
        positions={"A. Jones": "RB"},
    )
    rows = ri._board_players(contract, pool_keys={"A. Jones"})
    assert len(rows) == 1, rows
    assert rows[0][0] == "A. Jones"


def test_a_row_matching_no_roster_entry_keeps_its_canonical_name():
    """Unrostered board rows are the rank POPULATION — they must still be
    counted, under a stable key, or every threshold shrinks."""
    contract = _contract(
        ["QB Guy"],
        [
            _row("QB Guy", "QB Guy", "QB", 800.0),
            _row("Free Agent", "F. Agent", "QB", 700.0),
        ],
        positions={"QB Guy": "QB"},
    )
    keys = {k for k, _p, _v in ri._board_players(contract, pool_keys={"QB Guy"})}
    assert keys == {"QB Guy", "Free Agent"}


def test_a_player_id_is_never_used_as_the_rank_key():
    """#914's original bug, kept pinned: ids look like valid keys and
    match nothing the pool holds."""
    contract = _contract(
        ["QB Guy"], [_row("QB Guy", "QB Guy", "QB", 800.0)], positions={"QB Guy": "QB"}
    )
    keys = {k for k, _p, _v in ri._board_players(contract, pool_keys={"QB Guy"})}
    assert not any(k.startswith("id_") for k in keys)


# ══ Missing / duplicate / orphan ═══════════════════════════════════


def test_a_board_row_with_no_names_at_all_is_dropped_not_keyed_by_id():
    contract = _contract(
        ["QB Guy"],
        [
            _row("QB Guy", "QB Guy", "QB", 800.0),
            {"playerId": "id_ghost", "position": "QB", "rankDerivedValue": 500.0},
        ],
        positions={"QB Guy": "QB"},
    )
    keys = {k for k, _p, _v in ri._board_players(contract, pool_keys={"QB Guy"})}
    assert keys == {"QB Guy"}


def test_duplicate_board_rows_for_one_name_do_not_double_the_population():
    """A duplicated row would give one player two ranks and shift every
    threshold below him."""
    contract = _contract(
        ["QB Guy"],
        [
            _row("QB Guy", "QB Guy", "QB", 800.0),
            _row("QB Guy", "QB Guy", "QB", 795.0),
        ],
        positions={"QB Guy": "QB"},
    )
    rows = ri._board_players(contract, pool_keys={"QB Guy"})
    assert [k for k, _p, _v in rows].count("QB Guy") == 1


def test_an_orphan_roster_still_resolves_its_own_players():
    """Ties F6 to the ownerId repair: a team with no ownerId keys
    positionally, and its players must still join to the board."""
    contract = _contract(
        ["QB Guy"],
        [_row("QB Guy", "QB Guy", "QB", 800.0, age=26.0, team="KC")],
        positions={"QB Guy": "QB"},
    )
    contract["sleeper"]["teams"] = [
        {"ownerId": "", "name": "Orphan A", "players": ["QB Guy"]},
        {"ownerId": "", "name": "Orphan B", "players": []},
    ]
    out = ri.build_league_roster_intelligence(contract, team_count=12)
    assert len(out["teams"]) == 2
    holder = next(t for t in out["teams"].values() if t["rosteredCount"] == 1)
    assert {m["playerId"] for m in holder["core"]["members"]} == {"QB Guy"}


def test_no_pool_keys_supplied_falls_back_to_canonical_name():
    """The signature stays usable without the pool — and the fallback is
    the CANONICAL name, which is stable, not the first name that parses."""
    contract = _contract(
        ["Aaron Jones"],
        [_row("Aaron Jones", "A. Jones", "RB", 900.0)],
        positions={"Aaron Jones": "RB"},
    )
    keys = {k for k, _p, _v in ri._board_players(contract)}
    assert keys == {"Aaron Jones"}
