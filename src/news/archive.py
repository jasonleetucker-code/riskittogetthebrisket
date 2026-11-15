"""As-known news metadata archive: which headlines this system knew, and when.

``NewsService`` (``src/news/service.py``) aggregates providers into an
in-memory cache with a 7-day cutoff, so "which headlines existed when an alert
fired / a waiver was decided / a game kicked off" was never recorded, and the
providers' feeds roll forward and cannot be re-read later.  This module keeps
item METADATA at every aggregator refresh (Adaptive Learning G4 / IC-1 evidence
closure).  It changes no served response and nothing serves from it.

**Metadata only -- no article bodies.**  Kept: provider, the provider's item
id, ``publishedAt``, the first refresh that saw the item (``fetchedAt``), the
headline, the URL, kind/severity/tags and the matched players.  ``body`` /
``summary`` are never written (copyright; the URL points at the article).

**Append-only, deduplicated by provider id.**  One record per
``(provider, item id)``, written at the FIRST refresh that served it; later
refreshes that serve it again write nothing.  Gitignored ``data/news_archive/``
(override ``RISKIT_NEWS_ARCHIVE_DIR``), monthly ``ledger-YYYY-MM.jsonl`` +
``ledger.keys`` through the neutral owner ``src/utils/append_ledger``.  Never
rewritten.  Box-local, backed up by ``deploy/backup/riskit-state-backup.sh``,
outside every path the scheduled refresh force-adds.

**What "known" means.**  The items recorded are the refresh's aggregate --
after the service's own dedupe, 7-day cutoff and mention enrichment -- i.e. what
the site had and could show at ``fetchedAt``.

**Players.**  Each mention keeps the tagger's name / position / team /
ambiguity flag plus a ``sleeperId`` taken from the live board row whose EXACT
display name the tagger matched (``player_meta[name]["playerId"]``).  An
ambiguous mention, a name no board row carries, or a display name two board rows
share stays ``sleeperId: None`` with its reason -- never a guess.

**Missing is null.**  An empty URL / timestamp / headline is ``None``;
``publishedAt`` is recorded verbatim and ``publishedAtParsed`` is ``None`` when
it does not parse.

Writes happen on a background thread (:func:`archive_in_background`) so the
request that refreshed the cache never waits on disk, and never raise.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils import append_ledger as _al

LOG = logging.getLogger("news.archive")

SCHEMA = "news-metadata-archive/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "data" / "news_archive"
ENV_DIR = "RISKIT_NEWS_ARCHIVE_DIR"

# One writer at a time inside the API process (the only writer).
_WRITE_LOCK = threading.Lock()


def store_dir() -> Path:
    override = os.environ.get(ENV_DIR, "").strip()
    return Path(override) if override else DEFAULT_DIR


def _blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def _parse_iso(stamp: Any) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def record_key(provider: str | None, item_id: str | None) -> str:
    text = f"{SCHEMA}\x1f{provider or ''}\x1f{item_id or ''}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _mention(m: Any, player_meta: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any]:
    name = _blank_to_none(getattr(m, "name", None))
    out = {
        "name": name,
        "position": _blank_to_none(getattr(m, "position", None)),
        "team": _blank_to_none(getattr(m, "team", None)),
        "impact": _blank_to_none(getattr(m, "impact", None)),
        "ambiguous": bool(getattr(m, "ambiguous", False)),
        "sleeperId": None,
        "identityReason": None,
    }
    if out["ambiguous"]:
        out["identityReason"] = "ambiguous_mention"
    elif name is None:
        out["identityReason"] = "no_name"
    elif not player_meta:
        out["identityReason"] = "no_board_identity_map"
    else:
        meta = player_meta.get(name)
        if not isinstance(meta, Mapping):
            out["identityReason"] = "name_not_on_board"
        else:
            pid = _blank_to_none(meta.get("playerId"))
            if pid is None:
                out["identityReason"] = str(
                    meta.get("playerIdNullReason") or "board_row_has_no_player_id"
                )
            else:
                out["sleeperId"] = str(pid)
                out["identityReason"] = None
    return out


def build_records(
    items: Iterable[Any],
    *,
    fetched_at: str,
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
    recorded_at: str | None = None,
) -> list[dict[str, Any]]:
    """One metadata record per item (``NewsItem``-shaped objects). Pure."""
    recorded = recorded_at or datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for it in items:
        provider = _blank_to_none(getattr(it, "provider", None))
        item_id = _blank_to_none(getattr(it, "id", None))
        if item_id is None:
            continue  # no provider id -> nothing to deduplicate on; never keyed on a guess
        published = _blank_to_none(getattr(it, "ts", None))
        parsed = _parse_iso(published) if published else None
        out.append(
            {
                "schema": SCHEMA,
                "key": record_key(provider, item_id),
                "provider": provider,
                "providerLabel": _blank_to_none(getattr(it, "provider_label", None)),
                "providerItemId": item_id,
                "publishedAt": published,
                "publishedAtParsed": parsed.isoformat() if parsed else None,
                "fetchedAt": fetched_at,
                "recordedAt": recorded,
                "headline": _blank_to_none(getattr(it, "headline", None)),
                "url": _blank_to_none(getattr(it, "url", None)),
                "kind": _blank_to_none(getattr(it, "kind", None)),
                "severity": _blank_to_none(getattr(it, "severity", None)),
                "tags": list(getattr(it, "tags", None) or []),
                "players": [_mention(m, player_meta) for m in (getattr(it, "players", None) or [])],
            }
        )
    return out


def archive(
    items: Sequence[Any],
    *,
    fetched_at: str,
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
    base: Path | None = None,
) -> int:
    """Append every not-yet-recorded item; return how many were written."""
    base = Path(base) if base is not None else store_dir()
    records = build_records(items, fetched_at=fetched_at, player_meta=player_meta)
    if not records:
        return 0
    with _WRITE_LOCK:
        return _al.append_records(base, records)


def archive_safely(items: Sequence[Any], **kwargs: Any) -> int | None:
    """:func:`archive`, but never raises."""
    try:
        return archive(items, **kwargs)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("news metadata archive failed (served news unaffected): %s", exc)
        return None


def archive_in_background(
    items: Sequence[Any],
    *,
    fetched_at: str,
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> threading.Thread:
    """The ``NewsService`` refresh hook: archive off the request thread."""
    snapshot = list(items)
    thread = threading.Thread(
        target=archive_safely,
        args=(snapshot,),
        kwargs={"fetched_at": fetched_at, "player_meta": player_meta},
        name="news-archive",
        daemon=True,
    )
    thread.start()
    return thread


def known_at(when: datetime | str, base: Path | None = None) -> list[dict[str, Any]]:
    """Every archived item the system had seen at or before ``when``.

    Only records with ``fetchedAt <= when`` are eligible -- an item first seen
    later is never selectable, even if its ``publishedAt`` is earlier.
    """
    base = Path(base) if base is not None else store_dir()
    at = when if isinstance(when, datetime) else _parse_iso(when)
    if at is None:
        return []
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    out = []
    for record in _al.iter_all_records(base):
        if record.get("schema") != SCHEMA:
            continue
        seen = _parse_iso(record.get("fetchedAt"))
        if seen is not None and seen <= at:
            out.append(record)
    return out
