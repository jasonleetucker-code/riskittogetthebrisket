"""An exact-string join between two sides that were never canonicalised.

Backlog defect #18. ``compute_team_strength`` indexed the ROS aggregate
by ``canonicalName`` and looked players up by whatever the roster block
carried — ``canonicalName or displayName or name``. Neither side is
reliably canonical:

* ``src/ros/aggregate.py`` copies each source parser's ``canonical_name``
  verbatim and never imports ``resolve_canonical_name``, so 16 of 1,087
  live aggregate rows are stored non-lowercase.
* the roster side falls back to display names, which never were.

Measured 2026-07-27 on the live 12-team snapshot: 36 roster players
unmapped, **8 of which map once both sides go through
``resolve_canonical_name``**.

That is not cosmetic. An unmapped player contributes ZERO to
``teamRosStrength``, which sets the projected reverse-standings draft
order behind the Pick Projector — so eight phantom zeroes were biasing
which team is projected to pick 1.01.

WHY NOT ``.lower()``
────────────────────
It would fix 14 of the 16 and silently leave two. "Greg Rousseau" ->
"gregory rousseau" and "Chig Okonkwo" -> "chigoziem okonkwo" need the
alias map. A casefold looks like it works, which is worse than not
working. ``test_the_fix_is_not_a_casefold`` pins that.

WHY NOT FIX THE WRITER
──────────────────────
``canonicalName`` doubles as a DISPLAY fallback —
``displayName or canonicalName`` in ``src/api/terminal.py`` and three
frontend modules. Normalising what is written would render
"cam skattebo" wherever ``displayName`` is absent. One field, two jobs,
two different normalisations; the join is the one that wants this.
"""

from __future__ import annotations

from src.ros.team_strength import compute_team_strength
from src.utils.name_clean import resolve_canonical_name

AGG = [
    # Stored exactly as the live aggregate stores them — mixed case, and
    # two that also need alias expansion.
    {"canonicalName": "Dax Hill", "position": "DB", "rosValue": 40.0},
    {"canonicalName": "Greg Rousseau", "position": "DL", "rosValue": 55.0},
    {"canonicalName": "Chig Okonkwo", "position": "TE", "rosValue": 30.0},
    {"canonicalName": "joe flacco", "position": "QB", "rosValue": 25.0},
]


def _team(names):
    return [
        {
            "rosterId": 1,
            "ownerId": "o1",
            "teamName": "Test",
            "players": [{"name": n, "position": "QB"} for n in names],
        }
    ]


def _rows(names):
    return compute_team_strength(
        _team(names),
        aggregated_players=AGG,
        starter_slots=["QB"],
    )


def test_the_fixture_reproduces_the_live_shape():
    """Non-vacuity: the aggregate side must genuinely be non-canonical,
    or an exact join would already work and this file proves nothing."""
    off = [
        p["canonicalName"]
        for p in AGG
        if p["canonicalName"] != resolve_canonical_name(p["canonicalName"])
    ]
    assert len(off) >= 3, f"fixture is already canonical ({off}); the bug cannot be shown"


def test_a_casing_only_mismatch_now_maps():
    """ "dax hill" against a stored "Dax Hill"."""
    rows = _rows(["dax hill"])
    assert rows[0]["unmappedPlayerCount"] == 0, rows[0]["unmappedPlayers"]


def test_the_fix_is_not_a_casefold():
    """The two the naive fix misses.

    ``.lower()`` maps "Greg Rousseau" to "greg rousseau", which is not
    what the aggregate resolves to. Only the alias map closes it.
    """
    for roster_name in ("greg rousseau", "chig okonkwo"):
        rows = _rows([roster_name])
        assert rows[0]["unmappedPlayerCount"] == 0, (
            f"{roster_name!r} still unmapped — a casefold would leave it that way, "
            "which is why the join resolves rather than lowercases"
        )


def test_an_already_canonical_name_still_maps():
    """Control. A fix that only handled the broken cases while breaking
    the working one would show up here and nowhere else."""
    rows = _rows(["joe flacco"])
    assert rows[0]["unmappedPlayerCount"] == 0


def test_a_genuinely_unranked_player_stays_unmapped():
    """The guard must not map everything.

    28 of the live 36 really are unranked by every ROS source, and that
    is the state ``unmapped`` exists to report. A join that resolved
    them into existence would be worse than the bug.
    """
    rows = _rows(["nobody at all"])
    assert rows[0]["unmappedPlayerCount"] == 1


def test_the_unmapped_list_keeps_the_readable_name():
    """It is rendered, so it wants the display form, not the join key."""
    rows = _rows(["Some Unranked Guy"])
    assert rows[0]["unmappedPlayers"] == ["Some Unranked Guy"]


def test_mapping_a_player_actually_raises_team_strength():
    """The point of the fix, stated as a number.

    If the recovered players mapped but contributed nothing, the join
    would be fixed and the defect — phantom zeroes biasing the projected
    draft order — would remain.
    """
    mapped = _rows(["dax hill", "greg rousseau"])[0]["teamRosStrength"]
    unmapped = _rows(["nobody at all", "also nobody"])[0]["teamRosStrength"]
    assert mapped > unmapped, "recovered players must contribute, not just stop being counted"
