"""Published identity fields: position family, team evidence, CSV header tokens.

The position-family table is REGISTERED (V2.1 preregistration §3.2 R4) and these
tests pin it so a tuning edit is a visible, deliberate change.  The central rule
is that every helper abstains on a field it cannot read - missing is never a
mismatch, and similar names / positions are never merged.
"""

from __future__ import annotations

import pytest

from src.identity import published_fields as pf


def test_the_registered_family_table_is_frozen():
    assert {k: sorted(v) for k, v in pf.POSITION_FAMILIES.items()} == {
        "QB": ["QB"],
        "RB": ["FB", "HB", "RB"],
        "WR": ["WR"],
        "TE": ["TE"],
        "K": ["K", "PK"],
        "DL": ["DE", "DL", "DT", "EDGE", "IDL", "NT"],
        "LB": ["EDGE", "ILB", "LB", "MLB", "OLB"],
        "DB": ["CB", "DB", "FS", "S", "SS"],
    }
    assert pf.ALLOWED_DRIFT == frozenset(
        {frozenset({"DL", "LB"}), frozenset({"LB", "DB"}), frozenset({"RB", "FB"})}
    )


@pytest.mark.parametrize("raw", [None, "", "  ", "OL", "WR12", "NA", "?"])
def test_unknown_or_blank_position_is_no_family_never_a_mismatch(raw):
    assert pf.position_families(raw) == frozenset()
    assert pf.families_compatible(raw, ["WR"]) is None
    assert pf.families_compatible("WR", [raw]) is None


@pytest.mark.parametrize(
    ("entry", "row", "expected"),
    [
        ("wr", ["WR"], True),  # case-insensitive, otherwise verbatim
        ("DE", ["DL"], True),
        ("EDGE", ["LB"], True),  # EDGE sits in both DL and LB
        ("EDGE", ["DL"], True),
        ("DL", ["LB"], True),  # allowed drift
        ("LB", ["S"], True),  # allowed drift LB <-> DB
        ("RB", ["FB"], True),
        ("QB", ["WR"], False),
        ("WR", ["TE"], False),  # similar roles are NOT merged
        ("DL", ["DB"], False),  # DL <-> DB is not an allowed drift
        ("TE", ["WR", "RB"], False),
    ],
)
def test_family_compatibility(entry, row, expected):
    assert pf.families_compatible(entry, row) is expected


def test_two_way_alt_positions_extend_the_row_families():
    assert pf.families_compatible("WR", ["DB"]) is False
    assert pf.families_compatible("WR", ["DB"], alt_positions=["WR"]) is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("det", "DET"),
        (" DET ", "DET"),
        ("GBP", "GB"),  # scraper long forms fold
        ("KCC", "KC"),
        ("NEP", "NE"),
        ("TBB", "TB"),
        ("FA", None),  # a free agent is not evidence of a team
        ("", None),
        (None, None),
        ("ZZZ", None),  # unrecognised -> abstain
    ],
)
def test_team_evidence_abstains_on_anything_it_cannot_read(raw, expected):
    assert pf.team_evidence(raw) == expected


def test_header_tokens_ignore_separators_and_case_but_not_extra_words():
    n = pf.normalize_header_token
    assert n("Sleeper Id") == n("sleeper_id") == n("SleeperId") == n("sleeper-id") == "sleeperid"
    assert n("sleeper_id_source") not in pf.SLEEPER_ID_TOKENS
    assert n("player_id") in pf.VENDOR_ID_TOKENS
    assert n("playerID") in pf.VENDOR_ID_TOKENS
    assert n("Pos") in pf.POSITION_TOKENS and n("NFL Team") in pf.TEAM_TOKENS


def test_pick_by_tokens_takes_the_first_non_empty_accepted_spelling():
    row = {"name": "A", "team": "", "NFL Team": "DET", "Team": "SF"}
    assert pf.pick_by_tokens(row, pf.TEAM_TOKENS) == "DET"
    assert pf.pick_by_tokens({"name": "A"}, pf.TEAM_TOKENS) == ""
    assert pf.pick_by_tokens("not a dict", pf.TEAM_TOKENS) == ""  # type: ignore[arg-type]


def test_header_normalizer_matches_the_board_loaders_own():
    """The identity owner must read headers exactly as the board loader does."""
    from src.api import data_contract as dc

    for raw in ("Sleeper Id", "player_id", "NFL Team", "pos", "ktc-id", "", None, 5):
        assert pf.normalize_header_token(raw) == dc._normalize_header_token(raw)
    assert pf.SLEEPER_ID_TOKENS == dc._SLEEPER_ID_TOKENS
    row = {"x": "1", "Sleeper Id": "4881", "sleeper_id": "9"}
    assert pf.pick_by_tokens(row, pf.SLEEPER_ID_TOKENS) == dc._pick_provider_id(
        row, dc._SLEEPER_ID_TOKENS
    )
