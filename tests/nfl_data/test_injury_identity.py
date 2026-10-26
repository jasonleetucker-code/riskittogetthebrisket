"""ESPN athlete id -> Sleeper id for the injury feed: resolved, or refused with a counted reason.

``src/nfl_data/injury_identity.py`` composes the two rungs the injury consumers
already use (exact ESPN id via ``injury_history.EspnIdResolver``; exact name via
the canonical ``resolve_canonical_v2``).  It owns no matcher.
"""

from __future__ import annotations

from src.nfl_data import injury_feed, injury_history, injury_identity

DIRECTORY = {
    # exact ESPN id
    "100": {
        "full_name": "Alpha Player",
        "position": "WR",
        "team": "BUF",
        "active": True,
        "espn_id": "9001",
    },
    # no ESPN id in the directory (Sleeper's espn_id is sparse): resolvable by exact name
    "200": {"full_name": "Beta Player", "position": "RB", "team": "SF", "active": True},
    # two Sleeper players claim one ESPN id: must never resolve by id
    "300": {
        "full_name": "Gamma One",
        "position": "TE",
        "team": "KC",
        "active": True,
        "espn_id": "9003",
    },
    "301": {
        "full_name": "Gamma Two",
        "position": "TE",
        "team": "KC",
        "active": True,
        "espn_id": "9003",
    },
    # two indistinguishable players of one name: ambiguous by name
    "400": {"full_name": "Delta Twin", "position": "WR", "team": "DAL", "active": True},
    "401": {"full_name": "Delta Twin", "position": "WR", "team": "DAL", "active": True},
    # reachable only by a guarded (initial-expansion) rung: a guess, so refused
    "500": {"full_name": "Jaxon Smith-Njigba", "position": "WR", "team": "SEA", "active": True},
}


def _entry(espn_id: str, name: str, position: str = "WR", team: str = "BUF"):
    return injury_feed.entry_from_dict(
        {
            "espnAthleteId": espn_id,
            "fullName": name,
            "position": position,
            "teamAbbrev": team,
            "status": "OUT",
        }
    )


def _resolve(entries, directory=DIRECTORY):
    resolver = injury_history.EspnIdResolver(directory)
    return injury_identity.resolve_entries(entries, resolver=resolver)


def test_exact_espn_id_resolves_and_stamps_the_sleeper_id():
    resolved, report = _resolve([_entry("9001", "Alpha Player")])
    assert [(e.espn_athlete_id, e.sleeper_id) for e in resolved] == [("9001", "100")]
    assert report.to_dict() == {
        "considered": 1,
        "resolved": 1,
        "unresolved": 0,
        "byMethod": {"espn_id": 1},
        "unresolvedByReason": {},
    }


def test_id_missing_from_the_directory_falls_to_the_exact_name_rung():
    resolved, report = _resolve([_entry("7777", "Beta Player", "RB", "SF")])
    assert [e.sleeper_id for e in resolved] == ["200"]
    assert report.by_method == {"name:exact_clean": 1}


def test_espn_team_code_is_normalized_for_the_name_rung():
    directory = {
        "600": {"full_name": "Wash Player", "position": "WR", "team": "WAS", "active": True},
        "601": {"full_name": "Wash Player", "position": "WR", "team": "BUF", "active": True},
    }
    # ESPN says WSH; Sleeper says WAS.  Without normalization this is ambiguous.
    resolved, _report = _resolve([_entry("1", "Wash Player", "WR", "WSH")], directory)
    assert [e.sleeper_id for e in resolved] == ["600"]


def test_an_espn_id_shared_by_two_sleeper_players_is_refused_not_name_matched():
    resolved, report = _resolve([_entry("9003", "Gamma One", "TE", "KC")])
    assert resolved == []
    assert report.unresolved_by_reason == {"espn_id_shared_by_multiple_sleeper_players": 1}


def test_ambiguous_name_is_refused_and_counted():
    resolved, report = _resolve([_entry("1", "Delta Twin", "WR", "DAL")])
    assert resolved == []
    assert report.unresolved_by_reason == {"ambiguous": 1}


def test_a_guarded_fuzzy_answer_is_refused_never_accepted():
    resolved, report = _resolve([_entry("1", "J. Smith-Njigba", "WR", "SEA")])
    assert resolved == []
    assert report.unresolved_by_reason == {"fuzzy_match_refused": 1}


def test_unknown_player_and_blank_name_are_counted():
    resolved, report = _resolve([_entry("1", "Nobody Known"), _entry("2", "")])
    assert resolved == []
    assert report.unresolved_by_reason == {"no_candidate": 1, "no_name": 1}


def test_no_directory_refuses_everything_with_one_reason():
    resolved, report = _resolve([_entry("9001", "Alpha Player")], directory=None)
    assert resolved == []
    assert report.unresolved_by_reason == {"no_sleeper_directory": 1}


def test_two_espn_ids_for_one_sleeper_player_are_both_refused():
    entries = [_entry("9001", "Alpha Player"), _entry("7777", "Alpha Player", "WR", "BUF")]
    resolved, report = _resolve(entries)
    assert resolved == []
    assert report.unresolved_by_reason == {"sleeper_id_claimed_by_multiple_espn_ids": 2}


def test_order_is_preserved_and_unresolved_are_dropped():
    entries = [
        _entry("7777", "Beta Player", "RB", "SF"),
        _entry("1", "Nobody Known"),
        _entry("9001", "Alpha Player"),
    ]
    resolved, report = _resolve(entries)
    assert [e.sleeper_id for e in resolved] == ["200", "100"]
    assert (report.considered, report.resolved, report.unresolved) == (3, 2, 1)


# ── the alarm ──────────────────────────────────────────────────────────────


def _report(considered: int, unresolved: int) -> injury_identity.IdentityReport:
    return injury_identity.IdentityReport(
        considered=considered,
        resolved=considered - unresolved,
        unresolved_by_reason={"no_candidate": unresolved} if unresolved else {},
    )


def test_identity_error_is_none_for_an_empty_report():
    assert injury_identity.identity_error(_report(0, 0)) is None


def test_identity_error_when_nothing_resolves_at_any_size():
    err = injury_identity.identity_error(_report(3, 3))
    assert err is not None and err.startswith("no_entry_resolved:3,reasons=no_candidate:3")


def test_identity_error_fraction_boundaries():
    # 6 of 30 = exactly 20%: tolerated.  7 of 30 = 23%: broken.
    assert injury_identity.identity_error(_report(30, 6)) is None
    err = injury_identity.identity_error(_report(30, 7))
    assert err is not None and err.startswith("unresolved_above_20pct:7/30,reasons=")


def test_identity_error_fraction_is_not_judged_below_the_floor():
    assert injury_identity.identity_error(_report(10, 4)) is None  # noise at that size


def test_measured_live_rate_is_far_inside_the_threshold():
    """2 of 274 unresolved on the 2026-10-26 report (docstring of the module)."""
    assert injury_identity.identity_error(_report(274, 2)) is None
