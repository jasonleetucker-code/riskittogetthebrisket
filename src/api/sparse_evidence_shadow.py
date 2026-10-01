"""Shadow collection for the sparse-evidence estimator (Batch 3 Unit E, SHADOW ONLY).

The estimator (candidate C, flag ``sparse_evidence_estimator``) did not meet its
preregistered gate (G2c; ``docs/valuation/evidence/sparse-evidence-2026-10-01/``)
and stays OFF. The question it raises -- should a single-family row keep its
observation, with uncertainty carried separately? -- can only be settled by
outcome evidence: what these players' values do on later boards. This module
records, for each fresh board, both answers side by side so that evidence
accumulates:

* the incumbent (flag OFF, the 0.30 single-source retention -- what is served);
* candidate C (flag ON): its central estimate, sensitivity interval, censored
  bounds, refusals and the row's ``evidenceState``.

One JSON line per (board payload, code revision, inputs, estimator version),
appended to gitignored ``data/sparse_evidence_shadow/ledger.jsonl``. Existing
lines are never rewritten; a re-run on the same board is a no-op.

**It never writes a served field.** Both boards are built in memory through
``value_replay.build`` with the flag pinned per build and restored afterwards;
nothing here touches ``exports/``, the live contract, a flag default or any
promotion path. Record fields use their own names (``incumbentValue``,
``challengerValue``) so a ledger line can never be mistaken for a contract row.
Pinned by ``tests/api/test_sparse_evidence_shadow.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.api import sparse_evidence as se

SCHEMA = "sparse-evidence-shadow/v1"
FLAG = "sparse_evidence_estimator"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "data" / "sparse_evidence_shadow"
LEDGER_NAME = "ledger.jsonl"


def ledger_path(base: Path = DEFAULT_DIR) -> Path:
    return Path(base) / LEDGER_NAME


# ── the per-board comparison (pure) ─────────────────────────────────


def _rows(contract: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        name = row.get("displayName")
        if name:
            out[f"{name}|{row.get('position') or ''}"] = row
    return out


def _num(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def shadow_rows(
    incumbent: Mapping[str, Any], challenger: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Every row the estimator scoped, both answers side by side.

    Returns ``(rows, counts)``. ``counts`` names any row the two builds
    disagree on SCOPE for (a haircut row with no block, or a block on a row the
    incumbent did not haircut): those would mean the comparison is broken.
    """
    inc, ch = _rows(incumbent), _rows(challenger)
    out: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for key in sorted(set(inc) | set(ch)):
        i_row, c_row = inc.get(key) or {}, ch.get(key) or {}
        block = c_row.get("sparseEvidence")
        haircut = bool(i_row.get("singleSourceValuePenaltyApplied"))
        if not isinstance(block, Mapping):
            counts["haircutRowsWithoutBlock"] += haircut
            continue
        counts["scoped"] += 1
        counts["blockWithoutHaircut"] += not haircut
        interval = block.get("sensitivityInterval") or {}
        out.append(
            {
                "asset": key,
                "position": c_row.get("position"),
                "assetClass": c_row.get("assetClass"),
                "rookie": bool(c_row.get("rookie")),
                "evidenceState": block.get("evidenceState"),
                "evidenceCauses": list(block.get("evidenceCauses") or []),
                "estimatorState": block.get("state"),
                "observedFamily": block.get("observedFamily"),
                "observationCount": block.get("observationCount"),
                "observedValue": block.get("observedValue"),
                "challengerEstimate": block.get("centralEstimate"),
                "challengerInterval": [interval.get("low"), interval.get("high")],
                "intervalLabel": interval.get("label"),
                "bindingBounds": [
                    [c.get("family"), c.get("bound")]
                    for c in block.get("censoredFamiliesUsed") or []
                ],
                "nonBindingBounds": [
                    [c.get("family"), c.get("bound")] for c in block.get("nonBindingFamilies") or []
                ],
                "refusedFamilies": dict(block.get("refusedFamilies") or {}),
                "listedNotVotingFamilies": dict(block.get("listedNotVotingFamilies") or {}),
                "incumbentValue": _num(i_row.get("rankDerivedValue")),
                "incumbentRank": _num(i_row.get("canonicalConsensusRank")),
                "challengerValue": _num(c_row.get("rankDerivedValue")),
                "challengerRank": _num(c_row.get("canonicalConsensusRank")),
                "incumbentConfidence": i_row.get("confidenceBucket"),
                "challengerConfidence": c_row.get("confidenceBucket"),
            }
        )
    return out, dict(counts)


def assemble_record(
    *,
    board: Mapping[str, Any],
    pins: Mapping[str, Any],
    rows: list[dict[str, Any]],
    counts: Mapping[str, int],
    recorded_at: str,
) -> dict[str, Any]:
    """One ledger line. ``key`` is the board + code + inputs identity."""
    identity = {
        "payloadSha256": board.get("payloadSha256"),
        "codeRevision": pins.get("codeRevision"),
        "workingTreeDirty": pins.get("workingTreeDirty"),
        "inputsSha256": pins.get("inputsSha256"),
        "estimator": se.ESTIMATOR_VERSION,
    }
    key = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return {
        "schema": SCHEMA,
        "key": key,
        "identity": identity,
        "recordedAt": recorded_at,
        "board": dict(board),
        "pins": dict(pins),
        "label": (
            "SHADOW: incumbent = served (flag OFF); challenger = candidate C (flag ON), "
            "built in memory, never served. Interval is uncalibrated."
        ),
        "counts": dict(counts),
        "evidenceStates": dict(Counter(r["evidenceState"] for r in rows)),
        "rows": rows,
    }


# ── the append-only ledger ─────────────────────────────────────────


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


def append_record(path: Path, record: Mapping[str, Any]) -> bool:
    """Append ``record`` unless its key is already recorded. True when written."""
    key = record.get("key")
    if not key:
        raise ValueError("record has no key")
    if any(r.get("key") == key for r in iter_records(path)):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)
    torn = path.exists() and path.stat().st_size > 0 and not _ends_with_newline(path)
    with path.open("a", encoding="utf-8") as fh:
        if torn:  # a crash mid-append: start fresh, never rewrite what is there
            fh.write("\n")
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return True


def _ends_with_newline(path: Path) -> bool:
    with path.open("rb") as fh:
        fh.seek(-1, os.SEEK_END)
        return fh.read(1) == b"\n"


# ── building and recording one board ────────────────────────────────


def _inputs_sha(pins: Mapping[str, Any]) -> str:
    parts = {k: pins.get(k) for k in ("sourceCsvs", "freshnessState", "config", "fetchStamps")}
    parts["leagues"] = (pins.get("localLeagueSnapshots") or {}).get("files")
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def build_pair(raw: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The served board (flag OFF) and candidate C (flag ON), in memory."""
    from src.api import value_replay as vr  # noqa: PLC0415 -- heavy import, run time only

    with vr._flag(FLAG, False):
        incumbent = vr.build(raw)
    with vr._flag(FLAG, True):
        challenger = vr.build(raw)
    return incumbent, challenger


def record_board(
    raw: Mapping[str, Any],
    payload_path: Path,
    *,
    base: Path = DEFAULT_DIR,
    source: str | None = None,
) -> tuple[dict[str, Any], bool] | None:
    """Build both answers for one payload and append one ledger line.

    Returns ``(record, written)``; ``None`` when a built contract is malformed.
    """
    from src.api import feature_flags  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    incumbent, challenger = build_pair(raw)
    if not all(isinstance(c.get("playersArray"), list) for c in (incumbent, challenger)):
        return None
    rows, counts = shadow_rows(incumbent, challenger)
    replay_pins = vr.pins(Path(payload_path))
    pins = {
        "codeRevision": replay_pins.get("codeRevision"),
        "workingTreeDirty": replay_pins.get("workingTreeDirty"),
        "inputsSha256": _inputs_sha(replay_pins),
        "flagsAtRecord": feature_flags.snapshot(),
        "estimator": se.ESTIMATOR_VERSION,
        "singleSourceRetention": replay_pins.get("singleSourceRetention"),
        "contractVersion": replay_pins.get("contractVersion"),
    }
    data = Path(payload_path).read_bytes()
    board = {
        "source": source or Path(payload_path).name,
        "payloadSha256": hashlib.sha256(data).hexdigest(),
        "scrapeTimestamp": raw.get("scrapeTimestamp") or raw.get("date"),
        "boardHashIncumbent": vr.board_hash(incumbent),
        "boardHashChallenger": vr.board_hash(challenger),
        "rows": len(incumbent["playersArray"]),
    }
    record = assemble_record(
        board=board,
        pins=pins,
        rows=rows,
        counts=counts,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    return record, append_record(ledger_path(base), record)


def newest_live_payload(root: Path = REPO_ROOT) -> Path | None:
    """The newest served payload on this box (``exports/latest`` first)."""
    for directory in (root / "exports" / "latest", root / "data"):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("dynasty_data*.json"), reverse=True):
            try:
                if isinstance(json.loads(path.read_bytes()), dict):
                    return path
            except (OSError, ValueError):
                continue
    return None
