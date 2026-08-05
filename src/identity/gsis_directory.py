"""Build a Sleeper-shaped player directory that actually carries GSIS ids.

Why this exists
---------------
``src/identity/unified_mapper.resolve_player`` resolves *through* a
Sleeper player directory — ``{sleeper_id: {player_id, gsis_id, espn_id,
full_name, position, team}}``.  Its one live consumer,
``GET /api/player/{sleeper_id}/realized``, handed it
``sleeper_block["players"]`` — a key **no writer in this repo has ever
produced**.  The contract's Sleeper block carries ``idToPlayer``
(id → name) and ``positions`` (name → position) instead, so the mapper
was indexing ``None`` and every player on every board came back
``unmapped_player`` (audit W06-F003).

A key rename alone does not fix it: neither ``idToPlayer`` nor
``playerIds`` carries a ``gsis_id``, and GSIS is the id the nflverse
weekly rows are keyed on.  So this module assembles the directory from
what is actually in scope:

1. The cached Sleeper ``/v1/players/nfl`` dump when one is present — it
   carries ``gsis_id`` natively, so that leg is **id → id**, no name
   involved.  Read through ``consensus_edge.identity_join`` rather than
   re-implementing the cache read.
2. Otherwise the contract's own Sleeper block, with GSIS attached from
   the nflverse weekly rows the caller already fetched.

Leg 2 is a NAME join, and it is the only one available without the
dump, so it is written to fail loudly rather than guess:

* the key is ``normalize_player_name`` — the repo's one join key;
* a name that maps to more than one GSIS id is disambiguated by
  position **or refused**.  There is no fuzzy fallback and no
  "pick the first one": two players merged is worse than one missing;
* every refusal is counted (``ambiguous`` / ``unmatched``) and the
  counts ride out on the response, following the
  ``metadata.assetsUnpricedByBoard`` precedent in ``src/trade/finder.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.utils import normalize_player_name

_LOGGER = logging.getLogger(__name__)

# nflverse weekly rows name the player under one of these, most
# specific first.  ``player_id`` on those rows IS the GSIS id.
_NAME_KEYS = ("player_display_name", "player_name", "full_name")

# Per-id join status.  Anything other than ``ok`` means the row has no
# GSIS id and the surface must abstain rather than invent one.
STATUS_OK = "ok"
STATUS_AMBIGUOUS = "ambiguous_name"
STATUS_UNMATCHED = "no_nflverse_match"
STATUS_UNKNOWN_ID = "unknown_sleeper_id"


@dataclass(frozen=True)
class DirectoryBuild:
    """A directory plus the honest account of what it could not join."""

    directory: dict[str, dict[str, Any]] = field(default_factory=dict)
    sources: tuple[str, ...] = ()
    with_gsis: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    statuses: dict[str, str] = field(default_factory=dict)

    @property
    def entries(self) -> int:
        return len(self.directory)

    def status_for(self, sleeper_id: str) -> str:
        sid = str(sleeper_id or "").strip()
        row = self.directory.get(sid)
        if row is None:
            return STATUS_UNKNOWN_ID
        recorded = self.statuses.get(sid)
        if recorded:
            return recorded
        # No recorded refusal but no id either: the entry came from a
        # source that simply does not carry one.
        return STATUS_OK if str(row.get("gsis_id") or "").strip() else STATUS_UNMATCHED

    def as_meta(self) -> dict[str, Any]:
        """The counted-absence block stamped on the response."""
        return {
            "source": "+".join(self.sources) if self.sources else "none",
            "entries": self.entries,
            "gsisResolved": self.with_gsis,
            "gsisAmbiguous": self.ambiguous,
            "gsisUnmatched": self.unmatched,
        }


def build_gsis_name_index(rows: list[dict[str, Any]] | None) -> dict[str, list[tuple[str, str]]]:
    """``{normalized name: [(gsis_id, position), ...]}`` from nflverse rows.

    Distinct GSIS ids only — a player appears once per week and would
    otherwise be counted eighteen times.  A name carrying more than one
    entry is a genuine collision (nflverse's 2025 offense rows hold 8 of
    them, e.g. two Byron Murphys) and is left for the caller to refuse.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        gsis = str(row.get("player_id") or row.get("player_id_gsis") or "").strip()
        if not gsis:
            continue
        raw_name = ""
        for key in _NAME_KEYS:
            raw_name = str(row.get(key) or "").strip()
            if raw_name:
                break
        norm = normalize_player_name(raw_name)
        if not norm:
            continue
        if gsis in seen.setdefault(norm, set()):
            continue
        seen[norm].add(gsis)
        index.setdefault(norm, []).append((gsis, str(row.get("position") or "").strip().upper()))
    return index


def gsis_for_name(
    index: dict[str, list[tuple[str, str]]],
    name: str | None,
    position: str | None = None,
) -> tuple[str | None, str]:
    """``(gsis_id, status)`` for one name.

    Refuses on ambiguity.  Position narrows a collision only when it
    leaves exactly one candidate; a position vocabulary mismatch (the
    Sleeper block says ``DB``, nflverse says ``CB``) therefore refuses
    instead of guessing.
    """
    norm = normalize_player_name(name or "")
    if not norm:
        return None, STATUS_UNMATCHED
    candidates = index.get(norm) or []
    if not candidates:
        return None, STATUS_UNMATCHED
    if len(candidates) == 1:
        return candidates[0][0], STATUS_OK
    pos_u = str(position or "").strip().upper()
    if pos_u:
        narrowed = [c for c in candidates if c[1] == pos_u]
        if len(narrowed) == 1:
            return narrowed[0][0], STATUS_OK
    return None, STATUS_AMBIGUOUS


def directory_from_sleeper_block(sleeper_block: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Directory-shaped rows from the contract's ``sleeper`` block.

    ``idToPlayer`` is id → display name and ``positions`` is display
    name → position; together they are a directory missing exactly one
    field, ``gsis_id``.
    """
    block = sleeper_block if isinstance(sleeper_block, dict) else {}
    id_to_player = block.get("idToPlayer")
    positions = block.get("positions")
    if not isinstance(id_to_player, dict):
        return {}
    if not isinstance(positions, dict):
        positions = {}
    out: dict[str, dict[str, Any]] = {}
    for sid, name in id_to_player.items():
        sid_s = str(sid).strip()
        name_s = str(name or "").strip()
        if not sid_s or not name_s:
            continue
        out[sid_s] = {
            "player_id": sid_s,
            "full_name": name_s,
            "position": str(positions.get(name_s) or "").strip(),
            "team": "",
            "gsis_id": "",
            "espn_id": "",
        }
    return out


def build_directory(
    sleeper_block: dict[str, Any] | None,
    *,
    weekly_rows: list[dict[str, Any]] | None = None,
    cached_directory: dict[str, dict[str, Any]] | None = None,
) -> DirectoryBuild:
    """Assemble the best directory available, and count what is missing.

    The cached Sleeper dump wins per id, because it carries GSIS without
    a name ever being consulted.  The contract block fills in every id
    the dump does not price, and those get GSIS from the nflverse name
    index or nothing at all.
    """
    directory: dict[str, dict[str, Any]] = {}
    statuses: dict[str, str] = {}
    sources: list[str] = []

    if isinstance(cached_directory, dict):
        for sid, entry in cached_directory.items():
            if not isinstance(entry, dict):
                continue
            gsis = str(entry.get("gsis_id") or "").strip()
            if not gsis:
                # A dump without GSIS is the checked-in stub; it adds no
                # identity this module can use.
                continue
            sid_s = str(sid).strip()
            if not sid_s:
                continue
            row = dict(entry)
            row.setdefault("player_id", sid_s)
            directory[sid_s] = row
        if directory:
            sources.append("sleeper_directory")

    block_rows = directory_from_sleeper_block(sleeper_block)
    pending = {sid: row for sid, row in block_rows.items() if sid not in directory}
    if pending:
        sources.append("contract_sleeper_block")
        index = build_gsis_name_index(weekly_rows)
        if index:
            sources.append("nflverse_name_index")
        for sid, row in pending.items():
            gsis, status = gsis_for_name(index, row.get("full_name"), row.get("position"))
            if gsis:
                row["gsis_id"] = gsis
            else:
                statuses[sid] = status
            directory[sid] = row

    with_gsis = sum(1 for r in directory.values() if str(r.get("gsis_id") or "").strip())
    ambiguous = sum(1 for s in statuses.values() if s == STATUS_AMBIGUOUS)
    unmatched = sum(1 for s in statuses.values() if s == STATUS_UNMATCHED)
    if directory and not with_gsis:
        _LOGGER.warning(
            "gsis_directory: %d entries, 0 with a GSIS id (sources=%s)",
            len(directory),
            sources,
        )
    return DirectoryBuild(
        directory=directory,
        sources=tuple(sources),
        with_gsis=with_gsis,
        ambiguous=ambiguous,
        unmatched=unmatched,
        statuses=statuses,
    )
