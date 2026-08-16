"""Migration of the legacy production history stores into the ledger.

Two feeds, migrated in a fixed order because the second resolves
identity against evidence the first (and the archive backfill)
contribute:

1. ``data/board_history.sqlite`` (the C1-RET-02 recorder) — canonical
   board rows including picks, with ``player_id``, ``pipeline_version``
   (``contract_version``) and ``scraped_at`` provenance.  Recording of
   that store continues unchanged (the retention row keys on it); this
   is an ingest, not a retirement.
2. ``data/rank_history.jsonl`` — the long canonical rank/value log.
   Only what the log actually RECORDED migrates: stored ranks always,
   stored values only where a ``values`` block exists.  The rank→value
   Hill backfill ``rank_history.load_history`` performs at read time is
   deliberately NOT reproduced — a value minted by today's curve is not
   an observation, and the ledger refuses to launder it into one.

Identity: rank-history keys are ``canonicalName::assetClass`` with no
platform id.  Names resolve to ``player:<id>`` keys through the
ledger's own already-ingested identity evidence — the deterministic map
``(lower display name, asset_class) → player_id`` built from rows that
DO carry an id (board-history and archive rows).  A name matching zero
ids stays name-keyed; a name matching two or more is AMBIGUOUS and
stays name-keyed too, counted, never guessed.  Both feeds are
idempotent re-runs (the store's identity key absorbs replays).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.history import keys, store

ORIGIN_BOARD_HISTORY = "migration:board_history"
ORIGIN_RANK_HISTORY = "migration:rank_history"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOARD_HISTORY = _REPO_ROOT / "data" / "board_history.sqlite"
DEFAULT_RANK_HISTORY = _REPO_ROOT / "data" / "rank_history.jsonl"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


# ── board_history.sqlite → ledger ───────────────────────────────────────


def migrate_board_history(
    source: Path | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    source = source or DEFAULT_BOARD_HISTORY
    if not source.exists():
        return {"skipped": True, "reason": f"no board_history store at {source}"}

    conn = sqlite3.connect(str(source))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT as_of, player_key, contract_version, player_id, display_name, "
            "position, asset_class, rank_derived_value, canonical_consensus_rank, "
            "canonical_tier_id, confidence_bucket, scraped_at FROM board_history"
        ).fetchall()
    finally:
        conn.close()

    observations: list[dict[str, Any]] = []
    unresolved = 0
    empty = 0
    for r in rows:
        name = r["display_name"]
        asset_class = str(r["asset_class"] or "").strip().lower()
        position = r["position"]
        if asset_class == "pick" or (position and str(position).upper() == "PICK"):
            asset_key = keys.pick_asset_key(name)
            asset_class = keys.ASSET_CLASS_PICK
        else:
            asset_key = keys.player_asset_key(r["player_id"], name, position)
            if asset_class not in (keys.ASSET_CLASS_OFFENSE, keys.ASSET_CLASS_IDP):
                group = keys.canonical_position_group(position) if position else ""
                asset_class = (
                    keys.ASSET_CLASS_OFFENSE
                    if group == "OFFENSE"
                    else keys.ASSET_CLASS_IDP
                    if group == "IDP"
                    else asset_class or "unknown"
                )
        if not asset_key:
            unresolved += 1
            continue

        value = _num(r["rank_derived_value"])
        rank = r["canonical_consensus_rank"]
        rank = int(rank) if isinstance(rank, int) and rank > 0 else None
        if value is None and rank is None:
            empty += 1
            continue

        observed_at = str(r["scraped_at"] or "") or None
        observations.append(
            {
                "asset_key": asset_key,
                "asset_class": asset_class,
                "lane": store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": str(r["as_of"]),
                "observed_at": observed_at,
                "observed_at_zone": (
                    ("utc" if ("+" in observed_at or observed_at.endswith("Z")) else "naive")
                    if observed_at
                    else None
                ),
                "value": value,
                "rank": rank,
                "tier": int(r["canonical_tier_id"])
                if isinstance(r["canonical_tier_id"], int)
                else None,
                "confidence": str(r["confidence_bucket"] or "") or None,
                "display_name": str(name or "") or None,
                "position": str(position or "") or None,
                "player_id": str(r["player_id"] or "") or None,
                "scope": None,
                "pipeline_version": str(r["contract_version"] or "") or None,
                "origin": ORIGIN_BOARD_HISTORY,
            }
        )

    result = store.write_observations(observations, path=path)
    result.update(
        {"sourceRows": len(rows), "unresolved": unresolved, "empty": empty, "skipped": False}
    )
    return result


# ── rank_history.jsonl → ledger ─────────────────────────────────────────


def _identity_map(path: Path | None) -> dict[tuple[str, str], str]:
    """Deterministic ``(lower name, asset_class) → player_id`` map from
    the ledger's own id-bearing rows.  Ambiguity (two ids for one name
    within one class) removes the entry — never guessed."""
    conn = store.connect(path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT display_name, asset_class, player_id FROM observations "
            "WHERE player_id IS NOT NULL AND display_name IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    seen: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        k = (str(r["display_name"]).strip().lower(), str(r["asset_class"]))
        seen.setdefault(k, set()).add(str(r["player_id"]))
    return {k: next(iter(ids)) for k, ids in seen.items() if len(ids) == 1}


def _split_legacy_key(raw_key: str) -> tuple[str, str]:
    idx = raw_key.rfind("::")
    if idx < 0:
        return raw_key, "unknown"
    return raw_key[:idx], raw_key[idx + 2 :].strip().lower() or "unknown"


def _already_migrated_facts(path: Path | None) -> set[tuple[str, str, str]]:
    """Legacy facts this migration has ALREADY ingested, keyed by their
    LEGACY natural identity ``(lower name, asset_class, observed_date)``
    rather than by the resolved asset key.

    Load-bearing for idempotence (final-review blocker 2): the
    name→id resolution map grows as live recording adds identity
    evidence, so re-resolving on every run would migrate the SAME
    legacy fact again under a different (better or worse) key — a new
    observation identity the append-only store would admit, duplicating
    evidence on every deploy.  First migration wins instead: the key
    grade recorded reflects the evidence available when the fact was
    migrated, which is provenance-truthful, and a re-run is a genuine
    no-op.  This also refuses to re-ingest a date the legacy log later
    OVERWROTE in place (its documented same-date most-recent-wins
    behavior — RED-5): the ledger keeps the evidence from the first
    migration rather than silently following the rewrite.
    """
    conn = store.connect(path)
    try:
        rows = conn.execute(
            "SELECT DISTINCT display_name, asset_class, observed_date "
            "FROM observations WHERE origin=?",
            (ORIGIN_RANK_HISTORY,),
        ).fetchall()
    finally:
        conn.close()
    return {
        (
            str(r["display_name"] or "").strip().lower(),
            str(r["asset_class"]),
            str(r["observed_date"]),
        )
        for r in rows
    }


def migrate_rank_history(
    source: Path | None = None,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    source = source or DEFAULT_RANK_HISTORY
    if not source.exists():
        return {"skipped": True, "reason": f"no rank_history log at {source}"}

    id_map = _identity_map(path)
    already = _already_migrated_facts(path)

    observations: list[dict[str, Any]] = []
    unresolved_picks = 0
    name_keyed = 0
    ambiguous_or_unknown = 0
    already_migrated = 0
    entries = 0
    with source.open("r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entry = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(entry, dict):
                continue
            date_s = entry.get("date")
            ranks = entry.get("ranks")
            if not isinstance(date_s, str) or not isinstance(ranks, dict):
                continue
            entries += 1
            values = entry.get("values") if isinstance(entry.get("values"), dict) else {}

            for legacy_key, rank in ranks.items():
                name, asset_class = _split_legacy_key(str(legacy_key))
                norm_class = asset_class if asset_class in ("offense", "idp", "pick") else "unknown"
                if (name.strip().lower(), norm_class, date_s) in already:
                    already_migrated += 1
                    continue
                try:
                    rank_i = int(rank)
                except (TypeError, ValueError):
                    continue
                if rank_i <= 0:
                    continue
                # Only RECORDED values migrate.  load_history's Hill
                # reconstruction is refused by design.
                stored_val = _num(values.get(legacy_key)) if values else None

                if asset_class == "pick":
                    asset_key = keys.pick_asset_key(name)
                    if asset_key is None:
                        unresolved_picks += 1
                        continue
                else:
                    pid = id_map.get((name.strip().lower(), asset_class))
                    if pid:
                        asset_key = f"{keys.PLAYER_PREFIX}{pid}"
                    else:
                        # No or ambiguous identity evidence — explicit
                        # name-grade key, counted.
                        asset_key = keys.name_key_for_class(name, asset_class)
                        if asset_key is None:
                            ambiguous_or_unknown += 1
                            continue
                        name_keyed += 1

                observations.append(
                    {
                        "asset_key": asset_key,
                        "asset_class": norm_class,
                        "lane": store.LANE_CANONICAL,
                        "source_key": "",
                        "observed_date": date_s,
                        "observed_at": None,
                        "observed_at_zone": None,
                        "value": stored_val,
                        "rank": rank_i,
                        "tier": None,
                        "confidence": None,
                        "display_name": name,
                        "position": None,
                        "player_id": None,
                        "scope": None,
                        "pipeline_version": None,
                        "origin": ORIGIN_RANK_HISTORY,
                    }
                )

    result = store.write_observations(observations, path=path)
    result.update(
        {
            "entries": entries,
            "unresolvedPicks": unresolved_picks,
            "nameKeyed": name_keyed,
            "unkeyable": ambiguous_or_unknown,
            "alreadyMigrated": already_migrated,
            "skipped": False,
        }
    )
    return result
