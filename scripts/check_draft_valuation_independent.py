#!/usr/bin/env python3
"""Independent checker for the rookie-auction curve and per-class pick dollars (Batch G).

Run isolated so nothing from the production code can be imported::

    python3 -I scripts/check_draft_valuation_independent.py \\
        --production prod.json [--repo .] [--json report.json]

``--production`` is a JSON dump of what production computes and serves
(``scripts/draft_valuation_dump_production.py`` writes it): the curve over
the workbook's own inputs (the pinned golden), and, per generated class
(2027 / 2028 / 2029 for ``dynasty_main``), the served reference and whole
dollars, spine years and record checksum.

What this checker uses, and what it never uses:

* It imports NOTHING from ``src/`` or ``server.py``.  Its only code
  dependency is the Batch A literal transcription
  ``tests/draft_valuation/reference_workbook_formulas.py`` — verification
  code that evaluates the sheet cell by cell in IEEE doubles with
  spreadsheet function semantics and imports only the standard library.  It
  is loaded by file path, and refused if it ever imports anything else.
* Its inputs are DATA: the owner workbook transcription and its cached
  values (``tests/fixtures/draft_valuation/``), the owner package goldens,
  and the repo-tracked snapshot files under ``config/draft_valuation/``
  (frozen inputs, completed-class curves, stored published allocations).
  Every snapshot is cross-checked against the workbook transcription it was
  extracted from (column B for the frozen inputs, F/G/H for the spine
  classes) and against its own checksum.

Checks (each PASS or FAIL; nothing is tolerance-hidden — half-dollar and
whole-dollar values are compared exactly):

1. provenance — the fixtures are the owner workbook (sha256 pinned), the
   frozen inputs equal column B, each spreadsheet-sourced spine class equals
   its workbook column, every snapshot checksum recomputes;
2. golden — the transcription over the workbook's inputs reproduces the
   workbook's cached column L and the package goldens 72/72, and the
   production curve over the same inputs equals it (half dollars and whole
   dollars);
3. per class — for every generated class: this checker's spine (the three
   most recent completed classes on file strictly before it), its own
   evaluation of the formula over the frozen inputs and that spine (with the
   owner's earlier-pick-first K-step tie rule), its own whole-dollar step
   (largest remainder, else an exact forward DP), and exact equality with
   the production dump and the stored record for that year;
4. invariants — integers, each class exactly $1,200, non-increasing,
   floors / caps, All Years $3,600, whole dollars optimal (a forward DP
   bounded by the step-A deviation finds nothing better and the same
   lexicographic answer);
5. double-precision margin — the transcription computes in doubles, so every
   integer decision (the floor of 2C, the remainder ranking at the award
   cutoff) must clear double noise by a wide margin; a decision inside the
   noise is a FAIL ("cannot certify"), never a silent agreement.

Exit 0 when every check passes, 1 otherwise.  Read-only; writes only the
optional ``--json`` report.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import math
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

LEAGUE_KEY = "dynasty_main"
TEAMS, ROUNDS, BUDGET, PICKS = 12, 6, 1200, 72
WORKBOOK_SHA256 = "50d130e5a34d0bb4c2b7ae02cf8dc2bc5a03081263e17a869ba8f8c2eb1dce88"
#: A double-precision decision closer than this to its boundary is not certified.
DECISION_MARGIN = 1e-9

RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append({"status": "PASS" if ok else "FAIL", "check": name, "detail": detail})
    return ok


def labels() -> list[str]:
    return [f"{r}.{s:02d}" for r in range(1, ROUNDS + 1) for s in range(1, TEAMS + 1)]


def checksum_of(payload: dict) -> str:
    body = {k: v for k, v in payload.items() if k != "checksum"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def exact(value) -> Fraction:
    """A JSON number or decimal string as an exact rational (floats exactly)."""
    if isinstance(value, bool):
        raise TypeError(f"not a number: {value!r}")
    if isinstance(value, str):
        return Fraction(Decimal(value))
    if isinstance(value, (int, float)):
        return Fraction(value)
    raise TypeError(f"not a number: {value!r}")


# --- the reference transcription (verification code, stdlib only) ------------------------


_STDLIB_ALLOWED = {"math", "re", "fractions", "__future__"}


def load_reference(repo: Path):
    path = repo / "tests" / "draft_valuation" / "reference_workbook_formulas.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "__import__":
            arg = node.args[0] if node.args else None
            if isinstance(arg, ast.Constant):
                imported.add(str(arg.value).split(".")[0])
    foreign = sorted(imported - _STDLIB_ALLOWED)
    if not check("reference transcription imports only the standard library", not foreign):
        raise SystemExit(f"reference transcription imports {foreign}")
    spec = importlib.util.spec_from_file_location("_independent_reference", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


# --- the formula, via the transcription ---------------------------------------------------


def evaluate(ref, b: list, curves: list[list]) -> dict:
    """Column L (half dollars, exact) + decision margins, for 72 inputs and 3 curves."""
    rows = range(2, 74)
    key = lambda seq: {r: float(seq[r - 2]) for r in rows}  # noqa: E731
    sheet = ref.evaluate_sheet(key(b), key(curves[0]), key(curves[1]), key(curves[2]), M1=12)
    owner = ref.evaluate_integer_stage(sheet["C"], 12, tie_rule="earlier_first")
    c = sheet["C"]
    doubled = [c[r] * 2 for r in rows]
    floor_margin = min(min(x - math.floor(x), math.ceil(x) - x) or 1.0 for x in doubled)
    # The remainder ranking only matters at the award cutoff: the smallest
    # awarded remainder vs the largest unawarded one.
    j = sorted((sheet["J"][r] for r in rows), reverse=True)
    residual = int(sheet["_residual"][0])
    cutoff_margin = abs(j[residual - 1] - j[residual]) if 0 < residual < len(j) else float("inf")
    literal_l = [Fraction(sheet["L"][r]) for r in rows]
    owner_l = [Fraction(owner["L"][r]) for r in rows]
    return {
        "L": owner_l,
        "literalL": literal_l,
        "floorMargin": floor_margin,
        "cutoffMargin": cutoff_margin,
        "cutoffTie": cutoff_margin == 0.0,
    }


def whole_dollars(ref, values: list[Fraction]) -> tuple[list[int] | None, str]:
    """Step A (largest remainder) else an exact forward DP; ``(None, why)`` when infeasible."""
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    try:
        out, _plus = ref.whole_dollars(values, BUDGET, floors=floors, caps=caps)
        return out, "largest_remainder"
    except ref.Refused:
        pass
    bound = Fraction(1, 2)
    while bound <= BUDGET:
        found = ref.forward_dp_min_deviation(values, BUDGET, floors, caps, bound=bound)
        if found is not None:
            return list(found[1]), "constrained_forward_dp"
        bound *= 2
    return None, "infeasible"


def optimal(ref, values: list[Fraction], dollars: list[int]) -> bool:
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    dev = sum(abs(Fraction(d) - v) for d, v in zip(dollars, values))
    found = ref.forward_dp_min_deviation(values, BUDGET, floors, caps, bound=dev)
    return found is not None and found[0] == dev and list(found[1]) == list(dollars)


def invariants(ref, dollars, values) -> list[str]:
    floors, caps = ref.dynasty_main_whole_dollar_bounds()
    bad = ref.check_whole_dollar_invariants(dollars, values, BUDGET, floors, caps)
    if len(dollars) != PICKS:
        bad.append(f"pick_count_{len(dollars)}")
    if any(isinstance(d, bool) for d in dollars):
        bad.append("bool_is_not_a_dollar")
    return bad


# --- the checks ----------------------------------------------------------------------------


def run(repo: Path, production: dict) -> int:
    ref = load_reference(repo)
    fx = repo / "tests" / "fixtures" / "draft_valuation"
    cfg = repo / "config" / "draft_valuation"
    workbook = json.loads((fx / "workbook_2026_10_17.json").read_text(encoding="utf-8"))
    inputs = json.loads((fx / "workbook_2026_10_17_inputs.json").read_text(encoding="utf-8"))
    goldens = json.loads((fx / "package_goldens_2026_10_17.json").read_text(encoding="utf-8"))

    # 1. provenance --------------------------------------------------------------------
    check(
        "fixtures are the owner workbook (sha256)",
        workbook["source"]["sha256"] == WORKBOOK_SHA256
        and inputs["source"]["sha256"] == WORKBOOK_SHA256
        and goldens["sourceSha256"] == WORKBOOK_SHA256,
    )
    rows = workbook["curve"]["rows"]
    check("workbook transcription has 72 rows", len(rows) == PICKS, str(len(rows)))
    col = {c: [r[c] for r in rows] for c in "BCDEFGHIJKL"}
    headers = workbook["curve"]["headers"]
    year_col = {int(headers[c]): c for c in "FGH"}
    check("workbook spine columns are 2024/2025/2026", sorted(year_col) == [2024, 2025, 2026])

    frozen = json.loads(
        (cfg / "frozen_inputs" / "2026_spreadsheet_baseline.json").read_text(encoding="utf-8")
    )
    check("frozen inputs checksum recomputes", checksum_of(frozen) == frozen["checksum"]["value"])
    check("frozen inputs pick labels", [v["pick"] for v in frozen["values"]] == labels())
    b = [exact(v["value"]) for v in frozen["values"]]
    check(
        "frozen inputs equal workbook column B exactly",
        b == [exact(x) for x in col["B"]],
        "differs" if b != [exact(x) for x in col["B"]] else "",
    )

    curve_dir = cfg / "historical_curves" / LEAGUE_KEY
    ledger: dict[int, list[Fraction]] = {}
    for path in sorted(curve_dir.glob("*.json")):
        if not path.stem.isdigit():
            continue
        rec = json.loads(path.read_text(encoding="utf-8"))
        year = int(path.stem)
        ok = (
            checksum_of(rec) == rec["checksum"]["value"]
            and rec.get("draftClass") == year
            and rec.get("leagueKey") == LEAGUE_KEY
            and [r["pick"] for r in rec["referenceDollars"]] == labels()
        )
        check(f"{year} completed-class snapshot checksum + identity", ok)
        ledger[year] = [exact(r["dollars"]) for r in rec["referenceDollars"]]
        if year in year_col:
            check(
                f"{year} completed-class snapshot equals workbook column {year_col[year]}",
                ledger[year] == [exact(x) for x in col[year_col[year]]],
            )

    # 2. golden -------------------------------------------------------------------------
    golden = evaluate(ref, col["B"], [col["F"], col["G"], col["H"]])
    cached_l = [exact(x) for x in col["L"]]
    check(
        "golden: transcription column L = workbook cached L (72/72)",
        golden["literalL"] == cached_l,
        f"{sum(1 for a, c in zip(golden['literalL'], cached_l) if a != c)} differ",
    )
    check(
        "golden: earlier-pick-first tie rule = literal sheet rule on the workbook",
        golden["L"] == golden["literalL"],
    )
    pkg = goldens["rows"]
    check(
        "golden: = owner package goldens L and D (72/72)",
        [r["pick"] for r in pkg] == labels()
        and golden["L"] == [exact(r["L"]) for r in pkg]
        and golden["L"] == [exact(r["D"]) for r in pkg],
    )
    check(
        "golden: double-precision decisions clear the noise",
        golden["floorMargin"] > DECISION_MARGIN and golden["cutoffMargin"] > DECISION_MARGIN,
        f"floor {golden['floorMargin']:.3g}, cutoff {golden['cutoffMargin']:.3g}",
    )
    golden_whole, golden_method = whole_dollars(ref, golden["L"])
    prod_golden = production.get("golden") or {}
    prod_ref = [exact(x) for x in prod_golden.get("referenceDollars") or []]
    check(
        "golden: production half-dollar curve = independent (exact)",
        prod_ref == golden["L"],
        _first_diff(prod_ref, golden["L"]),
    )
    check(
        f"golden: production whole dollars = independent ({golden_method})",
        golden_whole is not None and prod_golden.get("finalWholeDollars") == golden_whole,
        _first_diff(prod_golden.get("finalWholeDollars") or [], golden_whole or []),
    )

    # 3-5. per generated class ----------------------------------------------------------
    classes = production.get("classes") or {}
    check("production dump names generated classes", bool(classes), str(sorted(classes)))
    all_years = 0
    store = cfg / "published_allocations" / LEAGUE_KEY
    for key in sorted(classes, key=int):
        year = int(key)
        served = classes[key]
        spine = [y for y in sorted(ledger) if y < year][-3:]
        if not check(f"{year} spine: three completed classes on file", len(spine) == 3, str(spine)):
            continue
        check(
            f"{year} spine years = production's served spine",
            served.get("spineYears") == spine,
            f"independent {spine} vs production {served.get('spineYears')}",
        )
        mine = evaluate(ref, b, [ledger[y] for y in spine])
        check(
            f"{year} double-precision decisions clear the noise",
            mine["floorMargin"] > DECISION_MARGIN and mine["cutoffMargin"] > DECISION_MARGIN,
            f"floor {mine['floorMargin']:.3g}, cutoff {mine['cutoffMargin']:.3g}",
        )
        check(f"{year} half-dollar curve totals exactly $1,200", sum(mine["L"]) == BUDGET)
        whole, method = whole_dollars(ref, mine["L"])
        if not check(f"{year} independent whole dollars exist ({method})", whole is not None):
            continue
        bad = invariants(ref, whole, mine["L"])
        check(f"{year} invariants (integers, $1,200, order, floors, caps)", not bad, str(bad))
        check(
            f"{year} whole dollars are the lexmax minimum-deviation answer",
            optimal(ref, mine["L"], whole),
        )
        prod_ref = [exact(x) for x in served.get("referenceDollars") or []]
        check(
            f"{year} production half-dollar curve = independent (exact)",
            prod_ref == mine["L"],
            _first_diff(prod_ref, mine["L"]),
        )
        prod_whole = served.get("finalWholeDollars") or []
        check(
            f"{year} production whole dollars = independent (exact)",
            prod_whole == whole,
            _first_diff(prod_whole, whole),
        )
        check(
            f"{year} production served state is current",
            served.get("allocationState") == "current",
            str(served.get("allocationState")),
        )
        recs = sorted((store / str(year)).glob("*.json"))
        if check(f"{year} a stored record is on file", bool(recs), str(store / str(year))):
            rec = json.loads(recs[-1].read_text(encoding="utf-8"))
            check(
                f"{year} stored record checksum recomputes",
                checksum_of(rec) == rec["checksum"]["value"],
            )
            check(
                f"{year} stored record = independent whole dollars",
                [r["dollars"] for r in rec["finalWholeDollars"]] == whole,
            )
            check(
                f"{year} stored record = independent half dollars",
                [exact(r["dollars"]) for r in rec["referenceDollars"]] == mine["L"],
            )
            check(
                f"{year} production serves the stored record",
                served.get("recordChecksum") == rec["checksum"]["value"],
            )
        all_years += sum(whole)
    check(
        "All Years = $1,200 x classes",
        all_years == BUDGET * len(classes),
        f"{all_years} for {len(classes)} classes",
    )
    return 1 if any(r["status"] == "FAIL" for r in RESULTS) else 0


def _first_diff(a, b) -> str:
    if len(a) != len(b):
        return f"length {len(a)} vs {len(b)}"
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return f"first difference at {labels()[i] if i < PICKS else i}: production {x} vs independent {y}"
    return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--production", required=True, help="JSON dump of production's output")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", help="write the report here as JSON")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    production = json.loads(Path(args.production).read_text(encoding="utf-8"))
    code = run(repo, production)
    print("Draft valuation — independent checker (no production imports)")
    for r in RESULTS:
        line = f"  {r['status']}  {r['check']}"
        if r["detail"] and r["status"] == "FAIL":
            line += f"  [{r['detail']}]"
        print(line)
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    print(f"\n{len(RESULTS) - failed} PASS, {failed} FAIL")
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {"results": RESULTS, "pass": len(RESULTS) - failed, "fail": failed}, indent=1
            )
            + "\n",
            encoding="utf-8",
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
