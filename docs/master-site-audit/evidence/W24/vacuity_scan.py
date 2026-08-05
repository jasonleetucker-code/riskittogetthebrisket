"""Static scan for assertions that cannot fail."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path("/home/user/riskittogetthebrisket")

ASSERT_METHODS = {
    "assertEqual",
    "assertNotEqual",
    "assertTrue",
    "assertFalse",
    "assertIs",
    "assertIsNot",
    "assertIsNone",
    "assertIsNotNone",
    "assertIn",
    "assertNotIn",
    "assertGreater",
    "assertGreaterEqual",
    "assertLess",
    "assertLessEqual",
    "assertAlmostEqual",
    "assertRaises",
    "assertIsInstance",
    "assertSetEqual",
    "assertDictEqual",
    "assertListEqual",
    "assertCountEqual",
    "assertRegex",
    "assertNotAlmostEqual",
    "assertLogs",
    "assertWarns",
    "fail",
}

SHAPE_ONLY = {
    "assertIsInstance",
    "assertIsNotNone",
    "assertIn",
    "assertTrue",
}


def dump(n):
    try:
        return ast.unparse(n)
    except Exception:  # noqa: BLE001
        return "<?>"


class FnScan:
    def __init__(self, fn, path):
        self.fn = fn
        self.path = path
        self.self_cmp = []
        self.asserts = 0
        self.shape_only = 0
        self.trivial = []
        self.has_any_assert = False
        self.pytest_raises = 0

    def run(self):
        for node in ast.walk(self.fn):
            if isinstance(node, ast.Assert):
                self.has_any_assert = True
                self.asserts += 1
                self.check_assert_expr(node.test, node.lineno)
            elif isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Attribute) and f.attr in ASSERT_METHODS:
                    self.has_any_assert = True
                    self.asserts += 1
                    if f.attr in SHAPE_ONLY:
                        self.shape_only += 1
                    if len(node.args) >= 2 and f.attr in {
                        "assertEqual",
                        "assertAlmostEqual",
                        "assertIs",
                    }:
                        a, b = dump(node.args[0]), dump(node.args[1])
                        if a == b:
                            self.self_cmp.append((node.lineno, f"{f.attr}({a}, {b})"))
                if isinstance(f, ast.Attribute) and f.attr == "raises":
                    self.pytest_raises += 1
                if isinstance(f, ast.Name) and f.id == "expect":
                    self.has_any_assert = True
        return self

    def check_assert_expr(self, test, lineno):
        # assert x == x
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left = dump(test.left)
            right = dump(test.comparators[0])
            if left == right and isinstance(test.ops[0], (ast.Eq, ast.Is, ast.LtE, ast.GtE)):
                self.self_cmp.append(
                    (lineno, f"assert {left} {type(test.ops[0]).__name__} {right}")
                )
            # assert len(x) >= 0  /  assert x >= 0 on a count
            if isinstance(test.ops[0], ast.GtE) and isinstance(test.comparators[0], ast.Constant):
                if test.comparators[0].value == 0 and isinstance(test.left, ast.Call):
                    fn = test.left.func
                    if isinstance(fn, ast.Name) and fn.id == "len":
                        self.trivial.append((lineno, f"assert {left} >= 0"))
        # assert isinstance(...)  alone
        if isinstance(test, ast.Call):
            f = test.func
            if isinstance(f, ast.Name) and f.id == "isinstance":
                self.shape_only += 1
        # assert True / assert 1
        if isinstance(test, ast.Constant) and test.value:
            self.trivial.append((lineno, f"assert {dump(test)}"))
        # assert a or b  where one side is near-always true
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            self.trivial.append((lineno, f"assert {dump(test)}  # disjunction"))


def main(dirs):
    out = {
        "no_assert": [],
        "self_compare": [],
        "shape_only_fn": [],
        "trivial": [],
        "totals": {},
    }
    nfn = 0
    for d in dirs:
        for p in sorted((ROOT / d).rglob("test_*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            rel = str(p.relative_to(ROOT))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test"):
                    continue
                nfn += 1
                s = FnScan(node, rel).run()
                if not s.has_any_assert and s.pytest_raises == 0:
                    out["no_assert"].append(f"{rel}:{node.lineno}:{node.name}")
                for ln, txt in s.self_cmp:
                    out["self_compare"].append(f"{rel}:{ln}: {txt}  [in {node.name}]")
                for ln, txt in s.trivial:
                    out["trivial"].append(f"{rel}:{ln}: {txt}  [in {node.name}]")
                if s.asserts > 0 and s.shape_only == s.asserts:
                    out["shape_only_fn"].append(
                        f"{rel}:{node.lineno}:{node.name} ({s.asserts} asserts)"
                    )
    out["totals"] = {
        "test_functions_scanned": nfn,
        "no_assert": len(out["no_assert"]),
        "self_compare": len(out["self_compare"]),
        "shape_only_fn": len(out["shape_only_fn"]),
        "trivial": len(out["trivial"]),
    }
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:] or ["tests"])
