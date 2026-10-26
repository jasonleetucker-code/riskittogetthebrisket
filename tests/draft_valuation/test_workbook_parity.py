"""Batch A — exact spreadsheet parity.

Three independent parties must agree on the owner's ``Draft Data`` workbook
(sha256 pinned below):

(a) the production module ``src/draft/rookie_auction/curve.py`` vs the
    workbook's cached values, every intermediate column, all 72 picks;
(b) the literal transcription ``reference_workbook_formulas.py`` vs the same
    cached values — and vs the workbook's FORMULA TEXT, so a changed formula
    in the sheet fails here instead of silently drifting;
(c) production vs the reference (here on the workbook inputs; randomized in
    ``test_curve_properties.py``).

Real-valued columns (C, E, J) are compared at the 10 significant digits a
Google Sheets export caches; integer and half-dollar columns (D, I, K, L)
exactly.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from src.draft.rookie_auction.curve import FORMULA_VERSION, WORKBOOK_PARAMS, compute_curve
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation import reference_workbook_formulas as ref

ROWS = range(2, 74)


@pytest.fixture(scope="module")
def production():
    rows = wb.rows()
    return compute_curve([r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"])


@pytest.fixture(scope="module")
def reference():
    return ref.evaluate_sheet(
        wb.by_row("B"),
        wb.by_row("F"),
        wb.by_row("G"),
        wb.by_row("H"),
        M1=int(wb.fixture()["curve"]["protectedRoundingParameterM1"]),
    )


# --- fixture provenance -------------------------------------------------------------


def test_fixture_records_the_owner_workbook_sha256():
    src = wb.fixture()["source"]
    assert src["sha256"] == wb.SOURCE_SHA256
    assert wb.inputs()["source"]["sha256"] == wb.SOURCE_SHA256
    # The repo's synced copy was cell-identical when the fixture was cut.
    assert src["comparedWith"]["fileName"] == "Draft Data.xlsx"
    assert src["comparedWith"]["cellDifferences"] == 0


def test_audit_facts_about_the_inputs():
    rows = wb.rows()
    assert [r["A"] for r in rows][:3] == [1.01, 1.02, 1.03] and rows[-1]["A"] == 6.12
    b = [r["B"] for r in rows]
    assert len(b) == 72 and sum(b) == 180036.5
    assert any(b[i + 1] > b[i] for i in range(71)), "column B is not strictly descending"
    headers = wb.fixture()["curve"]["headers"]
    assert (headers["F"], headers["G"], headers["H"]) == (2025.0, 2024.0, 2026.0)
    for col in "FGH":
        assert sum(r[col] for r in rows) == 1200
    assert wb.fixture()["curve"]["protectedRoundingParameterM1"] == 12
    assert wb.fixture()["curve"]["totals"]["L74"]["v"] == 1200


# --- (a) production == workbook -----------------------------------------------------


def test_production_matches_every_cached_column_for_all_72_picks(production):
    mismatches = []
    for prow, wrow in zip(production.rows, wb.rows()):
        real = {"C": prow.curve_value, "E": prow.spine, "J": prow.fraction}
        exact = {
            "D": prow.final_dollars,
            "I": prow.floor_units,
            "K": prow.monotone_units,
            "L": prow.final_dollars,
        }
        for col, ours in real.items():
            if wb.sig10(ours) != wrow[col]:
                mismatches.append((wrow["row"], col, ours, wrow[col]))
        for col, ours in exact.items():
            if Decimal(str(wrow[col])) != Decimal(ours):
                mismatches.append((wrow["row"], col, ours, wrow[col]))
    assert mismatches == []
    assert len(production.rows) == 72


def test_production_totals_and_parameters(production):
    assert production.total_units == 2400
    assert production.total_dollars == Decimal(1200)
    assert production.floor_pool_dollars == 84  # the sheet's literal ``1200-84``
    assert production.params.carry_picks == 12  # $M$1
    assert production.formula_version == FORMULA_VERSION
    # 0.6 * STDEV.S(B2:B7) / AVERAGE(B2:B7) = 0.6 * 985.61 / 5657.17 ~ 0.1045: the 0.08 ceiling binds.
    assert production.decay_rate == Decimal("0.08")
    assert production.residual_after_floor_units == 2400 - sum(r["I"] for r in wb.rows())
    assert production.residual_after_caps_units == 2400 - sum(r["K"] for r in wb.rows())


def test_spine_is_exact_rational(production):
    first = production.rows[0]
    # (MEDIAN(125.5,122.5,134) + AVERAGE(...)) / 2 = (125.5 + 382/3) / 2
    assert first.spine == (Fraction(251, 2) + Fraction(382, 3)) / 2


def test_decisions_are_far_from_double_precision_noise(production):
    # The spreadsheet evaluates in doubles (~1e-13 absolute error at these
    # magnitudes).  A margin this large proves both take the same decisions.
    assert production.precision_margin is not None
    assert production.precision_margin > Decimal("1e-6")


def test_production_grid_matches_the_workbook_grid(production):
    c = wb.cells()
    cols = "P Q R S T U V W X Y Z AA".split()
    grid = production.grid()
    for r in range(6):
        for s, col in enumerate(cols):
            assert Decimal(str(c[f"{col}{r + 2}"]["v"])) == grid[r][s]
        assert Decimal(str(c[f"AB{r + 2}"]["v"])) == production.round_totals()[r]
    for s, col in enumerate(cols):
        assert Decimal(str(c[f"{col}8"]["v"])) == production.slot_totals()[s]
    assert c["AB8"]["v"] == 1200 and c["AD1"]["v"] == 1


# --- (b) reference == workbook -------------------------------------------------------


@pytest.mark.parametrize("col", ["C", "E", "J"])
def test_reference_real_columns_match_cache(reference, col):
    cached = wb.by_row(col)
    assert [r for r in ROWS if wb.sig10(reference[col][r]) != cached[r]] == []


@pytest.mark.parametrize("col", ["D", "I", "K", "L"])
def test_reference_exact_columns_match_cache(reference, col):
    cached = wb.by_row(col)
    assert [r for r in ROWS if reference[col][r] != cached[r]] == []


def test_reference_downstream_cells_match_cache(reference):
    c = wb.cells()
    g = ref.evaluate_grid(reference["L"])
    for coord, value in {**g["grid"], **g["AB"], **g["row8"]}.items():
        assert value == c[coord]["v"], coord
    assert g["AB8"] == c["AB8"]["v"] and g["AD1"] == c["AD1"]["v"]
    for r, value in g["Q"].items():
        assert value == c[f"Q{r}"]["v"], r
    assert sum(g["Q"].values()) == c["Q117"]["v"] == 1200

    standings = {
        row: (
            c[f"O{row}"]["v"],
            c[f"P{row}"]["v"],
            (c.get(f"S{row}") or {}).get("v"),
            c[f"R{row}"]["v"],
        )
        for row in range(30, 42)
    }
    trades: dict[str, object] = {}
    for row in range(30, 203):
        key = (c.get(f"Y{row}") or {}).get("v")
        if key is not None and key not in trades:
            trades[key] = (c.get(f"X{row}") or {}).get("v")
    own = ref.evaluate_ownership(standings, trades, g["Q"])
    for row, owner in own["T"].items():
        assert owner == c[f"T{row}"]["v"], row
    for r, owner in own["R"].items():
        assert owner == c[f"R{r}"]["v"], r
    names = {row: c[f"T{row}"]["v"] for row in range(63, 75)}
    totals = ref.team_totals(names, own["R"], g["Q"])
    for row, total in totals.items():
        assert total == c[f"U{row}"]["v"], row
    assert sum(totals.values()) == c["U75"]["v"] == 1200


def test_reference_reproduces_the_orphan_m123_cell(reference):
    assert ref.evaluate_m123(reference["C"]) == wb.cells()["M123"]["v"] == 133


def _expected_template(col: str, row: int) -> str:
    return ref.FORMULA_TEMPLATES[col].format(r=row, p=row - 1)


@pytest.mark.parametrize("col", ["C", "D", "E", "I", "J", "K", "L"])
def test_transcription_matches_workbook_formula_text(col):
    c = wb.cells()
    for row in ROWS:
        template = "K2" if (col == "K" and row == 2) else col
        assert ref.normalize_formula(c[f"{col}{row}"]["f"]) == _expected_template(
            template, row
        ), f"{col}{row}"


def test_transcription_matches_downstream_formula_text():
    c = wb.cells()
    n = ref.normalize_formula
    cols = "P Q R S T U V W X Y Z AA".split()
    for gr in range(2, 8):
        for col in cols:
            assert n(c[f"{col}{gr}"]["f"]) == ref.FORMULA_TEMPLATES["grid"]
    assert n(c["AD1"]["f"]) == ref.FORMULA_TEMPLATES["AD1"]
    for r in range(45, 117):
        for col in "OPQR":
            assert n(c[f"{col}{r}"]["f"]) == ref.FORMULA_TEMPLATES[col].format(r=r), f"{col}{r}"
    for r in range(30, 42):
        assert n(c[f"T{r}"]["f"]) == ref.FORMULA_TEMPLATES["T"].format(r=r)
    for r in range(63, 75):
        assert n(c[f"U{r}"]["f"]) == ref.FORMULA_TEMPLATES["U"].format(r=r)
    assert n(c["M123"]["f"]) == ref.FORMULA_TEMPLATES["M123"]


# --- (c) production == reference on the workbook inputs ------------------------------


def test_production_equals_reference_on_workbook_inputs(production, reference):
    for prow in production.rows:
        r = prow.index + 2
        assert prow.floor_units == reference["I"][r]
        assert prow.monotone_units == reference["K"][r]
        assert prow.final_dollars == Decimal(str(reference["D"][r]))
        assert abs(float(prow.curve_value) - reference["C"][r]) < 1e-9


def test_workbook_params_are_the_sheet_literals():
    p = WORKBOOK_PARAMS
    assert (p.budget_dollars, p.team_count, p.rounds, p.carry_picks, p.units_per_dollar) == (
        1200,
        12,
        6,
        12,
        2,
    )
    assert dict(p.round_cap_units) == {5: 4, 6: 2}
    assert dict(p.round_floor_bonus_dollars) == {5: 1}


# --- mutation sensitivity: the parity checks must go red on a changed formula ---
#
# On the workbook inputs two parts of the formula never bind — the decay clamp
# (0.1045 -> 0.08) hides the head size, and monotonicity (round 4 ends at 4
# units) hides the round-5/6 caps — so the workbook alone cannot detect a
# mutation there.  Each mutation is therefore checked against the independent
# reference over the workbook inputs PLUS seeded random inputs where those
# parts do bind; it must disagree somewhere.


def _mutation_cases():
    from tests.draft_valuation.test_curve_properties import _case

    rows = wb.rows()
    yield [r["B"] for r in rows], [[r[c] for r in rows] for c in "FGH"]
    for seed in range(60):
        yield _case(seed)


@pytest.mark.parametrize(
    "mutation",
    [
        {"rookie_weight": Decimal("0.61"), "spine_weight": Decimal("0.39")},
        {"rookie_weight": Decimal("0.4"), "spine_weight": Decimal("0.6")},
        {"carry_picks": 11},
        {"carry_picks": 6},
        {"round_floor_bonus_dollars": {}},
        {"round_cap_units": {5: 6, 6: 2}},
        {"round_cap_units": {5: 4, 6: 4}},
        {"decay_rate_max": Decimal("0.09")},
        {"decay_head_count": 5},
        {"shape_amplitude": Decimal("0.25")},
    ],
    ids=lambda m: ",".join(f"{k}={v}" for k, v in sorted(m.items())),
)
def test_a_mutated_formula_is_detected(mutation):
    from dataclasses import replace

    from src.draft.rookie_auction.curve import CurveInvariantError

    params = replace(WORKBOOK_PARAMS, **mutation)
    for b, curves in _mutation_cases():
        try:
            res = compute_curve(b, curves, params)
        except CurveInvariantError:
            return  # refused outright also counts as detected
        out = ref.evaluate_sheet(
            *({i + 2: v for i, v in enumerate(col)} for col in (b, *curves)), M1=12
        )
        if [r.final_units for r in res.rows] != [int(out["D"][r] * 2) for r in ROWS]:
            return
    pytest.fail(f"mutation {mutation} was not detected by any case")


def test_caps_and_decay_head_are_exercised_somewhere():
    """Guard for the comment above: random inputs do make the caps bind."""
    cap_binding = 0
    for b, curves in _mutation_cases():
        res = compute_curve(b, curves)
        for r in res.rows[1:]:
            prev = res.rows[r.index - 1].monotone_units
            if r.cap_units is not None and r.floor_units + r.remainder_award > r.cap_units < prev:
                cap_binding += 1
    assert cap_binding > 0
