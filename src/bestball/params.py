"""Versioned parameter loading for ``src/bestball`` with a content-hashed id.

Same convention as :mod:`src.consensus_edge.params` (itself lifted from
``src/bdvm/params.py``): the ``paramSetId`` is a hash of the file's meaningful
content, computed at load time, so a stored result always names the exact
numbers that produced it.  ``_``-prefixed keys are human annotations and are
excluded from the hash.

No silent defaults: a missing or unreadable file raises, because a default
baked into code would make a stamped ``paramSetId`` describe numbers that did
not produce the result.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

MARGINAL_PARAMS_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "bestball" / "marginal_v1.json"
)

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None


class ParamsUnavailable(RuntimeError):
    """The parameter file is missing, unreadable or malformed."""


def _strip_comments(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_comments(v) for k, v in node.items() if not str(k).startswith("_")}
    if isinstance(node, list):
        return [_strip_comments(v) for v in node]
    return node


def param_set_id(doc: dict[str, Any]) -> str:
    """Content hash over the meaningful (non-``_``) keys, ignoring any stamped id."""
    meaningful = _strip_comments({k: v for k, v in doc.items() if k != "paramSetId"})
    raw = json.dumps(meaningful, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_marginal_params(path: Path | None = None, *, refresh: bool = False) -> dict[str, Any]:
    """The marginal-utility parameter set with ``paramSetId`` attached (a copy)."""
    global _CACHE
    target = path or MARGINAL_PARAMS_PATH
    with _LOCK:
        if _CACHE is not None and not refresh and path is None:
            return copy.deepcopy(_CACHE)
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ParamsUnavailable(f"cannot read {target}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ParamsUnavailable(f"{target} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ParamsUnavailable(f"{target} must contain a JSON object")
        for key in ("draws", "seed", "candidatesPerSlotFamily", "materialityPpg"):
            if key not in parsed:
                raise ParamsUnavailable(f"{target} is missing required key {key!r}")
        parsed["paramSetId"] = param_set_id(parsed)
        if path is None:
            _CACHE = parsed
        return copy.deepcopy(parsed)


def with_overrides(params: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """A copy of ``params`` with values replaced and ``paramSetId`` re-minted.

    The id always describes the numbers actually used — an override (for
    example the fast ``testDraws`` count) is a different parameter set.
    """
    out = {**copy.deepcopy(params), **overrides}
    out["paramSetId"] = param_set_id(out)
    return out
