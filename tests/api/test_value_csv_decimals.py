"""Value-signal CSVs keep published decimals; integer boards are unchanged.

DLF's Trade Analyzer Values run 0–~1000 to four decimals.  The value parser
used ``int(float(v))``, which turned 0.7 into 0 and cut every value under 10
to a whole number.  Fractions now survive, while an integral value stays an
``int`` so KTC / IDPTC parse bit-identically (owner directive 2026-09-24).
"""

from __future__ import annotations

from src.api import data_contract as dc


def _parse(tmp_path, text: str, key: str) -> dict[str, object]:
    path = tmp_path / f"{key}.csv"
    path.write_text(text, encoding="utf-8")
    dc._SOURCE_CSV_PARSE_CACHE.pop(str(path), None)
    lookup, err = dc._parse_source_csv_cached(path, key, "value", f"CSVs/site_raw/{key}.csv")
    assert err is None
    return {entry[0]: entry[1] for entries in lookup.values() for entry in entries}


def test_published_decimals_survive(tmp_path):
    got = _parse(
        tmp_path,
        "name,pos,team,value\nJosh Allen,QB,BUF,984.7047\nRyan Flournoy,WR,DAL,0.7000\n",
        "dlfValuesSfTep",
    )
    assert got["Josh Allen"] == 984.7047
    assert got["Ryan Flournoy"] == 0.7  # was int(float("0.7000")) == 0


def test_integer_boards_parse_bit_identically(tmp_path):
    got = _parse(tmp_path, "name,value\nJosh Allen,9999\nJa'Marr Chase,9876.0\n", "ktcCrowdSfTep")
    for name, expected in (("Josh Allen", 9999), ("Ja'Marr Chase", 9876)):
        assert got[name] == expected
        assert type(got[name]) is int
