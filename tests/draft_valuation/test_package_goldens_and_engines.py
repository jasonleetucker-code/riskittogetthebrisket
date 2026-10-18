"""Batch A — the owner package goldens, a second spreadsheet engine, and RANK ties.

* ``package_goldens_2026_10_17.json`` is the owner's implementation package
  golden fixture (ChatGPT forensic audit, 2026-10-17), stored byte-for-byte.
  It must agree with the workbook's cached values, and BOTH the production
  module and the independent reference must reproduce it.
* ``workbook_2026_10_17_libreoffice_recalc.json`` is the unmodified workbook
  recalculated by LibreOffice Calc at full double precision — an engine
  independent of Google Sheets and of this repository.
* ``rank_tie_cases_libreoffice.json`` holds adversarial exact RANK ties in
  column J, evaluated by LibreOffice with the workbook's own I/J/K/D formula
  text.  It proves what the spreadsheet does on a tie at the award cutoff
  (publishes $1,206) and that production refuses rather than publishes it.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from fractions import Fraction

import pytest

from src.draft.rookie_auction.curve import (
    CurveInvariantError,
    allocate_units,
    check_allocation,
    compute_curve,
    curve_receipt,
)
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation import reference_workbook_formulas as ref

GOLDENS = wb.FIXTURE_DIR / "package_goldens_2026_10_17.json"
GOLDENS_SHA256 = "77d6886f9fee4d510fa12de36c2f499bc97175236d5761cccbc03fdfa05045b6"
LO_RECALC = wb.FIXTURE_DIR / "workbook_2026_10_17_libreoffice_recalc.json"
TIES = wb.FIXTURE_DIR / "rank_tie_cases_libreoffice.json"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def goldens():
    return _load(GOLDENS)


@pytest.fixture(scope="module")
def production():
    rows = wb.rows()
    return compute_curve([r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"])


# --- owner package goldens ---------------------------------------------------------


def test_goldens_file_is_the_owner_package_copy(goldens):
    assert hashlib.sha256(GOLDENS.read_bytes()).hexdigest() == GOLDENS_SHA256
    assert goldens["sourceSha256"] == wb.SOURCE_SHA256
    assert goldens["historicalYears"] == {"F": 2025, "G": 2024, "H": 2026}
    p = goldens["formulaParameters"]
    assert (p["rookieSignalWeight"], p["historicalSpineWeight"], p["floorPool"], p["M1"]) == (
        0.6,
        0.4,
        84,
        12,
    )


def test_goldens_agree_with_the_workbook_cache(goldens):
    disagreements = [
        (g["pick"], col, g[col], w[col])
        for g, w in zip(goldens["rows"], wb.rows())
        for col in "BCDEFGHIJKL"
        if float(g[col]) != float(w[col])
    ]
    assert disagreements == []
    assert len(goldens["rows"]) == 72


def test_production_reproduces_the_goldens(goldens, production):
    bad = []
    for prow, g in zip(production.rows, goldens["rows"]):
        assert prow.label == g["pick"]
        for col, ours in (("C", prow.curve_value), ("E", prow.spine), ("J", prow.fraction)):
            if wb.sig10(ours) != g[col]:
                bad.append((g["pick"], col))
        for col, ours in (
            ("I", prow.floor_units),
            ("K", prow.monotone_units),
            ("D", prow.final_dollars),
            ("L", prow.final_dollars),
            ("independentD", prow.final_dollars),
        ):
            if Decimal(str(g[col])) != Decimal(ours):
                bad.append((g["pick"], col))
        # The package's own independent C used the 10-digit cached spine, so
        # it carries ~1e-8 of that rounding; exact C is within that bound.
        assert abs(float(prow.curve_value) - g["independentC"]) < 5e-8
    assert bad == []
    ir = goldens["independentReference"]
    assert ir["finalDollarsExactMatches"] == 72 and ir["totalDollars"] == 1200
    assert ir["roundingRemainderHalfDollarUnits"] == production.residual_after_caps_units == 17
    assert goldens["formulaParameters"]["decay"] == float(production.decay_rate)


def test_reference_reproduces_the_goldens(goldens):
    g_rows = {i + 2: g for i, g in enumerate(goldens["rows"])}
    out = ref.evaluate_sheet(
        {r: g["B"] for r, g in g_rows.items()},
        {r: g["F"] for r, g in g_rows.items()},
        {r: g["G"] for r, g in g_rows.items()},
        {r: g["H"] for r, g in g_rows.items()},
        M1=goldens["formulaParameters"]["M1"],
    )
    for r, g in g_rows.items():
        for col in "CEJ":
            assert wb.sig10(out[col][r]) == g[col], (g["pick"], col)
        for col in "IKDL":
            assert out[col][r] == g[col], (g["pick"], col)


# --- a second spreadsheet engine at full double precision ---------------------------


def test_production_matches_libreoffice_full_precision(production):
    lo = _load(LO_RECALC)
    assert lo["source"]["workbookSha256"] == wb.SOURCE_SHA256
    assert lo["totals"]["D74"] == 1200 and lo["totals"]["U75"] == 1200
    for prow, row in zip(production.rows, lo["rows"]):
        assert abs(float(prow.curve_value) - row["C"]) < 1e-11
        assert abs(float(prow.spine) - row["E"]) < 1e-11
        assert abs(float(prow.fraction) - row["J"]) < 1e-11
        assert prow.floor_units == row["I"] and prow.monotone_units == row["K"]
        assert prow.final_dollars == Decimal(str(row["D"])) == Decimal(str(row["L"]))


def test_reference_matches_libreoffice_full_precision():
    lo = _load(LO_RECALC)
    out = ref.evaluate_sheet(wb.by_row("B"), wb.by_row("F"), wb.by_row("G"), wb.by_row("H"))
    for row in lo["rows"]:
        r = row["row"]
        assert abs(out["C"][r] - row["C"]) < 1e-9
        assert out["K"][r] == row["K"] and out["D"][r] == row["D"]
    assert ref.evaluate_m123(out["C"]) == lo["totals"]["M123"]


# --- adversarial RANK ties (audit D8) ------------------------------------------------


@pytest.fixture(scope="module")
def ties():
    return _load(TIES)["cases"]


@pytest.mark.parametrize("case", ["overshoot_tie_at_cutoff", "benign_tie_inside_award"])
def test_integer_stage_matches_libreoffice_on_ties(ties, case):
    c = [Fraction(x) for x in ties[case]["curveValuesC"]]
    expected = ties[case]["expected"]
    alloc = allocate_units(c)
    assert list(alloc.floor_units) == expected["I"]
    assert [float(x) for x in alloc.fractions] == expected["J"]
    assert list(alloc.monotone_units) == expected["K"]
    assert [u / 2 for u in alloc.final_units] == expected["D"]
    assert alloc.total_units / 2 == expected["D74"]
    # The independent float transcription agrees with LibreOffice too.
    out = ref.evaluate_integer_stage({i + 2: float(x) for i, x in enumerate(c)})
    assert [out["K"][r] for r in range(2, 74)] == expected["K"]
    assert [out["D"][r] for r in range(2, 74)] == expected["D"]


def test_tie_at_cutoff_is_refused_not_published(ties):
    c = [Fraction(x) for x in ties["overshoot_tie_at_cutoff"]["curveValuesC"]]
    alloc = allocate_units(c)
    # The spreadsheet itself publishes $1206 here (QUOTIENT(-1,12)=0, MOD=11).
    assert alloc.total_units == 2412
    assert (alloc.residual_after_caps_units, alloc.carry_quotient, alloc.carry_mod) == (-1, 0, 11)
    assert alloc.precision_margin == 0
    with pytest.raises(CurveInvariantError, match="tie"):
        check_allocation(alloc)
    with pytest.raises(CurveInvariantError):
        allocate_units(c, check=True)


def test_harmless_tie_passes(ties):
    alloc = allocate_units(
        [Fraction(x) for x in ties["benign_tie_inside_award"]["curveValuesC"]], check=True
    )
    assert alloc.total_units == 2400


# --- receipts ---------------------------------------------------------------------


def test_receipt_is_deterministic_and_complete(production):
    a = curve_receipt(production, spine_years=(2024, 2025, 2026))
    b = curve_receipt(production, spine_years=(2024, 2025, 2026))
    assert a == b and len(a["receiptSha256"]) == 64
    assert a["inputs"]["spineYears"] == [2024, 2025, 2026]
    assert a["totalDollars"] == "1200" and sum(a["finalUnits"]) == 2400
    assert a["carryQuotient"] == 1 and a["carryMod"] == 5
    assert curve_receipt(production)["inputs"]["spineYears"] is None  # never guessed
    json.dumps(a)  # serialisable
