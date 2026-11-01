"""Text-mode file I/O must say its encoding.

``open(path)``, ``Path.read_text()`` and ``Path.write_text()`` fall back to the
LOCALE encoding when none is given: UTF-8 on the Linux runners and production
box, cp1252 on a Windows dev box.  The repo's files hold em dashes, box drawing
and player names with accents, so the same call that passes on Linux raises
``UnicodeDecodeError`` (or silently writes mojibake) on Windows.  PR #2008
fixed the instances that made the suite red there; this test keeps the next one
out.

WHAT IS CHECKED (AST, no imports, no network)
    * builtin ``open`` / ``io.open`` in a text mode (no ``b`` in the mode
      string; no mode at all is text) without ``encoding``;
    * ``<anything>.read_text()`` / ``.write_text(data)`` without ``encoding``;
    * ``<anything>.open("r"|"w"|"a"|"x"|"rt"|...)`` -- a ``Path.open`` / gzip
      style call with a literal TEXT mode -- without ``encoding``;
    * ``tempfile.NamedTemporaryFile`` / ``TemporaryFile`` /
      ``SpooledTemporaryFile`` with a literal text mode and no ``encoding``.

WHAT IS EXEMPT
    * binary mode (``"rb"``, ``"wb"``, ...);
    * a mode that is not a string literal (it cannot be proven text);
    * ``zf.open(name)`` and other ``.open`` calls whose first argument is not a
      text-mode literal (a ``ZipFile`` member name is not a mode);
    * a zero-argument ``.open()`` (``webbrowser``, sockets and ``Path.open``
      are indistinguishable without type information);
    * calls using ``*args`` / ``**kwargs`` (the encoding may be inside them).

SCOPE: ``tests/``, ``src/``, ``scripts/``, ``server.py`` and
``Dynasty Scraper.py`` -- the code CI runs and the suite exercises.  ``docs/``
holds audit-evidence scripts, some of them frozen byte-for-byte fixtures, and is
out of scope on purpose.  There is NO baseline: every existing instance was
fixed in the PR that added this test, so any offender is a new one.

``subprocess`` text mode (``text=True`` with no ``encoding``) has the same
locale dependence and is NOT covered here; #2008 handled those call sites by
hand.

FIXING A FAILURE: add ``encoding="utf-8"`` to the call (or open in binary mode
if the bytes are what you mean).  Do not add an allowlist.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SCAN_ROOTS = ("tests", "src", "scripts", "server.py", "Dynasty Scraper.py")

# A mode string that opens in TEXT mode: letters from the open() mode alphabet,
# no ``b``.
_TEXT_MODE = re.compile(r"^[rwaxt+U]*$")
_TEMPFILE_FACTORIES = {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _classify(call: ast.Call) -> str | None:
    """The offender kind for ``call``, or ``None`` when it is fine / unprovable."""
    if any(isinstance(a, ast.Starred) for a in call.args) or any(
        k.arg is None for k in call.keywords
    ):
        return None  # the encoding may travel in *args / **kwargs
    func = call.func
    kwargs = {k.arg for k in call.keywords}
    n_pos = len(call.args)

    def mode_node(positional_index: int) -> ast.AST | None:
        for k in call.keywords:
            if k.arg == "mode":
                return k.value
        return call.args[positional_index] if n_pos > positional_index else None

    is_builtin_open = isinstance(func, ast.Name) and func.id == "open"
    is_io_open = (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and isinstance(func.value, ast.Name)
        and func.value.id == "io"
    )
    if is_builtin_open or is_io_open:
        mode = mode_node(1)
        if mode is None:
            text = True
        else:
            literal = _const_str(mode)
            if literal is None:
                return None
            text = "b" not in literal
        if not text or "encoding" in kwargs or n_pos >= 4:
            return None
        return "open"

    if isinstance(func, ast.Attribute) and func.attr == "open":
        literal = _const_str(mode_node(0))
        if literal is not None and _TEXT_MODE.match(literal):
            if "encoding" in kwargs or n_pos >= 3:
                return None
            return "path.open"
        return None

    if isinstance(func, ast.Attribute) and func.attr == "read_text":
        return None if ("encoding" in kwargs or n_pos >= 1) else "read_text"

    if isinstance(func, ast.Attribute) and func.attr == "write_text":
        return None if ("encoding" in kwargs or n_pos >= 2) else "write_text"

    name = (
        func.attr
        if isinstance(func, ast.Attribute)
        else func.id
        if isinstance(func, ast.Name)
        else None
    )
    if name in _TEMPFILE_FACTORIES:
        # NamedTemporaryFile(mode='w+b', ...) -- the default is BINARY.
        literal = _const_str(mode_node(0))
        if literal is not None and "b" not in literal and "encoding" not in kwargs:
            return "tempfile"
    return None


def find_offenders(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    """``[(line, kind)]`` for every text-mode file call lacking an encoding."""
    tree = ast.parse(source, filename=filename)
    out = [
        (node.lineno, kind)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (kind := _classify(node))
    ]
    return sorted(out)


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        path = REPO_ROOT / root
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(
                p
                for p in sorted(path.rglob("*.py"))
                if "__pycache__" not in p.parts and "node_modules" not in p.parts
            )
    return files


# ── the guard ───────────────────────────────────────────────────────────


def test_no_text_mode_file_io_without_explicit_encoding():
    offenders: list[str] = []
    for path in _scanned_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line, kind in find_offenders(path.read_text(encoding="utf-8"), rel):
            offenders.append(f"{rel}:{line}  {kind}")
    assert not offenders, (
        f"{len(offenders)} text-mode file call(s) without an explicit encoding "
        "(locale-dependent: cp1252 on Windows, UTF-8 on Linux). Add "
        'encoding="utf-8" -- or open in binary mode -- see the module docstring:\n  '
        + "\n  ".join(offenders[:60])
        + ("\n  ..." if len(offenders) > 60 else "")
    )


def test_the_scan_actually_covers_the_trees():
    """A broken root or glob would make the guard pass by scanning nothing."""
    files = _scanned_files()
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in files}
    assert len(files) > 1500, f"only {len(files)} files scanned; SCAN_ROOTS is stale"
    assert "server.py" in rels and "Dynasty Scraper.py" in rels
    assert any(r.startswith("src/") for r in rels)
    assert any(r.startswith("scripts/") for r in rels)
    assert "tests/test_explicit_text_encoding.py" in rels


# ── mutation proofs: the scanner fails what it must and passes what it may ──


def _kinds(source: str) -> list[str]:
    return [k for _line, k in find_offenders(source)]


def test_scanner_flags_each_unencoded_text_call():
    assert _kinds("open('a.txt')") == ["open"]
    assert _kinds("open('a.txt', 'w')") == ["open"]
    assert _kinds("open('a.txt', mode='r')") == ["open"]
    assert _kinds("import io\nio.open('a.txt')") == ["open"]
    assert _kinds("p.read_text()") == ["read_text"]
    assert _kinds("p.write_text('x')") == ["write_text"]
    assert _kinds("p.open('w')") == ["path.open"]
    assert _kinds("p.open(mode='rt')") == ["path.open"]
    assert _kinds("import tempfile\ntempfile.NamedTemporaryFile('w')") == ["tempfile"]
    assert _kinds("from pathlib import Path\nPath('x').write_text(json.dumps(d))") == ["write_text"]


def test_scanner_accepts_encoded_binary_and_unprovable_calls():
    assert _kinds("open('a.txt', encoding='utf-8')") == []
    assert _kinds("open('a.txt', 'w', encoding='utf-8')") == []
    assert _kinds("open('a.txt', 'w', -1, 'utf-8')") == []
    assert _kinds("p.read_text(encoding='utf-8')") == []
    assert _kinds("p.read_text('utf-8')") == []
    assert _kinds("p.write_text('x', encoding='utf-8')") == []
    assert _kinds("p.write_text('x', 'utf-8')") == []
    assert _kinds("open('a.bin', 'rb')") == []
    assert _kinds("open('a.bin', 'wb')") == []
    assert _kinds("open('a.bin', mode='ab')") == []
    assert _kinds("p.open('rb')") == []
    assert _kinds("p.open('w', encoding='utf-8')") == []
    assert _kinds("open(path, mode)") == []  # mode not provable as text
    assert _kinds("open(*args)") == []
    assert _kinds("p.read_text(**kw)") == []
    assert _kinds("zf.open('member.csv')") == []  # a ZipFile member, not a mode
    assert _kinds("webbrowser.open()") == []
    assert _kinds("import tempfile\ntempfile.NamedTemporaryFile()") == []  # binary default
    assert _kinds("import tempfile\ntempfile.NamedTemporaryFile('w', encoding='utf-8')") == []


def test_scanner_reports_the_line_of_each_offender():
    src = "x = 1\n\nwith open('a') as fh:\n    pass\nq.read_text()\n"
    assert find_offenders(src) == [(3, "open"), (5, "read_text")]
