"""Shared plumbing for the AL-4a / AL-3b report-only scorecard scripts.

Only process concerns live here: the code-revision token, the private output
location, deterministic JSON writing and receipt emission. Every number the
scorecards publish comes from ``src/model_registry/game_day_calibration.py`` and
``src/model_registry/projection_scorecard.py``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[1]
#: Private: ``data/`` is gitignored and ``data/learning/`` is the learning store's
#: own tree. Never ``docs/`` (public) and never ``data/ros/`` (force-added by the
#: scheduled refresh).
SCORECARD_DIR = REPO / "data" / "learning" / "scorecards"


def _git(*args: str) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip()


def code_revision(paths: Iterable[str]) -> str:
    """``HEAD`` (+ ``-dirty-<digest>`` when the scorecard's own files differ from it)."""
    from src.model_registry.producer_receipts import evaluator_revision_token

    head = _git("rev-parse", "HEAD") or "unknown-revision"
    rels = list(paths)
    dirty = bool(_git("status", "--porcelain", "--", *rels))
    digest = hashlib.sha256(_git("diff", "HEAD", "--", *rels).encode("utf-8")).hexdigest()
    return evaluator_revision_token(head, dirty=dirty, tree_digest=digest)


def write_json(path: Path, payload: Any) -> Path:
    """Deterministic bytes: sorted keys, fixed separators, trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, sort_keys=True, indent=1, ensure_ascii=True) + "\n"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def emit(build: Callable[[], Iterable[Any]], *, label: str) -> dict[str, Any]:
    """Store receipts only when the operator enabled them (fail closed)."""
    from src.model_registry.producer_receipts import emit_safely, receipts_enabled

    if not receipts_enabled():
        receipts = list(build())
        print(
            f"learning receipts ({label}): built={len(receipts)} (store disabled; "
            "set RISKIT_RECEIPTS_ENABLED=1 to record)"
        )
        return {"ok": True, "built": len(receipts), "stored": False}
    return emit_safely(build, label=label)
