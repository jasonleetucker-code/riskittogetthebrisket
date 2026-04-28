"""Backend ↔ frontend parity for the ROS source registry.

Mirrors the dynasty parity test (``tests/api/test_source_registry_parity.py``).
Parses ``frontend/lib/ros-sources.js`` with a narrow regex + AST-style
walk (no eval) and diffs each entry against
``src/ros/sources/__init__.py::ROS_SOURCES``.

Adding a new ROS source REQUIRES updating both registries — this test
fails loudly when they drift.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from src.ros.sources import ROS_SOURCES

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PATH = REPO_ROOT / "frontend" / "lib" / "ros-sources.js"


def _strip_comments(src: str) -> str:
    """Strip JS comments, preserving ``//`` inside string literals.

    A naive ``//[^\\n]*`` regex eats URL substrings like ``https://...``
    inside our string values.  Walk the source character by character,
    track whether we're inside a string, and only strip line comments
    when outside one.  Block comments are still safe to strip with a
    single regex pass since ``/*`` doesn't appear in any URL.
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    out: list[str] = []
    i = 0
    n = len(src)
    in_str: str | None = None
    while i < n:
        ch = src[i]
        if in_str is None:
            if ch in ('"', "'"):
                in_str = ch
                out.append(ch)
                i += 1
                continue
            if ch == "/" and i + 1 < n and src[i + 1] == "/":
                # Skip to end-of-line
                while i < n and src[i] != "\n":
                    i += 1
                continue
        else:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(src[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
        out.append(ch)
        i += 1
    return "".join(out)


_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_NUMBER = re.compile(r"(-?\d+(?:\.\d+)?)")
_BOOL = re.compile(r"\b(true|false)\b")


def _parse_value(body: str, i: int) -> tuple[Any, int]:
    n = len(body)
    if i >= n:
        return None, i
    ch = body[i]
    if ch == '"':
        m = _STRING.match(body, i)
        if not m:
            return None, i + 1
        return m.group(1), m.end()
    if ch == "{":
        depth = 1
        end = i + 1
        while end < n and depth > 0:
            if body[end] == "{":
                depth += 1
            elif body[end] == "}":
                depth -= 1
            end += 1
        return None, end
    bool_m = _BOOL.match(body, i)
    if bool_m:
        return bool_m.group(1) == "true", bool_m.end()
    num_m = _NUMBER.match(body, i)
    if num_m:
        text = num_m.group(1)
        return (float(text) if "." in text else int(text)), num_m.end()
    if body.startswith("null", i):
        return None, i + 4
    return None, i + 1


def _parse_entry(raw: str) -> dict[str, Any]:
    body = raw.strip().lstrip("{").rstrip("}")
    body = _strip_comments(body)
    out: dict[str, Any] = {}
    i = 0
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\n\r,":
            i += 1
        if i >= n:
            break
        if body[i] == '"':
            m = _STRING.match(body, i)
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


def _parse_frontend() -> list[dict[str, Any]]:
    text = FRONTEND_PATH.read_text(encoding="utf-8")
    start = re.search(r"export const ROS_SOURCES\s*=\s*\[", text)
    if not start:
        raise AssertionError("ROS_SOURCES export missing in frontend/lib/ros-sources.js")
    idx = start.end()
    depth = 1
    while idx < len(text) and depth > 0:
        if text[idx] == "[":
            depth += 1
        elif text[idx] == "]":
            depth -= 1
        idx += 1
    body = text[start.end() : idx - 1]
    entries: list[str] = []
    depth = 0
    obj_start: int | None = None
    for i, ch in enumerate(body):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                entries.append(body[obj_start : i + 1])
                obj_start = None
    return [_parse_entry(e) for e in entries]


# Field-name mapping (snake_case → camelCase).
_PY_TO_JS = {
    "key": "key",
    "display_name": "displayName",
    "source_url": "sourceUrl",
    "source_type": "sourceType",
    "scoring_format": "scoringFormat",
    "is_superflex": "isSuperflex",
    "is_2qb": "is2qb",
    "is_te_premium": "isTePremium",
    "is_idp": "isIdp",
    "is_ros": "isRos",
    "is_dynasty": "isDynasty",
    "is_projection_source": "isProjectionSource",
    "base_weight": "baseWeight",
    "stale_after_hours": "staleAfterHours",
    "enabled": "enabled",
}


class TestRosSourceRegistryParity(unittest.TestCase):
    def test_keys_match_in_order(self):
        py_keys = [s["key"] for s in ROS_SOURCES]
        js_keys = [s.get("key") for s in _parse_frontend()]
        self.assertEqual(py_keys, js_keys)

    def test_field_values_match(self):
        js_by_key = {s["key"]: s for s in _parse_frontend()}
        for py in ROS_SOURCES:
            js = js_by_key.get(py["key"])
            self.assertIsNotNone(js, f"frontend missing entry for {py['key']}")
            for py_field, js_field in _PY_TO_JS.items():
                if py_field == "scraper":
                    continue
                self.assertEqual(
                    py.get(py_field),
                    js.get(js_field),
                    f"mismatch on {py['key']}.{py_field}",
                )


if __name__ == "__main__":
    unittest.main()
