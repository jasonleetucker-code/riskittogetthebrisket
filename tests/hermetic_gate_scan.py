"""Static scanner behind ``tests/test_hermetic_gate_inputs.py``.

Two ways a blocking-gate test comes to depend on a ROLLING checkout instead of
its own committed inputs:

* it names a specific ``exports/archive/dynasty_export_<ts>.zip`` -- the archive
  directory is a rolling window (``src/maintenance/retention.py`` keeps every zip
  for 14 days, then only the newest per calendar day), so the file is deleted by
  the scheduled refresh's own retention pass;
* it ``skip``s when such data is absent.  A skip is silent until the suite-wide
  skip budget (``config/ci/test_shards.json::max_skipped``) is crossed, and then
  EVERY PR and deploy gate turns red at once.

Both are found by reading the AST, never by running anything, so the scan costs
milliseconds and cannot itself depend on the data it polices.  Scopes marked
``@pytest.mark.livedata`` (and the modules listed in ``tests/conftest.py``) are
outside the blocking gate and are never reported.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
ARCHIVE_DIR = REPO / "exports" / "archive"

#: ``exports/archive/<anything>.zip`` as one literal.
_ARCHIVE_PATH_LITERAL = re.compile(r"exports[/\\]archive[/\\][^\s'\"]*\.zip")
#: A bare export name, e.g. ``dynasty_export_20261107_063955.zip``.
_EXPORT_NAME = re.compile(r"dynasty_export_\d{8}_\d{6}\.zip")

#: Words in a skip reason that say "the data this test needs is not in this
#: checkout".  Inventoried from the reasons the suite's own skips carry (see the
#: allowlist file for every current instance).  Matched case-insensitively
#: against the constant text of the reason.
SKIP_REASON_PATTERN = re.compile(
    r"checkout|clone|shallow|archiv|absent|not present|\bmissing\b|no local|"
    r"no complete|not on the|no full-contract|no .{0,40} in this environment",
    re.IGNORECASE,
)

_SKIP_CALLS = {"skip", "skipif", "skipTest", "importorskip", "skipIf", "skipUnless"}


@dataclass(frozen=True)
class Hit:
    kind: str  # "archive-literal" | "missing-data-skip"
    line: int
    detail: str


def _is_livedata_mark(node: ast.expr) -> bool:
    text = ast.unparse(node)
    return text.endswith("mark.livedata") or text.endswith("mark.livedata()")


def _module_is_livedata(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in n.targets)
        and "livedata" in ast.unparse(n.value)
        for n in tree.body
    )


def present_archive_names() -> frozenset[str]:
    """Export names currently in ``exports/archive`` (best effort, working tree)."""
    if not ARCHIVE_DIR.is_dir():
        return frozenset()
    return frozenset(p.name for p in ARCHIVE_DIR.glob("dynasty_export_*.zip"))


def _constant_text(node: ast.AST) -> str:
    """The literal text of a string / f-string; ``""`` for anything computed."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ""


def _call_name(fn: ast.expr) -> str | None:
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        return fn.attr
    return None


def _skip_reason(call: ast.Call) -> str:
    for kw in call.keywords:
        if kw.arg == "reason":
            return _constant_text(kw.value)
    # ``pytest.skip("why")`` / ``self.skipTest("why")``: first positional.  For
    # ``skipif(cond, reason=...)`` the reason is always the keyword, handled above.
    if call.args:
        return _constant_text(call.args[0])
    return ""


def scan_source(source: str, *, known_archives: frozenset[str] = frozenset()) -> list[Hit]:
    """Hits in one test module's source (outside ``livedata`` scopes)."""
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    hits: list[Hit] = []

    def visit(node: ast.AST, live: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            live = live or any(_is_livedata_mark(d) for d in node.decorator_list)
        if not live:
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                text = node.value
                named = _ARCHIVE_PATH_LITERAL.search(text)
                if named is None:
                    bare = _EXPORT_NAME.search(text)
                    if bare is not None and bare.group(0) in known_archives:
                        named = bare
                if named is not None:
                    hits.append(Hit("archive-literal", node.lineno, named.group(0)))
            if isinstance(node, ast.Call) and _call_name(node.func) in _SKIP_CALLS:
                reason = _skip_reason(node)
                if reason and SKIP_REASON_PATTERN.search(reason):
                    hits.append(Hit("missing-data-skip", node.lineno, reason))
        for child in ast.iter_child_nodes(node):
            visit(child, live)

    visit(tree, _module_is_livedata(tree))
    return sorted(hits, key=lambda h: (h.line, h.kind))


def gate_test_files(livedata_modules: frozenset[str]) -> list[Path]:
    """Test modules in the blocking gate: everything but fixtures and livedata modules."""
    out = []
    for path in sorted(TESTS.rglob("test_*.py")):
        rel = path.relative_to(TESTS)
        if rel.parts[0] == "fixtures" or path.name in livedata_modules:
            continue
        out.append(path)
    return out
