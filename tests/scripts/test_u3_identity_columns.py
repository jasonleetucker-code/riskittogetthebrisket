"""V2.1 U3: the name-only boards carry the position and team the vendor shows.

Outlier-integrity V2.1 preregistration §3.7 (U3): fantasyCalc, OTC,
DynastyDaddy, Flock (+ rookies), Navigator and DLF (the KTC / IDPTC boards are
written by the scraper, pinned in ``tests/identity``) append ``position`` and
``team`` as TRAILING columns.  Each cell is the vendor's own field, verbatim
(stripped, upper-cased); a field the vendor does not publish is blank — never a
guess.  The rank / value columns and their order are unchanged, so the board
content (``dataset_integrity.parse_board``) is the same dataset.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import fetch_dynasty_daddy as dd
from scripts import fetch_fantasycalc as fc
from scripts import fetch_fantasynavigator as fn
from scripts import fetch_flock_fantasy as ff
from scripts import fetch_flock_fantasy_rookies as ffr
from scripts import fetch_otcffb as otc
from src.sources.dataset_integrity import parse_board


def _read(path: Path):
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _same_content(path: Path, header: list[str], signal: str) -> None:
    """Dropping the U3 columns leaves the identical board content."""
    text = path.read_text(encoding="utf-8")
    fields, rows = _read(path)
    keep = [c for c in fields if c not in ("position", "team")]
    stripped = (
        ",".join(keep) + "\n" + "".join(",".join(str(r[c]) for c in keep) + "\n" for r in rows)
    )
    assert keep == header
    assert parse_board(text, signal=signal).rows == parse_board(stripped, signal=signal).rows


def test_fantasycalc_reads_team_from_maybe_team(tmp_path):
    data = [
        {"player": {"name": "Josh Allen", "position": "QB", "maybeTeam": "buf"}, "value": 10000},
        {"player": {"name": "No Team", "position": "WR"}, "value": 5000},
    ]
    rows = fc._parse_players(data)
    out = tmp_path / "fantasyCalc.csv"
    fc._write_csv(out, rows)
    fields, got = _read(out)
    assert fields == ["name", "value", "rank", "position", "team"]
    assert [(r["position"], r["team"]) for r in got] == [("QB", "BUF"), ("WR", "")]
    _same_content(out, ["name", "value", "rank"], "rank")


def test_otc_team_is_blank_when_not_published(tmp_path):
    rows = otc._parse_players({"players": [{"pos": "RB", "name": "Bijan Robinson", "value": 100}]})
    out = tmp_path / "otcffbSf.csv"
    otc._write_csv(out, rows)
    fields, got = _read(out)
    assert fields == ["name", "value", "rank", "position", "team"]
    assert (got[0]["position"], got[0]["team"]) == ("RB", "")


def test_dynasty_daddy_carries_position_and_team(tmp_path):
    rows = dd._parse_players(
        [{"full_name": "Puka Nacua", "position": "WR", "team": "LAR", "sf_trade_value": 9000}]
    )
    out = tmp_path / "dynastyDaddySf.csv"
    dd._write_csv(out, rows)
    fields, got = _read(out)
    assert fields == ["name", "value", "rank", "position", "team"]
    assert (got[0]["position"], got[0]["team"]) == ("WR", "LAR")
    _same_content(out, ["name", "value", "rank"], "rank")


@pytest.mark.parametrize("module", [ff, ffr])
def test_flock_boards_carry_position(module, tmp_path):
    entry = {"playerName": "Ashton Jeanty", "position": "RB", "averageRank": 3.5, "isRookie": True}
    rows = module._parse_players({"data": [entry]})
    out = tmp_path / "flock.csv"
    module._write_csv(out, rows)
    fields, got = _read(out)
    assert fields == ["name", "Rank", "position", "team"]
    assert (got[0]["position"], got[0]["team"]) == ("RB", "")
    _same_content(out, ["name", "Rank"], "rank")


def test_navigator_keeps_the_winning_rows_fields(tmp_path):
    base = {"roster_type": "sf_value", "rank_type": "dynasty", "_insert_date": "2026-10-20"}
    data = [
        {
            **base,
            "player_full_name": "Bijan Robinson",
            "_position": "RB",
            "team": "ATL",
            "player_value": 9000,
        },
        {
            **base,
            "player_full_name": "Bijan Robinson",
            "_position": "RB",
            "team": "OLD",
            "player_value": 8000,
        },
    ]
    rows = fn._parse_players(data)
    out = tmp_path / "fantasyNavigatorSf.csv"
    fn._write_csv(out, rows)
    fields, got = _read(out)
    assert fields == ["name", "value", "rank", "position", "team"]
    assert [(r["position"], r["team"]) for r in got] == [("RB", "ATL")]
