"""Append-only shadow ledger + write-once observation panels.

* The ledger is JSONL. A line is appended only when its ``key`` is not already
  present; existing lines are never rewritten, reordered or deleted. Re-running
  the recorder on the same board is a no-op.
* Panels are gzip JSON, one file per full input identity (board payload, code
  revision, value fingerprint, CSV tree, dataset-state tree -- see
  ``record.panel_identity``), written once. A second write with identical
  content is a no-op; a second write with DIFFERENT content for the same full
  identity is refused, because that would mean the build is not a function of
  its pinned inputs. Inputs that differ (a box timer refreshing a CSV between
  two runs on one payload) give a different name: a new panel, never a
  conflict.

Both live under gitignored ``data/robust_filter_shadow/`` by default.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "robust_filter_shadow"
LEDGER_NAME = "ledger.jsonl"
PANEL_DIR = "panels"


class PanelConflict(RuntimeError):
    """A panel already exists under this name with different content."""


def ledger_path(base: Path = DEFAULT_DIR) -> Path:
    return Path(base) / LEDGER_NAME


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    """Every parseable record, in file order. A torn final line is skipped."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                yield record


def existing_keys(path: Path) -> set[str]:
    return {str(r["key"]) for r in iter_records(path) if r.get("key")}


def append_record(path: Path, record: Mapping[str, Any]) -> bool:
    """Append ``record`` unless its key is already recorded. True when written."""
    key = record.get("key")
    if not key:
        raise ValueError("record has no key")
    if key in existing_keys(path):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    # Repair a torn last line (a crash mid-append) by starting on a fresh line,
    # never by rewriting what is already there.
    needs_newline = path.exists() and path.stat().st_size > 0 and not _ends_with_newline(path)
    with path.open("a", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return True


def _ends_with_newline(path: Path) -> bool:
    with path.open("rb") as fh:
        fh.seek(-1, os.SEEK_END)
        return fh.read(1) == b"\n"


def panel_name(identity: Mapping[str, Any]) -> str:
    """``<payload prefix>_<identity hash>.json.gz`` for a full panel identity.

    Panels written before 2026-10-01 were named ``<payload>_<fingerprint>``;
    each record stores its panel's path, so those still resolve.
    """
    payload = str(identity.get("payloadSha256") or "")
    if not payload or payload == "None":
        raise ValueError("panel identity has no payloadSha256")
    canonical = json.dumps(dict(identity), sort_keys=True, separators=(",", ":"), default=str)
    return f"{payload[:16]}_{hashlib.sha256(canonical.encode()).hexdigest()[:16]}.json.gz"


def _panel_bytes(panel: Mapping[str, Any]) -> bytes:
    raw = json.dumps(panel, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, compresslevel=9, mtime=0)


def write_panel(
    base: Path, identity: Mapping[str, Any], panel: Mapping[str, Any]
) -> tuple[Path, bool]:
    """Write a panel once under its full input identity. Returns ``(path, written)``."""
    target = Path(base) / PANEL_DIR / panel_name(identity)
    data = _panel_bytes(panel)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise PanelConflict(str(target))
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    return target, True


def read_panel(path: Path) -> dict[str, Any]:
    return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))
