"""The IDP Show 2026 projections → BDVM projection records.

The first REAL (non-proxy) statistical projection source for BDVM.
Jon Macri's projections post
(``theidpshow.com/p/2026-idp-fantasy-football-projections-rankings``)
is paywalled; per the established idpShow pattern the data itself is
served from embeds (Datawrapper ``dataset.csv`` / shared Google Sheet)
that are readable once the article HTML names them — the authenticated
fetch happens in ``scripts/fetch_idpshow_projections.py`` on the box
that holds ``idpshow_session.json``.  Everything in this module is
pure parsing/merging so it is fully testable offline.

Schema tolerance: the table's exact headers are unknown until the
first authenticated run, so parsing is alias-driven and the parse
report says exactly which columns mapped, which didn't, and which
approximations (if any) were applied.  A table that doesn't clearly
look like player projections is REJECTED — no snapshot is written from
a maybe.

Merge policy (documented): the reconstructed baseline is a stand-in
for absent data (BDVM §8.3).  When a player gains a real projection
record, that player's proxy records are dropped from the merged
snapshot; players the real source doesn't cover keep their proxy.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Iterable, Mapping

from src.bdvm.context import TRUE_POSITION_MAP
from src.bdvm.projections import ProjectionRecord, supersede_merge_into_snapshot

SOURCE_NAME = "idpShowProjections"

# When a table only publishes COMBINED tackles, we split solo/assist
# with the league-wide empirical share.  Documented approximation,
# surfaced in the parse report — never silent.
TACKLE_SOLO_SHARE = 0.62

# header (lowered, squeezed) → semantic field
_HEADER_ALIASES: dict[str, str] = {
    # identity
    "player": "name",
    "name": "name",
    "player name": "name",
    "pos": "position",
    "position": "position",
    "team": "team",
    "tm": "team",
    "gp": "games",
    "g": "games",
    "games": "games",
    "gms": "games",
    # tackles
    "solo": "def_tackles_solo",
    "solos": "def_tackles_solo",
    "solo tkl": "def_tackles_solo",
    "solo tackles": "def_tackles_solo",
    "tkl solo": "def_tackles_solo",
    "ast": "def_tackle_assists",
    "asst": "def_tackle_assists",
    "assists": "def_tackle_assists",
    "assisted tackles": "def_tackle_assists",
    "tkl ast": "def_tackle_assists",
    "tkl": "def_tackles",
    "tackles": "def_tackles",
    "total": "def_tackles",
    "total tkl": "def_tackles",
    "total tackles": "def_tackles",
    "comb": "def_tackles",
    "combined": "def_tackles",
    "combined tackles": "def_tackles",
    "tfl": "def_tackles_for_loss",
    "tkl loss": "def_tackles_for_loss",
    "tackles for loss": "def_tackles_for_loss",
    # pressure
    "sack": "def_sacks",
    "sacks": "def_sacks",
    "sk": "def_sacks",
    "qb hits": "def_qb_hits",
    "qb hit": "def_qb_hits",
    "hits": "def_qb_hits",
    "qh": "def_qb_hits",
    # coverage / splash
    "int": "def_interceptions",
    "ints": "def_interceptions",
    "interceptions": "def_interceptions",
    "pd": "def_pass_defended",
    "pbu": "def_pass_defended",
    "pass def": "def_pass_defended",
    "passes defensed": "def_pass_defended",
    "passes defended": "def_pass_defended",
    "ff": "def_fumbles_forced",
    "forced fumbles": "def_fumbles_forced",
    "fr": "fumble_recovery_own",
    "fum rec": "fumble_recovery_own",
    "fumble recoveries": "fumble_recovery_own",
    "td": "def_tds",
    "tds": "def_tds",
    "def td": "def_tds",
    "saf": "def_safety",
    "safety": "def_safety",
    "safeties": "def_safety",
    # direct points
    "pts": "fpts",
    "points": "fpts",
    "fpts": "fpts",
    "fantasy points": "fpts",
    "big 3": "fpts",
    "big3": "fpts",
    "big 3 pts": "fpts",
    "proj pts": "fpts",
    "projected points": "fpts",
    "ppg": "fpg",
    "pts/g": "fpg",
    "points per game": "fpg",
}

_STAT_FIELDS = {
    "def_tackles_solo",
    "def_tackle_assists",
    "def_tackles",
    "def_tackles_for_loss",
    "def_sacks",
    "def_qb_hits",
    "def_interceptions",
    "def_pass_defended",
    "def_fumbles_forced",
    "fumble_recovery_own",
    "def_tds",
    "def_safety",
}

# IDP Show position labels → BDVM true positions (superset of the
# shared map; ED/IDL are house style there).
_POSITION_ALIASES = {**TRUE_POSITION_MAP, "ED": "EDGE", "IDL": "DT", "DI": "DT"}


class IdpShowParseError(ValueError):
    pass


# A leading "Projected " / "Proj " on a stat header carries no meaning
# here — this whole module parses a projection sheet, so every column is
# projected by definition.  Stripped before alias lookup.
#
# Why: measured 2026-07-30 on the live sheet, every stat header arrived
# prefixed ("Projected Solo Tackles", "Projected Sacks", "Projected
# TFL", ...).  None matched, so ``statColumns`` came back EMPTY, the
# table was rejected as ``not_a_projection_table``, and the caller
# reported it as "expired cookies / paywall?" — a misdiagnosis, since
# the cookies were valid and the right table had been fetched.
#
# Safe by construction: stripping only ever widens what matches, and it
# cannot collide with the two aliases that already spell the prefix out
# ("projected points" -> "points", "proj pts" -> "pts"), both of which
# still resolve to ``fpts``.  ``_squeeze`` is used for headers only
# (one call site), so player names and position values are untouched.
_PROJECTED_PREFIX = re.compile(r"^(?:projected|proj)\s+")


def _squeeze(header: str) -> str:
    cleaned = (
        re.sub(r"[^a-z0-9/ ]+", "", str(header or "").strip().lower()).replace("  ", " ").strip()
    )
    return _PROJECTED_PREFIX.sub("", cleaned).strip()


def _num(v: Any) -> float | None:
    s = str(v if v is not None else "").strip().replace(",", "")
    if not s or s in ("-", "--"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_projection_csv(csv_text: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse one candidate table.  Returns (rows, report).

    A usable projection table needs a name column, a position column,
    and either >= 2 defensive stat columns or a direct points column.
    Anything less → ``report["usable"] = False`` and zero rows.
    """
    reader = csv.reader(io.StringIO(csv_text))
    try:
        raw_header = next(reader)
    except StopIteration:
        return [], {"usable": False, "reason": "empty_csv"}

    mapping: dict[int, str] = {}
    unmapped: list[str] = []
    for idx, col in enumerate(raw_header):
        semantic = _HEADER_ALIASES.get(_squeeze(col))
        if semantic is not None and semantic not in mapping.values():
            mapping[idx] = semantic
        else:
            unmapped.append(str(col))

    mapped = set(mapping.values())
    stat_cols = mapped & _STAT_FIELDS
    usable = (
        "name" in mapped
        and "position" in mapped
        and (len(stat_cols) >= 2 or "fpts" in mapped or "fpg" in mapped)
    )
    report: dict[str, Any] = {
        "usable": usable,
        "mappedColumns": sorted(mapped),
        "unmappedColumns": unmapped,
        "statColumns": sorted(stat_cols),
        "approximations": [],
        "skippedRows": 0,
    }
    if not usable:
        report["reason"] = "not_a_projection_table"
        return [], report

    split_needed = "def_tackles" in mapped and "def_tackles_solo" not in mapped
    if split_needed:
        report["approximations"].append(f"tackle_split_solo_share_{TACKLE_SOLO_SHARE:.2f}")

    rows: list[dict[str, Any]] = []
    for raw in reader:
        entry: dict[str, Any] = {"stats": {}}
        for idx, semantic in mapping.items():
            if idx >= len(raw):
                continue
            value = raw[idx]
            if semantic in ("name", "team"):
                entry[semantic] = str(value or "").strip()
            elif semantic == "position":
                entry["position"] = _POSITION_ALIASES.get(str(value or "").strip().upper(), None)
            elif semantic in ("games", "fpts", "fpg"):
                entry[semantic] = _num(value)
            else:
                n = _num(value)
                if n is not None:
                    entry["stats"][semantic] = n
        name = entry.get("name") or ""
        # Datawrapper name cells sometimes carry rank prefixes ("1. Name")
        name = re.sub(r"^\s*\d+[.)]\s*", "", name).strip()
        if not name or entry.get("position") is None:
            report["skippedRows"] += 1
            continue
        entry["name"] = name
        if split_needed and "def_tackles" in entry["stats"]:
            combined = entry["stats"]["def_tackles"]
            entry["stats"]["def_tackles_solo"] = combined * TACKLE_SOLO_SHARE
            entry["stats"]["def_tackle_assists"] = combined * (1.0 - TACKLE_SOLO_SHARE)
        # Never emit ``def_tackles``: realized_points interprets a
        # published value under that name as the PRE-2025 gamebook SOLO
        # total (see its _tackle_view), so passing a combined count
        # through would inflate every solo-scored league.  Solo/assist
        # carry the information.
        entry["stats"].pop("def_tackles", None)
        if not entry["stats"] and entry.get("fpts") is None and entry.get("fpg") is None:
            report["skippedRows"] += 1
            continue
        rows.append(entry)

    report["rowCount"] = len(rows)
    if not rows:
        report["usable"] = False
        report["reason"] = "no_parseable_rows"
    return rows, report


def pick_best_table(
    candidates: Iterable[tuple[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """From (label, csv_text) candidates, parse all and keep the best.

    Best = usable table with the most (rows × stat columns); an
    article can embed several charts (per-position tables, teasers).
    When multiple usable tables exist they are combined, deduped by
    (name, position) with the stat-richer row winning.
    """
    parsed: list[tuple[str, list[dict[str, Any]], dict[str, Any]]] = []
    reports: dict[str, Any] = {}
    for label, text in candidates:
        rows, report = parse_projection_csv(text)
        reports[label] = report
        if report.get("usable"):
            parsed.append((label, rows, report))
    if not parsed:
        return [], {"usable": False, "tables": reports}

    combined: dict[tuple[str, str], dict[str, Any]] = {}
    for _label, rows, _report in parsed:
        for row in rows:
            key = (row["name"].lower(), row["position"])
            existing = combined.get(key)
            if existing is None or len(row["stats"]) > len(existing["stats"]):
                combined[key] = row
    summary = {
        "usable": True,
        "tables": reports,
        "usableTableCount": len(parsed),
        "playerCount": len(combined),
    }
    return list(combined.values()), summary


def records_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    season: int,
    as_of: str,
    name_normalizer,
) -> list[ProjectionRecord]:
    records = []
    for row in rows:
        games = row.get("games") or 17.0
        stats = dict(row.get("stats") or {})
        fpts = row.get("fpts")
        fpg = row.get("fpg")
        if not stats and fpts is None and fpg is None:
            continue
        records.append(
            ProjectionRecord(
                source=SOURCE_NAME,
                player_key=name_normalizer(row["name"]),
                position=row["position"],
                season=season,
                as_of=as_of,
                games=float(games),
                stat_line=stats or None,
                stat_basis="season",
                fpts=float(fpts) if fpts is not None else None,
                fpg=float(fpg) if fpg is not None else None,
                scoring_native=False,  # Big-3 points ≠ this league's scoring
                is_proxy=False,
            )
        )
    return records


def merge_into_snapshot(
    new_records: list[ProjectionRecord],
    *,
    season: int,
    as_of: str,
    label: str = "idpshow",
) -> tuple[Any, dict[str, Any]]:
    """Merge real records over the latest snapshot (proxy-replacement
    policy) and write a new immutable snapshot.  The policy itself is
    the shared ``supersede_merge_into_snapshot`` — one implementation
    for every real source."""
    if not new_records:
        raise IdpShowParseError("refusing to write a snapshot from zero records")
    return supersede_merge_into_snapshot(
        new_records,
        source_name=SOURCE_NAME,
        season=season,
        as_of=as_of,
        label=label,
    )
