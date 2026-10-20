"""The ``source_rank`` history lane (outlier-integrity-v2 U4; RECORD-ONLY).

Owner directive 2026-10-20, preregistration
``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §3.2 / §6 and
architecture §3: the per-source, per-observation history that Layer B's
segment baselines (B3) and continuity holds (B4) read — "the median of the
source's previous 3 accepted boards / observations".

Recording moves no value. It is gated by ``source_rank_history_record``
(default OFF) at the fresh-scrape recording site in ``server.py``, beside the
temporal ledger, and only on fresh scrapes (a restart never fabricates a board).
Reading it changes values only through ``outlier_integrity_v2`` (default OFF).

Storage is deliberately NOT a new lane in ``data/temporal_ledger.sqlite``:
that ledger's schema is a production-wide contract (``store.VALID_LANES``), and
this lane holds a folded per-source state rather than per-asset observations.
Two files under ``<root>/data/history/source_rank/`` (gitignored like the rest
of ``data/``):

* ``records.jsonl`` — append-only, one ``oiv2-board-record/v1`` per board
  (``source_integrity.board_record``) with the folded state's hash; never
  rewritten (evidence);
* ``state.json`` — the folded ``IntegrityHistory`` after the newest board
  (``source_integrity.advance``), replaced atomically.

A build reads the state only when it is strictly older than the board being
built, so a replay of a past board can never read a later state; a replay of a
historical tree (``csv_root``) reads that tree's own lane, which exists only if
the replay harness wrote it — never production's.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LANE_DIR = Path("data") / "history" / "source_rank"
STATE_FILE = "state.json"
RECORDS_FILE = "records.jsonl"


def lane_dir(root: Path) -> Path:
    return Path(root) / LANE_DIR


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def load_state(root: Path, *, before: datetime | None = None) -> dict[str, Any] | None:
    """The folded state, or ``None`` when absent, unreadable, or not strictly
    older than ``before`` (a board never reads its own or a later state)."""
    path = lane_dir(root) / STATE_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if before is not None:
        as_of = _parse(raw.get("asOf"))
        if as_of is None or as_of >= before:
            return None
    return raw


def record_board(root: Path, record: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Append ``record`` and replace the folded ``state`` (atomic rename).

    Idempotent on a repeated board: a record whose ``asOf`` is not newer than
    the current state's is skipped (``{"written": False, "reason": ...}``), so a
    retried promotion cannot double-advance the history.
    """
    d = lane_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    current = load_state(root)
    if current is not None:
        cur, new = _parse(current.get("asOf")), _parse(record.get("asOf"))
        if cur is not None and (new is None or new <= cur):
            return {"written": False, "reason": "not_newer_than_state"}
    blob = json.dumps(state, sort_keys=True, separators=(",", ":"))
    state_hash = hashlib.sha256(blob.encode()).hexdigest()
    with (d / RECORDS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**record, "stateSha256": state_hash}, sort_keys=True) + "\n")
    fd, tmp = tempfile.mkstemp(dir=str(d), prefix=".state.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(blob)
        os.replace(tmp, d / STATE_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return {"written": True, "asOf": record.get("asOf"), "stateSha256": state_hash}


def record_contract(contract: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    """Fold one built contract into the lane (the ``server.py`` entry point)."""
    from src.api import source_integrity as si  # noqa: PLC0415

    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    record = si.board_record(contract)
    history = si.IntegrityHistory.from_json(load_state(base))
    state = si.advance(history, record).to_json()
    return record_board(base, record, state)
