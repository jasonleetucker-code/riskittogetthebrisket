"""Find tests that assert a value the test itself installed on a mock/patch."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path("/home/user/riskittogetthebrisket")


def dump(n):
    try:
        return ast.unparse(n)
    except Exception:  # noqa: BLE001
        return "<?>"


def main():
    hits = []
    for p in sorted((ROOT / "tests").rglob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = str(p.relative_to(ROOT))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test"):
                continue
            installed = {}  # literal-source -> lineno
            for node in ast.walk(fn):
                # x.return_value = <expr>  /  x.side_effect = [<expr>]
                if isinstance(node, ast.Assign) and len(node.targets) == 1:
                    t = node.targets[0]
                    if isinstance(t, ast.Attribute) and t.attr in {
                        "return_value",
                        "side_effect",
                    }:
                        installed[dump(node.value)] = node.lineno
                # monkeypatch.setattr(target, lambda ...: <expr>)
                if isinstance(node, ast.Call):
                    f = node.func
                    if (
                        isinstance(f, ast.Attribute)
                        and f.attr in {"setattr", "patch", "object"}
                        and len(node.args) >= 2
                    ):
                        installed[dump(node.args[-1])] = node.lineno
                    if isinstance(f, ast.Name) and f.id in {"patch"} and node.keywords:
                        for kw in node.keywords:
                            if kw.arg == "return_value":
                                installed[dump(kw.value)] = node.lineno
            if not installed:
                continue
            for node in ast.walk(fn):
                expected = None
                lineno = None
                if isinstance(node, ast.Call):
                    f = node.func
                    if (
                        isinstance(f, ast.Attribute)
                        and f.attr in {"assertEqual", "assertIs"}
                        and len(node.args) >= 2
                    ):
                        expected = dump(node.args[1])
                        lineno = node.lineno
                elif isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare):
                    if len(node.test.ops) == 1 and isinstance(node.test.ops[0], (ast.Eq, ast.Is)):
                        expected = dump(node.test.comparators[0])
                        lineno = node.lineno
                if expected and expected in installed and len(expected) > 3:
                    hits.append(
                        f"{rel}:{lineno}: asserts `{expected[:70]}` which the test installed "
                        f"on a mock at line {installed[expected]}  [in {fn.name}]"
                    )
    print(json.dumps({"count": len(hits), "hits": hits}, indent=1))


if __name__ == "__main__":
    main()
