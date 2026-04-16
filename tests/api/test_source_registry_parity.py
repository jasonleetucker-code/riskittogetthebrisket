"""Backend/frontend source-registry parity test.

The frontend statically mirrors the Python canonical source registry
(``src/api/data_contract.py::_RANKING_SOURCES``) in
``frontend/lib/dynasty-data.js::RANKING_SOURCES``.  The two MUST stay
in lockstep — any drift in keys, weights, scopes, or retail/backbone
flags breaks the single-source-of-truth invariant between client and
server.

This test parses the frontend JS registry out of the JS source file
using a targeted regex + AST-style walk (no eval), then runs
``assert_ranking_source_registry_parity()`` against the Python
registry.  Failures surface as actionable diffs.

When adding a new source:
    1. Register it in ``src/api/data_contract.py::_RANKING_SOURCES``.
    2. Mirror it in ``frontend/lib/dynasty-data.js::RANKING_SOURCES``.
    3. Run this test — it must pass.  If it fails, your frontend
       registry doesn't match the Python one.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    assert_ranking_source_registry_parity,
    get_ranking_source_registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_REGISTRY_PATH = REPO_ROOT / "frontend" / "lib" / "dynasty-data.js"


def _parse_frontend_registry() -> list[dict[str, Any]]:
    """Extract RANKING_SOURCES entries from the frontend JS file.

    The parser is deliberately narrow: it reads the JS source file as
    plain text, locates the ``RANKING_SOURCES = [`` array literal, and
    walks the top-level objects inside.  For each entry it extracts
    the known JSON-compatible fields by regex.  Non-JSON-compatible
    tokens (comments, undefined identifiers) are skipped.

    The narrow parse surface is intentional: we want the test to fail
    loudly on any unusual edit to the frontend registry shape, so
    drift gets flagged immediately rather than silently ignored.

    Returns a list of dicts with the same camelCase fields as
    ``get_ranking_source_registry()``.  The caller wires this into
    ``assert_ranking_source_registry_parity()`` to compare against
    the Python registry.
    """
    if not FRONTEND_REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"Frontend registry file not found: {FRONTEND_REGISTRY_PATH}"
        )
    text = FRONTEND_REGISTRY_PATH.read_text(encoding="utf-8")

    start_match = re.search(
        r"export const RANKING_SOURCES\s*=\s*\[",
        text,
    )
    if not start_match:
        raise ValueError(
            "Could not locate `export const RANKING_SOURCES = [` in frontend/lib/dynasty-data.js"
        )
    start = start_match.end()
    # Walk balanced brackets to locate the matching closing `]`.
    depth = 1
    idx = start
    while idx < len(text) and depth > 0:
        ch = text[idx]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        idx += 1
    if depth != 0:
        raise ValueError("Could not match closing `]` for RANKING_SOURCES array")
    array_body = text[start : idx - 1]

    # Walk top-level `{ ... }` entries in the array body.
    entries: list[str] = []
    depth = 0
    obj_start: int | None = None
    for i, ch in enumerate(array_body):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                entries.append(array_body[obj_start : i + 1])
                obj_start = None

    parsed_entries: list[dict[str, Any]] = []
    for raw_entry in entries:
        parsed_entries.append(_parse_entry(raw_entry))
    return parsed_entries


_STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
_NUMBER_LITERAL = re.compile(r"(-?\d+(?:\.\d+)?)")
_BOOL_LITERAL = re.compile(r"\b(true|false)\b")
_NULL_LITERAL = re.compile(r"\bnull\b")


def _strip_comments(src: str) -> str:
    """Remove // line comments and /* ... */ block comments from a JS snippet."""
    # Block comments first.
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    # Then line comments (up to end of line).
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _parse_entry(raw: str) -> dict[str, Any]:
    """Parse one JS object literal into a dict."""
    body = raw.strip()
    if body.startswith("{"):
        body = body[1:]
    if body.endswith("}"):
        body = body[:-1]
    body = _strip_comments(body)
    out: dict[str, Any] = {}
    # Walk the body key by key.  Fields are: `key: value,`.  We
    # don't support nested objects; the frontend registry only uses
    # scalar values and a single array literal (``extraScopes``).
    i = 0
    n = len(body)
    while i < n:
        # Skip whitespace and commas between fields.
        while i < n and body[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        # Parse a quoted or bare identifier key.
        if body[i] == '"':
            m = _STRING_LITERAL.match(body, i)
            if not m:
                break
            key = m.group(1)
            i = m.end()
        else:
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", body[i:])
            if not m:
                break
            key = m.group(0)
            i += len(key)
        # Skip ':' and whitespace.
        while i < n and body[i] in " \t\n\r":
            i += 1
        if i >= n or body[i] != ":":
            break
        i += 1
        while i < n and body[i] in " \t\n\r":
            i += 1
        value, i = _parse_value(body, i)
        out[key] = value
    return out


def _parse_value(body: str, i: int) -> tuple[Any, int]:
    n = len(body)
    if i >= n:
        return None, i
    ch = body[i]
    if ch == '"':
        m = _STRING_LITERAL.match(body, i)
        if not m:
            return None, i + 1
        return m.group(1), m.end()
    if ch == "[":
        # Array of strings (``extraScopes``).  Parse elements until ].
        depth = 1
        end = i + 1
        while end < n and depth > 0:
            if body[end] == "[":
                depth += 1
            elif body[end] == "]":
                depth -= 1
            end += 1
        inner = body[i + 1 : end - 1]
        elements: list[Any] = []
        inner_i = 0
        while inner_i < len(inner):
            # Skip whitespace and commas.
            while inner_i < len(inner) and inner[inner_i] in " \t\n\r,":
                inner_i += 1
            if inner_i >= len(inner):
                break
            val, inner_i = _parse_value(inner, inner_i)
            elements.append(val)
        return elements, end
    if ch == "{":
        # Not expected in the frontend registry — skip to matching }.
        depth = 1
        end = i + 1
        while end < n and depth > 0:
            if body[end] == "{":
                depth += 1
            elif body[end] == "}":
                depth -= 1
            end += 1
        return None, end
    mb = _BOOL_LITERAL.match(body, i)
    if mb:
        return mb.group(0) == "true", mb.end()
    mn = _NULL_LITERAL.match(body, i)
    if mn:
        return None, mn.end()
    mnum = _NUMBER_LITERAL.match(body, i)
    if mnum:
        raw = mnum.group(0)
        return float(raw) if "." in raw else int(raw), mnum.end()
    # Bare identifier (enum) — read until whitespace or comma.
    end = i
    while end < n and body[end] not in " \t\n\r,":
        end += 1
    token = body[i:end]
    # Known scope constants — map to their string values.
    _SCOPE_CONSTANTS = {
        "SOURCE_SCOPE_OVERALL_OFFENSE": "overall_offense",
        "SOURCE_SCOPE_OVERALL_IDP": "overall_idp",
        "SOURCE_SCOPE_POSITION_IDP": "position_idp",
    }
    if token in _SCOPE_CONSTANTS:
        return _SCOPE_CONSTANTS[token], end
    # Unknown identifier — leave as raw string for visibility in diffs.
    return token, end


class TestBackendFrontendRegistryParity(unittest.TestCase):
    def setUp(self) -> None:
        self.maxDiff = None
        self.py_registry = get_ranking_source_registry()
        self.js_registry = _parse_frontend_registry()

    def test_keys_and_count_match(self) -> None:
        py_keys = [s["key"] for s in self.py_registry]
        js_keys = [s.get("key") for s in self.js_registry]
        self.assertEqual(
            py_keys,
            js_keys,
            "Registry key order mismatch between backend and frontend",
        )

    def test_assert_parity_passes(self) -> None:
        errors = assert_ranking_source_registry_parity(self.js_registry)
        self.assertEqual(
            errors,
            [],
            "Registry parity check failed:\n" + "\n".join(errors),
        )

    def test_every_js_entry_has_column_label(self) -> None:
        for entry in self.js_registry:
            self.assertIn(
                "columnLabel",
                entry,
                f"Frontend entry {entry.get('key')} missing columnLabel",
            )

    def test_every_weight_is_1_0(self) -> None:
        # This is a guardrail on the "no silent weight boosts" rule —
        # if a weight ever drifts off 1.0, either the user asked for
        # it via overrides (which this test does NOT exercise) or
        # someone forgot to update the registry comment explaining
        # why.  Run with a weight != 1.0 to fail loudly.
        for entry in self.py_registry:
            self.assertEqual(
                entry["weight"],
                1.0,
                f"Python registry default weight for {entry['key']} is "
                f"{entry['weight']}; every source must default to 1.0 "
                "(see registry note in src/api/data_contract.py)",
            )
        for entry in self.js_registry:
            self.assertEqual(
                entry.get("weight"),
                1,
                f"Frontend registry default weight for {entry.get('key')} is "
                f"{entry.get('weight')}; every source must default to 1.0",
            )


if __name__ == "__main__":
    unittest.main()
