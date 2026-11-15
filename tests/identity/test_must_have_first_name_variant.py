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
    # The call must carry the verified-rookie gate (review finding on #2096).
    call = block[block.index("_unique_identified_first_name_variant(") :]
    call = call[: call.index("\n        _target_name")]
    assert "candidate_ok=" in call
    assert "_player_years_exp_local(" in call and "== 0" in call


def test_a_veteran_sharing_a_first_name_variant_never_absorbs_a_rookie():
    # No position hints exist in rookie_must_have.txt, so the position guard
    # cannot fire; the rookie gate is what keeps "Chris Smith" (rookie) out of
    # "Christian Smith" (veteran LB).
    rows = _rows(Christian_Smith={"_sleeperId": "1"})
    years_exp = {"Christian Smith": 6}
    ok = lambda c: years_exp.get(c) == 0  # noqa: E731
    assert uniq("Chris Smith", rows) == "Christian Smith"  # the gap without the gate
    assert uniq("Chris Smith", rows, candidate_ok=ok) is None


def test_unknown_rookie_status_is_fail_closed():
    rows = _rows(Matt_Hibner={"_sleeperId": "13324"})
    assert uniq("Matthew Hibner", rows, candidate_ok=lambda c: None == 0) is None  # noqa: E711


def test_the_rookie_gate_filters_before_uniqueness():
    # A veteran variant must not make a verified rookie variant "ambiguous".
    rows = _rows(Christian_Smith={"_sleeperId": "1"}, Christopher_Smith={"_sleeperId": "2"})
    years_exp = {"Christian Smith": 6, "Christopher Smith": 0}
    ok = lambda c: years_exp.get(c) == 0  # noqa: E731
    assert uniq("Chris Smith", rows, candidate_ok=ok) == "Christopher Smith"


def test_the_two_archive_cases_pass_the_rookie_gate():
    # Pinned archive dynasty_export_20261106_194518: both identified rows carry
    # Sleeper years_exp 0 (Matt Hibner 13324, Jam Miller 13403).
    rows = _rows(Matt_Hibner={"_sleeperId": "13324"}, Jam_Miller={"_sleeperId": "13403"})
    years_exp = {"Matt Hibner": 0, "Jam Miller": 0}
    ok = lambda c: years_exp.get(c) == 0  # noqa: E731
    assert uniq("Matthew Hibner", rows, candidate_ok=ok) == "Matt Hibner"
    assert uniq("Jamarion Miller", rows, candidate_ok=ok) == "Jam Miller"
