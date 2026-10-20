"""The ONE fairness-band owner -- fairness_bands_v2 (owner decisions 2026-10-20).

Pins:
* the owner classifies every shared validation case (offense, IDP, picks incl.
  R4-R6, consolidation, deep and large packages, boundaries) as the fixture's
  stated formula says, on the LARGER PACKAGE UTILITY (OD-F2);
* a 1-for-1 is byte-identical to v1 over a grid (utility == adjusted total);
* the depth bias is gone: a fixed utility shortfall reads the same at every
  piece count;
* missing input is REFUSED identically to the JS mirror (shared fixture): a
  non-finite gap / base, a missing utilities container, a non-finite package
  PIECE at the owner's package-values entry point, and a zero base beside a
  gap at or above the floor;
* the published relativePct / absoluteGap rounding equals the JS mirror's
  (shared generated fixture, including half-ties);
* the JS mirror's constants equal the JSON owner;
* no consumer computes its own base from adjusted totals (structural scan);
* the version / status / owner decisions / OD-F4 validation are recorded, the
  250 floor lives in config (not a code literal), and the package model
  (q = 0.78) is untouched.
"""

from __future__ import annotations

import ast
import inspect
import json
import math
import re
import unittest
from pathlib import Path

from src.valuation_math import fairness_bands as fb
from src.valuation_math import package_model

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((ROOT / "tests/fixtures/fairness_band_cases.json").read_text(encoding="utf-8"))
REFUSALS = json.loads(
    (ROOT / "tests/fixtures/fairness_band_refusal_cases.json").read_text(encoding="utf-8")
)
ROUNDING = json.loads(
    (ROOT / "tests/fixtures/fairness_band_rounding_cases.json").read_text(encoding="utf-8")
)
JS = (ROOT / "frontend/lib/fairness-bands.js").read_text(encoding="utf-8")
CONFIG_RAW = json.loads((ROOT / "config/trade/fairness_bands.json").read_text(encoding="utf-8"))

_SKIP = object()


def _decode(token):
    """The refusal fixture's token vocabulary (shared with the JS test)."""
    if not isinstance(token, str):
        return token
    if token == "NaN":
        return math.nan
    if token == "Infinity":
        return math.inf
    if token == "-Infinity":
        return -math.inf
    if token == "null":
        return None
    if token == "undefined":
        return _SKIP  # no Python equivalent of a JS undefined
    if token.startswith("str:"):
        return token[4:]
    if token == "bool:true":
        return True
    if token == "object:{}":
        return {}
    raise AssertionError(f"unknown token {token!r}")


class SharedCases(unittest.TestCase):
    def test_every_case(self) -> None:
        self.assertEqual(FIXTURE["bands"], fb.CONFIG["version"])
        mixes = " ".join(c["assetMix"] for c in FIXTURE["cases"])
        for needed in ("offense", "idp", "picks", "R4-R6", "consolidation", "deep", "large"):
            self.assertIn(needed, mixes)
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["id"]):
                got = fb.classify(case["gap"], case["largerUtility"])
                self.assertEqual(got["level"], case["expectedLevel"])

    def test_package_cases_take_the_base_from_the_owner(self) -> None:
        for case in FIXTURE["cases"]:
            if "sideA" not in case:
                continue
            with self.subTest(case=case["id"]):
                a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(
                    case["sideA"], case["sideB"]
                )
                self.assertEqual(round(a_adj - b_adj), case["gap"])
                self.assertEqual(round(max(a_adj, b_adj)), case["v1LargerAdjusted"])
                base = fb.larger_package_utility(case["sideA"], case["sideB"])
                self.assertAlmostEqual(base, case["largerUtility"], places=2)
                got = fb.classify_packages(a_adj - b_adj, case["sideA"], case["sideB"])
                self.assertEqual(got["level"], case["expectedLevel"])

    def test_the_fixture_exercises_the_change(self) -> None:
        # Not a re-pin of v1: at least one deep package changes level.
        changed = [c["id"] for c in FIXTURE["cases"] if c["expectedLevel"] != c["v1Level"]]
        self.assertTrue(changed)
        self.assertTrue(all("sideA" in c for c in FIXTURE["cases"] if c["id"] in changed))


class OneForOneIsByteIdentical(unittest.TestCase):
    """OD-F2: a 1-for-1 (and a 1-for-0) is unchanged from v1."""

    GRID = (1, 7, 100, 249, 250, 251, 499.5, 1000, 1389, 2777.8, 3000, 7142.9, 7143, 9999)

    def test_grid(self) -> None:
        for a in self.GRID:
            for b in (*self.GRID, None):
                side_b = [] if b is None else [b]
                a_adj, b_adj, _, _ = package_model.adjusted_pair_totals([a], side_b)
                gap = a_adj - b_adj
                v1 = fb.classify(gap, max(a_adj, b_adj))  # the retired base, same owner
                v2 = fb.classify_packages(gap, [a], side_b)
                with self.subTest(a=a, b=b):
                    self.assertEqual(json.dumps(v1, sort_keys=True), json.dumps(v2, sort_keys=True))
                    self.assertEqual(fb.larger_package_utility([a], side_b), max(a_adj, b_adj))


class DepthBiasRemoved(unittest.TestCase):
    """v1 divided a utility gap by an adjusted side that adds the discarded
    depth back, so the fair band widened with piece count.  v2 reads a fixed
    utility shortfall the same at every k."""

    def test_fixed_shortfall_reads_the_same_at_every_piece_count(self) -> None:
        q = package_model.PACKAGE_MODELS[package_model.GEOM_Q078_V1]["q"]
        for stud in (6000.0, 9000.0):
            for short in (0.03, 0.05, 0.08, 0.12):
                rels, levels = set(), set()
                for k in (1, 2, 4, 6, 8, 12):
                    w = sum(q**i for i in range(k))
                    pieces = [stud * (1 - short) / w] * k
                    a_adj, b_adj, _, _ = package_model.adjusted_pair_totals([stud], pieces)
                    band = fb.classify_packages(a_adj - b_adj, [stud], pieces)
                    rels.add(round(band["relativePct"], 0))
                    levels.add(band["level"])
                with self.subTest(stud=stud, short=short):
                    self.assertEqual(len(levels), 1, levels)
                    self.assertLessEqual(max(rels) - min(rels), 1.0)


class Refusal(unittest.TestCase):
    """MISSING IS NEVER ZERO: non-finite input is refused, never 'fair'."""

    def test_code(self) -> None:
        self.assertEqual(REFUSALS["code"], fb.INPUT_ERROR_CODE)
        self.assertEqual(fb.FairnessInputError.code, fb.INPUT_ERROR_CODE)
        self.assertTrue(issubclass(fb.FairnessInputError, ValueError))

    def test_classify_cases(self) -> None:
        self.assertEqual(REFUSALS["inconsistentCode"], fb.INPUT_INCONSISTENT_CODE)
        for case in REFUSALS["classify"]:
            gap, base = _decode(case["gap"]), _decode(case["base"])
            if gap is _SKIP or base is _SKIP:
                continue
            with self.subTest(case=case):
                if case["expect"] == "refuse":
                    code = case.get("expectCode", REFUSALS["code"])
                    with self.assertRaises(fb.FairnessInputError) as ctx:
                        fb.classify(gap, base)
                    self.assertEqual(ctx.exception.code, code)
                    with self.assertRaises(fb.FairnessInputError):
                        fb.is_even(gap, base)
                else:
                    self.assertEqual(fb.classify(gap, base)["level"], case["expect"])

    def test_base_containers(self) -> None:
        for case in REFUSALS["baseContainers"]:
            container = _decode(case["container"])
            if container is _SKIP:
                continue
            with self.subTest(case=case):
                with self.assertRaises(fb.FairnessInputError) as ctx:
                    fb.fairness_base(container)
                self.assertEqual(ctx.exception.code, REFUSALS["code"])

    def test_package_pieces(self) -> None:
        """The owner's package-values entry point refuses a non-finite piece
        (the package model would price a NaN piece as absent, i.e. 0)."""
        for case in REFUSALS["packagePieces"]:
            a, b = case["a"], case["b"]
            a = _decode(a) if isinstance(a, str) else [_decode(v) for v in a]
            b = _decode(b) if isinstance(b, str) else [_decode(v) for v in b]
            with self.subTest(case=case):
                if case["expect"] == "refuse":
                    for call in (
                        lambda: fb.package_utilities(a, b),
                        lambda: fb.larger_package_utility(a, b),
                        lambda: fb.classify_packages(0, a, b),
                        lambda: fb.package_utilities(a, b, model_id=package_model.KTC_2026_04),
                    ):
                        with self.assertRaises(fb.FairnessInputError) as ctx:
                            call()
                        self.assertEqual(ctx.exception.code, REFUSALS["code"])
                else:
                    self.assertAlmostEqual(
                        fb.larger_package_utility(a, b), case["expect"], places=9
                    )

    def test_base_cases(self) -> None:
        for case in REFUSALS["base"]:
            utilities = [_decode(u) for u in case["utilities"]]
            with self.subTest(case=case):
                if case["expect"] == "refuse":
                    with self.assertRaises(fb.FairnessInputError):
                        fb.fairness_base(utilities)
                else:
                    self.assertEqual(fb.fairness_base(utilities), case["expect"])

    def test_nan_never_reads_fair_through_any_helper(self) -> None:
        for call in (
            lambda: fb.classify(math.nan, 5000),
            lambda: fb.is_even(math.nan, 5000),
            lambda: fb.relative_pct(math.nan, 5000),
            lambda: fb.fair_threshold(math.nan),
            # Review of #1886: the package-values entry point priced a NaN
            # piece as absent and answered 'fair'.
            lambda: fb.classify_packages(0.0, [5000, math.nan], [5000]),
            lambda: fb.classify_packages(0, [math.nan], []),
            lambda: fb.fairness_base(None),
            # A zero base beside a gap above the floor is missing data.
            lambda: fb.classify(5000, 0),
        ):
            with self.assertRaises(fb.FairnessInputError):
                call()

    def test_numpy_scalars_are_treated_alike(self) -> None:
        import numpy as np  # noqa: PLC0415

        for gap in (np.int64(300), np.float64(300.0)):
            self.assertEqual(fb.classify(gap, np.int64(5000))["level"], "slight")
        with self.assertRaises(fb.FairnessInputError):
            fb.classify(np.float64("nan"), 5000)


class PublishedRoundingParity(unittest.TestCase):
    """relativePct / absoluteGap are rounded with JS Math.round semantics (the
    fixture is generated from the JS mirror), so both languages publish the
    same number on half-ties -- Python's round() did not."""

    def test_rounding_fixture(self) -> None:
        self.assertGreater(len(ROUNDING["cases"]), 300)
        for case in ROUNDING["cases"]:
            got = fb.classify(case["gap"], case["base"])
            with self.subTest(case=case):
                self.assertEqual(got["level"], case["level"])
                self.assertEqual(got["relativePct"], case["relativePct"])
                self.assertEqual(got["absoluteGap"], case["absoluteGap"])

    def test_fixture_exercises_half_ties(self) -> None:
        legacy = sum(
            1
            for c in ROUNDING["cases"]
            if round(abs(c["gap"]) / c["base"] * 100, 2) != c["relativePct"]
            or round(abs(c["gap"]), 1) != c["absoluteGap"]
        )
        self.assertGreater(legacy, 0)


class JsMirror(unittest.TestCase):
    def _js_const(self, name: str):
        m = re.search(rf"export const {name} = ([^;]+);", JS)
        self.assertIsNotNone(m, name)
        raw = m.group(1).strip()
        frozen = re.fullmatch(r"Object\.freeze\((.*)\)", raw, re.S)
        return json.loads(frozen.group(1) if frozen else raw)

    def test_constants_equal_the_owner(self) -> None:
        self.assertEqual(self._js_const("FAIRNESS_BANDS_VERSION"), fb.CONFIG["version"])
        self.assertEqual(self._js_const("FAIRNESS_BANDS_STATUS"), fb.CONFIG["status"])
        self.assertEqual(self._js_const("FAIRNESS_BANDS_BASIS"), fb.CONFIG["basis"])
        self.assertEqual(float(self._js_const("ABSOLUTE_MINIMUM")), fb.ABSOLUTE_MINIMUM)
        self.assertEqual(float(self._js_const("SLIGHT_PCT")), fb.SLIGHT_PCT)
        self.assertEqual(float(self._js_const("UNFAIR_PCT")), fb.UNFAIR_PCT)
        self.assertEqual(float(self._js_const("LOPSIDED_PCT")), fb.LOPSIDED_PCT)
        self.assertEqual(self._js_const("FAIR_TRADE_LEVELS"), list(fb.FAIR_TRADE_LEVELS))
        self.assertEqual(self._js_const("FAIRNESS_INPUT_ERROR_CODE"), fb.INPUT_ERROR_CODE)
        self.assertEqual(
            self._js_const("FAIRNESS_INPUT_INCONSISTENT_CODE"), fb.INPUT_INCONSISTENT_CODE
        )

    def test_labels_equal_the_owner(self) -> None:
        for level, label in fb.LABELS.items():
            self.assertIn(f'{level}: "{label}"', JS)


# ── One denominator owner: no consumer derives a base from adjusted totals ──

_PY_SCAN = (ROOT / "src",)
_PY_BAND_CALLS = {"classify", "is_even", "relative_pct", "fair_threshold"}
_JS_SCAN = (ROOT / "frontend/lib", ROOT / "frontend/app", ROOT / "frontend/components")
_JS_BAND_CALL = re.compile(
    r"\b(classifyGap|isFairGap|relativeGapPct|meterVerdict|verdictFromGap|colorFromGap)\("
)


def _js_second_arg(text: str, start: int) -> str:
    """The second top-level argument of the call whose ``(`` ends at ``start``."""
    depth, args, cur = 0, [], []
    for ch in text[start:]:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    args.append("".join(cur))
    return args[1] if len(args) > 1 else ""


def _py_offenders(source: str, path: str) -> list[str]:
    out = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
        owner = isinstance(f, ast.Attribute) and getattr(f.value, "id", None) in (
            "fairness_bands",
            "fb",
        )
        if name not in _PY_BAND_CALLS or not owner:
            continue
        base = ast.unparse(node.args[1])
        if re.search(r"\bmax\(|adj|Adjusted|given", base):
            out.append(f"{path}:{node.lineno}: {base}")
    return out


def _js_offenders(source: str, path: str) -> list[str]:
    out = []
    for m in _JS_BAND_CALL.finditer(source):
        base = _js_second_arg(source, m.end())
        if re.search(r"Math\.max\(|adjusted|\.given|largerSide\b", base):
            line = source.count("\n", 0, m.start()) + 1
            out.append(f"{path}:{line}: {base.strip()}")
    return out


class OneDenominatorOwner(unittest.TestCase):
    def test_scan_fires_on_a_v1_style_caller(self) -> None:
        py = "from src.valuation_math import fairness_bands\nfairness_bands.classify(g, max(a_adj, b_adj))\n"
        js = "const v = classifyGap(gap, Math.max(totals[0].adjusted, totals[1].adjusted));"
        self.assertTrue(_py_offenders(py, "decoy.py"))
        self.assertTrue(_js_offenders(js, "decoy.js"))
        self.assertFalse(_py_offenders("fairness_bands.classify(g, larger_utility)\n", "ok.py"))
        self.assertFalse(_js_offenders("classifyGap(gap, largerUtility);", "ok.js"))

    def test_no_consumer_passes_an_adjusted_base(self) -> None:
        offenders: list[str] = []
        for root in _PY_SCAN:
            for path in root.rglob("*.py"):
                if path.name == "fairness_bands.py":
                    continue
                offenders += _py_offenders(path.read_text(encoding="utf-8"), str(path))
        for root in _JS_SCAN:
            for path in [*root.rglob("*.js"), *root.rglob("*.jsx")]:
                if "node_modules" in path.parts or path.name == "fairness-bands.js":
                    continue
                offenders += _js_offenders(path.read_text(encoding="utf-8"), str(path))
        self.assertEqual(offenders, [])

    def test_no_adjusted_basis_percentage_is_printed(self) -> None:
        """Review of #1886: the meter / tray / explanation printed
        ``percentageGap`` (gap / larger ADJUSTED side) beside a badge graded on
        the larger PACKAGE UTILITY, so SLIGHT EDGE could sit beside "3%".  The
        printed percentage is ``meterVerdict(...).percentText``; no production
        frontend file may call ``percentageGap`` (its export stays for tests)."""
        offenders = []
        for sub in ("app", "components", "lib"):
            for path in sorted((ROOT / "frontend" / sub).rglob("*.js*")):
                text = path.read_text(encoding="utf-8")
                for m in re.finditer(r"(?<!function )\bpercentageGap\(", text):
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{text[: m.start()].count(chr(10)) + 1}"
                    )
        self.assertEqual(offenders, [])


class Properties(unittest.TestCase):
    def test_sign_blind(self) -> None:
        for g in (0, 100, 400, 1200, 5000):
            self.assertEqual(fb.classify(g, 10000)["level"], fb.classify(-g, 10000)["level"])

    def test_monotone_in_gap(self) -> None:
        order = {lvl: i for i, lvl in enumerate(fb.LEVELS)}
        for larger in (1000, 5000, 10000, 40000):
            prev = 0
            for g in range(0, larger, max(1, larger // 200)):
                cur = order[fb.classify(g, larger)["level"]]
                self.assertGreaterEqual(cur, prev, (g, larger))
                prev = cur

    def test_scale_invariant_above_the_minimum(self) -> None:
        for pct in (1.0, 3.0, 4.0, 8.9, 9.1, 17.9, 18.1, 30.0):
            levels = {
                fb.classify(larger * pct / 100, larger)["level"]
                for larger in (10000, 20000, 40000)  # every gap here is >= 250
            }
            self.assertEqual(len(levels), 1, pct)

    def test_absolute_minimum_protects_small_packages(self) -> None:
        self.assertEqual(fb.classify(200, 1000)["level"], "fair")
        self.assertEqual(fb.classify(250, 1000)["level"], "lopsided")

    def test_no_asset_class_input(self) -> None:
        self.assertEqual(list(inspect.signature(fb.classify).parameters), ["gap", "larger_utility"])

    def test_empty_pairing_is_fair_with_no_relative(self) -> None:
        self.assertEqual(
            fb.classify(0, 0), {**fb.classify(0, 0), "level": "fair", "relativePct": None}
        )

    def test_fair_threshold_is_the_band_edge(self) -> None:
        for base in (0, 1000, 7142.9, 7143, 20000):
            t = fb.fair_threshold(base)
            self.assertEqual(fb.classify(t - 0.01, base)["level"], "fair")
            if base > 0:
                self.assertNotEqual(fb.classify(t + 0.01, base)["level"], "fair")


class RollbackModel(unittest.TestCase):
    def test_ktc_has_no_utility_so_its_adjusted_totals_stand_in(self) -> None:
        a, b = [7200], [6000, 500]
        ktc = package_model.KTC_2026_04
        a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(a, b, model_id=ktc)
        self.assertEqual(fb.package_utilities(a, b, model_id=ktc), (a_adj, b_adj))
        g = package_model.GEOM_Q078_V1
        q = package_model.PACKAGE_MODELS[g]["q"]
        self.assertEqual(
            fb.package_utilities(a, b, model_id=g),
            (package_model.geom_utility(a, q), package_model.geom_utility(b, q)),
        )


class Provenance(unittest.TestCase):
    def test_version_status_and_owner_decisions(self) -> None:
        r = fb.receipt()
        self.assertEqual(r["version"], "fairness_bands_v2")
        self.assertEqual(r["status"], "PRIOR_OWNER_APPROVED_2026-10-20")
        self.assertEqual(r["basis"], "larger_package_utility")
        self.assertEqual(r["postLaunchValidation"], "OD-F4")
        self.assertEqual(CONFIG_RAW["postLaunchValidation"]["state"], "PENDING")
        decisions = CONFIG_RAW["ownerDecisions"]
        for key in ("OD-F1", "OD-F2", "OD-F3", "OD-F5"):
            self.assertIn(key, decisions)
        self.assertTrue((ROOT / decisions["record"]).is_file())
        # v1 is recorded as retired, not loadable.
        self.assertIn("fairness_bands_v1", CONFIG_RAW["retired"])

    def test_fair_trade_levels_are_od_f1(self) -> None:
        self.assertEqual(fb.FAIR_TRADE_LEVELS, ("fair",))
        self.assertTrue(fb.counts_as_fair_trade("fair"))
        for level in ("slight", "unfair", "lopsided", None, "", "FAIR"):
            self.assertFalse(fb.counts_as_fair_trade(level))

    def test_floor_is_config_not_a_code_literal(self) -> None:
        self.assertEqual(CONFIG_RAW["absoluteMinimum"], 250)
        self.assertTrue(CONFIG_RAW["absoluteMinimumStatus"].startswith("PRIOR_OWNER_APPROVED"))
        tree = ast.parse(
            (ROOT / "src/valuation_math/fairness_bands.py").read_text(encoding="utf-8")
        )
        literals = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
        }
        for number in (250, 3.5, 9.0, 18.0):
            self.assertNotIn(number, literals)

    def test_package_model_untouched(self) -> None:
        self.assertEqual(package_model.PACKAGE_MODELS[package_model.GEOM_Q078_V1]["q"], 0.78)
        self.assertEqual(fb.legacy_magnitude("fair"), "even")
        self.assertEqual(fb.legacy_magnitude("slight"), "lean")
        self.assertEqual(fb.legacy_magnitude("unfair"), "stretch")
        self.assertEqual(fb.legacy_magnitude("lopsided"), "stretch")


if __name__ == "__main__":
    unittest.main()
