"""INDEPENDENT literal transcription of the ``Draft Data`` workbook formulas.

This is verification code, not production code.  It deliberately imports
nothing from ``src/`` and shares no helper with
``src/draft/rookie_auction/curve.py``: it evaluates the sheet the way the
spreadsheet does — cell by cell, in IEEE doubles, with spreadsheet function
semantics (``ROUNDDOWN`` truncates, ``RANK`` gives ties the same rank,
``QUOTIENT`` truncates toward zero, ``MOD`` takes the divisor's sign,
``STDEV.S`` is the sample deviation, ``INT`` floors).  Each column function
quotes the formula it transcribes, and :data:`FORMULA_TEMPLATES` holds the
whitespace-free formula text for every templated column so a test can prove
the transcription still matches the workbook's formulas verbatim.

Three independent things must then agree: the workbook's cached values, this
transcription, and the production module.
"""

from __future__ import annotations

import math
import re

FIRST, LAST = 2, 73  # rows of the pick table
BUDGET = 1200

_C = (
    "=1+--(INT((ROW()-ROW($B$2))/12)=4)+(1200-84)*(0.6*((B{r}+0)*EXP(-(MAX(0.03,MIN(0.08,"
    "0.6*_xlfn.STDEV.S($B$2:$B$7)/AVERAGE($B$2:$B$7))))*(ROW()-ROW($B$2)))*(1-0.2*EXP(-0.12*"
    "(ROW()-ROW($B$2)))))/SUMPRODUCT(($B$2:$B$73+0)*EXP(-(MAX(0.03,MIN(0.08,0.6*_xlfn.STDEV.S("
    "$B$2:$B$7)/AVERAGE($B$2:$B$7))))*(ROW($B$2:$B$73)-ROW($B$2)))*(1-0.2*EXP(-0.12*(ROW("
    "$B$2:$B$73)-ROW($B$2)))))+0.4*(((E{r}-1)*(E{r}>1))/SUMPRODUCT(($E$2:$E$73-1)*($E$2:$E$73>1))))"
)

#: Whitespace-free formula text per column; ``{r}`` = this row, ``{p}`` = row-1.
FORMULA_TEMPLATES: dict[str, str] = {
    "C": _C,
    "D": (
        "=(K{r}+IF(ROW()-ROW($K$2)<$M$1,QUOTIENT(1200*2-SUM($K$2:$K$73),$M$1)"
        "+--(ROW()-ROW($K$2)<MOD(1200*2-SUM($K$2:$K$73),$M$1)),0))/2"
    ),
    "E": "=(MEDIAN(F{r}:H{r})+AVERAGE(F{r}:H{r}))/2",
    "I": "=ROUNDDOWN(C{r}*2,0)",
    "J": "=C{r}*2-I{r}",
    "K2": "=I2+--(RANK(J2,$J$2:$J$73,0)<=1200*2-SUM($I$2:$I$73))",
    "K": (
        "=MIN(I{r}+--(RANK(J{r},$J$2:$J$73,0)<=1200*2-SUM($I$2:$I$73)),"
        "IF(INT((ROW()-ROW($C$2))/12)=4,4,IF(INT((ROW()-ROW($C$2))/12)=5,2,10^9)),K{p})"
    ),
    "L": "=D{r}",
    "grid": "=INDEX($L$1:$L$73,2+(ROW()-ROW($P$2))*12+(COLUMN()-COLUMN($P$2)))",
    "AD1": "=1200/SUM($P$2:$AA$7)",
    "Q": "=INDEX($P$2:$AA$7,O{r},P{r})*$AD$1",
    "O": "=INT((ROW()-ROW($O$45))/12)+1",
    "P": "=MOD(ROW()-ROW($P$45),12)+1",
    "R": (
        '=IF(INDEX($S$30:$S$41,MATCH(P{r},$R$30:$R$41,0))<>"",INDEX($T$30:$T$41,MATCH(P{r},'
        '$R$30:$R$41,0)),IFERROR(INDEX($X$30:$X$202,MATCH(TEXT(O{r},"0")&"|"&TRIM(INDEX('
        "$P$30:$P$41,MATCH(13-P{r},$O$30:$O$41,0))),$Y$30:$Y$202,0)),INDEX($P$30:$P$41,"
        "MATCH(13-P{r},$O$30:$O$41,0))))"
    ),
    "T": '=IF(S{r}<>"",S{r},INDEX($P$30:$P$41,MATCH(13-R{r},$O$30:$O$41,0)))',
    "Y": '=TEXT(V{r},"0")&"|"&TRIM(W{r})',
    "U": "=SUMIF($R$45:$R$116,T{r},$Q$45:$Q$116)",
    "M123": (
        "=ROUNDDOWN(C2,0)+--((1+SUMPRODUCT(--(($C$2:$C$73-ROUNDDOWN($C$2:$C$73,0))>(C2-"
        "ROUNDDOWN(C2,0))))+SUMPRODUCT(--(($C$2:$C$73-ROUNDDOWN($C$2:$C$73,0))=(C2-ROUNDDOWN("
        "C2,0))),--(ROW($C$2:$C$73)<ROW())))<=1200-SUMPRODUCT(ROUNDDOWN($C$2:$C$73,0)))"
    ),
}


def normalize_formula(text: str) -> str:
    return re.sub(r"\s+", "", text)


# --- spreadsheet function semantics -------------------------------------------------


def ROUNDDOWN(x: float, digits: int = 0) -> int:
    assert digits == 0
    return math.trunc(x)


def INT(x: float) -> int:
    return math.floor(x)


def QUOTIENT(n: float, d: float) -> int:
    return math.trunc(n / d)


def MOD(n: float, d: float) -> float:
    return n - d * math.floor(n / d)


def AVERAGE(xs) -> float:
    xs = list(xs)
    return sum(xs) / len(xs)


def MEDIAN(xs) -> float:
    s = sorted(xs)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def STDEV_S(xs) -> float:
    xs = list(xs)
    mu = AVERAGE(xs)
    return math.sqrt(sum((x - mu) ** 2 for x in xs) / (len(xs) - 1))


def RANK(x: float, rng, order: int = 0) -> int:
    assert order == 0  # descending
    return 1 + sum(1 for v in rng if v > x)


def B2I(flag: bool) -> int:  # the sheet's ``--(cond)``
    return 1 if flag else 0


# --- the sheet ----------------------------------------------------------------------


def evaluate_sheet(
    B: dict[int, float], F: dict[int, float], G: dict[int, float], H: dict[int, float], M1: int = 12
) -> dict[str, dict[int, float]]:
    """Evaluate columns E, C, I, J, K, D, L for rows 2..73 exactly as the sheet does.

    Inputs are keyed by SHEET ROW (2..73), like the cells they came from.
    """
    rows = range(FIRST, LAST + 1)

    def ROW_RANGE():
        return rows

    # E{r} = (MEDIAN(F:H)+AVERAGE(F:H))/2
    E = {r: (MEDIAN([F[r], G[r], H[r]]) + AVERAGE([F[r], G[r], H[r]])) / 2 for r in rows}

    head = [B[r] for r in range(2, 8)]  # $B$2:$B$7
    rate = max(0.03, min(0.08, 0.6 * STDEV_S(head) / AVERAGE(head)))
    decay_den = sum(
        (B[q] + 0) * math.exp(-rate * (q - 2)) * (1 - 0.2 * math.exp(-0.12 * (q - 2)))
        for q in ROW_RANGE()
    )
    spine_den = sum((E[q] - 1) * B2I(E[q] > 1) for q in ROW_RANGE())

    C: dict[int, float] = {}
    for r in rows:
        decay_num = (B[r] + 0) * math.exp(-rate * (r - 2)) * (1 - 0.2 * math.exp(-0.12 * (r - 2)))
        C[r] = (
            1
            + B2I(INT((r - 2) / 12) == 4)
            + (1200 - 84)
            * (0.6 * decay_num / decay_den + 0.4 * (((E[r] - 1) * B2I(E[r] > 1)) / spine_den))
        )

    out = evaluate_integer_stage(C, M1)
    out.update({"E": E, "C": C, "_rate": {0: rate}})
    return out


def evaluate_integer_stage(C: dict[int, float], M1: int = 12) -> dict[str, dict[int, float]]:
    """Columns I, J, K, D, L for a given column C (keyed by sheet row 2..73)."""
    rows = range(FIRST, LAST + 1)
    I = {r: ROUNDDOWN(C[r] * 2, 0) for r in rows}  # noqa: E741 — the sheet's column name
    J = {r: C[r] * 2 - I[r] for r in rows}
    J_range = [J[q] for q in rows]
    residual = 1200 * 2 - sum(I.values())

    K: dict[int, int] = {}
    for r in rows:
        award = B2I(RANK(J[r], J_range, 0) <= residual)
        if r == 2:
            K[r] = I[r] + award  # K2: no MIN, no cap
        else:
            cap = 4 if INT((r - 2) / 12) == 4 else (2 if INT((r - 2) / 12) == 5 else 10**9)
            K[r] = min(I[r] + award, cap, K[r - 1])

    k_sum = sum(K.values())
    D: dict[int, float] = {}
    for r in rows:
        if (r - 2) < M1:
            extra = QUOTIENT(1200 * 2 - k_sum, M1) + B2I((r - 2) < MOD(1200 * 2 - k_sum, M1))
        else:
            extra = 0
        D[r] = (K[r] + extra) / 2
    L = dict(D)
    return {"I": I, "J": J, "K": K, "D": D, "L": L, "_residual": {0: residual}}


def evaluate_grid(L: dict[int, float]) -> dict[str, object]:
    """P2:AA7, AB2:AB7, P8:AA8, AB8, AD1 and Q45:Q116."""
    cols = "P Q R S T U V W X Y Z AA".split()
    grid = {}
    for gr in range(2, 8):
        for ci, col in enumerate(cols):
            idx = 2 + (gr - 2) * 12 + ci  # INDEX($L$1:$L$73, ...) is 1-based from L1
            grid[f"{col}{gr}"] = L[idx]  # L1 is the header, so INDEX k -> row k
    ab = {f"AB{gr}": sum(grid[f"{c}{gr}"] for c in cols) for gr in range(2, 8)}
    row8 = {f"{c}8": sum(grid[f"{c}{gr}"] for gr in range(2, 8)) for c in cols}
    ab8 = sum(ab.values())
    ad1 = 1200 / sum(grid.values())
    q = {}
    for r in range(45, 117):
        o = INT((r - 45) / 12) + 1
        p = int(MOD(r - 45, 12) + 1)
        q[r] = grid[f"{cols[p - 1]}{o + 1}"] * ad1
    return {"grid": grid, "AB": ab, "row8": row8, "AB8": ab8, "AD1": ad1, "Q": q}


def evaluate_ownership(
    standings: dict[int, tuple[float, str, str | None, float]],
    trades: dict[str, str],
    Q: dict[int, float],
) -> dict[str, object]:
    """T30:T41, R45:R116 and U63:U74.

    ``standings`` maps sheet row 30..41 -> (O rank, P owner, S override, R pick#).
    ``trades`` maps the Y key ("round|original owner") -> X new owner.
    """

    def owner_by_rank(rank):
        for row, (o, p, _s, _r) in standings.items():
            if o == rank:
                return p
        raise KeyError(rank)

    T = {}
    for row, (_o, _p, s, rpick) in standings.items():
        T[row] = s if s not in (None, "") else owner_by_rank(13 - rpick)

    R = {}
    for r in range(45, 117):
        o = INT((r - 45) / 12) + 1
        p = int(MOD(r - 45, 12) + 1)
        slot_row = next(row for row, v in standings.items() if v[3] == p)
        if standings[slot_row][2] not in (None, ""):
            R[r] = T[slot_row]
        else:
            key = f"{o}|{owner_by_rank(13 - p).strip()}"  # TEXT(O,"0")&"|"&TRIM(...)
            # IFERROR(INDEX(X, MATCH(key, Y, 0)), original): a found key wins even when X is
            # blank; ``trades`` holds the FIRST row of each key, as MATCH(..., 0) does.
            R[r] = trades[key] if key in trades else owner_by_rank(13 - p)
    return {"T": T, "R": R}


def team_totals(names: dict[int, str], R: dict[int, str], Q: dict[int, float]) -> dict[int, float]:
    """U63:U74 = SUMIF($R$45:$R$116, T, $Q$45:$Q$116)."""
    return {row: sum(Q[r] for r in range(45, 117) if R[r] == name) for row, name in names.items()}


def evaluate_m123(C: dict[int, float]) -> int:
    """The orphan whole-dollar largest-remainder cell M123 (row 2 frame)."""
    frac = {r: C[r] - ROUNDDOWN(C[r], 0) for r in C}
    me = 2
    rank = (
        1
        + sum(1 for r in C if frac[r] > frac[me])
        + sum(1 for r in C if frac[r] == frac[me] and r < 123)
    )
    return ROUNDDOWN(C[me], 0) + B2I(rank <= 1200 - sum(ROUNDDOWN(C[r], 0) for r in C))
