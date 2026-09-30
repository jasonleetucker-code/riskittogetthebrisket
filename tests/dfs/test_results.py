"""Contest results: realized ownership/points joined honestly; forecasts evaluated, nothing promoted."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.dfs.imports import ImportError_, parse_draftkings_salaries
from src.dfs.results import evaluate, parse_standings
from src.dfs.rules import get_ruleset

FIX = Path(__file__).parent / "fixtures"
RS = get_ruleset("draftkings.nfl.classic")
HEAD = "Rank,EntryId,EntryName,TimeRemaining,Points,Lineup,,Player,Roster Position,%Drafted,FPTS"


def _athletes():
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    return athletes


def _lineup_text(athletes):
    by = {}
    for a in athletes:
        by.setdefault(a.positions[0], []).append(a)
    parts = [("QB", by["QB"][0]), ("RB", by["RB"][0]), ("RB", by["RB"][1])]
    parts += [("WR", by["WR"][i]) for i in range(3)] + [("TE", by["TE"][0])]
    parts += [("FLEX", by["RB"][2]), ("DST", by["DST"][0])]
    return " ".join(f"{slot} {a.name}" for slot, a in parts), [a.player_id for _, a in parts]


def _file(athletes, player_rows, lineups):
    rows = [HEAD]
    n = max(len(player_rows), len(lineups))
    for i in range(n):
        left = (
            f'{i + 1},{1000 + i},user{i},0,{150 - i},"{lineups[i]}"'
            if i < len(lineups)
            else ",,,,,"
        )
        right = ",".join(player_rows[i]) if i < len(player_rows) else ",,,"
        rows.append(f"{left},,{right}")
    return "\n".join(rows) + "\n"


def test_realized_join_quarantine_duplication_and_absent_is_not_zero():
    athletes = _athletes()
    qb = next(a for a in athletes if a.positions == ["QB"])
    rb = next(a for a in athletes if a.positions == ["RB"])
    text, ids = _lineup_text(athletes)
    player_rows = [
        [qb.name, "QB", "35.50%", "22.4"],
        [rb.name, "RB", "12%", "8"],
        ["Nobody Here", "WR", "3%", "1"],  # not on the slate
    ]
    parsed = parse_standings(_file(athletes, player_rows, [text, text, text + " "]), RS, athletes)
    assert parsed["layoutVerification"] == "assumed"
    assert parsed["realized"][qb.player_id] == {"ownership": 35.5, "points": 22.4}
    assert parsed["quarantined"][0]["reason"] == "no_slate_athlete"
    f = parsed["field"]
    assert f["entries"] == 3 and f["resolvedLineups"] == 3
    assert sorted(f["sample"][0]["lineup"]) == sorted(ids)  # FLEX resolved via the unique name
    d = parsed["duplication"]
    sample = d.pop("fitSample")
    assert d == {
        "lineupsCompared": 3,
        "distinctLineups": 1,
        "entriesInDuplicatedLineups": 3,
        "histogram": {"3": 1},
        "maxCopies": 3,
    }
    assert sample["repeated"] == [{"players": sorted(ids), "count": 3, "weight": 1.0}]
    assert sample["singles"] == [] and sample["repeatedTruncated"] is False


def test_two_slate_athletes_the_join_cannot_separate_are_quarantined():
    athletes = _athletes()
    wrs = [a for a in athletes if a.positions == ["WR"]][:2]
    wrs[1].name = wrs[0].name
    parsed = parse_standings(_file(athletes, [[wrs[0].name, "WR", "10%", "5"]], []), RS, athletes)
    assert parsed["realized"] == {}
    assert parsed["quarantined"][0]["reason"] == "ambiguous_identity"


def test_evaluation_statistics_are_exact_and_absent_players_are_excluded_not_zeroed():
    athletes = _athletes()
    a, b, c = athletes[:3]
    a.ownership, b.ownership, c.ownership = 30.0, 4.0, 12.0  # c will be absent from results
    a.projection, b.projection = 20.0, 10.0
    realized = {
        a.player_id: {"ownership": 20.0, "points": 26.0},
        b.player_id: {"ownership": 6.0, "points": 7.0},
    }
    ev = evaluate(athletes, realized)
    # ownership errors: +10, -2 → bias 4, MAE 6, RMSE sqrt(52)
    assert ev["ownership"] == {"n": 2, "bias": 4.0, "mae": 6.0, "rmse": round(52**0.5, 3)}
    # projection errors: -6, +3 → bias -1.5, MAE 4.5
    assert ev["projection"]["bias"] == -1.5 and ev["projection"]["mae"] == 4.5
    assert ev["notInResults"] == 1
    assert {x["band"] for x in ev["ownershipBands"]} == {"0–5%", "30–100%"}


def test_wrong_layout_and_other_platforms_are_refused():
    athletes = _athletes()
    with pytest.raises(ImportError_) as exc:
        parse_standings("Rank,Points\n1,100\n", RS, athletes)
    assert exc.value.code == "RESULTS_FILE_UNRECOGNISED"
    with pytest.raises(ImportError_) as exc:
        parse_standings(HEAD + "\n", get_ruleset("fanduel.nfl.classic"), athletes)
    # No verified FanDuel standings export: refused, pointing at the canonical format.
    assert exc.value.code == "RESULTS_FILE_UNRECOGNISED"
    assert "PlayerId" in exc.value.detail["expected"]
