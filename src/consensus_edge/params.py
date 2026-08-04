"""Versioned parameter loading with a content-hashed identity.

Every Consensus Edge payload carries a ``paramSetId``.  It is a hash of
the parameter file's content, so a stored result can always be traced to
the exact numbers that produced it, and editing a shipped parameter
produces a new id rather than silently changing the meaning of old rows.

The pattern is lifted from ``src/bdvm/params.py`` deliberately: this repo
already has one convention for "constants that might change and must
stay attributable", and a second one would be a drift risk, not a
feature.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

PARAMS_PATH = Path(__file__).resolve().parents[2] / "config" / "consensus_edge" / "params_v1.json"

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None


class ParamsUnavailable(RuntimeError):
    """The parameter file is missing or unreadable.

    Raised rather than falling back to defaults baked into code: a
    silent default would mean the ``paramSetId`` on a payload did not
    describe the numbers that produced it, which defeats the point of
    stamping it.
    """


def _strip_comments(node: Any) -> Any:
    """Drop ``_``-prefixed annotation keys before hashing.

    The rationale blocks are for humans and change far more often than
    the values.  Hashing them would churn the id on a comment edit and
    make two genuinely identical parameter sets look different.
    """
    if isinstance(node, dict):
        return {k: _strip_comments(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [_strip_comments(v) for v in node]
    return node


def load(path: Path | None = None, *, refresh: bool = False) -> dict[str, Any]:
    """Return the parameter set, with ``paramSetId`` attached.

    Cached per process; ``refresh=True`` re-reads (used by tests that
    write a temporary parameter file).
    """
    global _CACHE
    target = path or PARAMS_PATH
    with _LOCK:
        if _CACHE is not None and not refresh and path is None:
            return _CACHE
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ParamsUnavailable(f"cannot read {target}: {exc}") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ParamsUnavailable(f"{target} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ParamsUnavailable(f"{target} must contain a JSON object")

        meaningful = _strip_comments(parsed)
        digest = hashlib.sha256(
            json.dumps(meaningful, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        parsed["paramSetId"] = digest
        if path is None:
            _CACHE = parsed
        return parsed


def param_set_id(path: Path | None = None) -> str:
    return str(load(path)["paramSetId"])
