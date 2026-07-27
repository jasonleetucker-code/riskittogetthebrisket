"""Which ``src/`` modules can a request actually reach?

Backlog defect #9: "43 of 208 ``src/`` modules unreachable (~12,571
lines)". That figure was never re-derivable — no instrument produced it
and no test pins it — so it aged into folklore. This is the instrument.

It is the same import walk ``tests/api/test_feature_flag_reachability.py``
uses to classify feature flags, widened from "which flags can fire" to
"which modules can run at all", because they are the same question asked
of different things and there should not be two answers.

FOUR REACHABILITY CLASSES, and the distinction matters
──────────────────────────────────────────────────────
``SERVER``   imported transitively from ``server.py``. A request can
             reach it.
``SCRIPT``   reachable only from ``scripts/``. Operator tooling — real
             code doing real work, and NOT a defect. Counting it as
             dead is how a refit script gets deleted by someone tidying.
``TEST``     reachable only from ``tests/``. Usually a module whose only
             consumer is the test written for it — the shape that
             produced ``usage_signals`` and ``opportunity_stats``.
``ORPHAN``   nothing imports it, anywhere, including its own tests.

Only ORPHAN is unambiguously dead. Reporting a single "unreachable"
number collapses three very different situations into one, which is
why the original 43 could not be acted on.

WHAT THIS DOES NOT ESTABLISH
────────────────────────────
Reachability is static. A module loaded by a dynamic dispatch — a
registry of string names, an ``importlib`` call, an entry point — looks
orphaned here and is not. ``src/ros/sources/`` is exactly that shape and
is annotated in the output rather than silently accused. Treat ORPHAN as
"worth checking", never as "safe to delete".

Usage::

    python3 scripts/audit/measure_module_reachability.py
    python3 scripts/audit/measure_module_reachability.py --json
    python3 scripts/audit/measure_module_reachability.py --class ORPHAN
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

#: Packages resolved by string name at runtime rather than by import.
#: Modules under these are annotated, not accused.
DYNAMIC_DISPATCH_HINTS = ("src.ros.sources", "src.news.providers", "src.adapters")


def _module_path(dotted: str) -> Path | None:
    direct = REPO_ROOT / (dotted.replace(".", "/") + ".py")
    if direct.exists():
        return direct
    package = REPO_ROOT / dotted.replace(".", "/") / "__init__.py"
    return package if package.exists() else None


def _dotted_of(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _src_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("src"))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("src"):
                found.add(node.module)
                # ``from src.a import b`` — b may be a module or a symbol;
                # _module_path discards the ones that are not files.
                found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _closure(roots: list[Path]) -> set[str]:
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        for dotted in _src_imports(stack.pop()):
            if dotted in seen:
                continue
            path = _module_path(dotted)
            if path is None:
                continue
            seen.add(dotted)
            stack.append(path)
    return seen


def _all_py(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]


def _loc(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def measure() -> dict[str, Any]:
    server = REPO_ROOT / "server.py"
    from_server = _closure([server]) if server.exists() else set()
    from_scripts = _closure(_all_py(REPO_ROOT / "scripts"))
    from_tests = _closure(_all_py(REPO_ROOT / "tests"))

    modules: list[dict[str, Any]] = []
    for path in _all_py(REPO_ROOT / "src"):
        dotted = _dotted_of(path)
        if dotted in from_server:
            cls = "SERVER"
        elif dotted in from_scripts:
            cls = "SCRIPT"
        elif dotted in from_tests:
            cls = "TEST"
        else:
            cls = "ORPHAN"
        modules.append(
            {
                "module": dotted,
                "path": str(path.relative_to(REPO_ROOT)),
                "lines": _loc(path),
                "reachability": cls,
                "dynamicDispatch": dotted.startswith(DYNAMIC_DISPATCH_HINTS),
            }
        )

    by_class: dict[str, dict[str, int]] = {}
    for m in modules:
        row = by_class.setdefault(m["reachability"], {"modules": 0, "lines": 0})
        row["modules"] += 1
        row["lines"] += m["lines"]

    return {
        "totalModules": len(modules),
        "totalLines": sum(m["lines"] for m in modules),
        "byClass": by_class,
        "modules": sorted(modules, key=lambda m: (-m["lines"], m["module"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--class",
        dest="want",
        choices=["SERVER", "SCRIPT", "TEST", "ORPHAN"],
        help="List only modules in this class.",
    )
    parser.add_argument("--top", type=int, default=25)
    args = parser.parse_args()

    result = measure()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(
        f"[reachability] {result['totalModules']} modules under src/, "
        f"{result['totalLines']:,} lines"
    )
    for cls in ("SERVER", "SCRIPT", "TEST", "ORPHAN"):
        row = result["byClass"].get(cls, {"modules": 0, "lines": 0})
        print(f"  {cls:<8} {row['modules']:>4} modules  {row['lines']:>8,} lines")

    wanted = args.want or "ORPHAN"
    rows = [m for m in result["modules"] if m["reachability"] == wanted]
    print(f"\n  {wanted} (top {args.top} by size):")
    for m in rows[: args.top]:
        note = "  [dynamic-dispatch package]" if m["dynamicDispatch"] else ""
        print(f"    {m['lines']:>5}  {m['module']}{note}")
    if len(rows) > args.top:
        print(f"    ... and {len(rows) - args.top} more")
    if wanted == "ORPHAN":
        print(
            "\n  ORPHAN means nothing imports it, including its own tests.\n"
            "  It does NOT mean safe to delete — see this module's docstring\n"
            "  on dynamic dispatch."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
