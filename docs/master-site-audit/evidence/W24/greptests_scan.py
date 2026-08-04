"""Find 'grep tests': tests whose only assertions are substring checks on source text."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path("/home/user/riskittogetthebrisket")

SRC_NAMES = {
    "src",
    "source",
    "code",
    "text",
    "content",
    "body",
    "js",
    "py",
    "raw",
    "sql",
    "contents",
    "file_text",
    "module_src",
    "SRC",
    "CODE",
    "TEXT",
    "WORKFLOW",
    "SOURCE",
}


def dump(n):
    try:
        return ast.unparse(n)
    except Exception:  # noqa: BLE001
        return "<?>"


def reads_source(fn) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in {"read_text", "getsource", "read"}:
                return True
    return False


def main():
    hits = []
    total = 0
    for p in sorted((ROOT / "tests").rglob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = str(p.relative_to(ROOT))
        module_reads_source = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr in {"read_text", "getsource"}
            for n in ast.walk(tree)
        )
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not fn.name.startswith("test"):
                continue
            total += 1
            asserts = []
            for node in ast.walk(fn):
                if isinstance(node, ast.Assert):
                    asserts.append(node.test)
                elif isinstance(node, ast.Call):
                    f = node.func
                    if isinstance(f, ast.Attribute) and f.attr in {
                        "assertIn",
                        "assertNotIn",
                        "assertRegex",
                    }:
                        if len(node.args) >= 2:
                            asserts.append(("in", node.args[1]))
                    elif isinstance(f, ast.Attribute) and f.attr.startswith("assert"):
                        asserts.append(("other", node))
            if not asserts:
                continue
            substr = 0
            for a in asserts:
                if isinstance(a, tuple):
                    if a[0] == "in":
                        hay = dump(a[1])
                        if any(s in hay for s in SRC_NAMES):
                            substr += 1
                    continue
                if isinstance(a, ast.Compare) and any(
                    isinstance(o, (ast.In, ast.NotIn)) for o in a.ops
                ):
                    hay = dump(a.comparators[0])
                    if any(s in hay for s in SRC_NAMES):
                        substr += 1
            if substr and substr == len(asserts) and (reads_source(fn) or module_reads_source):
                hits.append(f"{rel}:{fn.lineno}:{fn.name} ({substr} substring asserts)")
    print(json.dumps({"total_tests": total, "grep_tests": len(hits), "hits": hits}, indent=1))


if __name__ == "__main__":
    main()
