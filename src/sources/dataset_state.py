"""Source dataset state — when did a source's DATA last change, not its fetch.

One owner for "how current is what this source is contributing".  Owner
directive 2026-09-23 (``docs/sources/SOURCE_FRESHNESS_WEIGHTING.md``).

Three clocks, never collapsed into one:

* **fetch** — ``data/scrape_state/<key>_last_success`` (existing; not
  duplicated here).  "Did our infrastructure retrieve something?"
* **lastAnyMeaningfulChangeAt** — at least one canonical (identity →
  value/rank) pair genuinely changed.  Proves the provider is alive.
* **lastBroadDatasetChangeAt** — a change event touching at least
  ``broadChange.minRows`` rows AND ``broadChange.minFraction`` of the
  subset.  Evidence of a board-wide / batch publication.  ONLY this clock
  is gated by the threshold; a 2-row edit still moves the first clock.

Per-row observation age (``rowChangedAt``) is kept for sources whose
publication style is not a full snapshot, so a 2-player edit refreshes
exactly those two players and not the whole board.

Invariants (each pinned by ``tests/sources/test_dataset_state.py``):

* an unchanged re-fetch moves NO data clock;
* a markup-only change moves no clock (markup never enters the content);
* a FAILED board (HTML / CAPTCHA / challenge / unreadable) moves no clock
  and never replaces the last valid content;
* a DEGRADED board (parsed but suspicious) moves no clock either — a
  partial scrape must not read as a publication — but its health is
  recorded, because the pipeline reads the CSV on disk;
* players and picks are independent subsets with independent clocks.

State is persisted per source as ``data/scrape_state/<key>_dataset.json``
(per-key files, so the production IDP Show timer and the GitHub refresh
never write the same file), rewritten only when content or health changes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.sources.dataset_integrity import (
    FAILED,
    HEALTHY,
    SUBSET_PICKS,
    SUBSET_PLAYERS,
    ParsedBoard,
    assess_row_count,
    parse_board,
)

SCHEMA_VERSION = 1
SUBSETS: tuple[str, str] = (SUBSET_PLAYERS, SUBSET_PICKS)

#: Bounded history lengths — enough to learn cadence over months, small
#: enough that a state file stays a few tens of KB.
MAX_CHANGE_HISTORY = 240
MAX_ROW_COUNT_HISTORY = 30

STATE_SUFFIX = "_dataset.json"


@dataclass(frozen=True)
class BroadChangePolicy:
    """When a change event counts as a broad dataset publication."""

    min_rows: int = 5
    min_fraction: float = 0.02

    def is_broad(self, rows_changed: int, rows_total: int) -> bool:
        if rows_changed <= 0:
            return False
        need = max(self.min_rows, int(round(self.min_fraction * max(rows_total, 0))))
        return rows_changed >= need


DEFAULT_POLICY = BroadChangePolicy()


def utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(text: Any) -> datetime | None:
    if not text or not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:10]


def _subset_fingerprint(row_hashes: dict[str, str]) -> str:
    h = hashlib.sha256()
    for key in sorted(row_hashes):
        h.update(key.encode("utf-8"))
        h.update(b"\x1f")
        h.update(row_hashes[key].encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()[:24]


def empty_state(source_key: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "sourceKey": source_key,
        # ``lastSuccessfulParseAt`` is DERIVED at read time (the fetch stamp
        # while ``health.state`` is HEALTHY) rather than stored, so an
        # unchanged healthy re-fetch does not rewrite this file.
        "health": {"state": None, "errors": [], "warnings": [], "since": None},
        "upstream": {"publishedAt": None, "version": None},
        "subsets": {},
    }


def _rolling_median(values: list[int]) -> float | None:
    vals = sorted(v for v in values if isinstance(v, int) and v > 0)
    if not vals:
        return None
    mid = len(vals) // 2
    return float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def observe(
    state: dict[str, Any] | None,
    *,
    source_key: str,
    board: ParsedBoard,
    observed_at: datetime,
    upstream_published_at: str | None = None,
    dataset_version: str | None = None,
    policy: BroadChangePolicy = DEFAULT_POLICY,
    track_rows: bool = True,
) -> dict[str, Any]:
    """Fold one parsed board into the source's state.  Pure: returns a new dict.

    ``track_rows`` controls whether per-row observation times are kept (off
    for SNAPSHOT-style sources, whose every change republishes the board).
    """
    new = json.loads(json.dumps(state)) if state else empty_state(source_key)
    new["schemaVersion"] = SCHEMA_VERSION
    new["sourceKey"] = source_key
    at = utc_iso(observed_at)

    # Row-count collapse is judged against the source's OWN history.
    players_prev = (new.get("subsets") or {}).get(SUBSET_PLAYERS) or {}
    picks_prev = (new.get("subsets") or {}).get(SUBSET_PICKS) or {}
    totals = [
        a + b
        for a, b in zip(
            players_prev.get("rowCountHistory") or [], picks_prev.get("rowCountHistory") or []
        )
    ] or list(players_prev.get("rowCountHistory") or [])
    assess_row_count(board, _rolling_median(totals))

    health_state = board.health
    prev_health = new.get("health") or {}
    if prev_health.get("state") != health_state or prev_health.get("errors") != board.errors[:10]:
        new["health"] = {
            "state": health_state,
            "errors": board.errors[:10],
            "warnings": board.warnings[:10],
            "since": at,
        }
    if health_state != HEALTHY:
        # FAILED or DEGRADED: the last valid content and every data clock
        # stay exactly as they were.
        return new

    upstream = new.setdefault("upstream", {"publishedAt": None, "version": None})
    subsets = new.setdefault("subsets", {})

    for subset in SUBSETS:
        rows = board.subset_rows(subset)
        prev = subsets.get(subset)
        if not rows and not prev:
            continue
        hashes = {k: _row_hash(v) for k, v in rows.items()}
        fingerprint = _subset_fingerprint(hashes) if hashes else None
        if prev is None:
            subsets[subset] = {
                "fingerprint": fingerprint,
                "rowCount": len(hashes),
                "firstObservedAt": at,
                "contentSince": at,
                "lastAnyMeaningfulChangeAt": at,
                "lastBroadDatasetChangeAt": at,
                "firstObservationIsBaseline": True,
                "changeHistory": [],
                "rowCountHistory": [len(hashes)],
                "rowHashes": hashes,
                "rowChangedAt": {k: at for k in hashes} if track_rows else {},
            }
            continue
        if fingerprint == prev.get("fingerprint"):
            continue
        prev_hashes: dict[str, str] = prev.get("rowHashes") or {}
        changed_keys = [k for k, h in hashes.items() if prev_hashes.get(k) != h]
        removed = [k for k in prev_hashes if k not in hashes]
        added = [k for k in changed_keys if k not in prev_hashes]
        rows_changed = len(changed_keys) + len(removed)
        if rows_changed == 0:
            continue
        total = max(len(hashes), len(prev_hashes))
        broad = policy.is_broad(rows_changed, total)
        history = list(prev.get("changeHistory") or [])
        history.append(
            {
                "at": at,
                "rowsChanged": rows_changed,
                "rowsAdded": len(added),
                "rowsRemoved": len(removed),
                "rowsTotal": total,
                "broad": broad,
            }
        )
        counts = list(prev.get("rowCountHistory") or []) + [len(hashes)]
        row_changed_at: dict[str, str] = {}
        if track_rows:
            old_at = prev.get("rowChangedAt") or {}
            fallback = prev.get("lastBroadDatasetChangeAt") or prev.get("firstObservedAt")
            row_changed_at = {
                k: (at if k in set(changed_keys) else old_at.get(k) or fallback) for k in hashes
            }
        subsets[subset] = {
            **prev,
            "fingerprint": fingerprint,
            "rowCount": len(hashes),
            "contentSince": at,
            "lastAnyMeaningfulChangeAt": at,
            "lastBroadDatasetChangeAt": at if broad else prev.get("lastBroadDatasetChangeAt"),
            "changeHistory": history[-MAX_CHANGE_HISTORY:],
            "rowCountHistory": counts[-MAX_ROW_COUNT_HISTORY:],
            "rowHashes": hashes,
            "rowChangedAt": row_changed_at,
        }

    if upstream_published_at or dataset_version:
        if (upstream_published_at, dataset_version) != (
            upstream.get("publishedAt"),
            upstream.get("version"),
        ):
            upstream["publishedAt"] = upstream_published_at
            upstream["version"] = dataset_version
    return new


def state_path(state_dir: Path, source_key: str) -> Path:
    return Path(state_dir) / f"{source_key}{STATE_SUFFIX}"


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def dump_state(state: dict[str, Any]) -> str:
    """Deterministic serialization: sorted keys, one entry per line, so a
    git diff of a refresh shows exactly the rows that changed."""
    return json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def save_state(path: Path, state: dict[str, Any]) -> bool:
    """Write only when the serialized state differs.  Returns True if written."""
    path = Path(path)
    text = dump_state(state)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def record_source_file(
    *,
    source_key: str,
    csv_path: Path,
    signal: str,
    state_dir: Path,
    observed_at: datetime,
    upstream_published_at: str | None = None,
    dataset_version: str | None = None,
    policy: BroadChangePolicy = DEFAULT_POLICY,
    track_rows: bool = True,
) -> tuple[dict[str, Any], bool]:
    """Read one CSV, fold it into ``<state_dir>/<key>_dataset.json``.

    A missing file is a FAILED observation (clocks untouched), never an
    empty board.
    """
    path = state_path(state_dir, source_key)
    prior = load_state(path)
    try:
        text = Path(csv_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        board = ParsedBoard(health=FAILED, errors=[f"source CSV unreadable: {exc}"])
    else:
        board = parse_board(text, signal=signal)
    new = observe(
        prior,
        source_key=source_key,
        board=board,
        observed_at=observed_at,
        upstream_published_at=upstream_published_at,
        dataset_version=dataset_version,
        policy=policy,
        track_rows=track_rows,
    )
    return new, save_state(path, new)
