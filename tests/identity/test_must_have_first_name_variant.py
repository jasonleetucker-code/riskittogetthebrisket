"""W06-F001 -- the must-have rookie guarantee must not mint a ghost beside an identified row.

The scraper's dedup first-name-drift rung folds "Matthew Hibner" into
"Matt Hibner", but the must-have rookie guarantee runs afterwards and, finding
no exact/normalized match for "Matthew Hibner", created a fresh id-less row
(``_fallbackReason == "must_have_rookie_guarantee"``).  The guarantee now asks
``unique_identified_first_name_variant`` -- the same rule and identity gate as
the rung -- before creating anything.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.utils.name_clean import unique_identified_first_name_variant as uniq

SCRAPER = Path(__file__).resolve().parents[2] / "Dynasty Scraper.py"


def _rows(**kw):
    return {k.replace("_", " "): v for k, v in kw.items()}


def test_unique_identified_variant_is_found():
    rows = _rows(Matt_Hibner={"_sleeperId": "13324"})
    assert uniq("Matthew Hibner", rows) == "Matt Hibner"
    rows = _rows(Jam_Miller={"_sleeperId": "13403"})
    assert uniq("Jamarion Miller", rows) == "Jam Miller"


def test_idless_candidate_is_never_a_match():
    assert uniq("Matthew Hibner", _rows(Matt_Hibner={"_composite": 5})) is None


def test_ambiguous_is_fail_closed():
    rows = _rows(Matt_Hibner={"_sleeperId": "1"}, Matth_Hibner={"_sleeperId": "2"})
    assert uniq("Matthew Hibner", rows) is None


def test_position_conflict_blocks_but_unknown_does_not():
    rows = _rows(Matt_Hibner={"_sleeperId": "1"})
    assert uniq("Matthew Hibner", rows, position_of=lambda n: "RB", preferred_position="TE") is None
    assert (
        uniq("Matthew Hibner", rows, position_of=lambda n: "TE", preferred_position="TE")
        == "Matt Hibner"
    )
    assert (
        uniq("Matthew Hibner", rows, position_of=lambda n: "", preferred_position="TE")
        == "Matt Hibner"
    )


def test_exact_row_and_non_variants_are_ignored():
    rows = _rows(Matthew_Hibner={"_sleeperId": "1"}, Rob_Henry={"_sleeperId": "2"})
    assert uniq("Matthew Hibner", rows) is None
    assert uniq("Derrick Henry", rows) is None


def test_must_have_guarantee_consults_the_rule_before_creating_a_row():
    src = SCRAPER.read_text(encoding="utf-8")
    start = src.index("# Must-have rookie guarantee: ensure every listed must-have rookie")
    block = src[start : start + 4000]
    assert re.search(r"_existing_key = _unique_identified_first_name_variant\(", block)
