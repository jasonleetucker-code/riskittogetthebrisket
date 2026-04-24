"""ESPN endpoint schema drift detection (upgrade item #8).

ESPN's undocumented endpoints drift without warning — a field
rename, an added wrapper, a removed sub-object can break our
parsers silently.  This module takes a sample response from each
endpoint we consume, hashes the shape, and compares to a stored
baseline.  When the shape changes, emit an alert.

Shape hash
----------
For each sample, walk the JSON tree and produce a canonical
token stream like::

    root:object
      injuries:list[object]
        team:object
          abbreviation:string
        injuries:list[object]
          athlete:object
            id:string|number
            displayName:string

Two responses with the same keys + types hash identical,
regardless of values.  A rename or added field changes the hash.

Baseline lives in ``config/espn_schema_baseline.json`` — a
``{endpoint: {hash, first_seen}}`` dict.  Operators bump the
baseline after confirming a drift is benign.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)


def shape_of(node: Any, _depth: int = 0, _max_depth: int = 6) -> str:
    """Recursively describe the shape of a JSON value.

    Returns a canonical string hashable for drift detection.
    Caps recursion depth at 6 so deeply nested lists don't blow
    the algorithm.
    """
    if _depth >= _max_depth:
        return "..."
    if node is None:
        return "null"
    if isinstance(node, bool):
        return "bool"
    if isinstance(node, int):
        return "int"
    if isinstance(node, float):
        return "float"
    if isinstance(node, str):
        return "string"
    if isinstance(node, list):
        if not node:
            return "list[]"
        # Merge types of ALL elements — prevents a single element
        # with an extra field from changing the hash every time.
        child_shapes = sorted({shape_of(e, _depth + 1, _max_depth) for e in node[:50]})
        return f"list[{'|'.join(child_shapes)}]"
    if isinstance(node, dict):
        parts = []
        for key in sorted(node.keys()):
            parts.append(f"{key}:{shape_of(node[key], _depth + 1, _max_depth)}")
        return "object{" + ",".join(parts) + "}"
    return type(node).__name__


def hash_shape(node: Any) -> str:
    return hashlib.sha256(shape_of(node).encode("utf-8")).hexdigest()[:16]


def load_baseline(path: Path | None = None) -> dict[str, dict[str, Any]]:
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "espn_schema_baseline.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("espn schema baseline load failed: %s", exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def save_baseline(
    baseline: dict[str, dict[str, Any]], *, path: Path | None = None,
) -> Path:
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "espn_schema_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def detect_drift(
    sample_by_endpoint: dict[str, Any],
    *,
    baseline_path: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Compare sample responses to the stored baseline.

    Returns ``{endpoint: {"status", "current_hash", "baseline_hash"}}``
    where status ∈ {"unchanged", "drifted", "new"}.

    ``new`` endpoints aren't flagged as drift; they get added to
    the baseline on the next ``save_baseline(updated)`` call.
    """
    baseline = load_baseline(baseline_path)
    out: dict[str, dict[str, Any]] = {}
    for endpoint, sample in sample_by_endpoint.items():
        h = hash_shape(sample)
        prior = baseline.get(endpoint)
        if not prior or not isinstance(prior, dict):
            out[endpoint] = {
                "status": "new", "current_hash": h, "baseline_hash": None,
            }
            continue
        prior_hash = str(prior.get("hash") or "")
        if h == prior_hash:
            out[endpoint] = {
                "status": "unchanged", "current_hash": h,
                "baseline_hash": prior_hash,
            }
        else:
            out[endpoint] = {
                "status": "drifted", "current_hash": h,
                "baseline_hash": prior_hash,
            }
    return out


def format_drift_email(drift_report: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """Build (subject, body) for an alert email."""
    drifted = [
        ep for ep, info in drift_report.items()
        if info.get("status") == "drifted"
    ]
    new = [
        ep for ep, info in drift_report.items()
        if info.get("status") == "new"
    ]
    subject = f"[Brisket Ops] ESPN schema drift — {len(drifted)} endpoints changed"
    lines = []
    if drifted:
        lines.append("Endpoints whose shape changed:")
        for ep in drifted:
            info = drift_report[ep]
            lines.append(
                f"  • {ep}: {info['baseline_hash'][:8]} → {info['current_hash'][:8]}"
            )
        lines.append("")
        lines.append(
            "Action: inspect the response, confirm parser still works, "
            "then bump the baseline via:"
        )
        lines.append("    python3 scripts/update_espn_schema_baseline.py")
    if new:
        lines.append("")
        lines.append("New endpoints (first observed):")
        for ep in new:
            lines.append(f"  • {ep}: {drift_report[ep]['current_hash'][:8]}")
    return subject, "\n".join(lines)


def run_drift_check(
    fetchers: dict[str, Callable[[], Any]],
    *,
    delivery: Callable[[str, str, str], bool] | None = None,
    to_email: str | None = None,
    baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Fetch every endpoint, compare shapes, fire one email if
    drift detected.  Returns a summary."""
    samples: dict[str, Any] = {}
    for endpoint, fetch in fetchers.items():
        try:
            samples[endpoint] = fetch()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("drift-check fetch %s failed: %s", endpoint, exc)
    report = detect_drift(samples, baseline_path=baseline_path)
    drifted_count = sum(1 for v in report.values() if v.get("status") == "drifted")
    summary = {
        "endpoints_checked": len(samples),
        "drifted": drifted_count,
        "new": sum(1 for v in report.values() if v.get("status") == "new"),
        "report": report,
    }
    if drifted_count > 0 and delivery and to_email:
        subject, body = format_drift_email(report)
        try:
            summary["delivered"] = bool(delivery(to_email, subject, body))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("drift-check delivery failed: %s", exc)
            summary["delivered"] = False
    return summary
