"""The rookie-auction pick-dollar curve — the owner-approved spreadsheet formula.

This module is the canonical calculation of "how many auction dollars is each
rookie-draft pick worth".  It reproduces, column by column, the formula in the
owner's ``Draft Data`` Google Sheet (``CSVs/Draft Data.xlsx``, tab
``Draft Data``, rows 2-73).  The owner directive of 2026-10-18 makes that
formula the approved methodology, so this module transcribes it rather than
improving it.  ``docs/draft/DRAFT_DATA_WORKBOOK_MAP.md`` maps every column;
``tests/draft_valuation/`` pins exact parity against the workbook's cached
values and against an independent literal transcription.

Pipeline (sheet column in brackets; ``i`` is the 0-based pick index, row
``i + 2``; ``r = i // team_count`` is the 0-based round index):

* ``[B]`` rookie-value input per pick (not required to be descending).
* ``[F,G,H]`` three historical dollar curves (one per completed rookie draft).
* ``[E]`` spine ``(MEDIAN(F,G,H) + AVERAGE(F,G,H)) / 2`` — exact rational.
* decay rate ``k = clamp(0.6 * STDEV.S(B[0:6]) / AVERAGE(B[0:6]), 0.03, 0.08)``.
* ``[C]`` ``floor_i + (budget - Σfloor) * (0.6 * decayShare_i + 0.4 *
  spineShare_i)`` where ``floor_i = 1 + [r == 4]`` dollars,
  ``decayShare_i = w_i / Σw`` with ``w_i = B_i * e^(-k i) * (1 - 0.2 e^(-0.12 i))``,
  ``spineShare_i = max(E_i - 1, 0) / Σ max(E_j - 1, 0)``.
* ``[I]`` ``ROUNDDOWN(C_i * 2, 0)`` — floored half-dollar units.
* ``[J]`` ``C_i * 2 - I_i`` — the fractional remainder.
* ``[K]`` remainder priority (the ``budget*2 - ΣI`` largest remainders earn
  one unit; a tie AT the cutoff goes to the earlier draft position — owner
  decision 2026-10-18, see below), then the late-round caps (round 5: 4 units,
  round 6: 2 units) and monotonicity (``K_i <= K_{i-1}``).  Row 2 (pick 1.01)
  has neither cap nor predecessor, exactly as in the sheet.
* ``[D]`` ``(K_i + carry_i) / 2`` where the residual ``S = budget*2 - ΣK`` is
  spread over the first ``M1`` picks: ``QUOTIENT(S, M1) + [i < MOD(S, M1)]``.
  ``M1`` (sheet cell ``M1``, value 12) is a protected rounding parameter.
* ``[L]`` ``= D`` — the half-dollar curve: the mathematical reference.
* **whole dollars** (owner decision 2026-10-18, a separately identified final
  step): :func:`~src.draft.rookie_auction.apportion.apportion_whole_dollars`
  floors L, gives the residual to the largest remainders (earlier pick first
  on ties) and verifies sum / monotonicity / floors / caps, or refuses.
  :attr:`CurveResult.final_whole_dollars` holds the 72 published integers.

Arithmetic.  Every integer stage (I, J's ranking, K, D) is decided by the
real-valued column C, which involves ``exp`` and a standard deviation.  C is
evaluated in :class:`decimal.Decimal` at :data:`DECIMAL_PRECISION` significant
digits (correctly rounded ``exp`` / ``sqrt``) and the spine in exact
:class:`fractions.Fraction`; the outputs are integer half-dollar units, so
there is no float drift anywhere.  The spreadsheet itself evaluates in IEEE
doubles, so the result also reports :attr:`CurveResult.precision_margin` —
the smallest distance between any decision quantity and its decision
boundary.  A margin far above double-precision noise (~1e-12 here) proves the
spreadsheet and this module take the same integer decisions; a margin near
zero is surfaced, never hidden.

Invariants checked on every result (violations raise
:class:`CurveInvariantError`, never a silently different number): the final
units sum to exactly ``budget * units_per_dollar``, every pick is
non-negative, and the final curve is non-increasing.

The one departure from the literal sheet (owner decision 2026-10-18): the
sheet's ``RANK`` gives equal remainders the same rank, so a tie straddling
the award cutoff over-awards and the sheet publishes e.g. $1,206.  This module
awards exactly the residual, ties to the earlier draft position, so the
half-dollar curve always totals the budget.  With no tie at the cutoff —
including the real workbook inputs — the two rules are identical (pinned by
test); ``allocate_units(tie_rule="sheet_literal")`` keeps the literal rule
for evidence only.

Out of scope here, deliberately: which rookie values feed column B (Batch B),
which completed drafts form the spine (Batch C / ``snapshots.py``), who owns
which pick (``src/identity/picks.py``), and the draft order
(``src/public_league/draft_order.py``).  Package Value Adjustment never
applies to these dollars.  Pure, stdlib-only, no I/O.
"""

from __future__ import annotations

import decimal
import hashlib
import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, Mapping, Sequence

from src.draft.rookie_auction.apportion import (
    ApportionmentRefused,
    WholeDollarApportionment,
    apportion_whole_dollars,
)

__all__ = [
    "DECIMAL_PRECISION",
    "FORMULA_VERSION",
    "CurveInputError",
    "CurveInvariantError",
    "CurveParams",
    "CurveResult",
    "PickRow",
    "UnitAllocation",
    "WORKBOOK_PARAMS",
    "TIE_RULE_EARLIER_PICK_FIRST",
    "TIE_RULE_SHEET_LITERAL",
    "allocate_units",
    "check_allocation",
    "compute_curve",
    "curve_receipt",
    "spine_from_curves",
    "whole_dollar_constraints",
    "whole_dollar_step",
]

#: Identity of the transcribed formula.  Bump only with an owner-approved
#: methodology change; snapshots record it so a curve computed under one
#: version is never compared as if it came from another.
FORMULA_VERSION = "draft_data_workbook_v1"

#: Significant digits for the Decimal evaluation of column C.
DECIMAL_PRECISION = 60

#: K-step remainder award at a tie on the cutoff (owner decision 2026-10-18).
TIE_RULE_EARLIER_PICK_FIRST = "earlier_pick_first"
TIE_RULE_SHEET_LITERAL = "sheet_literal"


class CurveInputError(ValueError):
    """The inputs cannot be evaluated by the spreadsheet formula."""


class CurveInvariantError(RuntimeError):
    """Spreadsheet semantics produced a result that breaks a curve invariant."""


def _dec(text: str) -> Decimal:
    return Decimal(text)


@dataclass(frozen=True)
class CurveParams:
    """Every constant the spreadsheet formula uses, named.

    The defaults (:data:`WORKBOOK_PARAMS`) are the literal values in the
    workbook.  ``budget_dollars`` is the sheet's ``1200``; ``units_per_dollar``
    its ``*2`` / ``/2`` (half-dollar units); ``carry_picks`` its ``$M$1``.
    The sheet hard-codes ``1200-84``: 84 is ``Σ floor`` for the default
    config (72 picks x $1 + 12 round-5 picks x $1), and this module derives
    it from the floors rather than carrying the literal.
    """

    budget_dollars: int = 1200
    team_count: int = 12
    rounds: int = 6
    carry_picks: int = 12
    units_per_dollar: int = 2
    base_floor_dollars: int = 1
    #: 1-based round -> extra floor dollars (sheet: ``--(INT(..)/12)=4)``).
    round_floor_bonus_dollars: Mapping[int, int] = field(default_factory=lambda: {5: 1})
    #: 1-based round -> cap in units (sheet: ``IF(..=4, 4, IF(..=5, 2, 10^9))``).
    round_cap_units: Mapping[int, int] = field(default_factory=lambda: {5: 4, 6: 2})
    decay_head_count: int = 6
    decay_coefficient: Decimal = _dec("0.6")
    decay_rate_min: Decimal = _dec("0.03")
    decay_rate_max: Decimal = _dec("0.08")
    shape_amplitude: Decimal = _dec("0.2")
    shape_rate: Decimal = _dec("0.12")
    rookie_weight: Decimal = _dec("0.6")
    spine_weight: Decimal = _dec("0.4")
    spine_curve_count: int = 3

    @property
    def pick_count(self) -> int:
        return self.team_count * self.rounds

    @property
    def budget_units(self) -> int:
        return self.budget_dollars * self.units_per_dollar

    def floor_dollars(self, index: int) -> int:
        return self.base_floor_dollars + int(
            self.round_floor_bonus_dollars.get(index // self.team_count + 1, 0)
        )

    def cap_units(self, index: int) -> int | None:
        cap = self.round_cap_units.get(index // self.team_count + 1)
        return None if cap is None else int(cap)

    def validate(self) -> None:
        ints = {
            "budget_dollars": self.budget_dollars,
            "team_count": self.team_count,
            "rounds": self.rounds,
            "carry_picks": self.carry_picks,
            "units_per_dollar": self.units_per_dollar,
            "decay_head_count": self.decay_head_count,
            "spine_curve_count": self.spine_curve_count,
        }
        for name, value in ints.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise CurveInputError(f"{name} must be a positive integer, got {value!r}")
        if self.carry_picks > self.pick_count:
            raise CurveInputError("carry_picks (M1) cannot exceed the number of picks")
        if self.decay_head_count < 2 or self.decay_head_count > self.pick_count:
            raise CurveInputError("decay_head_count must be in [2, pick_count] (STDEV.S)")
        floor_total = sum(self.floor_dollars(i) for i in range(self.pick_count))
        if floor_total > self.budget_dollars:
            raise CurveInputError("floors exceed the budget")


WORKBOOK_PARAMS = CurveParams()


@dataclass(frozen=True)
class PickRow:
    """One pick, carrying every intermediate column of the sheet."""

    index: int
    round: int
    slot: int
    label: str
    rookie_value: Decimal  # B
    spine_inputs: tuple[Fraction, ...]  # F, G, H
    spine: Fraction  # E
    decay_weight: Decimal  # B_i * e^(-k i) * (1 - 0.2 e^(-0.12 i))
    decay_share: Decimal
    spine_share: Decimal
    floor_dollars: int
    curve_value: Decimal  # C
    floor_units: int  # I
    fraction: Decimal  # J
    remainder_rank: int  # RANK(J_i, J, 0)
    remainder_award: int  # 0 / 1
    cap_units: int | None
    monotone_units: int  # K
    carry_units: int  # the D-column residual share (first M1 picks)
    final_units: int  # 2 * D
    final_dollars: Decimal  # D == L


@dataclass(frozen=True)
class CurveResult:
    params: CurveParams
    formula_version: str
    decay_rate: Decimal
    floor_pool_dollars: int  # the sheet's literal 84
    residual_after_floor_units: int  # budget*2 - ΣI
    residual_after_caps_units: int  # budget*2 - ΣK
    carry_quotient: int  # QUOTIENT(S, M1)
    carry_mod: int  # MOD(S, M1)
    rows: tuple[PickRow, ...]
    total_units: int
    precision_margin: Decimal | None
    #: The final whole-dollar allocation (owner decision 2026-10-18), or
    #: ``None`` with ``whole_dollars_refusal`` naming the violated constraint.
    whole_dollars: WholeDollarApportionment | None = None
    whole_dollars_refusal: str | None = None

    @property
    def final_whole_dollars(self) -> tuple[int, ...]:
        """The 72 published whole-dollar pick values.  Raises if refused."""
        if self.whole_dollars is None:
            raise CurveInvariantError(f"whole-dollar step refused: {self.whole_dollars_refusal}")
        return self.whole_dollars.dollars

    @property
    def dollars(self) -> tuple[Decimal, ...]:
        return tuple(r.final_dollars for r in self.rows)

    @property
    def units(self) -> tuple[int, ...]:
        return tuple(r.final_units for r in self.rows)

    @property
    def total_dollars(self) -> Decimal:
        return Decimal(self.total_units) / Decimal(self.params.units_per_dollar)

    def grid(self) -> tuple[tuple[Decimal, ...], ...]:
        """The sheet's ``P2:AA7`` round x slot grid (row = round)."""
        n = self.params.team_count
        return tuple(
            tuple(self.rows[r * n + s].final_dollars for s in range(n))
            for r in range(self.params.rounds)
        )

    def round_totals(self) -> tuple[Decimal, ...]:
        """``AB2:AB7``."""
        return tuple(sum(row, Decimal(0)) for row in self.grid())

    def slot_totals(self) -> tuple[Decimal, ...]:
        """``P8:AA8`` — what each draft slot is worth across all rounds."""
        g = self.grid()
        return tuple(sum((g[r][s] for r in range(len(g))), Decimal(0)) for s in range(len(g[0])))


def _to_decimal(value: object, what: str) -> Decimal:
    if value is None:
        raise CurveInputError(f"{what} is missing (missing is never zero)")
    if isinstance(value, bool):
        raise CurveInputError(f"{what} must be a number, got {value!r}")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, float):
        d = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            d = Decimal(value.strip())
        except decimal.InvalidOperation as exc:
            raise CurveInputError(f"{what} is not a number: {value!r}") from exc
    elif isinstance(value, Fraction):
        d = _frac_to_dec(value)
    else:
        raise CurveInputError(f"{what} must be a number, got {type(value).__name__}")
    if not d.is_finite():
        raise CurveInputError(f"{what} must be finite, got {value!r}")
    return d


def _to_fraction(value: object, what: str) -> Fraction:
    d = _to_decimal(value, what)
    return Fraction(d)


def _frac_to_dec(f: Fraction) -> Decimal:
    return Decimal(f.numerator) / Decimal(f.denominator)


def _median(values: Sequence[Fraction]) -> Fraction:
    s = sorted(values)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def spine_from_curves(curves: Sequence[Sequence[object]], params: CurveParams = WORKBOOK_PARAMS):
    """Column E: ``(MEDIAN(F:H) + AVERAGE(F:H)) / 2`` per pick, exact."""
    if len(curves) != params.spine_curve_count:
        raise CurveInputError(
            f"expected {params.spine_curve_count} historical curves, got {len(curves)}"
        )
    n = params.pick_count
    clean: list[list[Fraction]] = []
    for c_idx, curve in enumerate(curves):
        if len(curve) != n:
            raise CurveInputError(f"historical curve {c_idx} has {len(curve)} picks, need {n}")
        clean.append(
            [_to_fraction(v, f"historical curve {c_idx} pick {i}") for i, v in enumerate(curve)]
        )
    spine: list[tuple[tuple[Fraction, ...], Fraction]] = []
    for i in range(n):
        vals = tuple(c[i] for c in clean)
        e = (_median(vals) + sum(vals, Fraction(0)) / len(vals)) / 2
        spine.append((vals, e))
    return spine


def _excel_quotient(n: int, d: int) -> int:
    """``QUOTIENT`` truncates toward zero (unlike Python ``//``)."""
    q = abs(n) // abs(d)
    return q if (n >= 0) == (d > 0) else -q


def _excel_mod(n: int, d: int) -> int:
    """``MOD`` takes the sign of the divisor — the same as Python ``%``."""
    return n % d


def _label(round_: int, slot: int) -> str:
    return f"{round_}.{slot:02d}"


def compute_curve(
    rookie_values: Sequence[object],
    historical_curves: Sequence[Sequence[object]],
    params: CurveParams = WORKBOOK_PARAMS,
) -> CurveResult:
    """Evaluate the spreadsheet formula.  See the module docstring."""
    params.validate()
    n = params.pick_count
    if len(rookie_values) != n:
        raise CurveInputError(f"expected {n} rookie values, got {len(rookie_values)}")
    with decimal.localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        ctx.rounding = decimal.ROUND_HALF_EVEN
        return _compute(rookie_values, historical_curves, params, n)


def _compute(rookie_values, historical_curves, params: CurveParams, n: int) -> CurveResult:
    b = [_to_decimal(v, f"rookie value pick {i}") for i, v in enumerate(rookie_values)]
    if any(v <= 0 for v in b):
        raise CurveInputError("rookie values must be strictly positive (zero is not a value)")
    spine = spine_from_curves(historical_curves, params)

    head = b[: params.decay_head_count]
    head_mean = sum(head, Decimal(0)) / len(head)
    if head_mean <= 0:
        raise CurveInputError("AVERAGE of the decay head is not positive (#DIV/0! in the sheet)")
    var = sum(((x - head_mean) ** 2 for x in head), Decimal(0)) / (len(head) - 1)
    ratio = params.decay_coefficient * var.sqrt() / head_mean
    k = max(params.decay_rate_min, min(params.decay_rate_max, ratio))

    weights = [
        b[i] * (-k * i).exp() * (1 - params.shape_amplitude * (-params.shape_rate * i).exp())
        for i in range(n)
    ]
    w_total = sum(weights, Decimal(0))
    if w_total <= 0:
        raise CurveInputError("decay weights sum to zero (#DIV/0! in the sheet)")
    excess = [(e - 1) if e > 1 else Fraction(0) for _, e in spine]
    excess_total = sum(excess, Fraction(0))
    if excess_total <= 0:
        raise CurveInputError("no spine value exceeds $1 (#DIV/0! in the sheet)")

    floors = [params.floor_dollars(i) for i in range(n)]
    floor_pool = sum(floors)
    pool = Decimal(params.budget_dollars - floor_pool)
    upd = params.units_per_dollar

    decay_share = [w / w_total for w in weights]
    spine_share = [_frac_to_dec(x / excess_total) for x in excess]
    c = [
        floors[i]
        + pool * (params.rookie_weight * decay_share[i] + params.spine_weight * spine_share[i])
        for i in range(n)
    ]
    alloc = allocate_units(c, params)

    rows = tuple(
        PickRow(
            index=i,
            round=i // params.team_count + 1,
            slot=i % params.team_count + 1,
            label=_label(i // params.team_count + 1, i % params.team_count + 1),
            rookie_value=b[i],
            spine_inputs=spine[i][0],
            spine=spine[i][1],
            decay_weight=weights[i],
            decay_share=decay_share[i],
            spine_share=spine_share[i],
            floor_dollars=floors[i],
            curve_value=c[i],
            floor_units=alloc.floor_units[i],
            fraction=alloc.fractions[i],
            remainder_rank=alloc.ranks[i],
            remainder_award=alloc.awards[i],
            cap_units=alloc.caps[i],
            monotone_units=alloc.monotone_units[i],
            carry_units=alloc.carry_units[i],
            final_units=alloc.final_units[i],
            final_dollars=Decimal(alloc.final_units[i]) / Decimal(upd),
        )
        for i in range(n)
    )
    result = CurveResult(
        params=params,
        formula_version=FORMULA_VERSION,
        decay_rate=k,
        floor_pool_dollars=floor_pool,
        residual_after_floor_units=alloc.residual_after_floor_units,
        residual_after_caps_units=alloc.residual_after_caps_units,
        carry_quotient=alloc.carry_quotient,
        carry_mod=alloc.carry_mod,
        rows=rows,
        total_units=alloc.total_units,
        precision_margin=alloc.precision_margin,
    )
    check_allocation(alloc, params)
    whole, refusal = whole_dollar_step(alloc.final_units, params)
    return replace(result, whole_dollars=whole, whole_dollars_refusal=refusal)


def whole_dollar_constraints(params: CurveParams = WORKBOOK_PARAMS):
    """Per-pick integer floors and caps (dollars) the whole-dollar step verifies.

    Floors: $1 per pick plus the round-5 bonus (the formula's own floors).
    Caps: the round caps converted from units (round 5 = $2, round 6 = $1);
    pick 1.01 is uncapped, like K2.
    """
    n = params.pick_count
    floors = [params.floor_dollars(i) for i in range(n)]
    caps: list[int | None] = []
    for i in range(n):
        cap = params.cap_units(i) if i > 0 else None
        if cap is not None and cap % params.units_per_dollar:
            raise CurveInputError(f"round cap of {cap} units is not a whole-dollar amount")
        caps.append(None if cap is None else cap // params.units_per_dollar)
    return floors, caps


def whole_dollar_step(final_units: Sequence[int], params: CurveParams = WORKBOOK_PARAMS):
    """``(apportionment, None)`` or ``(None, conflict)`` for a unit curve."""
    floors, caps = whole_dollar_constraints(params)
    values = [Fraction(u, params.units_per_dollar) for u in final_units]
    try:
        return (
            apportion_whole_dollars(values, params.budget_dollars, floors=floors, caps=caps),
            None,
        )
    except ApportionmentRefused as exc:
        return None, str(exc)


@dataclass(frozen=True)
class UnitAllocation:
    """Columns I, J, K and D for a given column C (the integer stage)."""

    floor_units: tuple[int, ...]  # I
    fractions: tuple[Decimal, ...]  # J
    ranks: tuple[int, ...]  # RANK(J_i, J, 0) — ties share a rank
    awards: tuple[int, ...]
    caps: tuple[int | None, ...]
    monotone_units: tuple[int, ...]  # K
    residual_after_floor_units: int
    residual_after_caps_units: int
    carry_quotient: int
    carry_mod: int
    carry_units: tuple[int, ...]
    final_units: tuple[int, ...]  # 2 * D
    precision_margin: Decimal | None

    @property
    def total_units(self) -> int:
        return sum(self.final_units)


def allocate_units(
    curve_values: Sequence[object],
    params: CurveParams = WORKBOOK_PARAMS,
    *,
    check: bool = False,
    tie_rule: str = TIE_RULE_EARLIER_PICK_FIRST,
) -> UnitAllocation:
    """The sheet's integer stage (I -> J -> K -> D) over a given column C.

    ``tie_rule``:

    * ``earlier_pick_first`` (default; owner decision 2026-10-18) — exactly
      ``residual`` units are awarded, to the largest remainders, ties at the
      cutoff going to the earlier (higher) draft position.  Identical to the
      sheet whenever no tie straddles the cutoff — which includes the real
      workbook inputs — and otherwise the one place the canonical curve
      departs from the literal sheet: the half-dollar total is always exactly
      the budget.
    * ``sheet_literal`` — the sheet's ``RANK(...) <= residual``, where equal
      remainders share a rank and a tie at the cutoff over-awards (the sheet
      then publishes e.g. $1,206).  Kept only as evidence of what the sheet
      does; ``check=False`` returns that result unrefused.

    :func:`compute_curve` always uses the default rule and always checks.
    """
    if tie_rule not in (TIE_RULE_EARLIER_PICK_FIRST, TIE_RULE_SHEET_LITERAL):
        raise CurveInputError(f"unknown tie rule {tie_rule!r}")
    params.validate()
    n = params.pick_count
    if len(curve_values) != n:
        raise CurveInputError(f"expected {n} curve values, got {len(curve_values)}")
    with decimal.localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        c = [_to_decimal(v, f"curve value pick {i}") for i, v in enumerate(curve_values)]
        upd = params.units_per_dollar
        budget_units = params.budget_units
        doubled = [x * upd for x in c]
        # ROUNDDOWN(x, 0) truncates toward zero (a floor for positive C).
        i_units = [int(x.to_integral_value(rounding=decimal.ROUND_DOWN)) for x in doubled]
        j = [doubled[i] - i_units[i] for i in range(n)]
        residual = budget_units - sum(i_units)
        ranks = [1 + sum(1 for other in j if other > j[i]) for i in range(n)]
        if tie_rule == TIE_RULE_SHEET_LITERAL:
            awards = [1 if ranks[i] <= residual else 0 for i in range(n)]
        else:
            order = sorted(range(n), key=lambda i: (-j[i], i))
            awarded = set(order[: max(0, residual)])
            awards = [1 if i in awarded else 0 for i in range(n)]

        # K2 (index 0) has no MIN(): no cap and no predecessor.
        caps = [None] + [params.cap_units(i) for i in range(1, n)]
        k_units: list[int] = []
        for i in range(n):
            candidate = i_units[i] + awards[i]
            if i == 0:
                k_units.append(candidate)
                continue
            bound = caps[i] if caps[i] is not None else 10**9
            k_units.append(min(candidate, bound, k_units[i - 1]))

        s = budget_units - sum(k_units)
        m1 = params.carry_picks
        q = _excel_quotient(s, m1)
        mod = _excel_mod(s, m1)
        carry = [(q + (1 if i < mod else 0)) if i < m1 else 0 for i in range(n)]
        final_units = [k_units[i] + carry[i] for i in range(n)]
        alloc = UnitAllocation(
            floor_units=tuple(i_units),
            fractions=tuple(j),
            ranks=tuple(ranks),
            awards=tuple(awards),
            caps=tuple(caps),
            monotone_units=tuple(k_units),
            residual_after_floor_units=residual,
            residual_after_caps_units=s,
            carry_quotient=q,
            carry_mod=mod,
            carry_units=tuple(carry),
            final_units=tuple(final_units),
            precision_margin=_precision_margin(doubled, j, residual),
        )
    if check:
        check_allocation(alloc, params)
    return alloc


def _precision_margin(doubled: Sequence[Decimal], j: Sequence[Decimal], residual: int):
    """Smallest distance between a decision quantity and its boundary.

    Two kinds of integer decision depend on the real-valued C: the floor of
    ``2C`` (distance of ``2C`` to the nearest integer) and the remainder
    award (the gap between the last awarded and the first unawarded J).
    """
    margins: list[Decimal] = []
    for x in doubled:
        frac = x - x.to_integral_value(rounding=decimal.ROUND_FLOOR)
        margins.append(min(frac, 1 - frac))
    ordered = sorted(j, reverse=True)
    if 0 < residual < len(ordered):
        margins.append(ordered[residual - 1] - ordered[residual])
    return min(margins) if margins else None


def check_allocation(alloc: UnitAllocation, params: CurveParams = WORKBOOK_PARAMS) -> None:
    """Refuse a result that breaks the pool invariants (never 'fix' it)."""
    expected = params.budget_units
    if alloc.total_units != expected:
        raise CurveInvariantError(
            f"final units sum to {alloc.total_units}, not {expected} "
            f"(spreadsheet semantics; residual after caps {alloc.residual_after_caps_units}; "
            "an exact RANK tie at the award cutoff needs an owner-approved tie-break)"
        )
    units = alloc.final_units
    if any(u < 0 for u in units):
        raise CurveInvariantError("a pick is worth less than $0")
    for i in range(1, len(units)):
        if units[i] > units[i - 1]:
            raise CurveInvariantError(
                f"curve rises at pick index {i} ({units[i - 1]} -> {units[i]} units)"
            )


def iter_labels(params: CurveParams = WORKBOOK_PARAMS) -> Iterable[str]:
    for i in range(params.pick_count):
        yield _label(i // params.team_count + 1, i % params.team_count + 1)


def _sha(obj: object) -> str:
    text = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dstr(d: Decimal | Fraction, places: int = 30) -> str:
    if isinstance(d, Fraction):
        d = _frac_to_dec(d)
    return format(d.quantize(Decimal(1).scaleb(-places)).normalize(), "f")


def curve_receipt(
    result: CurveResult,
    *,
    spine_years: Sequence[int] | None = None,
    input_provenance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """A JSON-serialisable, self-hashing receipt of one curve evaluation.

    Records the input hashes, the spine years (``None`` when the caller did
    not say — never guessed), the formula version and parameters, checksums
    of every intermediate column, the rounding carry, the exact total and the
    validation outcome.  ``receiptSha256`` covers everything else.
    """
    with decimal.localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        rows = result.rows
        p = result.params
        body: dict[str, object] = {
            "formulaVersion": result.formula_version,
            "params": {
                "budgetDollars": p.budget_dollars,
                "teamCount": p.team_count,
                "rounds": p.rounds,
                "carryPicksM1": p.carry_picks,
                "unitsPerDollar": p.units_per_dollar,
                "roundFloorBonusDollars": {
                    str(k): v for k, v in sorted(p.round_floor_bonus_dollars.items())
                },
                "roundCapUnits": {str(k): v for k, v in sorted(p.round_cap_units.items())},
                "rookieWeight": str(p.rookie_weight),
                "spineWeight": str(p.spine_weight),
            },
            "inputs": {
                "rookieValuesSha256": _sha([_dstr(r.rookie_value) for r in rows]),
                "historicalCurvesSha256": [
                    _sha([_dstr(r.spine_inputs[k]) for r in rows])
                    for k in range(len(rows[0].spine_inputs))
                ],
                "spineYears": list(spine_years) if spine_years is not None else None,
                "provenance": dict(input_provenance) if input_provenance is not None else None,
            },
            "decayRate": _dstr(result.decay_rate),
            "floorPoolDollars": result.floor_pool_dollars,
            "residualAfterFloorUnits": result.residual_after_floor_units,
            "residualAfterCapsUnits": result.residual_after_caps_units,
            "carryQuotient": result.carry_quotient,
            "carryMod": result.carry_mod,
            "intermediateChecksums": {
                "E": _sha([_dstr(r.spine) for r in rows]),
                "C": _sha([_dstr(r.curve_value) for r in rows]),
                "I": _sha([r.floor_units for r in rows]),
                "J": _sha([_dstr(r.fraction) for r in rows]),
                "K": _sha([r.monotone_units for r in rows]),
                "D": _sha([r.final_units for r in rows]),
            },
            "finalUnits": [r.final_units for r in rows],
            "totalDollars": format(result.total_dollars.normalize(), "f"),
            "precisionMargin": None
            if result.precision_margin is None
            else _dstr(result.precision_margin),
            "validation": {"sumsToBudget": True, "nonNegative": True, "nonIncreasing": True},
            "tieRule": TIE_RULE_EARLIER_PICK_FIRST,
            "wholeDollars": (
                result.whole_dollars.receipt([r.label for r in rows])
                if result.whole_dollars is not None
                else {"refused": result.whole_dollars_refusal}
            ),
        }
    body["receiptSha256"] = _sha(body)
    return body
