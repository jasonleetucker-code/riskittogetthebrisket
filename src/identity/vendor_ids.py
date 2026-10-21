"""Vendor-id → canonical player mapping (VID; outlier-integrity V2.1 §3.7).

The identity owner's append-only record of which canonical (Sleeper) player a
vendor's OWN player id names.  It exists so a future reader (outlier-integrity
V2.1 Layer A, rule A1, in the detection branch - PR #1884, NOT part of this
module or of main) can contradict a vendor entry whose id belongs to someone
else, which V2 could not do: no mapping existed on the board path.  Collecting
the evidence must start before that reader can be trusted, because an id seen
for the first time cannot be confirmed retroactively (``as_of`` reads only
ARRIVING observations).  RECORD-ONLY: this module changes no value, join, rank
or vote and nothing on the board path imports it.

Registered entry rule, and nothing looser:

* **(a) vendor-published Sleeper id** — the same vendor row publishes its own
  id AND a Sleeper id that names a player in the identity owner's directory.
  One observation suffices.
* **(b) VERIFIED join** — the vendor row's name resolves, on an EXACT name rung
  of the identity owner's directory, to exactly one player whose position
  FAMILY (V2.1 R4 table) and team both agree with what the row publishes.
  It becomes a mapping only after the same source key showed it on **≥ 2
  content-distinct datasets** (content hash of the board's value/rank
  columns, the ``dataset_state`` notion of a distinct publication).  Two
  modes of one capture (KTC Crowd and Trades) are different source keys, so
  they never confirm each other.

**A conflict is never resolved automatically.**  Once any observation maps a
vendor id to a second player, that id is ``unresolved_conflict`` for good:
:meth:`VendorIdMap.resolve` answers ``None`` and A1 abstains.  Appending is the
only write; nothing is ever edited or deleted, so a replay can rebuild the map
"as it stood" at any board time (``as_of`` — ARRIVING evidence only).

The store is JSON lines at ``data/identity/vendor_id_map.jsonl``.  To keep it
small, a line is appended only when it can change a state: a new player for a
vendor id, or a not-yet-confirming dataset for a (source, vendor id, player).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.identity import published_fields as pf

STORE_REL = Path("data") / "identity" / "vendor_id_map.jsonl"
BASIS_VENDOR_SLEEPER_ID = "vendor_published_sleeper_id"
BASIS_VERIFIED_JOIN = "verified_join"
MIN_VERIFIED_DATASETS = 2

STATE_MAPPED = "mapped"
STATE_CONFLICT = "unresolved_conflict"
STATE_INSUFFICIENT = "insufficient_evidence"
STATE_UNKNOWN = "unknown"


def namespace_for(source_key: str) -> str:
    """The id namespace of a source: its recorded PROVIDER (one provider's
    keys share ids — KTC Crowd / Trades / Market), else the source key itself
    (narrower, never merged with another source by guess)."""
    from src.sources.source_census import provider_of  # noqa: PLC0415

    provider = provider_of(source_key)
    return f"provider:{provider}" if provider else f"source:{source_key}"


@dataclass(frozen=True)
class VidObservation:
    namespace: str
    vendor_id: str
    sleeper_id: str
    basis: str
    source: str
    dataset_hash: str
    observed_at: str
    name: str = ""
    position: str = ""
    team: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_instant(text: object) -> datetime | None:
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class VendorIdMap:
    """The mapping as derived from a set of observations."""

    def __init__(self, observations: Iterable[VidObservation]) -> None:
        self._sids: dict[tuple[str, str], set[str]] = {}
        self._vendor_sid: set[tuple[str, str, str]] = set()
        self._verified: dict[tuple[str, str, str, str], set[str]] = {}
        #: (namespace, vendor id, sleeper id) confirmed by one source key on
        #: >= MIN_VERIFIED_DATASETS content-distinct datasets.
        self._confirmed: set[tuple[str, str, str]] = set()
        self.observation_count = 0
        for obs in observations:
            self._add(obs)

    def _add(self, obs: VidObservation) -> None:
        self.observation_count += 1
        self._sids.setdefault((obs.namespace, obs.vendor_id), set()).add(obs.sleeper_id)
        if obs.basis == BASIS_VENDOR_SLEEPER_ID:
            self._vendor_sid.add((obs.namespace, obs.vendor_id, obs.sleeper_id))
        elif obs.basis == BASIS_VERIFIED_JOIN:
            hashes = self._verified.setdefault(
                (obs.namespace, obs.vendor_id, obs.sleeper_id, obs.source), set()
            )
            hashes.add(obs.dataset_hash)
            if len(hashes) >= MIN_VERIFIED_DATASETS:
                self._confirmed.add((obs.namespace, obs.vendor_id, obs.sleeper_id))

    @classmethod
    def load(cls, path: Path, *, as_of: datetime | None = None) -> VendorIdMap:
        """The map from the store at ``path``; with ``as_of``, only
        observations made strictly BEFORE it (a board never sees its own or a
        later capture).  A missing store is an empty map; an unreadable line is
        skipped (an append-only log's torn tail), never guessed."""
        return cls(read_observations(path, as_of=as_of))

    def state(self, namespace: str, vendor_id: str) -> str:
        sids = self._sids.get((namespace, str(vendor_id)))
        if not sids:
            return STATE_UNKNOWN
        if len(sids) > 1:
            return STATE_CONFLICT
        (sid,) = tuple(sids)
        key = (namespace, str(vendor_id), sid)
        if key in self._vendor_sid or key in self._confirmed:
            return STATE_MAPPED
        return STATE_INSUFFICIENT

    def resolve(self, namespace: str, vendor_id: str) -> str | None:
        """The canonical Sleeper id for a vendor id, or ``None`` (unknown,
        insufficient evidence, or a conflict — A1 abstains)."""
        if self.state(namespace, vendor_id) != STATE_MAPPED:
            return None
        (sid,) = tuple(self._sids[(namespace, str(vendor_id))])
        return sid

    def resolver_for(self, source_key: str) -> Callable[[str], str | None]:
        namespace = namespace_for(source_key)
        return lambda vendor_id: self.resolve(namespace, vendor_id)

    def census(self) -> dict[str, int]:
        out = {STATE_MAPPED: 0, STATE_CONFLICT: 0, STATE_INSUFFICIENT: 0}
        for ns, vid in self._sids:
            st = self.state(ns, vid)
            out[st] = out.get(st, 0) + 1
        out["observations"] = self.observation_count
        return out

    # Used by the recorder to append only state-changing lines.
    def _would_change(self, obs: VidObservation) -> bool:
        sids = self._sids.get((obs.namespace, obs.vendor_id), set())
        if obs.sleeper_id not in sids:
            return True
        if obs.basis == BASIS_VENDOR_SLEEPER_ID:
            return (obs.namespace, obs.vendor_id, obs.sleeper_id) not in self._vendor_sid
        hashes = self._verified.get(
            (obs.namespace, obs.vendor_id, obs.sleeper_id, obs.source), set()
        )
        return obs.dataset_hash not in hashes and len(hashes) < MIN_VERIFIED_DATASETS


def read_observations(path: Path, *, as_of: datetime | None = None) -> list[VidObservation]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []
    out: list[VidObservation] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            obs = VidObservation(
                **{k: raw[k] for k in VidObservation.__dataclass_fields__ if k in raw}
            )
        except (ValueError, TypeError, KeyError):
            continue
        if as_of is not None:
            seen = _parse_instant(obs.observed_at)
            if seen is None or seen >= as_of:
                continue
        out.append(obs)
    return out


# ── Evidence: one vendor row → an observation ──────────────────────────


def verified_join(index: Any, *, raw_name: str, position: object, team: object) -> str | None:
    """Registered rule (b): the Sleeper id a vendor row's name names on an
    EXACT name rung, when exactly one such directory player agrees on position
    family AND team.  ``None`` otherwise — including any missing field."""
    from src.identity.name_primitives import clean_name, normalize_lookup_name  # noqa: PLC0415
    from src.identity.published_fields import families_compatible, team_evidence  # noqa: PLC0415

    entry_team = team_evidence(team)
    if not raw_name or entry_team is None or not str(position or "").strip():
        return None
    cleaned = clean_name(raw_name)
    if not cleaned:
        return None
    pool = list(index.by_clean.get(cleaned) or ()) or list(
        index.by_lookup.get(normalize_lookup_name(cleaned)) or ()
    )
    hits = []
    for cand in pool:
        _bd, fps = index.facts_by_sleeper_id.get(cand.sleeper_id, (None, ()))
        if families_compatible(position, [cand.position, *fps]) is not True:
            continue
        if team_evidence(cand.team) != entry_team:
            continue
        hits.append(cand.sleeper_id)
    return hits[0] if len(set(hits)) == 1 else None


def observation_for_row(
    *,
    source_key: str,
    row: Mapping[str, Any],
    index: Any,
    dataset_hash: str,
    observed_at: str,
    namespace: str | None = None,
) -> VidObservation | None:
    """``row`` carries ``name``, ``vendorId`` and, where published,
    ``sleeperId`` / ``position`` / ``team``."""
    vendor_id = str(row.get("vendorId") or "").strip()
    if not vendor_id:
        return None
    ns = namespace or namespace_for(source_key)
    name = str(row.get("name") or "")
    position = str(row.get("position") or "").strip().upper()
    team = str(row.get("team") or "").strip().upper()
    published_sid = str(row.get("sleeperId") or "").strip()
    if published_sid:
        if index is not None and published_sid not in index.by_sleeper_id:
            return None  # an id naming nobody is no evidence
        return VidObservation(
            ns,
            vendor_id,
            published_sid,
            BASIS_VENDOR_SLEEPER_ID,
            source_key,
            dataset_hash,
            observed_at,
            name,
            position,
            team,
        )
    if index is None:
        return None
    sid = verified_join(index, raw_name=name, position=position, team=team)
    if sid is None:
        return None
    return VidObservation(
        ns,
        vendor_id,
        sid,
        BASIS_VERIFIED_JOIN,
        source_key,
        dataset_hash,
        observed_at,
        name,
        position,
        team,
    )


def csv_rows_with_vendor_ids(text: str) -> list[dict[str, str]]:
    """The vendor rows of one source CSV, read with the identity owner's header
    tokens (``published_fields``), so the recorder reads exactly the fields the
    board loader's identity columns name.  ``[]`` when the CSV carries no
    vendor-id column."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    header = {pf.normalize_header_token(c) for c in (reader.fieldnames or [])}
    if not (header & pf.VENDOR_ID_TOKENS):
        return []
    out: list[dict[str, str]] = []
    for csvrow in reader:
        name = ""
        for alias in ("name", "Name", "player", "Player", "player_name", "PlayerName"):
            if csvrow.get(alias):
                name = str(csvrow[alias]).strip()
                break
        if not name:
            continue
        out.append(
            {
                "name": name,
                "vendorId": pf.pick_by_tokens(csvrow, pf.VENDOR_ID_TOKENS).strip(),
                "sleeperId": pf.pick_by_tokens(csvrow, pf.SLEEPER_ID_TOKENS).strip(),
                "position": pf.pick_by_tokens(csvrow, pf.POSITION_TOKENS).strip(),
                "team": pf.pick_by_tokens(csvrow, pf.TEAM_TOKENS).strip(),
            }
        )
    return out


def dataset_hash_of_csv(text: str, signal: str = "value") -> str:
    """Content hash of the board's meaningful value/rank columns — two files
    that differ only in identity columns or row order are one dataset."""
    from src.sources.dataset_integrity import parse_board  # noqa: PLC0415

    board = parse_board(text, signal=signal)
    canonical = json.dumps(board.rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def append_observations(path: Path, observations: Iterable[VidObservation]) -> int:
    """Append the state-changing observations; returns how many were written.
    Append-only: existing lines are never rewritten."""
    path = Path(path)
    current = VendorIdMap(read_observations(path))
    lines: list[str] = []
    for obs in observations:
        if current._would_change(obs):
            lines.append(obs.to_json())
            current._add(obs)
    if not lines:
        return 0
    return _append_lines(path, lines)


def _append_lines(path: Path, lines: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for line in lines:
            handle.write(line + "\n")
    return len(lines)


def record_from_site_raw(
    site_raw_dir: Path,
    *,
    index: Any,
    store_path: Path,
    observed_at: str,
    source_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Fold every vendor-id-carrying CSV in ``site_raw_dir`` into the store.

    Record-only: it changes no value, join or vote.  Returns a census."""
    summary: dict[str, Any] = {"observedAt": observed_at, "sources": {}, "appended": 0}
    if index is None:
        summary["skipped"] = "identity_directory_unavailable"
        return summary
    wanted = set(source_keys) if source_keys is not None else None
    observations: list[VidObservation] = []
    for path in sorted(Path(site_raw_dir).glob("*.csv")):
        key = path.stem
        if wanted is not None and key not in wanted:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        rows = csv_rows_with_vendor_ids(text)
        if not rows:
            continue
        dhash = dataset_hash_of_csv(text)
        ns = namespace_for(key)
        made = [
            obs
            for row in rows
            if (
                obs := observation_for_row(
                    source_key=key,
                    row=row,
                    index=index,
                    dataset_hash=dhash,
                    observed_at=observed_at,
                    namespace=ns,
                )
            )
            is not None
        ]
        observations.extend(made)
        summary["sources"][key] = {
            "rows": len(rows),
            "observations": len(made),
            "datasetHash": dhash,
        }
    summary["appended"] = append_observations(store_path, observations)
    summary["census"] = VendorIdMap.load(store_path).census()
    return summary
