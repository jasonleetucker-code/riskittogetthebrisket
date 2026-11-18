"""Static scanner behind ``tests/test_hermetic_gate_inputs.py``.

Two ways a blocking-gate test comes to depend on a ROLLING checkout instead of
its own committed inputs:

* it names (or lists) a specific ``exports/archive/dynasty_export_<ts>.zip`` -- the archive
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
    r"no complete|not on the|no full-contract|no .{0,40} in this environment|"
    r"not found|no data|does not exist|unavailable",
    re.IGNORECASE,
)

_LISTING_CALLS = {"glob", "rglob", "listdir", "iterdir", "scandir"}
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


def _folded(node: ast.AST) -> str | None:
    """Text of a string built from constants with ``+`` or ``/`` (path joins).

    Non-constant operands (``REPO``, a variable) contribute nothing, so
    ``REPO / "exports" / "archive" / "x.zip"`` folds to ``exports/archive/x.zip``.
    ``None`` when ``node`` is not such an expression."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        left, right = _folded(node.left), _folded(node.right)
        if left is None and right is None:
            return None
        sep = "/" if isinstance(node.op, ast.Div) else ""
        return sep.join(x for x in (left or "", right or "") if x)
    if isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
        return ""
    return None


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


def scan_source(source: str) -> list[Hit]:
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
    consumed: set[int] = set()

    def archive_name(text: str) -> str | None:
        named = _ARCHIVE_PATH_LITERAL.search(text) or _EXPORT_NAME.search(text)
        return named.group(0) if named else None

    def visit(node: ast.AST, live: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            live = live or any(_is_livedata_mark(d) for d in node.decorator_list)
        if not live and id(node) not in consumed:
            if isinstance(node, ast.BinOp):
                text = _folded(node)
                name = archive_name(text) if text else None
                if name is not None:
                    hits.append(Hit("archive-literal", node.lineno, name))
                    consumed.update(id(n) for n in ast.walk(node))
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                name = archive_name(node.value)
                if name is not None:
                    hits.append(Hit("archive-literal", node.lineno, name))
            if isinstance(node, ast.Call):
                called = _call_name(node.func)
                if called in _SKIP_CALLS:
                    reason = _skip_reason(node)
                    if reason and SKIP_REASON_PATTERN.search(reason):
                        hits.append(Hit("missing-data-skip", node.lineno, reason))
                if called in _LISTING_CALLS:
                    text = ast.unparse(node)
                    if "exports" in text and "archive" in text:
                        hits.append(Hit("archive-listing", node.lineno, text[:80]))
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
