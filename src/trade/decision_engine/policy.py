"""The declared policy table: strategy x A-class x P-class -> verdict code.

No weights and no aggregate utility.  The table, its bands and its essentials
live in ``config/trade/decision_engine_v1.json``; :func:`load_params` resolves
the two numbers owned elsewhere (``materialityPpg`` / ``largeMultiple`` from
``config/trade/analyze_trade.json``) and stamps a content-hash ``paramSetId``
over the RESOLVED parameters, so a change in either file changes the id.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.trade.decision_engine.contracts import STRATEGIES, TermResult

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "config" / "trade" / "decision_engine_v1.json"

A_CLASSES = ("O+", "O", "0", "F", "F+")
P_CLASSES = ("O+", "O", "0", "F", "F+", "-")
_VERDICTS = ("YES", "NO", "TIE")
_DECIDED_BY = ("A", "P", "both", "strategy", "none")
#: Verdict order used by the monotonicity check (TIE sits between NO and YES).
VERDICT_ORDER = {"NO": 0, "TIE": 1, "YES": 2}


class PolicyConfigError(ValueError):
    """The policy config is incomplete or malformed -- never silently defaulted."""


def _resolve_pointer(pointer: str) -> Any:
    path, _, keys = pointer.partition("#")
    node: Any = json.loads((ROOT / path).read_text(encoding="utf-8"))
    for key in keys.split("."):
        if not isinstance(node, Mapping) or key not in node:
            raise PolicyConfigError(f"unresolvable parameter pointer {pointer!r}")
        node = node[key]
    if not isinstance(node, (int, float)) or isinstance(node, bool):
        raise PolicyConfigError(f"{pointer!r} must be a number")
    return float(node)


def _strip_comments(node: Any) -> Any:
    if isinstance(node, Mapping):
        return {k: _strip_comments(v) for k, v in node.items() if not str(k).startswith("_")}
    if isinstance(node, list):
        return [_strip_comments(v) for v in node]
    return node


def param_set_id(params: Mapping[str, Any]) -> str:
    body = {k: v for k, v in params.items() if k != "paramSetId"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "de1-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def validate_params(params: Mapping[str, Any]) -> None:
    policy = params.get("policy")
    if not isinstance(policy, Mapping):
        raise PolicyConfigError("policy table missing")
    for s in STRATEGIES:
        for a in A_CLASSES:
            for p in P_CLASSES:
                row = policy.get(f"{s}|{a}|{p}")
                if not isinstance(row, Mapping):
                    raise PolicyConfigError(f"policy row {s}|{a}|{p} missing")
                if row.get("verdict") not in _VERDICTS or row.get("decidedBy") not in _DECIDED_BY:
                    raise PolicyConfigError(f"policy row {s}|{a}|{p} malformed")
    if len(policy) != len(STRATEGIES) * len(A_CLASSES) * len(P_CLASSES):
        raise PolicyConfigError("policy table has undeclared rows")
    for s in STRATEGIES:
        ess = (params.get("essentials") or {}).get(s)
        if not isinstance(ess, list) or "A" not in ess:
            raise PolicyConfigError(f"essentials for {s} must include A")
    c = params["terms"]["C"]
    for key in ("materialityPpg", "largeMultiple", "zPrior", "precisionGateFraction"):
        if not isinstance(c.get(key), (int, float)) or c[key] <= 0:
            raise PolicyConfigError(f"terms.C.{key} must be a positive number")


def load_params(path: Path | None = None) -> dict[str, Any]:
    """The resolved, validated parameters with their ``paramSetId``."""
    raw = json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))
    params = copy.deepcopy(_strip_comments(raw))
    c = params["terms"]["C"]
    c["materialityPpg"] = _resolve_pointer(c["materialityPpgFrom"])
    c["largeMultiple"] = _resolve_pointer(c["largeMultipleFrom"])
    validate_params(params)
    params["paramSetId"] = param_set_id(params)
    return params


def class_key(term: TermResult | None, *, voting_required: bool = False) -> str:
    """A voting term's class; ``-`` when the term does not vote."""
    if term is None or not term.counted_as_vote:
        if voting_required:
            raise ValueError("the A term must vote before a policy row can be read")
        return "-"
    if term.direction == "neutral" or term.direction is None:
        return "0"
    base = "F" if term.direction == "favours" else "O"
    return base + "+" if term.magnitude_class == "large" else base


@dataclass(frozen=True)
class PolicyOutcome:
    verdict: str  # YES / NO (a TIE is NO with neutral_tag)
    neutral_tag: bool
    decided_by: str
    row_key: str
    raw_verdict: str


def decide_row(
    params: Mapping[str, Any], strategy: str, a_class: str, p_class: str
) -> PolicyOutcome:
    key = f"{strategy}|{a_class}|{p_class}"
    row = params["policy"][key]
    raw = row["verdict"]
    return PolicyOutcome(
        verdict="NO" if raw == "TIE" else raw,
        neutral_tag=raw == "TIE",
        decided_by=row["decidedBy"],
        row_key=key,
        raw_verdict=raw,
    )
