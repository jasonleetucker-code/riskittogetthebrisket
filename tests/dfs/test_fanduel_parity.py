"""FanDuel through the SAME models: header-detected entries, canonical results, shared settlement."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from src.dfs.contests import Contest, PayoutBand
from src.dfs.entries import export_into_entries, parse_entries
from src.dfs.imports import ImportError_, apply_platform_average, parse_fanduel_players
from src.dfs.optimizer import Constraints, optimize
from src.dfs.results import CANONICAL_COLS, parse_standings
from src.dfs.rules import get_ruleset
from src.dfs.settlement import settle

FIX = Path(__file__).parent / "fixtures"
FD = get_ruleset("fanduel.nfl.classic")
SLOTS = [s.name for s in FD.slots]


@pytest.fixture(scope="module")
def slate():
    athletes, _ = parse_fanduel_players(
        (FIX / "synthetic_fd_nfl_classic_players.csv").read_text(encoding="utf-8")
    )
    apply_platform_average(athletes)
    res = optimize(FD, athletes, Constraints(lineups=2, min_unique=2))
    lineups = [[p["playerId"] for p in lu["players"]] for lu in res["lineups"]]
    return athletes, lineups


def _entries_csv(rows):
    head = ["entry_id", "contest_id", "contest_name", "entry_fee", *SLOTS, "Instructions"]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(head)
    for r in rows:
        w.writerow(r)
    return out.getvalue()


def test_fanduel_entry_file_is_header_detected_marked_unverified_and_round_trips(slate):
    athletes, lineups = slate
    text = _entries_csv(
        [
            ["E1", "C9", "Sunday Million", "$3.00", *lineups[0], ""],
            ["E2", "C9", "Sunday Million", "$3.00", *([""] * len(SLOTS)), ""],
        ]
    )
    parsed = parse_entries(text, FD, athletes)
    assert parsed["layout"] == "fanduel_entries_header_detected_v1"
    assert parsed["layoutVerification"] == "assumed"
    assert parsed["counts"] == {"empty": 1, "complete": 1, "partial": 0, "unresolved": 0}
    out, report = export_into_entries(
        FD,
        [{"index": 1, "players": [{"slot": s, "playerId": p} for s, p in zip(SLOTS, lineups[1])]}],
        parsed["entries"],
        athletes,
        parsed["exportLayout"],
    )
    rows = list(csv.reader(io.StringIO(out)))
    assert rows[0] == [
        "entry_id",
        "contest_id",
        "contest_name",
        "entry_fee",
        *SLOTS,
    ]  # the file's own columns
    assert rows[1][:4] == ["E1", "C9", "Sunday Million", "$3.00"] and rows[1][4:] == lineups[1]
    assert report["assigned"] == [{"entryId": "E1", "lineupIndex": 1}]


def test_an_unrecognised_fanduel_entry_file_is_refused_not_guessed(slate):
    athletes, _ = slate
    with pytest.raises(ImportError_) as exc:
        parse_entries("id,player1,player2\nE1,a,b\n", FD, athletes)
    assert (
        exc.value.code == "ENTRY_FILE_UNRECOGNISED" and exc.value.detail["expectedSlots"] == SLOTS
    )


def _canonical(entries, players):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(CANONICAL_COLS)
    n = max(len(entries), len(players))
    for i in range(n):
        e = entries[i] if i < len(entries) else ["", "", "", "", ""]
        p = players[i] if i < len(players) else ["", "", ""]
        w.writerow([*e, *p])
    return out.getvalue()


def test_fanduel_results_via_the_canonical_format_settle_through_the_shared_path(slate):
    athletes, lineups = slate
    lu = "|".join(lineups[0])
    other = "|".join(lineups[1])
    text = _canonical(
        [
            ["E1", "me (1/1)", "1", "150.5", lu],
            ["E2", "rival", "1", "150.5", lu],
            ["E3", "x", "3", "90", other],
        ],
        [[lineups[0][0], "35.5%", "22.4"], ["not-on-slate", "3%", "1"]],
    )
    parsed = parse_standings(text, FD, athletes, owner_username="me")
    assert (
        parsed["layout"] == "canonical_results_v1"
        and parsed["layoutVerification"] == "defined_by_chaseupside"
    )
    assert parsed["realized"][lineups[0][0]] == {"ownership": 35.5, "points": 22.4}  # joined by ID
    assert parsed["quarantined"][0]["reason"] == "no_slate_athlete"
    assert parsed["duplication"]["histogram"] == {"1": 1, "2": 1}
    contest = Contest(
        name="FD mini",
        platform="fanduel",
        sport="nfl",
        format="classic",
        entry_fee_cents=300,
        tie_rule="split_positions",
        ladder=[PayoutBand(1, 1, 1000), PayoutBand(2, 2, 200)],
    )
    s = settle(contest, parsed["pointsCounts"], parsed["ownerEntries"])
    assert (
        s["state"] == "complete" and s["rows"][0]["payout"]["eachCents"] == 600
    )  # tied 1st/2nd split


def test_canonical_lineups_with_the_wrong_slot_count_are_unresolved_not_guessed(slate):
    athletes, lineups = slate
    text = _canonical([["E1", "a", "1", "100", "|".join(lineups[0][:-1])]], [])
    parsed = parse_standings(text, FD, athletes)
    assert parsed["field"]["unresolvedLineups"] == 1  # wrong slot count: kept, never guessed
