"""Shared scanner for owner-locked feature flags (not a test module).

Used by ``tests/api/test_dlf_idp_hold_locked.py`` (a false-y value would LIFT
the DLF IDP hold) and ``tests/api/test_dlf_values_hold_locked.py`` (a true-y
value would ACTIVATE DLF Values voting).  It finds tracked surfaces that
ASSIGN an owner-locked ``RISKIT_FEATURE_*`` variable a forbidden value.

Recognised (each pinned by a recogniser test in both callers):

* shell / env-file / systemd ``Environment=`` / YAML / JSON / Python
  assignments of the literal variable name;
* the subshell ``(VAR=0 cmd)``, command substitution ``$(VAR=0 cmd)`` and
  backtick ``\\`VAR=0 cmd\\``` forms -- an assignment followed by a command
  word, as opposed to prose such as ``(VAR=0 + restart`` or ````VAR=0````;
* INDIRECT names built at run time -- ``RISKIT_FEATURE_${NAME}=0``,
  ``RISKIT_FEATURE_$NAME=0``, ``f"RISKIT_FEATURE_{name.upper()}"] = "0"`` --
  in a file that also names the locked flag.  That is the feasible bound: a
  dynamic name with no mention of the flag anywhere in the file is not
  attributable, and plain variable indirection (``env[F] = "1"`` where
  ``F = "RISKIT_..."``) is not recognised.

Prose stays documentation: comment lines, and any assignment followed by
``+`` (``VAR=0 + restart``) or a closing backtick.

The scan covers every tracked file under ``deploy/``, ``.github/``,
``config/``, ``scripts/``, ``src/`` and ``frontend/``, ``server.py``, and env /
systemd unit files anywhere in the tree.  ``tests/`` and ``docs/`` are
excluded: tests force flags in-process to measure, docs describe.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

FALSEY = r"(?:0|false|no|off)"
TRUTHY = r"(?:1|true|yes|on)"

#: Directories whose tracked files configure, deploy or run the product.
SURFACE_DIRS = ("deploy/", ".github/", "config/", "scripts/", "src/", "frontend/")
SURFACE_FILES = frozenset({"server.py"})
#: Env / unit files anywhere in the tree.
SURFACE_NAME = re.compile(
    r"(^|/)(\.env[^/]*|[^/]*\.env(\.[^/]*)?|[^/]*\.(service|timer|socket|path)(\.template)?)$"
)
_EXCLUDED_PREFIXES = ("tests/", "docs/", "frontend/node_modules/")

_SEP = r"""["']?\s*\]?\s*[=:,]\s*["']?"""
#: An assignment followed by a command word: ``VAR=0 python ...``.
_COMMAND_AFTER = re.compile(r"""^["']?\s+(?!\+)[A-Za-z_./$"'\\-]""")
#: Prose continuations: ``VAR=0 + restart``, ````VAR=0````.
_PROSE_AFTER = re.compile(r"""^["']?\s*(\+|`)""")


def _literal(env: str, values: str) -> re.Pattern[str]:
    return re.compile(re.escape(env) + _SEP + values + r"\b", re.IGNORECASE)


def _indirect(values: str) -> re.Pattern[str]:
    name = r"RISKIT_FEATURE_(?:\$\{[^}]*\}|\$[A-Za-z_]\w*|\{[^}]*\})\w*"
    return re.compile(name + _SEP + values + r"\b", re.IGNORECASE)


def _is_assignment(line: str, m: re.Match[str]) -> bool:
    rest = line[m.end() :]
    if _PROSE_AFTER.match(rest):
        return False
    before = line[max(0, m.start() - 1) : m.start()]
    if before in ("(", "`"):
        # ``(VAR=0 cmd)`` / ``$(VAR=0 cmd)`` / `` `VAR=0 cmd` `` run a command;
        # ``(VAR=0)`` alone or followed by prose is a parenthesised mention.
        return bool(_COMMAND_AFTER.match(rest))
    return True


def forbidden_assignments(text: str, env: str, values: str, flag: str) -> list[str]:
    """Lines of ``text`` that ASSIGN ``env`` one of ``values`` (regex
    alternation, e.g. :data:`FALSEY`), literally or through an indirect name
    in a file that names ``flag``."""
    literal = _literal(env, values)
    indirect = _indirect(values) if _names_flag(text, flag) else None
    hits = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("#", "//", "*", ";")):
            continue
        for pattern in (literal, indirect):
            if pattern is None:
                continue
            if any(_is_assignment(line, m) for m in pattern.finditer(line)):
                hits.append(line.strip())
                break
    return hits


def _names_flag(text: str, flag: str) -> bool:
    return flag in text or flag.upper() in text


def tracked_surface_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        pytest.skip("git is unavailable; cannot enumerate tracked files")
    files = []
    for rel in filter(None, out.split("\0")):
        if rel.startswith(_EXCLUDED_PREFIXES):
            continue
        if rel.startswith(SURFACE_DIRS) or rel in SURFACE_FILES or SURFACE_NAME.search(rel):
            path = REPO / rel
            if path.is_file():
                files.append(path)
    return files


def surface_offenders(env: str, values: str, flag: str) -> dict[str, list[str]]:
    files = tracked_surface_files()
    assert files, "found no tracked deploy/config surface to scan"
    offenders = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "RISKIT_FEATURE_" not in text:
            continue
        hits = forbidden_assignments(text, env, values, flag)
        if hits:
            offenders[str(path.relative_to(REPO))] = hits
    return offenders
