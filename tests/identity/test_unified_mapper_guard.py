"""``unified_mapper.resolve_player`` — what it is allowed to accept.

Fed the 544 source-CSV names that FAILED the production canonical-name
join, plus a directory built from the live board, the ladder returned a
match for **11** of them at its default 0.85 threshold — every one a
different human, each reported at 0.857-0.923 with
``match_method='fuzzy_name'``, a method the docstring caps at 0.90
(audit W06-F006).  Separately, two players sharing a name resolved by
dict insertion order at confidence 1.00 while the caller's ``team`` was
ignored.

The guard is structural, not a threshold tweak: a fuzzy accept now
requires the same surname AND a compatible first name, both anchored on
the same initial letter — which is what separates a typo from a
different name.
"""

from __future__ import annotations

import pytest

from src.identity import unified_mapper


@pytest.fixture(autouse=True)
def _reset():
    unified_mapper.reset_metrics()
    unified_mapper.reload_overrides()
    yield
    unified_mapper.reset_metrics()
    unified_mapper.reload_overrides()


def _dir(*entries):
    return {
        e["player_id"]: e
        for e in (
            {
                "player_id": str(i),
                "full_name": name,
                "position": pos,
                "team": team,
                "gsis_id": f"00-000{i:04d}",
                "espn_id": str(1000 + i),
            }
            for i, (name, pos, team) in enumerate(entries, start=1)
        )
    }


# The eleven pairs measured on the live corpus: (query, directory row).
_FALSE_MERGES = [
    ("Tevin Coleman", "Kevin Coleman", "WR"),
    ("Ian Thomas", "Brian Thomas", "WR"),
    ("Eric Gray", "Cedric Gray", "LB"),
    ("Ty Montgomery", "Tyren Montgomery", "WR"),
    ("Mike Williams", "Mykel Williams", "DL"),
    ("Cedrick Wilson", "Eric Wilson", "LB"),
    ("Jordan Travis", "Jordan Davis", "DL"),
    ("Jacob Harris", "Jacob Parrish", "DB"),
    ("Amari Cooper", "Omar Cooper", "WR"),
    ("Jordan Wilkins", "Jordan Watkins", "WR"),
    ("Cedrick Wilson Jr.", "Eric Wilson", "LB"),
]


@pytest.mark.parametrize("query,directory_name,pos", _FALSE_MERGES)
def test_the_eleven_false_merges_are_refused(query, directory_name, pos):
    directory = _dir((directory_name, pos, "AAA"))
    got = unified_mapper.resolve_player(directory, name=query, position=pos)
    assert got is None, f"{query} was merged into {directory_name}"


def test_a_single_character_typo_still_resolves():
    """What fuzzy is FOR.  Same initial, same surname, one slipped key."""
    directory = _dir(("Michael Thomas", "WR", "NO"))
    got = unified_mapper.resolve_player(directory, name="Micheal Thomas", position="WR")
    assert got is not None
    assert got.full_name == "Michael Thomas"
    assert got.match_method == "fuzzy_name"


def test_a_fuzzy_match_never_outranks_a_verified_one():
    """The ladder documents fuzzy as 0.75-0.90.  It used to report the
    raw difflib ratio, so a guess could claim 0.98 — above the rung that
    checked name AND team AND position."""
    directory = _dir(("Michael Thomas", "WR", "NO"))
    got = unified_mapper.resolve_player(directory, name="Micheal Thomas", position="WR")
    assert got is not None
    assert got.confidence <= 0.90


def test_team_is_consulted_between_name_pos_and_name_only():
    """Two Josh Allens.  The caller supplied a team and the ladder
    ignored it, so the answer came back at confidence 1.00 and flipped
    with dict insertion order."""
    directory = _dir(("Josh Allen", "QB", "BUF"), ("Josh Allen", "LB", "JAX"))
    got = unified_mapper.resolve_player(directory, name="Josh Allen", team="JAX")
    assert got is not None
    assert got.team == "JAX"
    assert got.match_method == "name_team"
    reversed_dir = {k: directory[k] for k in reversed(list(directory))}
    again = unified_mapper.resolve_player(reversed_dir, name="Josh Allen", team="JAX")
    assert again is not None
    assert again.team == "JAX"


def test_an_undisambiguated_homonym_refuses():
    """No team, no position, two candidates: any answer is a coin flip
    on dict order, so there is no answer."""
    directory = _dir(("Josh Allen", "QB", "BUF"), ("Josh Allen", "LB", "JAX"))
    assert unified_mapper.resolve_player(directory, name="Josh Allen") is None
    assert unified_mapper.resolve_player(directory, name="Josh Allen", team="KC") is None


def test_the_manual_override_beats_the_directory_it_exists_to_override(tmp_path):
    """The override rung sat BELOW the exact-sleeper-id rung, so it only
    fired for ids the directory did not know — while every documented
    use case ("same name, different player") is an id the directory DOES
    know.  The layer was unreachable for its stated purpose."""
    overrides = tmp_path / "ov.json"
    overrides.write_text(
        '{"999": {"gsis_id": "00-9999999", "espn_id": "123",'
        ' "full_name": "OVERRIDE NAME", "position": "WR", "team": "ZZZ"}}',
        encoding="utf-8",
    )
    directory = {
        "999": {
            "player_id": "999",
            "gsis_id": "00-0000001",
            "full_name": "DIRECTORY NAME",
            "position": "RB",
            "team": "AAA",
        }
    }
    got = unified_mapper.resolve_player(directory, sleeper_id="999", overrides_path=overrides)
    assert got is not None
    assert got.match_method == "manual_override"
    assert got.gsis_id == "00-9999999"


def test_documentation_keys_are_not_loaded_as_overrides(tmp_path):
    """``config/identity/id_overrides.json`` ships ``_comment`` and
    ``_example_entry_only``; the latter was loaded as a live override
    whose gsis id is 00-0000000."""
    overrides = tmp_path / "ov.json"
    overrides.write_text(
        '{"_comment": "docs", "_example_entry_only":'
        ' {"gsis_id": "00-0000000", "full_name": "Example Player"}}',
        encoding="utf-8",
    )
    unified_mapper.reload_overrides()
    loaded = unified_mapper._load_overrides(overrides)
    assert loaded == {}


def test_resolve_many_indexes_the_directory_once(monkeypatch):
    """``_index_directory`` sat inside ``resolve_player`` and
    ``resolve_many`` looped it: 200 inputs against an 11k directory took
    14.6s, 99.5% of it rebuilding the same index 199 times, against a
    docstring promising "the index is built once, not per-row"."""
    calls = {"n": 0}
    real = unified_mapper._index_directory

    def counting(players_dir):
        calls["n"] += 1
        return real(players_dir)

    monkeypatch.setattr(unified_mapper, "_index_directory", counting)
    directory = _dir(*[(f"Player{i} Surname{i}", "WR", "AAA") for i in range(1, 51)])
    inputs = [{"sleeper_id": str(i)} for i in range(1, 41)]
    resolved, unresolved = unified_mapper.resolve_many(directory, inputs)
    assert len(resolved) == 40
    assert unresolved == []
    assert calls["n"] == 1


def test_the_nickname_class_resolves_through_the_curated_table_not_a_guess():
    """"Kenny"/"Kenneth" is structurally identical to "Ty"/"Tyren" — a
    short form of a first name, same surname — and one of those pairs is
    two different people.  No name-similarity rule can separate them, so
    the fuzzy rung refuses both and the nickname class resolves the way
    the rest of the pipeline resolves it: through the human-maintained
    ``CANONICAL_NAME_ALIASES`` table, as an EXACT match.
    """
    directory = _dir(("Kenny Gainwell", "RB", "TB"), ("Tyren Montgomery", "WR", "AAA"))
    got = unified_mapper.resolve_player(directory, name="Kenneth Gainwell", position="RB")
    assert got is not None
    assert got.full_name == "Kenny Gainwell"
    assert got.match_method != "fuzzy_name"
    assert unified_mapper.resolve_player(directory, name="Ty Montgomery", position="WR") is None
