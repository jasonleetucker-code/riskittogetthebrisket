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

Owner gate (default OFF): merging these records into a snapshot changes
the fundamental values BDVM serves, so ``scripts/fetch_idpshow_projections.py``
only calls :func:`merge_into_snapshot` when the owner has switched it on
(``src/bdvm/idpshow_switch.py``).  Otherwise the parsed records go to a
SHADOW file via :func:`write_shadow_file` under ``data/bdvm/shadow/`` -
a tree no BDVM reader opens (every loader reads ``projections_*.json``
under ``data/bdvm/projections/<season>/`` only).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.bdvm.context import TRUE_POSITION_MAP
from src.bdvm.idpshow_switch import MERGE_ENV_VAR
from src.bdvm.projections import (
    REPO_ROOT,
    ProjectionRecord,
    latest_snapshot_path,
    load_snapshot,
    supersede_merge_into_snapshot,
)

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
    # The sheet's current layout may carry the position ONLY as a
    # position-rank code (``ED1`` / ``S69`` / ``DT46`` - the code with the
    # positional rank glued on), the same 2026-05 rename the rankings
    # fetcher documents (scripts/fetch_idpshow.py::_parse_dataset).  It is
    # its own semantic, NOT an alias of ``position``: the value needs its
    # digits stripped before it is a position label, and an explicit
    # ``position`` column always wins when both are present.
    "position rank": "position_rank",
    "pos rank": "position_rank",
    "positional rank": "position_rank",
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
    # The OPPONENT-recovery column the realized engine scores
    # ``idp_fum_rec`` from (2026-10-01: this mapped to ``fumble_recovery_own``
    # — a defender recovering his own team's fumble, which the host does not
    # pay — so every projected recovery scored zero).  A projected FR is a
    # defensive takeaway; projections carry no play-by-play supplement, so
    # nothing is subtracted from it.
    "fr": "fumble_recovery_opp",
    "fum rec": "fumble_recovery_opp",
    "fumble recoveries": "fumble_recovery_opp",
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
    "fumble_recovery_opp",
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


def _position_from_rank_code(value: Any) -> str | None:
    """``"ED1"`` / ``"S69"`` / ``"DT46"`` -> a BDVM true position, else None.

    The leading letters are the position; everything from the first digit on
    is the positional rank and carries no position information.  Same rule as
    the rankings fetcher's ``POSITION RANK`` handling.  A value with no
    leading letters (a bare rank like ``"12"``) or an unrecognised label is
    ``None`` - the row is then skipped and counted, never guessed.
    """
    m = re.match(r"[A-Z]+", str(value or "").strip().upper())
    return _POSITION_ALIASES.get(m.group(0)) if m else None


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

    A usable projection table needs a name column, a position source (a
    ``Pos``/``Position`` column, or failing that a ``Position Rank`` code
    column such as ``ED1``), and either >= 2 defensive stat columns or a
    direct points column.  Anything less → ``report["usable"] = False``
    and zero rows.

    The report names what it saw: ``headerColumns`` (every raw header),
    ``mappedColumns`` / ``unmappedColumns``, ``positionSource`` and, for a
    rejected table, ``missingRoles`` - so "no usable data" is never again
    indistinguishable from an expired cookie.
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
    has_name = "name" in mapped
    has_position = "position" in mapped or "position_rank" in mapped
    has_measure = len(stat_cols) >= 2 or "fpts" in mapped or "fpg" in mapped
    usable = has_name and has_position and has_measure
    if "position" in mapped:
        position_source: str | None = "position_column"
    elif "position_rank" in mapped:
        position_source = "position_rank_code"
    else:
        position_source = None
    report: dict[str, Any] = {
        "usable": usable,
        "headerColumns": [str(c) for c in raw_header],
        "mappedColumns": sorted(mapped),
        "unmappedColumns": unmapped,
        "statColumns": sorted(stat_cols),
        "positionSource": position_source,
        "approximations": [],
        "skippedRows": 0,
    }
    if not usable:
        report["reason"] = "not_a_projection_table"
        report["missingRoles"] = [
            role
            for role, present in (
                ("name", has_name),
                ("position", has_position),
                ("stats_or_points", has_measure),
            )
            if not present
        ]
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
            elif semantic == "position_rank":
                entry["position_from_rank"] = _position_from_rank_code(value)
            elif semantic in ("games", "fpts", "fpg"):
                entry[semantic] = _num(value)
            else:
                n = _num(value)
                if n is not None:
                    entry["stats"][semantic] = n
        # An explicit position column always wins; the rank code is only the
        # position source when the sheet has no such column.
        from_rank = entry.pop("position_from_rank", None)
        if "position" not in mapped:
            entry["position"] = from_rank
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


# ---------------------------------------------------------------------------
# Shadow output - the default while the owner gate is closed
# ---------------------------------------------------------------------------

#: Where parsed-but-not-merged records go.  Deliberately OUTSIDE
#: ``data/bdvm/projections/``: every BDVM reader (``latest_snapshot_path``,
#: ``projection_scorecard``, ``projection_observations``, the service) opens
#: ``projections_*.json`` under ``<SNAPSHOT_DIR>/<season>/`` and nothing else.
#: ``data/`` is gitignored repo-wide, so this is box-local evidence.
SHADOW_DIR = REPO_ROOT / "data" / "bdvm" / "shadow" / "idpshow_projections"

SHADOW_SCHEMA_VERSION = 1


def shadow_path(
    season: int, as_of: str, base_dir: Path | None = None, status: str = "parsed"
) -> Path:
    """``<SHADOW_DIR>/<season>/idpshow_<YYYY-MM-DD>.json`` for parsed records.

    A failed parse (``status != "parsed"``) is a DIAGNOSTIC and gets its own
    name (``idpshow_<date>_<status>.json``) so a later failed rerun the same
    day can never overwrite the day's good evidence.
    """
    suffix = "" if status == "parsed" else f"_{status}"
    return (base_dir or SHADOW_DIR) / str(season) / f"idpshow_{str(as_of)[:10]}{suffix}.json"


def _record_payload(r: ProjectionRecord) -> dict[str, Any]:
    return {
        "source": r.source,
        "playerKey": r.player_key,
        "position": r.position,
        "season": r.season,
        "asOf": r.as_of,
        "games": r.games,
        "statLine": dict(r.stat_line) if r.stat_line is not None else None,
        "statBasis": r.stat_basis,
        "fpg": r.fpg,
        "fpts": r.fpts,
        "scoringNative": r.scoring_native,
        "isProxy": r.is_proxy,
    }


def merge_preview(
    records: Iterable[ProjectionRecord],
    *,
    season: int,
    snapshot_dir: Path | None = None,
) -> dict[str, Any]:
    """What switching the merge on would do to the latest snapshot.  READ ONLY.

    Counts, not values: how many players the IDP Show would cover, how many
    reconstructed-baseline proxies it would supersede, and how many of its
    players another real source already covers (they would become a
    two-source consensus).  The owner decision is about exactly these numbers.
    """
    covered = {r.player_key for r in records}
    try:
        prior = latest_snapshot_path(season, base_dir=snapshot_dir)
        if prior is None:
            return {
                "priorSnapshot": None,
                "idpShowPlayers": len(covered),
                "note": "no prior snapshot: a merge would write IDP Show records only",
            }
        _prior_as_of, existing = load_snapshot(prior)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"unavailable": f"{type(exc).__name__}: {exc}"}
    existing_keys = {r.player_key for r in existing}
    other_real = sorted({r.source for r in existing if not r.is_proxy and r.source != SOURCE_NAME})
    return {
        "priorSnapshot": prior.name,
        "priorRecords": len(existing),
        "idpShowPlayers": len(covered),
        "proxiesWouldSupersede": sum(1 for r in existing if r.is_proxy and r.player_key in covered),
        "playersWithNoPriorRecord": len(covered - existing_keys),
        "playersAlsoCoveredByRealSource": {
            src: len(covered & {r.player_key for r in existing if r.source == src})
            for src in other_real
        },
    }


def write_shadow_file(
    records: list[ProjectionRecord],
    *,
    season: int,
    as_of: str,
    mode: str,
    status: str,
    parse_summary: Mapping[str, Any],
    base_dir: Path | None = None,
    snapshot_dir: Path | None = None,
) -> Path:
    """Write the parse result where BDVM will not read it.  Atomic.

    ``mode`` is ``"shadow"`` (merge switch OFF: these records were NOT merged
    into any snapshot) or ``"merge"`` (switch ON; only used to leave a
    diagnostic when the table was unusable).  ``status`` is ``"parsed"`` or
    ``"no_usable_table"``.  A same-day rerun replaces that status's file for the
    day: shadow output is evidence, not an immutable snapshot.
    """
    path = shadow_path(season, as_of, base_dir, status)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": SHADOW_SCHEMA_VERSION,
        "kind": "idpshow_projections_shadow",
        "notice": (
            "SHADOW OUTPUT - BDVM does not read this file. Real IDP Show records "
            "enter BDVM snapshots only when the owner switches the merge on "
            f"({MERGE_ENV_VAR}=1 or --merge-into-snapshot)."
        ),
        "source": SOURCE_NAME,
        "season": season,
        "asOf": str(as_of)[:10],
        "mode": mode,
        "status": status,
        "mergeSwitch": {"envVar": MERGE_ENV_VAR, "enabled": mode == "merge"},
        "parseSummary": dict(parse_summary),
        "recordCount": len(records),
        "mergePreview": (
            merge_preview(records, season=season, snapshot_dir=snapshot_dir) if records else None
        ),
        "records": [_record_payload(r) for r in records],
    }
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".idpshow_shadow.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path
